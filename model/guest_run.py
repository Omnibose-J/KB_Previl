"""I-14 — 손님 프로파일(동행·목적) 판정. 설계는 §I-14(실행 전 등록).

§16에서 기각된 것은 **시간대 비율과 실제 시간대별 유동인구의 상관**이다.
동행·목적은 애초에 정형 대조군이 없어 "정확도만 보장하고 사실로만 제공"으로
등록됐고(§I-2-①), 그 검정은 아직 하지 않았다.

`time` 은 **뽑되 내보내지 않는다.** 프롬프트를 §H-10 그대로 유지해야 §16의 판정과
비교가 되므로 필드는 남기지만, 화면에 띄우면 창업자가 "저녁 장사가 되는 동네"로
읽고 그 추론이 정확히 기각된 것이다(§I-14).

    python -m model.guest_run --judge
    python -m model.guest_run --stats
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import time

from model.demand_run import PROMPT          # §H-10 원문 그대로 — 바꾸지 않는다
from model.llm import MODEL, DailyLimit, client, complete, new_fails, report
from pipeline.config import DB_PATH

CAP = 400
PARTY = ("alone", "date", "family", "friends", "work")
PURPOSE = ("meal", "cafe", "drink")
# 화면에 내보내는 필드. time 은 여기 없다 (§I-14).
EXPOSED = ("party", "purpose")


def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS guest_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT, mgtno TEXT,
        time TEXT, party TEXT, purpose TEXT)""")
    con.commit()


def parse(d):
    """스키마 밖 값을 막는다. §16에서 party="sister", time="evening" 이 나왔다."""
    q = (d.get("quote") or "").strip()
    tm = d.get("time") if q else None
    party = d.get("party")
    purpose = d.get("purpose")
    return (tm if tm in ("morning", "lunch", "afternoon", "dinner", "night") else None,
            party if party in PARTY else None,
            purpose if purpose in PURPOSE else None)


def judge(con, workers, cap):
    cli = client()
    done = {r[0] for r in con.execute("SELECT rowid_post FROM guest_label")}
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

    fails = new_fails()

    def one(item):
        rid, place, mg, txt = item
        raw = complete(cli, PROMPT + txt[:700], 400, fails)
        if raw is None:
            return None
        try:
            return (rid, place, mg, *parse(json.loads(raw)))
        except json.JSONDecodeError:
            fails["JSONDecodeError"] += 1
            return None

    t0 = time.time()
    buf = []
    saved = 0
    stopped = ""
    sql = "INSERT OR REPLACE INTO guest_label VALUES(?,?,?,?,?,?)"
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
    n, = con.execute("SELECT count(*) FROM guest_label").fetchone()
    print(f"판정 {n:,}건 누적 (이번에 {saved:,}건) · {time.time()-t0:.0f}초")
    if stopped:
        print(f"  {stopped}")
    report(fails, saved, len(todo))
    return saved


def stats(con):
    try:
        n, = con.execute("SELECT count(*) FROM guest_label").fetchone()
    except sqlite3.OperationalError:
        print("guest_label 없음")
        return
    print(f"guest_label {n:,}건 · model={MODEL}")
    for col in ("party", "purpose", "time"):
        rows = con.execute(
            f"SELECT {col}, count(*) FROM guest_label WHERE {col} IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC").fetchall()
        tot = sum(k for _, k in rows)
        mark = "" if col in EXPOSED else "   ← 비노출 (§I-14)"
        print(f"  {col:8s} 판정 {tot:6,} ({tot/max(n,1):5.1%}){mark}")
        print("           " + " · ".join(f"{v} {k:,}" for v, k in rows))


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
