"""I-15 — 경쟁자 강점(칭찬 요인) 추출. 설계는 §I-15(실행 전 등록).

§I-11은 불만만 뽑았다. 그래서 산출물이 반쪽이었다.

    약점 = 내가 파고들 틈  ·  강점 = 내가 넘어야 할 기준선

옆집이 "양이 많다"로 알려져 있으면 그것이 이 동네 손님의 기대치다. 모르고
들어가면 같은 값에 적게 주는 집이 된다.

**범주가 §I-11과 대칭이 아니다.** 불만은 운영 실패(대기·위생·소음)에 몰리고
칭찬은 상품 자체(맛·양·재료)에 몰린다. 억지로 축을 맞추면 없는 범주를 만든다.

    python -m model.merit_run --judge
    python -m model.merit_run --stats
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
# §I-15 닫힌 목록 — 실행 중 늘리지 않는다.
CATS = ("taste", "portion", "value", "mood", "kind", "fresh")

PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. 글쓴이가 **칭찬한 항목**만
뽑아 JSON으로 출력하라. 불만은 담지 마라.

각 항목은 칭찬이 있을 때만 true, 없거나 언급이 없으면 false 로 둔다.
quote 는 칭찬 하나에 대한 원문 25자 이내 인용이다. 칭찬이 하나도 없으면 빈 문자열.

{
 "taste":   true|false,   // 맛있다, 맛이 좋다
 "portion": true|false,   // 양이 많다, 푸짐하다
 "value":   true|false,   // 가격 대비 만족스럽다, 가성비가 좋다
 "mood":    true|false,   // 분위기·인테리어가 좋다
 "kind":    true|false,   // 응대가 친절하다
 "fresh":   true|false,   // 재료가 신선하다
 "quote":   "칭찬 원문 25자 이내 인용. 칭찬 없으면 빈 문자열"
}

글: """


def init_db(con):
    cols = ", ".join(f"{c} INTEGER" for c in CATS)
    con.execute(f"""CREATE TABLE IF NOT EXISTS merit_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT, mgtno TEXT,
        {cols}, quote TEXT)""")
    con.commit()


def parse(d):
    vals = [1 if d.get(c) is True else 0 for c in CATS]
    q = (d.get("quote") or "").strip()
    if any(vals) and not q:
        return None            # §H-9-① 인용 없는 판정은 무효
    return vals, q[:60]


def judge(con, workers, cap):
    cli = client()
    done = {r[0] for r in con.execute("SELECT rowid_post FROM merit_label")}
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
    sql = f"INSERT OR REPLACE INTO merit_label VALUES({ph})"
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
    n, = con.execute("SELECT count(*) FROM merit_label").fetchone()
    print(f"판정 {n:,}건 누적 (이번에 {saved:,}건) · {time.time()-t0:.0f}초")
    if stopped:
        print(f"  {stopped}")
    report(fails, saved, len(todo))
    return saved


def stats(con):
    try:
        n, = con.execute("SELECT count(*) FROM merit_label").fetchone()
    except sqlite3.OperationalError:
        print("merit_label 없음")
        return
    print(f"merit_label {n:,}건")
    for c in CATS:
        k, = con.execute(f"SELECT count(*) FROM merit_label WHERE {c}=1").fetchone()
        s, = con.execute(
            f"SELECT count(DISTINCT mgtno) FROM merit_label WHERE {c}=1").fetchone()
        print(f"  {c:9s} {k:6,} ({k/max(n,1):5.1%})  점포 {s:,}곳")
    any_sql = " OR ".join(f"{c}=1" for c in CATS)
    a, = con.execute(f"SELECT count(*) FROM merit_label WHERE {any_sql}").fetchone()
    print(f"  칭찬 있는 글 {a:,} ({a/max(n,1):.1%})")
    print("  주의: 칭찬은 불만보다 흔하고 협찬 글이 섞인다 — 강점 목록은 약점보다"
          " 신뢰도가 낮다 (§I-15)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--workers", type=int, default=12)
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
