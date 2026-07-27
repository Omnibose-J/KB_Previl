"""I-9 — 1인당 지출 추출. 설계는 §I-9(실행 전 등록).

정형의 객단가(`sales_amt/sales_cnt`)는 51.4% 격자에만 있다. 나머지 48.6%는
상권 밖이라 매출 데이터가 아예 없는데, 창업자는 그 자리에서도 가격을 정해야
한다. **상권 안에서 정형과 맞는지 먼저 보고, 맞을 때만 상권 밖에 쓴다.**

이미 수집한 `absa_post`를 재사용한다(재수집 없음).

    python -m model.price_run --judge
    python -m model.price_run --stats
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import time

from model.llm import MODEL, DailyLimit, client, complete, new_fails, report
from pipeline.config import DB_PATH

CAP = 400              # 지명당 판정 상한
LO, HI = 1000, 300000  # 1인당 지출로 받아들이는 범위(원)

# §I-9 — 실행 중 바꾸지 않는다.
PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. 글쓴이가 **1인당 얼마를
썼는지**만 뽑아 JSON으로 출력하라. 가게 위치·맛·분위기는 무시한다.

규칙:
- 1인분 가격, 인당 금액, 메뉴 하나 가격이 나오면 그 값을 쓴다.
- 총액만 있고 **인원이 명시된 경우에만** 나눈다. 인원을 모르면 null 이다.
  추측해서 나누지 마라.
- 금액이 여럿이면 대표 식사 1인분에 해당하는 값을 고른다.
- 근거 원문을 반드시 인용하라. 인용이 비면 그 값은 버려진다.

{
 "per_person": 숫자(원) 또는 null,
 "basis": "unit"|"divided"|null,
   // unit = 1인분·인당 금액이 직접 있음, divided = 총액을 명시된 인원으로 나눔
 "n_people": 숫자 또는 null,   // basis 가 divided 일 때만
 "quote": "금액이 나온 원문 25자 이내 인용. 없으면 빈 문자열"
}

글: """


def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS price_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT,
        per_person INTEGER, basis TEXT, quote TEXT)""")
    con.commit()


def parse(d):
    """스키마 밖 값을 걸러 (per_person, basis, quote) 또는 None 을 낸다.

    LLM 이 문자열 "null", "26,800원", 소수를 돌려주는 경우가 실제로 있다
    (§H-10 에서 time 에 "evening"·party 에 "sister" 가 나온 것과 같은 종류).
    """
    q = (d.get("quote") or "").strip()
    if not q:
        return None                      # §H-9-① 인용 없으면 무효
    basis = d.get("basis")
    if basis not in ("unit", "divided"):
        return None
    v = d.get("per_person")
    if isinstance(v, str):
        v = "".join(ch for ch in v if ch.isdigit())
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        return None
    if not (LO <= v <= HI):
        return None
    if basis == "divided":
        n = d.get("n_people")
        try:
            n = int(float(n))
        except (TypeError, ValueError):
            return None                  # 인원 불명 총액은 버린다
        if n < 1:
            return None
    return v, basis, q[:60]


def judge(con, workers, cap):
    cli = client()
    done = {r[0] for r in con.execute("SELECT rowid_post FROM price_label")}
    per = defaultdict(int)
    todo = []
    for rid, place, txt in con.execute(
            "SELECT rowid, place, text FROM absa_post ORDER BY rowid"):
        if rid in done or per[place] >= cap:
            continue
        per[place] += 1
        todo.append((rid, place, txt))
    print(f"판정 대상 {len(todo):,}건 (지명당 상한 {cap}) · model={MODEL}")
    if not todo:
        return 0

    fails = new_fails()

    def one(item):
        rid, place, txt = item
        raw = complete(cli, PROMPT + txt[:700], 400, fails)
        if raw is None:
            return None                                  # 호출 실패
        try:
            got = parse(json.loads(raw))
        except json.JSONDecodeError:
            fails["JSONDecodeError"] += 1
            return None
        if not got:
            return (rid, place, None, None, None)        # 판정했으나 금액 없음
        return (rid, place, *got)

    t0 = time.time()
    buf = []
    saved = 0
    stopped = ""
    sql = "INSERT OR REPLACE INTO price_label VALUES(?,?,?,?,?)"
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for i, res in enumerate(ex.map(one, todo), 1):
                if res:
                    buf.append(res)
                if len(buf) >= 300:
                    con.executemany(sql, buf)
                    con.commit()
                    saved += len(buf)
                    buf = []
                    print(f"  {i:,}/{len(todo):,} · {time.time()-t0:.0f}초", flush=True)
    except DailyLimit as e:
        stopped = f"일일 한도 소진 — {e}"
    if buf:
        con.executemany(sql, buf)
        saved += len(buf)
    con.commit()
    n, = con.execute("SELECT count(*) FROM price_label").fetchone()
    print(f"판정 {n:,}건 누적 (이번에 {saved:,}건) · {time.time()-t0:.0f}초")
    if stopped:
        print(f"  {stopped}")
    report(fails, saved, len(todo))
    return saved


def stats(con):
    try:
        n, = con.execute("SELECT count(*) FROM price_label").fetchone()
    except sqlite3.OperationalError:
        print("price_label 없음")
        return
    got = con.execute(
        "SELECT count(*) FROM price_label WHERE per_person IS NOT NULL").fetchone()[0]
    print(f"price_label {n:,}건 · 금액 추출 {got:,} ({got/max(n,1):.1%})")
    rows = con.execute("SELECT basis, count(*) FROM price_label "
                       "WHERE per_person IS NOT NULL GROUP BY 1").fetchall()
    print("  근거   " + " · ".join(f"{b} {c:,}" for b, c in rows))
    vals = [r[0] for r in con.execute(
        "SELECT per_person FROM price_label WHERE per_person IS NOT NULL "
        "ORDER BY per_person")]
    if vals:
        def pct(p):
            return vals[min(len(vals) - 1, int(len(vals) * p))]
        print(f"  분포   1분위 {pct(.25):,}원 · 중앙값 {pct(.5):,}원 · "
              f"3분위 {pct(.75):,}원 · 최대 {vals[-1]:,}원")
    ok = con.execute(
        "SELECT count(*) FROM (SELECT place FROM price_label "
        "WHERE per_person IS NOT NULL GROUP BY place HAVING count(*)>=10)").fetchone()[0]
    print(f"  금액 10건 이상 지명: {ok}  (§I-9 기준 30개)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--cap", type=int, default=CAP)
    a = ap.parse_args()
    con = sqlite3.connect(DB_PATH)
    init_db(con)
    rc = 0
    if a.judge:
        # 한 건도 저장 못 했으면 exit!=0 — 큐가 "완료"로 넘기면 안 된다
        rc = 0 if judge(con, a.workers, a.cap) else 2
    if a.stats or not a.judge:
        stats(con)
    con.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
