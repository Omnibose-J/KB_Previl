"""H-3 — 입지 측면 텍스트 분류 수집·판정. 설계는 §H-9(실행 전 등록).

§H-8이 남긴 핵심: **감성이 아니라 주제 × 방향으로 코딩한다.** "사람이 많아서
들어가기가"는 방문객에게 불만이지만 창업자에게는 유동인구다. 감성 라벨을
붙이는 순간 방문객 관점이 섞인다.

각 항목에 인용문을 필수로 요구한다. 인용이 비면 그 항목은 무효다 — §H-8에서
입지 언급이 아닌 글이 잡히는 오판을 확인했고, 인용 요구가 그 필터다.

    python -m model.absa_run --collect     # 글 수집 → absa_post
    python -m model.absa_run --judge       # LLM 판정 → absa_label
    python -m model.absa_run --stats
"""
import argparse
import json
import random
import re
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from model.senti_gate import API, _headers, _sess
from pipeline.config import DB_PATH, ENV_PATH

SEED = 0
YEAR = 2019                 # §H-9 기준연도
WIN = (2018 * 12 + 1, 2019 * 12 + 1)   # 관측 창: 2018-01 ~ 2018-12
N_PLACE = 60                # 지명 수
N_SHOP = 40                 # 지명당 점포
JUDGE_CAP = 150             # 지명당 LLM 판정 상한
MODEL = "gpt-4o-mini"
TAG = re.compile(r"<[^>]+>")
ADDR = re.compile(r"서울특별시\s+(\S+구)\s+(\S+?[동가])(?:\s|$)")

# §H-9-⑧ — 실행 중 바꾸지 않는다.
PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. 가게의 '위치·입지'에
관한 언급만 뽑아 JSON으로 출력하라. 맛·가격·서비스·메뉴·인테리어는 제외한다.

각 항목은 해당 언급이 있을 때만 값을 채우고, 없으면 null 로 둔다.
quote 가 비면 그 항목은 무시되므로, 근거가 되는 원문을 반드시 20자 이내로 인용하라.

{
 "crowd":      {"dir": "many"|"few"|null, "quote": ""},        // 사람/손님이 많다·적다, 붐빈다·한산하다
 "access":     {"dir": "easy"|"hard"|null, "quote": ""},       // 찾아가기 쉽다·어렵다, 역/주차 접근성
 "visibility": {"dir": "visible"|"hidden"|null, "quote": ""},  // 눈에 잘 띈다·안쪽이라 안 보인다
 "surround":   {"dir": "lively"|"quiet"|"declining"|null, "quote": ""}  // 주변이 번화·한적·쇠퇴
}

글: """


def ym(y, m):
    return y * 12 + (m or 6)


def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS absa_post (
        place TEXT, mgtno TEXT, postdate INTEGER, text TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS absa_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT,
        crowd TEXT, access TEXT, visibility TEXT, surround TEXT)""")
    con.commit()


def targets(con):
    """§H-9-③ 표본 — 마포구 전면 제외."""
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place"))
    tp = {r[0] for r in con.execute("SELECT DISTINCT place FROM trend")}
    shops = defaultdict(list)
    gu_cnt = defaultdict(lambda: defaultdict(int))
    for gid, nm, addr, oy, om, cy, cm, closed in con.execute(
            "SELECT grid_id, bplcnm, addr, open_y, open_m, close_y, close_m, is_closed "
            "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL "
            "AND bplcnm IS NOT NULL"):
        p = g2p.get(gid)
        if not p:
            continue
        m = ADDR.search((addr or "") + " ")
        if not m:
            continue
        gu_cnt[p][m.group(1)] += 1
        o = ym(oy, om)
        c = ym(cy, cm) if (closed == 1 and cy) else None
        shops[p].append((nm.strip(), m.group(2), o, c))

    cand = []
    for p, lst in shops.items():
        if p not in tp:
            continue
        gu = max(gu_cnt[p].items(), key=lambda kv: kv[1])[0]
        if gu == "마포구":
            continue
        t0 = ym(YEAR, 1)
        oper = [s for s in lst if s[2] < t0 and (s[3] is None or s[3] >= t0)]
        coh = [s for s in lst if t0 <= s[2] < t0 + 12]
        if len(oper) >= 50 and len(coh) >= 20:
            cand.append((p, gu, oper))
    cand.sort(key=lambda r: -len(r[2]))
    cand = cand[:N_PLACE]

    rnd = random.Random(SEED)
    out = []
    for p, gu, oper in cand:
        pool = list(oper)
        rnd.shuffle(pool)
        for nm, dong, _o, _c in pool[:N_SHOP]:
            if len(nm) >= 2:
                out.append((p, dong, nm))
    print(f"지명 {len(cand)} · 수집 대상 점포 {len(out):,} (마포구 제외)")
    return out


def fetch(h, dong, name, tries=3):
    for a in range(tries):
        try:
            r = _sess(h).get(API, timeout=20, params={
                "query": f"{dong} {name}", "display": 100, "sort": "sim"})
            if r.status_code != 200:
                time.sleep(1 + a)
                continue
            out = []
            for it in r.json().get("items", []):
                pd = (it.get("postdate") or "").strip()
                if len(pd) != 8:
                    continue
                t = ym(int(pd[:4]), int(pd[4:6]))
                if WIN[0] <= t < WIN[1]:
                    txt = TAG.sub("", (it.get("title") or "") + " "
                                  + (it.get("description") or "")).strip()
                    if txt:
                        out.append((int(pd), txt))
            return out
        except Exception:
            time.sleep(1 + a)
    return None


def collect(con, workers):
    init_db(con)
    con.execute("DELETE FROM absa_post")
    con.commit()
    tg = targets(con)
    h = _headers()
    t0 = time.time()
    n_ok = 0
    rows = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (place, _dong, name), posts in zip(
                tg, ex.map(lambda x: fetch(h, x[1], x[2]), tg)):
            if posts is None:
                continue
            n_ok += 1
            for pd, txt in posts:
                rows.append((place, name, pd, txt))
            if len(rows) >= 2000:
                con.executemany("INSERT INTO absa_post VALUES(?,?,?,?)", rows)
                con.commit()
                rows = []
    if rows:
        con.executemany("INSERT INTO absa_post VALUES(?,?,?,?)", rows)
    con.commit()
    n, = con.execute("SELECT count(*) FROM absa_post").fetchone()
    p, = con.execute("SELECT count(DISTINCT place) FROM absa_post").fetchone()
    print(f"조회 성공 {n_ok:,}/{len(tg):,} · 글 {n:,}건 · 지명 {p} · "
          f"{time.time()-t0:.0f}초")


def judge(con, workers, cap):
    from openai import OpenAI
    init_db(con)
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    cli = OpenAI(api_key=env["OPENAI_API_KEY"])

    done = {r[0] for r in con.execute("SELECT rowid_post FROM absa_label")}
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
        return

    def one(item):
        rid, place, txt = item
        try:
            r = cli.chat.completions.create(
                model=MODEL, temperature=0, max_tokens=220,
                response_format={"type": "json_object"},
                messages=[{"role": "user", "content": PROMPT + txt[:700]}])
            d = json.loads(r.choices[0].message.content)
            vals = []
            for k in ("crowd", "access", "visibility", "surround"):
                v = d.get(k) or {}
                dr, q = v.get("dir"), (v.get("quote") or "").strip()
                # §H-9-① 인용이 비면 무효
                vals.append(dr if (dr and q) else None)
            return (rid, place, *vals)
        except Exception:
            return None

    t0 = time.time()
    buf = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(one, todo), 1):
            if res:
                buf.append(res)
            if len(buf) >= 300:
                con.executemany(
                    "INSERT OR REPLACE INTO absa_label VALUES(?,?,?,?,?,?)", buf)
                con.commit()
                buf = []
                print(f"  {i:,}/{len(todo):,} · {time.time()-t0:.0f}초", flush=True)
    if buf:
        con.executemany("INSERT OR REPLACE INTO absa_label VALUES(?,?,?,?,?,?)", buf)
    con.commit()
    n, = con.execute("SELECT count(*) FROM absa_label").fetchone()
    print(f"판정 완료 {n:,}건 · {time.time()-t0:.0f}초")


def stats(con):
    n, = con.execute("SELECT count(*) FROM absa_post").fetchone()
    print(f"absa_post {n:,}건 · 지명 "
          f"{con.execute('SELECT count(DISTINCT place) FROM absa_post').fetchone()[0]}")
    try:
        m, = con.execute("SELECT count(*) FROM absa_label").fetchone()
    except sqlite3.OperationalError:
        print("absa_label 없음")
        return
    print(f"absa_label {m:,}건")
    for col in ("crowd", "access", "visibility", "surround"):
        rows = con.execute(
            f"SELECT {col}, count(*) FROM absa_label WHERE {col} IS NOT NULL "
            f"GROUP BY 1 ORDER BY 2 DESC").fetchall()
        tot = sum(c for _, c in rows)
        detail = " · ".join(f"{v} {c:,}" for v, c in rows)
        print(f"  {col:11s} 언급 {tot:6,} ({tot/max(m,1):5.1%})   {detail}")
    ok = con.execute(
        "SELECT count(*) FROM (SELECT place FROM absa_label "
        "WHERE crowd IS NOT NULL GROUP BY place HAVING count(*)>=10)").fetchone()[0]
    print(f"  crowd 언급 10건 이상 지명: {ok}  (§H-9-⑥ 기준 30개)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--judge", action="store_true")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--cap", type=int, default=JUDGE_CAP)
    a = ap.parse_args()
    con = sqlite3.connect(DB_PATH)
    if a.collect:
        collect(con, a.workers)
    if a.judge:
        judge(con, max(a.workers, 8), a.cap)
    if a.stats or not (a.collect or a.judge):
        stats(con)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
