"""D2 — 업종 구성 변화가 상가 가격 변화에 선행하는가 (Glaeser 재현, Part F).

§11-D 와 예측변수·통제·검정 절차가 같고 **결과변수만 다르다**. 거기서는
개업 유입률이었고 `past_inflow` 가 거의 다 설명해 남는 분산이 얇았다.
여기서는 법정동 상가 ㎡당 단가의 변화율이다.

임계는 docs/unstructured-plan.md §F-6 에 실행 전 등록되어 있다. §F-0 에
**이번이 마지막 재시도임**을 명시했다 — 기각되면 §11-D 와 묶어 닫는다.

    python -m model.dong_exp
"""
import argparse
import sqlite3
import sys

import numpy as np

from model.dong import K, build
from model.place_exp import (FDR_Q, NBOOT, NPLACEBO, cluster_boot, design,
                             fmt_ci, loyo_r2, ols, placebo_p, zscore)
from pipeline.config import DB_PATH

BASE = ["past_price_growth", "size", "past_inflow"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    panel, miss = build()
    print(f"패널 {len(panel):,}행 · 법정동 {len({r['dong'] for r in panel})} "
          f"· 주소 파싱 실패 {miss:,}")
    if len(panel) < 100:
        print("표본 부족 — SKIP")
        return 1

    rows = [dict(r) for r in panel]
    for r in rows:
        r["place"] = r["dong"]                      # 클러스터 키
        d = r["share_now"] - r["share_prev"]
        for c in range(K):
            r[f"d{c}"] = float(d[c])

    y = np.array([r["price_growth_next"] for r in rows], dtype=float)
    print(f"결과변수 log(price_next/price_now): 평균 {y.mean():+.4f} · SD {y.std():.4f}")
    print(f"통제: {' · '.join(BASE)} · 연도 고정효과")
    print(f"보정: BH FDR q<={FDR_Q} (K={K} 동시검정) · 위약 {NPLACEBO}회\n")

    zscore(rows, BASE + [f"d{c}" for c in range(K)])

    # 기저 모델이 얼마나 설명하는가 — §11-D 에서 past_inflow 가 다 먹었던 전례
    r2_base, n_cv = loyo_r2(rows, BASE, "price_growth_next")
    print(f"기저 LOYO-CV R² {r2_base:+.4f} (n={n_cv})")
    Xb, nb = design(rows, BASE)
    bb = ols(Xb, y)
    for i, nm in enumerate(nb):
        if nm == "const" or nm.startswith("year_"):
            continue
        boot = cluster_boot(rows, BASE, "price_growth_next", i)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        print(f"  {nm:20s} {bb[i]:+.4f}  CI {fmt_ci(boot)}  "
              f"{'0 배제' if (lo > 0 or hi < 0) else '0 포함'}")

    print(f"\n컨셉별 (각각 기저 + 컨셉 1개)")
    res = []
    for c in range(K):
        cols = BASE + [f"d{c}"]
        X, names = design(rows, cols)
        b = ols(X, y)
        i = names.index(f"d{c}")
        boot = cluster_boot(rows, cols, "price_growth_next", i)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        p = 2 * min((boot <= 0).mean(), (boot >= 0).mean())
        res.append({"c": c, "coef": b[i], "lo": lo, "hi": hi,
                    "p": max(p, 1 / NBOOT)})

    res.sort(key=lambda d: d["p"])
    m = len(res)
    for rank, d in enumerate(res, 1):
        d["bh"] = d["p"] * m / rank
    run = 1.0
    passed = []
    for d in reversed(res):
        run = min(run, d["bh"])
        d["bh"] = run
        if run <= FDR_Q:
            passed.append(d)

    con = sqlite3.connect(DB_PATH)
    label = {}
    for c in range(K):
        s = con.execute(
            "SELECT l.bplcnm FROM licence l JOIN shop_concept s ON s.mgtno=l.mgtno "
            "WHERE s.concept=? LIMIT 4", (c,)).fetchall()
        label[c] = " · ".join((x[0] or "") for x in s)
    con.close()

    print(f"{'컨셉':>6s} {'계수':>9s} {'95% CI':>22s} {'p':>7s} {'BH q':>7s}  대표 상호명")
    for d in res[:a.top]:
        print(f"  c{d['c']:02d} {d['coef']:+9.4f} [{d['lo']:+.4f},{d['hi']:+.4f}] "
              f"{d['p']:7.4f} {d['bh']:7.4f}  {label[d['c']][:48]}")

    print(f"\nFDR q<={FDR_Q} 통과: {len(passed)}개")
    ok = False
    if passed:
        for d in sorted(passed, key=lambda x: -abs(x["coef"])):
            print(f"  c{d['c']:02d} {d['coef']:+.4f}  {label[d['c']][:60]}")
        top = max(passed, key=lambda x: abs(x["coef"]))
        cols = BASE + [f"d{top['c']}"]
        X, names = design(rows, cols)
        b = ols(X, y)
        i = names.index(f"d{top['c']}")
        pp, _ = placebo_p(rows, cols, "price_growth_next", i, b[i],
                          [f"d{top['c']}"])
        ok = pp <= 0.05
        print(f"\n위약 대조 (c{top['c']:02d}, 법정동 라벨 셔플 {NPLACEBO}회): "
              f"p={pp:.3f} → {'PASS' if ok else 'FAIL'}")
    else:
        print("  없음 — 보정 후 살아남는 컨셉이 없다.")

    print("\n" + "=" * 60)
    print(f"D2 판정: {'채택' if ok else '기각'}"
          f"   (FDR 통과 {len(passed)}개"
          f"{' · 위약 PASS' if ok else ''})")
    if not ok:
        print("§F-0 에 따라 §11-D 와 묶어 닫는다 — Glaeser 방법은 서울 요식업에서")
        print("재현되지 않는다. 결과변수를 바꿔서도 재현되지 않았다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
