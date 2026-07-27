"""G-1 생존 편향 검정 — 감성 분석의 선결 관문.

폐업한 가게의 블로그 글이 구조적으로 덜 검색된다면, 어떤 감성 점수를 매기든
그 편향에 오염된다. 긍정이라서 살아남은 게 아니라 살아남아서 글이 남은 것을
재게 되기 때문이다. 이 관문을 통과해야 §G-2 수집으로 간다.

설계의 요점은 **두 군의 관측 기간을 같게 맞추는 것**이다. 폐업 시점이 제각각
이면 "폐업 이전"의 길이가 달라져 비교가 성립하지 않는다. 그래서 개업 후
24개월 이상 생존한 점포만 대상으로 하고, 개업 +12~+24개월 창에 쓰인 글만
센다 — 그 창에서는 두 군 모두 영업 중이었다.

임계는 docs/unstructured-plan.md §G-1 에 실행 전 등록되어 있다.

    python -m model.senti_gate
"""
import argparse
import random
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests

from model.dong import ADDR
from pipeline.config import DB_PATH, ENV_PATH

API = "https://openapi.naver.com/v1/search/blog.json"
OPEN_YEARS = (2016, 2019)      # §G-1
PER_ARM = 300                  # 각 군 표본
GU = "마포구"
SEED = 0
NBOOT = 2000
CI_RULE = "폐업 계수 CI가 0 포함"
RATE_RULE = 0.10               # 글 보유율 차이 10%p 이내

_local = threading.local()


def _headers():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return {"X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"]}


def _sess(h):
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update(h)
        _local.s = s
    return s


def ym(y, m):
    return y * 12 + (m or 6)


def pick(con):
    """(mgtno, 동명, 상호명, 개업ym, 폐업여부) — 두 군 각 PER_ARM."""
    rows = []
    for mgtno, nm, addr, oy, om, cy, cm, closed in con.execute(
            "SELECT mgtno, bplcnm, addr, open_y, open_m, close_y, close_m, is_closed "
            "FROM licence WHERE addr LIKE ? AND bplcnm IS NOT NULL "
            "AND open_y BETWEEN ? AND ?", (f"%{GU}%", *OPEN_YEARS)):
        m = ADDR.search((addr or "") + " ")
        if not m or m.group(1) != GU or len(nm.strip()) < 2:
            continue
        o = ym(oy, om)
        c = ym(cy, cm) if (closed == 1 and cy) else None
        # 두 군 모두 관측 창(+12~+24m)에서 영업 중이어야 한다
        if c is not None and c < o + 24:
            continue
        if c is None:
            arm = "생존"                       # 3년 이상 생존
        elif c < o + 36:
            arm = "폐업"                       # 창 이후 3년 내 폐업
        else:
            continue                           # 3년 넘게 살고 나중에 폐업 → 제외
        rows.append((mgtno, m.group(2), nm.strip(), o, arm))

    rnd = random.Random(SEED)
    out = []
    for arm in ("폐업", "생존"):
        pool = [r for r in rows if r[4] == arm]
        rnd.shuffle(pool)
        out += pool[:PER_ARM]
        print(f"  {arm}군 후보 {len(pool):,} → 표본 {min(len(pool), PER_ARM)}")
    return out


def count_in_window(h, dong, name, open_ym, tries=3):
    """개업 +12~+24개월에 쓰인 글 수. -> (n, total, truncated)"""
    lo, hi = open_ym + 12, open_ym + 24
    for a in range(tries):
        try:
            r = _sess(h).get(API, timeout=20, params={
                "query": f"{dong} {name}", "display": 100, "sort": "sim"})
            if r.status_code != 200:
                time.sleep(1 + a)
                continue
            d = r.json()
            n = 0
            for it in d.get("items", []):
                pd = (it.get("postdate") or "").strip()
                if len(pd) != 8:
                    continue
                t = ym(int(pd[:4]), int(pd[4:6]))
                if lo <= t < hi:
                    n += 1
            total = int(d.get("total") or 0)
            return n, total, 1 if total > 100 else 0
        except (requests.RequestException, ValueError):
            time.sleep(1 + a)
    return None, None, None


def ols(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    con = sqlite3.connect(DB_PATH)
    print(f"G-1 생존 편향 검정 · {GU} · 개업 {OPEN_YEARS[0]}~{OPEN_YEARS[1]}")
    print("관측 창 = 개업 +12~+24개월 (두 군 모두 영업 중인 구간)\n")
    sample = pick(con)
    con.close()
    if len(sample) < 200:
        print("표본 부족 — SKIP")
        return 1

    h = _headers()
    t0 = time.time()

    def work(r):
        n, total, trunc = count_in_window(h, r[1], r[2], r[3])
        return r, n, total, trunc

    res = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        for r, n, total, trunc in ex.map(work, sample):
            if n is not None:
                res.append({"arm": r[4], "open": r[3], "n": n,
                            "total": total, "trunc": trunc, "name": r[2]})
    print(f"\n조회 {len(res)}/{len(sample)} · {time.time()-t0:.0f}초")

    closed = [r for r in res if r["arm"] == "폐업"]
    alive = [r for r in res if r["arm"] == "생존"]
    print(f"\n{'':6s} {'n':>5s} {'글수 평균':>10s} {'중앙값':>7s} {'보유율':>8s} {'상한초과':>8s}")
    for nm, g in (("폐업", closed), ("생존", alive)):
        cnt = np.array([x["n"] for x in g], dtype=float)
        rate = float(np.mean(cnt > 0))
        tr = float(np.mean([x["trunc"] for x in g]))
        print(f"{nm:6s} {len(g):5d} {cnt.mean():10.2f} {np.median(cnt):7.1f} "
              f"{rate:8.1%} {tr:8.1%}")

    # 상한 아티팩트 통제 — 100건 상한에 걸린 가게는 관측 창의 글이 잘린다.
    # 상한에 걸리는 비율이 두 군에서 크게 다르면(글 많은 쪽이 더 걸린다) 창
    # 안 글이 체계적으로 덜 잡혀 결과가 뒤집힐 수 있다. 그래서 양쪽 다 전수
    # 관측인 부분집합(total<=100)으로 다시 잰다. 임계는 바꾸지 않는다.
    def verdict(rows, tag):
        cl = [x for x in rows if x["arm"] == "폐업"]
        al = [x for x in rows if x["arm"] == "생존"]
        if len(cl) < 40 or len(al) < 40:
            print(f"\n[{tag}] 표본 부족 (폐업 {len(cl)} · 생존 {len(al)}) — 판정 보류")
            return None
        rc = float(np.mean([x["n"] > 0 for x in cl]))
        ra = float(np.mean([x["n"] > 0 for x in al]))
        gap = abs(rc - ra)
        yv = np.array([np.log1p(x["n"]) for x in rows])
        yrs = sorted({x["open"] // 12 for x in rows})
        cols = [np.ones(len(rows)),
                np.array([1.0 if x["arm"] == "폐업" else 0.0 for x in rows])]
        for yy in yrs[1:]:
            cols.append(np.array([1.0 if x["open"] // 12 == yy else 0.0
                                  for x in rows]))
        X = np.column_stack(cols)
        b = ols(X, yv)
        rng = np.random.default_rng(SEED)
        bt = []
        for _ in range(NBOOT):
            idx = rng.integers(0, len(rows), len(rows))
            try:
                bt.append(ols(X[idx], yv[idx])[1])
            except np.linalg.LinAlgError:
                pass
        lo, hi = np.percentile(bt, [2.5, 97.5])
        ok_ci, ok_rate = (lo <= 0 <= hi), (gap <= RATE_RULE)
        print(f"\n[{tag}]  폐업 {len(cl)} · 생존 {len(al)}")
        print(f"  폐업 계수 {b[1]:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]  "
              f"{'0 포함 PASS' if ok_ci else '0 배제 FAIL'}")
        print(f"  글 보유율 {rc:.1%} vs {ra:.1%} · 차이 {gap:.1%}  "
              f"{'PASS' if ok_rate else 'FAIL'}")
        return ok_ci and ok_rate

    full_ok = verdict(res, "주 분석 · 전체")
    sub = [x for x in res if x["trunc"] == 0]
    sub_ok = verdict(sub, "상한 통제 · total<=100 만")

    rate_c = float(np.mean([x["n"] > 0 for x in closed]))
    rate_a = float(np.mean([x["n"] > 0 for x in alive]))
    gap = abs(rate_c - rate_a)

    # log(1+글수) ~ 폐업 + 개업연도
    rows = closed + alive
    yv = np.array([np.log1p(x["n"]) for x in rows])
    years = sorted({x["open"] // 12 for x in rows})
    cols = [np.ones(len(rows)),
            np.array([1.0 if x["arm"] == "폐업" else 0.0 for x in rows])]
    for yy in years[1:]:
        cols.append(np.array([1.0 if x["open"] // 12 == yy else 0.0 for x in rows]))
    X = np.column_stack(cols)
    b = ols(X, yv)

    rng = np.random.default_rng(SEED)
    boot = []
    for _ in range(NBOOT):
        idx = rng.integers(0, len(rows), len(rows))
        try:
            boot.append(ols(X[idx], yv[idx])[1])
        except np.linalg.LinAlgError:
            pass
    lo, hi = np.percentile(boot, [2.5, 97.5])

    print(f"\n폐업 계수 {b[1]:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
    print(f"글 보유율 차이 {gap:.1%}  (기준 ≤ {RATE_RULE:.0%})")

    ok_ci = lo <= 0 <= hi
    ok_rate = gap <= RATE_RULE
    print("\n" + "=" * 60)
    print(f"최종 판정  전체 {'PASS' if full_ok else 'FAIL'} · "
          f"상한 통제 {'PASS' if sub_ok else ('FAIL' if sub_ok is not None else '보류')}")
    if full_ok and sub_ok:
        print("=> 통과. §G-2 수집으로 간다.")
    else:
        print("=> 미통과. §G-6-1 에 따라 감성 분석을 중단한다.")
        print("   단 편향의 '방향'은 예상과 반대다 — 폐업 가게 글이 더 많다.")
        print("   §6 의 배제 사유를 '역인과(폐업→글 감소)'가 아니라")
        print("   '생존 여부와 글 노출량이 연관됨(방향 무관)'으로 고쳐 적는다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
