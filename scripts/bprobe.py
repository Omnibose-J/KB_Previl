"""§I-21 B0 — 확장 검색어가 측면 관련 스니펫을 돌려주는가. 크롤링 0, LLM 0.

    python scripts/bprobe.py            # 수집 → scratch_bprobe/raw.json
    python scripts/bprobe.py --score    # 이미 받은 것만 채점
"""
import argparse
import json
import random
import sqlite3
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from model.senti_gate import API, _headers, _sess          # noqa: E402
from model.absa_run import TAG, WIN, ym                    # noqa: E402
from pipeline.config import DB_PATH                        # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

SEED = 0
N_SHOP = 200
OUT = Path(__file__).resolve().parent.parent / "scratch_bprobe"

# §I-21 등록 — 중립어로 고정. 부정어를 쓰면 검색이 불만을 골라내 버린다.
KW = {"wait": "웨이팅", "seat": "자리", "service": "친절", "clean": "청결",
      "price": "가격", "noise": "시끄러움", "parking": "주차"}
RET_MIN, KWHIT_MIN = 0.50, 0.30                            # §I-21 통과 기준


def fetch(h, query, tries=3):
    """(창 내 글 수, [(postdate, text)]) — 실패는 None 으로 구분한다."""
    for a in range(tries):
        try:
            r = _sess(h).get(API, timeout=20, params={
                "query": query, "display": 100, "sort": "sim"})
            if r.status_code != 200:
                time.sleep(1 + a)
                continue
            out = []
            for it in r.json().get("items", []):
                pd = (it.get("postdate") or "").strip()
                if len(pd) != 8:
                    continue
                t = ym(int(pd[:4]), int(pd[4:6]))
                txt = TAG.sub("", (it.get("title") or "") + " "
                              + (it.get("description") or "")).strip()
                if txt:
                    out.append({"pd": int(pd), "in_win": WIN[0] <= t < WIN[1],
                                "text": txt})
            return out
        except Exception:
            time.sleep(1 + a)
    return None


def collect():
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    shops = con.execute(
        "SELECT DISTINCT place, mgtno FROM absa_post ORDER BY place, mgtno").fetchall()
    seen = {r[0] for r in con.execute("SELECT DISTINCT text FROM absa_post")}
    con.close()
    rnd = random.Random(SEED)
    rnd.shuffle(shops)
    pick = shops[:N_SHOP]
    print(f"점포 {len(pick)}곳 · 쿼리 {len(pick) * (1 + len(KW)):,}회")

    h = _headers()
    jobs = []
    for place, shop in pick:
        jobs.append((place, shop, "_base", f"{place} {shop}"))
        for asp, kw in KW.items():
            jobs.append((place, shop, asp, f"{shop} {kw}"))

    OUT.mkdir(exist_ok=True)
    res, t0, fail = [], time.time(), 0

    def one(j):
        place, shop, asp, q = j
        items = fetch(h, q)
        return {"place": place, "shop": shop, "aspect": asp, "query": q,
                "items": items}

    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, r in enumerate(ex.map(one, jobs), 1):
            if r["items"] is None:
                fail += 1
            res.append(r)
            if i % 200 == 0:
                print(f"  {i:,}/{len(jobs):,} · {time.time()-t0:.0f}초 · 실패 {fail}")
    print(f"수집 완료 {len(res):,}건 · {time.time()-t0:.0f}초 · 실패 {fail}")
    (OUT / "raw.json").write_text(json.dumps(res, ensure_ascii=False),
                                  encoding="utf-8")
    (OUT / "seen.json").write_text(json.dumps(sorted(seen), ensure_ascii=False),
                                   encoding="utf-8")
    return res


def score():
    res = json.loads((OUT / "raw.json").read_text(encoding="utf-8"))
    seen = set(json.loads((OUT / "seen.json").read_text(encoding="utf-8")))

    agg = defaultdict(lambda: {"combo": 0, "ret": 0, "posts": 0, "kw": 0, "new": 0})
    for r in res:
        a = agg[r["aspect"]]
        a["combo"] += 1
        if not r["items"]:
            continue
        win = [it for it in r["items"] if it["in_win"]]
        if win:
            a["ret"] += 1
        for it in win:
            a["posts"] += 1
            if r["aspect"] != "_base" and KW[r["aspect"]] in it["text"]:
                a["kw"] += 1
            if it["text"] not in seen:
                a["new"] += 1

    print(f"\n{'측면':<10}{'조합':>6}{'창내반환':>10}{'창내글':>8}"
          f"{'키워드포함':>11}{'신규글':>9}  판정")
    passed = []
    for asp in ("_base", *KW):
        a = agg.get(asp)
        if not a:
            continue
        ret = a["ret"] / a["combo"] if a["combo"] else 0
        kw = a["kw"] / a["posts"] if a["posts"] else 0
        new = a["new"] / a["posts"] if a["posts"] else 0
        if asp == "_base":
            v = "(기준선)"
        else:
            v = "PASS" if ret >= RET_MIN and kw >= KWHIT_MIN else "FAIL"
            if v == "PASS":
                passed.append(asp)
        print(f"{asp:<10}{a['combo']:>6}{ret:>10.1%}{a['posts']:>8,}"
              f"{kw:>11.1%}{new:>9.1%}  {v}")

    print(f"\n§I-21 통과 측면 {len(passed)}개: {' · '.join(passed) or '없음'}")
    print("등록된 조건: 통과 2개 미만이면 arm B 폐기 → "
          + ("B1 진행" if len(passed) >= 2 else "arm B 폐기"))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    if not a.score:
        collect()
    return score()


if __name__ == "__main__":
    sys.exit(main())
