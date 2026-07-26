"""Evaluation harness. Exists before any model does, on purpose.

Split is by cohort year, never random: a random split would put 2019 shops in
both train and test, and neighbouring shops share their cell's history, so the
model would be scored on information it already saw. Recommending a location is
inherently a forecast, and the only honest test of a forecast is a later period.

Three baselines, because "our model gets AUC 0.63" means nothing alone:
  base_rate   - predict the train survival rate for everyone. AUC 0.5 by
                construction; its Brier score is the bar for calibration.
  by_uptae    - predict the train survival rate of that 업태.
  prior_surv  - use the cell's own past cohort survival directly, no learning.
The third is the real competitor: if a model cannot beat "just look at how shops
did here before", it is adding nothing.
"""
import argparse
import sys
from collections import defaultdict

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from pipeline.db import init

from .dataset import build

TRAIN_YEARS = list(range(2013, 2019))     # 2013-2018
TEST_YEARS = list(range(2019, 2023))      # 2019-2022


def load_split(con, train_years, test_years, horizon=3, verbose=True,
               with_trend=False, with_mention=False, gu=None,
               exclude_succession=False):
    overlap = set(train_years) & set(test_years)
    if overlap:
        raise ValueError(f"train/test 연도 겹침: {sorted(overlap)}")
    if max(train_years) >= min(test_years):
        raise ValueError(
            f"시간 분리 위반: train 최대 {max(train_years)} >= test 최소 {min(test_years)}")

    def gather(years):
        X, y, meta = [], [], []
        for yr in years:
            a, b, m, _ = build(con, yr, horizon, with_trend=with_trend,
                               with_mention=with_mention, gu=gu,
                               exclude_succession=exclude_succession)
            X += a
            y += b
            meta += m
            if verbose:
                print(f"    {yr}: {len(b):,}건 생존율 {sum(b)/len(b)*100:.1f}%", flush=True)
        return X, np.array(y), meta

    if verbose:
        print(f"  train {train_years[0]}-{train_years[-1]}")
    Xtr, ytr, mtr = gather(train_years)
    if verbose:
        print(f"  test  {test_years[0]}-{test_years[-1]}")
    Xte, yte, mte = gather(test_years)
    return (Xtr, ytr, mtr), (Xte, yte, mte)


def lift_at_decile(y_true, y_score, q=0.1):
    """Survival rate of the top-decile predictions, relative to overall."""
    n = len(y_true)
    k = max(1, int(n * q))
    idx = np.argsort(-np.asarray(y_score))[:k]
    top = np.asarray(y_true)[idx].mean()
    overall = np.asarray(y_true).mean()
    return top / overall if overall else float("nan")


def score(name, y_true, p, out=None):
    try:
        auc = roc_auc_score(y_true, p)
    except ValueError:
        auc = float("nan")
    br = brier_score_loss(y_true, np.clip(p, 0, 1))
    lift = lift_at_decile(y_true, p)
    print(f"  {name:<14} AUC {auc:.4f}   Brier {br:.4f}   lift@10% {lift:.3f}")
    if out is not None:
        out[name] = {"auc": auc, "brier": br, "lift": lift}
    return auc, br, lift


# ---------------------------------------------------------------- baselines
def baseline_base_rate(Xtr, ytr, Xte):
    return np.full(len(Xte), ytr.mean())


def baseline_by_uptae(Xtr, ytr, Xte):
    agg = defaultdict(list)
    for f, y in zip(Xtr, ytr):
        agg[f["uptae"]].append(y)
    rate = {k: float(np.mean(v)) for k, v in agg.items() if len(v) >= 30}
    g = ytr.mean()
    return np.array([rate.get(f["uptae"], g) for f in Xte])


def baseline_prior_surv(Xtr, ytr, Xte):
    """No learning at all - the cell's own past cohort survival."""
    g = ytr.mean()
    return np.array([(f["prior_surv_3y"] if f["prior_surv_3y"] is not None else g)
                     for f in Xte])


BASELINES = {
    "base_rate": baseline_base_rate,
    "by_uptae": baseline_by_uptae,
    "prior_surv": baseline_prior_surv,
}


def run_baselines(train, test, out=None):
    Xtr, ytr, _ = train
    Xte, yte, _ = test
    print(f"\n베이스라인  (test n={len(yte):,}, 실제 생존율 {yte.mean()*100:.1f}%)")
    for name, fn in BASELINES.items():
        score(name, yte, fn(Xtr, ytr, Xte), out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="split만 확인")
    ap.add_argument("--baselines-only", action="store_true")
    ap.add_argument("--models", default="", help="logit,gbm")
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--assert-beats-baseline", action="store_true")
    ap.add_argument("--min-gain", type=float, default=0.02)
    a = ap.parse_args()

    print(f"train {TRAIN_YEARS}  test {TEST_YEARS}")
    print(f"교집합: {sorted(set(TRAIN_YEARS) & set(TEST_YEARS)) or '없음'}")
    if a.dry:
        if set(TRAIN_YEARS) & set(TEST_YEARS):
            return 1
        print(f"시간 분리 OK: train 최대 {max(TRAIN_YEARS)} < test 최소 {min(TEST_YEARS)}")
        return 0

    con = init()
    print("\n데이터 구성")
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, a.horizon)

    results = {}
    run_baselines(train, test, results)

    if a.baselines_only:
        return 0

    names = [s for s in a.models.split(",") if s] or ["logit", "gbm"]
    from .train import fit_predict
    print("\n모델")
    for nm in names:
        p, _ = fit_predict(nm, train, test)
        score(nm, test[1], p, results)

    if a.assert_beats_baseline:
        best_base = max(results[b]["auc"] for b in BASELINES)
        best_model = max(results[n]["auc"] for n in names)
        gain = best_model - best_base
        print(f"\n최고 베이스라인 AUC {best_base:.4f} · 최고 모델 AUC {best_model:.4f}")
        print(f"개선 {gain:+.4f} (요구 +{a.min_gain})")
        if gain < a.min_gain:
            print("-> FAIL: 베이스라인을 유의하게 이기지 못했다. "
                  "임계·split·지표를 바꾸지 말고 이 결과를 그대로 보고할 것.")
            return 1
        print("-> PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
