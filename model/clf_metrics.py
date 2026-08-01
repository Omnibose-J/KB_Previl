"""Thresholded classification metrics for the horizon/feature-set spectrum.

AUC is threshold-free, but reviewers ask for precision/recall/F1. Those need a
cut point, and picking one on the holdout would be tuning on the test set. So
every threshold here is derived from TRAIN predictions only, then applied to
the holdout unchanged:

  t50    fixed 0.5
  base   quantile such that predicted-positive share == train survival rate
  f1max  threshold maximizing survive-class F1 on train

Survive-class F1 is inflated by the base rate (an all-survive classifier
already scores F1 0.88 at h=1), so every block prints that baseline first and
both classes are reported. Citation rules live in docs/model-findings.md 32:
never quote survive-F1 without the all-survive baseline, and always label the
horizon, feature set, and holdout year.

Measurement only - nothing here feeds the deployed model or grid_score.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import (accuracy_score, balanced_accuracy_score,
                             f1_score, precision_score, recall_score,
                             roc_auc_score)

from pipeline.db import init

from .cache import cached_split
from .train import WINNER, fit_predict

# (label, horizon, train years, test years, feature set). The NUM2 rows are
# the ceiling lineage (site_area included - store attribute, never ranking);
# the DEPLOY row is the shipped ranking model for reference.
CELLS = [
    ("H1-2025", 1, range(2005, 2025), [2025], "NUM2"),
    ("H1-2024", 1, range(2005, 2024), [2024], "NUM2"),
    ("H2-2024", 2, range(2005, 2024), [2024], "NUM2"),
    ("H3-2023", 3, range(2005, 2023), [2023], "NUM2"),
    ("H3-2023", 3, range(2005, 2023), [2023], "DEPLOY"),
]


def block(name, y, yhat):
    ps = precision_score(y, yhat, pos_label=1, zero_division=0)
    rs = recall_score(y, yhat, pos_label=1, zero_division=0)
    fs = f1_score(y, yhat, pos_label=1, zero_division=0)
    pc = precision_score(y, yhat, pos_label=0, zero_division=0)
    rc = recall_score(y, yhat, pos_label=0, zero_division=0)
    fc = f1_score(y, yhat, pos_label=0, zero_division=0)
    print(f"    [{name}] 생존 P {ps:.4f} R {rs:.4f} F1 {fs:.4f} | "
          f"폐업 P {pc:.4f} R {rc:.4f} F1 {fc:.4f} | "
          f"macro-F1 {(fs + fc) / 2:.4f} acc {accuracy_score(y, yhat):.4f} "
          f"bal-acc {balanced_accuracy_score(y, yhat):.4f}")


def best_f1_threshold(y, p):
    # scan train-score quantiles; coarse on purpose - a finer grid tunes noise
    ts = np.unique(np.quantile(p, np.linspace(0.01, 0.99, 99)))
    best_t, best_f = 0.5, -1.0
    for t in ts:
        f = f1_score(y, (p >= t).astype(int), zero_division=0)
        if f > best_f:
            best_t, best_f = float(t), f
    return best_t


def run_cell(con, label, h, train_years, test_years, feats, model):
    from .robustness import FEATURE_SETS
    cols = FEATURE_SETS[feats]
    train, test = cached_split(con, list(train_years), list(test_years), h,
                               verbose=False)
    y_te = np.asarray(test[1])
    p_te, _ = fit_predict(model, train, test, num=cols)
    p_tr, _ = fit_predict(model, train, train, num=cols)  # threshold source
    y_tr = np.asarray(train[1])

    base = y_tr.mean()
    t_base = float(np.quantile(p_tr, 1 - base))
    t_f1 = best_f1_threshold(y_tr, p_tr)

    print(f"\n{label} · {feats} · h={h}y · test {test_years[0]} "
          f"(n={len(y_te):,}, 생존율 {y_te.mean() * 100:.1f}%)  "
          f"AUC {roc_auc_score(y_te, p_te):.4f}")
    print(f"    임계값(전부 train에서 결정): base-rate {t_base:.4f} · f1max {t_f1:.4f}")
    block("전원 생존 예측(베이스라인)", y_te, np.ones_like(y_te))
    block("t=0.50", y_te, (p_te >= 0.5).astype(int))
    block(f"t=base({t_base:.3f})", y_te, (p_te >= t_base).astype(int))
    block(f"t=f1max({t_f1:.3f})", y_te, (p_te >= t_f1).astype(int))


def main():
    ap = argparse.ArgumentParser(
        description="horizon × 피처셋 스펙트럼의 임계 기반 분류 지표")
    ap.add_argument("--model", default=WINNER)
    ap.add_argument("--only", help="쉼표구분 셀 라벨 (예: H1-2025)")
    a = ap.parse_args()

    cells = CELLS
    if a.only:
        want = {s.strip() for s in a.only.split(",")}
        cells = [c for c in CELLS if c[0] in want]

    con = init()
    print(f"분류 지표 — 모델 {a.model} · 임계값은 train 예측에서만 결정")
    for c in cells:
        run_cell(con, *c, a.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
