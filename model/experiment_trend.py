"""Does search-trend data actually improve survival prediction?

The comparison has to be fair or it proves nothing, so:
  - one dataset is built ONCE with trend fields attached
  - both arms train on exactly the same rows, the same years, the same models
  - the only difference is whether the two trend columns are in the feature list

Training starts at 2017 because DataLab series begin 2016-01 and the trend
feature needs 12 months of lookback. That shrinks the sample relative to the
main model, which is why the no-trend arm is re-run here rather than compared
against the previously reported 0.6327 - comparing across different samples
would be the easy way to manufacture an improvement.

If trend does not help, that is the finding. Do not tune until it does.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from pipeline.db import init

from .evaluate import BASELINES, lift_at_decile, load_split
from .train import NUM, TREND, fit_predict

TRAIN_YEARS = [2017, 2018]
TEST_YEARS = [2019, 2020, 2021, 2022]


def report(name, y, p):
    auc = roc_auc_score(y, p)
    br = brier_score_loss(y, np.clip(p, 0, 1))
    lf = lift_at_decile(y, p)
    print(f"  {name:<22} AUC {auc:.4f}   Brier {br:.4f}   lift@10% {lf:.3f}")
    return auc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--min-gain", type=float, default=0.005)
    a = ap.parse_args()

    con = init()
    print(f"train {TRAIN_YEARS}  test {TEST_YEARS}   (트렌드 lookback 때문에 2017년부터)")
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, a.horizon,
                             verbose=True, with_trend=True)
    Xtr, ytr, _ = train
    Xte, yte, _ = test

    cov_tr = sum(1 for f in Xtr if f.get("trend_12m") is not None) / len(Xtr)
    cov_te = sum(1 for f in Xte if f.get("trend_12m") is not None) / len(Xte)
    print(f"\n트렌드 피처 보유율  train {cov_tr*100:.1f}%  test {cov_te*100:.1f}%")

    print(f"\n베이스라인 (test n={len(yte):,}, 실제 생존율 {yte.mean()*100:.1f}%)")
    for nm, fn in BASELINES.items():
        report(nm, yte, fn(Xtr, ytr, Xte))

    print("\n동일 표본 · 동일 모델 · 피처셋만 다름")
    res = {}
    for kind in ("logit", "gbm"):
        for label, cols in (("without trend", NUM), ("with trend", NUM + TREND)):
            p, _ = fit_predict(kind, train, test, num=cols)
            res[(kind, label)] = report(f"{kind} {label}", yte, p)

    print("\n트렌드 추가 효과")
    ok = False
    for kind in ("logit", "gbm"):
        d = res[(kind, "with trend")] - res[(kind, "without trend")]
        print(f"  {kind:<6} AUC {res[(kind,'without trend')]:.4f} -> "
              f"{res[(kind,'with trend')]:.4f}   ({d:+.4f})")
        ok = ok or d >= a.min_gain

    print()
    if ok:
        print(f"-> 검색 트렌드가 예측력을 높였다 (기준 +{a.min_gain})")
    else:
        print(f"-> 검색 트렌드는 유의한 개선을 주지 못했다 (기준 +{a.min_gain}). "
              "이 결과를 그대로 기록한다 — 튜닝으로 뒤집지 않는다.")

    # coefficient direction, for interpretation
    from .train import weights
    pairs, _, _ = weights(train, top=40, num=NUM + TREND)
    tr = [(n, c) for n, c in pairs if n in TREND]
    if tr:
        print("\n트렌드 피처 계수 (양수=생존↑)")
        for n, c in tr:
            print(f"  {n:<16} {c:>+8.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
