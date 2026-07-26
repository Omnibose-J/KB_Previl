"""E3 — 1-year and 5-year horizons. Contract: docs/experiment-plan.md E3.

The 3-year label is a product decision as much as a modelling one, and the UI
wants a survival curve rather than a single verdict. This asks whether the same
ranking holds at other horizons, which is the precondition for showing one grade
with several curves instead of three unrelated grades.

The observable-denominator rule carries over unchanged: a shop only enters a
horizon's cohort once that many years have actually elapsed since it opened, so
the 5-year test window necessarily ends earlier than the 1-year one. Comparing
the two on different windows is intended - forcing them onto the same window
would mean scoring the 5-year model on shops with no 5-year verdict.
"""
import argparse
import sys

import numpy as np
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .cache import cached_split
from .evaluate import TEST_YEARS, baseline_prior_surv
from .train import CONFIRMED_TRAIN_YEARS, DEPLOY, WINNER, fit_predict

# 1y can look further forward than 3y (more cohorts have elapsed); 5y must stop
# earlier. Both follow from the observable denominator, not from tuning.
WINDOWS = {1: list(range(2019, 2025)), 3: TEST_YEARS, 5: [2019, 2020, 2021]}


def grades(p, k=10):
    order = np.argsort(-np.asarray(p))
    g = np.empty(len(p), dtype=int)
    n = len(p)
    for i in range(k):
        g[order[int(n * i / k):int(n * (i + 1) / k)]] = i + 1
    return g


def run(con, h, cols, model):
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, WINDOWS[h], h)
    y = test[1]
    p, _ = fit_predict(model, train, test, num=cols)
    auc = roc_auc_score(y, p)
    prior = roc_auc_score(y, baseline_prior_surv(train[0], train[1], test[0]))
    k = 10 if len(y) >= 5000 else 5
    g = grades(p, k)
    obs = [float(y[g == i].mean()) for i in range(1, k + 1)]
    mono = all(obs[i] >= obs[i + 1] - 0.02 for i in range(k - 1))
    print(f"  {h}년  test {WINDOWS[h][0]}-{WINDOWS[h][-1]} n={len(y):,}  "
          f"전체생존 {y.mean()*100:.1f}%  AUC {auc:.4f} (prior_surv {prior:.4f})  "
          f"{k}분위 단조 {'O' if mono else 'X'}")
    print(f"        등급별 실측: " + " · ".join(f"{v*100:.1f}" for v in obs))
    return {"h": h, "auc": auc, "prior": prior, "mono": mono, "obs": obs,
            "beats": auc > prior, "meta": test[2], "grade": g, "n": len(y)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=WINNER)
    a = ap.parse_args()
    con = init()
    cols = list(DEPLOY)
    print(f"E3 horizon 1년 / 3년 / 5년 — 모델 {a.model} · 세트 DEPLOY({len(cols)})")

    res = {h: run(con, h, cols, a.model) for h in (3, 1, 5)}

    print(f"\n  3년 등급과의 순위 일치 (Spearman ρ, 공통 점포 기준)")
    base = {(m["grid_id"], m["open_ym"]): g for m, g in zip(res[3]["meta"], res[3]["grade"])}
    for h in (1, 5):
        pairs = [(base[k], g) for k, g in
                 (((m["grid_id"], m["open_ym"]), g) for m, g in
                  zip(res[h]["meta"], res[h]["grade"])) if k in base]
        if len(pairs) < 100:
            print(f"    {h}년: 공통 표본 {len(pairs)}건 — 비교 불가")
            continue
        rho = spearmanr([x for x, _ in pairs], [y for _, y in pairs]).statistic
        print(f"    {h}년 vs 3년  ρ={rho:.3f}  (공통 {len(pairs):,}건)  "
              f"{'>= 0.8 — UI는 등급 하나 + horizon별 곡선으로 단순화 가능' if rho >= 0.8 else '< 0.8 — 등급을 horizon별로 따로 제시해야 한다'}")

    print(f"\n  판정 (사전 등록: 각 horizon에서 모델 > prior_surv 그리고 등급별 실측 단조)")
    for h in (1, 5):
        ok = res[h]["beats"] and res[h]["mono"]
        print(f"    {h}년 horizon: {'통과' if ok else '기각 — 해당 horizon은 모델 없이 실측 코호트 곡선만 제공'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
