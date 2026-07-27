"""H-4 — 시간대 수요 성격 판정. 설계는 §H-10(실행 전 등록).

§15-H가 닫은 것: 텍스트의 **입지 조건** 서술은 실제와 무관하다(역거리 차이 0m).
당연하다 — 역거리·밀도는 정형이 이미 정확히 안다.

**텍스트만 아는 것은 "누가 언제 오는가"다.** 정형의 `tz_*`는 몇 명이
지나갔는지만 알고, 무엇을 하러 왔는지는 모른다. 그것을 재는 것이 H-4다.

이미 수집한 `absa_post`를 재사용한다(재수집 없음).

    python -m model.demand_run --judge
    python -m model.demand_run --stats
"""
import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
import time

from pipeline.config import DB_PATH, ENV_PATH

MODEL = "gpt-4o-mini"
CAP = 150          # 지명당 판정 상한 (§H-9와 동일)

# §H-10 — 실행 중 바꾸지 않는다.
PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. 글쓴이의 **방문 맥락**만
뽑아 JSON으로 출력하라. 가게의 위치·맛·가격 평가는 무시한다.

근거가 없으면 null 로 둔다. 추측하지 말고 글에 드러난 것만 답하라.

{
 "time": "morning"|"lunch"|"afternoon"|"dinner"|"night"|null,
   // morning 아침, lunch 점심(11~14시), afternoon 오후·티타임,
   // dinner 저녁(17~21시), night 야간·술자리(21시 이후)
 "party": "alone"|"date"|"family"|"friends"|"work"|null,
   // work = 회식·업무 미팅
 "purpose": "meal"|"cafe"|"drink"|null,
 "quote": "시간·동행을 드러낸 원문 20자 이내 인용. 없으면 빈 문자열"
}

글: """


def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS demand_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT,
        time TEXT, party TEXT, purpose TEXT)""")
    con.commit()


def judge(con, workers, cap, model=MODEL, prompt=PROMPT, table="demand_label"):
    from openai import OpenAI
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    cli = OpenAI(api_key=env["OPENAI_API_KEY"])

    done = {r[0] for r in con.execute(f"SELECT rowid_post FROM {table}")}
    per = defaultdict(int)
    todo = []
    for rid, place, txt in con.execute(
            "SELECT rowid, place, text FROM absa_post ORDER BY rowid"):
        if rid in done or per[place] >= cap:
            continue
        per[place] += 1
        todo.append((rid, place, txt))
    print(f"판정 대상 {len(todo):,}건 (지명당 상한 {cap}) · model={model}")
    if not todo:
        return 0

    # 실패를 삼키면 "한 건도 저장 못 한 채 exit 0" 이 된다. RPD 한도에 걸렸을 때
    # 실제로 그렇게 끝났다 (§16). 종류별로 세서 마지막에 드러낸다.
    fails = defaultdict(int)

    def one(item):
        rid, place, txt = item
        try:
            r = cli.chat.completions.create(
                model=model, temperature=0, max_tokens=140,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": prompt + txt[:700]}])
            d = json.loads(r.choices[0].message.content)
            q = (d.get("quote") or "").strip()
            # 인용이 없으면 time 은 무효 (§H-9-① 규칙 승계)
            tm = d.get("time") if q else None
            return (rid, place, tm, d.get("party"), d.get("purpose"))
        except Exception as e:
            fails[type(e).__name__] += 1
            return None

    t0 = time.time()
    buf = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(one, todo), 1):
            if res:
                buf.append(res)
            if len(buf) >= 300:
                con.executemany(
                    f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?)", buf)
                con.commit()
                buf = []
                print(f"  {i:,}/{len(todo):,} · {time.time()-t0:.0f}초", flush=True)
    if buf:
        con.executemany(f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?)", buf)
    con.commit()
    n, = con.execute(f"SELECT count(*) FROM {table}").fetchone()
    saved = n - len(done)
    print(f"판정 완료 {n:,}건 (이번에 {saved:,}건) · {time.time()-t0:.0f}초")
    if fails:
        print("  실패 " + " · ".join(f"{k} {v:,}" for k, v in
                                    sorted(fails.items(), key=lambda kv: -kv[1])))
    return saved


def stats(con):
    try:
        n, = con.execute("SELECT count(*) FROM demand_label").fetchone()
    except sqlite3.OperationalError:
        print("demand_label 없음")
        return
    print(f"demand_label {n:,}건")
    for col in ("time", "party", "purpose"):
        rows = con.execute(
            f"SELECT {col}, count(*) FROM demand_label WHERE {col} IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC").fetchall()
        tot = sum(c for _, c in rows)
        print(f"  {col:8s} 판정 {tot:6,} ({tot/max(n,1):5.1%})  "
              + " · ".join(f"{v} {c:,}" for v, c in rows))
    ok = con.execute(
        "SELECT count(*) FROM (SELECT place FROM demand_label "
        "WHERE time IS NOT NULL GROUP BY place HAVING count(*)>=10)").fetchone()[0]
    print(f"  time 10건 이상 지명: {ok}  (§H-10 기준 30개)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--cap", type=int, default=CAP)
    a = ap.parse_args()
    con = sqlite3.connect(DB_PATH)
    init_db(con)
    if a.judge:
        judge(con, a.workers, a.cap)
    if a.stats or not a.judge:
        stats(con)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
