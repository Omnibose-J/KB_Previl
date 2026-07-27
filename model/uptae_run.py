"""I-13 — 텍스트에서 업종 복원. 설계는 §I-13(실행 전 등록).

지금까지 비정형 실험에는 **정답 라벨이 없었다.** 인허가 `uptae` 는 관청이 등록한
값이고 텍스트와 독립적으로 만들어졌다 — 정답이다.

이것은 제품 기능이 아니라 **추출 도구의 타당도 검정**이다. §I-9(가격)·§I-11(불만)은
대조군이 없어 정확도만 주장하는데, 그 주장이 서려면 같은 도구가 정답 있는 문제를
풀 수 있어야 한다. 미달하면 그 둘도 함께 의심해야 한다(§I-13에 미리 적었다).

    python -m model.uptae_run --judge
    python -m model.uptae_run --stats
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

# §I-13 닫힌 목록 — 실행 중 바꾸지 않는다. '기타'는 미분류라 제외.
UPTAE_MAP = {
    "한식": "korean",
    "분식": "snack", "김밥(도시락)": "snack",
    "경양식": "western", "패스트푸드": "western",
    "호프/통닭": "bar", "정종/대포집/소주방": "bar",
    "감성주점": "bar", "통닭(치킨)": "bar",
    "일식": "japanese", "횟집": "japanese",
    "중국식": "chinese",
    "까페": "cafe", "전통찻집": "cafe",
}
CLASSES = ("korean", "snack", "western", "bar", "japanese", "chinese", "cafe")

PROMPT = """다음은 한국어 음식점 관련 블로그 글의 일부다. 이 가게가 **어떤 종류의
음식점인지** 하나만 골라 JSON으로 출력하라.

 korean   한식 (고기·찌개·백반·국밥·한정식)
 snack    분식 (떡볶이·김밥·순대·라면)
 western  양식·경양식·패스트푸드 (파스타·스테이크·피자·버거)
 bar      술집·호프·치킨 (맥주·소주·안주 중심, 치킨집 포함)
 japanese 일식 (초밥·라멘·돈카츠·횟집)
 chinese  중식 (짜장면·짬뽕·탕수육)
 cafe     카페·찻집 (커피·디저트 중심)

글에서 판단할 근거가 없으면 null 로 둔다. 가게 이름만 보고 추측하지 마라.
근거가 되는 원문을 반드시 20자 이내로 인용하라. 인용이 비면 무효다.

{
 "kind":  "korean"|"snack"|"western"|"bar"|"japanese"|"chinese"|"cafe"|null,
 "quote": "음식·메뉴가 드러난 원문 20자 이내 인용. 없으면 빈 문자열"
}

글: """


def init_db(con):
    con.execute("""CREATE TABLE IF NOT EXISTS uptae_label (
        rowid_post INTEGER PRIMARY KEY, place TEXT, mgtno TEXT, kind TEXT)""")
    con.commit()


def truth(con):
    """(place, 상호명) → 정답 클래스. §I-13 — 모호한 것은 버린다.

    §15-H에서 이름만으로 조인해 6,183 → 83,864행으로 부풀렸고 없는 유의성이
    생겼다. 격자가 둘 이상이거나 업태가 둘 이상이면 추측하지 않고 버린다.
    """
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place"))
    grids = defaultdict(set)
    kinds = defaultdict(set)
    for gid, nm, up in con.execute(
            "SELECT grid_id, bplcnm, uptae FROM licence "
            "WHERE grid_id IS NOT NULL AND bplcnm IS NOT NULL AND uptae IS NOT NULL"):
        p = g2p.get(gid)
        if not p:
            continue
        k = UPTAE_MAP.get(up)
        if not k:
            continue                      # '기타'·목록 밖 업태 제외
        key = (p, nm.strip())
        grids[key].add(gid)
        kinds[key].add(k)
    out = {}
    amb_g = amb_k = 0
    for key, ks in kinds.items():
        if len(grids[key]) > 1:
            amb_g += 1
            continue
        if len(ks) > 1:
            amb_k += 1
            continue
        out[key] = next(iter(ks))
    print(f"정답 확보 {len(out):,}곳 · 격자 모호로 제외 {amb_g:,} · 업태 모호로 제외 {amb_k:,}")
    return out


def judge(con, workers, cap):
    cli = client()
    gt = truth(con)
    done = {r[0] for r in con.execute("SELECT rowid_post FROM uptae_label")}
    per = defaultdict(int)
    todo = []
    for rid, place, mg, txt in con.execute(
            "SELECT rowid, place, mgtno, text FROM absa_post ORDER BY rowid"):
        if rid in done or per[place] >= cap:
            continue
        if (place, mg) not in gt:
            continue                      # 정답이 없는 글은 판정하지 않는다
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
            d = json.loads(raw)
        except json.JSONDecodeError:
            fails["JSONDecodeError"] += 1
            return None
        q = (d.get("quote") or "").strip()
        k = d.get("kind")
        if k not in CLASSES or not q:     # 인용 없거나 스키마 밖이면 무효
            k = None
        return (rid, place, mg, k)

    t0 = time.time()
    buf = []
    saved = 0
    stopped = ""
    sql = "INSERT OR REPLACE INTO uptae_label VALUES(?,?,?,?)"
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
    n, = con.execute("SELECT count(*) FROM uptae_label").fetchone()
    print(f"판정 {n:,}건 누적 (이번에 {saved:,}건) · {time.time()-t0:.0f}초")
    if stopped:
        print(f"  {stopped}")
    report(fails, saved, len(todo))
    return saved


def stats(con):
    try:
        n, = con.execute("SELECT count(*) FROM uptae_label").fetchone()
    except sqlite3.OperationalError:
        print("uptae_label 없음")
        return
    got, = con.execute(
        "SELECT count(*) FROM uptae_label WHERE kind IS NOT NULL").fetchone()
    print(f"uptae_label {n:,}건 · 판정된 글 {got:,} ({got/max(n,1):.1%})")
    for k, c in con.execute("SELECT kind, count(*) FROM uptae_label "
                            "WHERE kind IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"):
        print(f"  {k:<10s}{c:>7,}")
    shops, = con.execute("SELECT count(DISTINCT place||'|'||mgtno) FROM uptae_label "
                         "WHERE kind IS NOT NULL").fetchone()
    print(f"  판정된 점포 {shops:,}곳  (§I-13 최소 500)")


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
