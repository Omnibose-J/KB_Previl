"""I-11 — 경쟁자 약점(불만 요인) 추출. 설계는 §I-11(실행 전 등록).

**정형에 대조군이 없다.** 예측력도 수렴 타당도도 주장하지 않고 판정 정확도만
책임진다(§I-6). 산출은 비율이 아니라 **목록**이다(§I-10-③) — "이 동네 대기 불만
43%" 보다 "반경 내 대기 불만이 있는 가게: A·B·C" 가 창업자에게 쓸모 있다.

`parking` 은 다른 여섯과 성격이 다르다. 창업자가 고칠 수 없는 입지 제약이라
차별화 지점이 아니다. 컬럼으로는 같이 담되 화면에서 분리한다(§I-11).

이미 수집한 `absa_post` 를 재사용한다(재수집 없음).

    python -m model.gripe_run --judge
    python -m model.gripe_run --stats
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

CAP = 400
# §I-11 닫힌 목록 — 실행 중 늘리지 않는다.
CATS = ("wait", "seat", "service", "clean", "price", "noise", "parking")
# §I-11 마지막 열 — 창업자가 고칠 수 있나
FIXABLE = ("wait", "seat", "service", "clean", "price")
PARTIAL = ("noise",)                                       # 부분
CONSTRAINT = ("parking",)                                  # 입지 제약, 차별화 지점 아님

PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. 글쓴이가 **불만을 말한
항목**만 뽑아 JSON으로 출력하라. 칭찬은 담지 마라.

각 항목은 불만이 있을 때만 true, 없거나 언급이 없으면 false 로 둔다.
quote 는 불만 하나에 대한 원문 25자 이내 인용이다. 불만이 하나도 없으면 빈 문자열.

{
 "wait":    true|false,   // 대기·웨이팅이 길다, 줄 서야 한다
 "seat":    true|false,   // 좌석이 좁다·불편하다·자리가 없다
 "service": true|false,   // 응대가 불친절하다·느리다
 "clean":   true|false,   // 위생·청결이 나쁘다
 "price":   true|false,   // 가격이 비싸다·가격 대비 아쉽다
 "noise":   true|false,   // 시끄럽다·정신없다
 "parking": true|false,   // 주차가 어렵다·주차장이 없다
 "quote":   "불만 원문 25자 이내 인용. 불만 없으면 빈 문자열"
}

글: """


def init_db(con):
    cols = ", ".join(f"{c} INTEGER" for c in CATS)
    con.execute(f"""CREATE TABLE IF NOT EXISTS gripe_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT, mgtno TEXT,
        {cols}, quote TEXT)""")
    con.commit()


def parse(d):
    """(값들, quote) 또는 None. 불만이 하나라도 true 면 인용을 요구한다."""
    vals = [1 if d.get(c) is True else 0 for c in CATS]
    q = (d.get("quote") or "").strip()
    if any(vals) and not q:
        return None            # §H-9-① 인용 없는 불만은 무효
    return vals, q[:60]


def judge(con, workers, cap):
    cli = client()
    done = {r[0] for r in con.execute("SELECT rowid_post FROM gripe_label")}
    per = defaultdict(int)
    todo = []
    for rid, place, mg, txt in con.execute(
            "SELECT rowid, place, mgtno, text FROM absa_post ORDER BY rowid"):
        if rid in done or per[place] >= cap:
            continue
        per[place] += 1
        todo.append((rid, place, mg, txt))
    print(f"판정 대상 {len(todo):,}건 (지명당 상한 {cap}) · model={MODEL}")
    if not todo:
        return 0

    ph = ",".join("?" * (len(CATS) + 4))
    sql = f"INSERT OR REPLACE INTO gripe_label VALUES({ph})"
    fails = new_fails()

    def one(item):
        rid, place, mg, txt = item
        raw = complete(cli, PROMPT + txt[:700], 400, fails)
        if raw is None:
            return None
        try:
            got = parse(json.loads(raw))
        except json.JSONDecodeError:
            fails["JSONDecodeError"] += 1
            return None
        if not got:
            return None
        vals, q = got
        return (rid, place, mg, *vals, q)

    t0 = time.time()
    buf = []
    saved = 0
    stopped = ""
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
    n, = con.execute("SELECT count(*) FROM gripe_label").fetchone()
    print(f"판정 {n:,}건 누적 (이번에 {saved:,}건) · {time.time()-t0:.0f}초")
    if stopped:
        print(f"  {stopped}")
    report(fails, saved, len(todo))
    return saved


def stats(con):
    try:
        n, = con.execute("SELECT count(*) FROM gripe_label").fetchone()
    except sqlite3.OperationalError:
        print("gripe_label 없음")
        return
    print(f"gripe_label {n:,}건")
    for c in CATS:
        k, = con.execute(f"SELECT count(*) FROM gripe_label WHERE {c}=1").fetchone()
        mark = ("   ← 입지 제약(고칠 수 없음)" if c in CONSTRAINT else
                "   ← 부분적으로만 고칠 수 있음" if c in PARTIAL else "")
        print(f"  {c:9s} {k:6,} ({k/max(n,1):5.1%}){mark}")
    any_sql = " OR ".join(f"{c}=1" for c in CATS)
    a, = con.execute(f"SELECT count(*) FROM gripe_label WHERE {any_sql}").fetchone()
    print(f"  불만 있는 글 {a:,} ({a/max(n,1):.1%})")
    shops, = con.execute(
        f"SELECT count(DISTINCT mgtno) FROM gripe_label WHERE {any_sql}").fetchone()
    print(f"  불만이 잡힌 점포 {shops:,}곳  ← §I-10-③ 목록의 원소")


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
        rc = 0 if judge(con, a.workers, a.cap) else 2
    if a.stats or not a.judge:
        stats(con)
    con.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())
