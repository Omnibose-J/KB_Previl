"""E-M — pick the model on internal validation, confirm it on the holdout once.

Contract: docs/experiment-plan.md E-M. The rule that shapes this file is that
selection and confirmation must not share a dataset. Scoring six families (and
their hyperparameters) against 2019-2022 and then reporting the best of them
would make the holdout a validation set: with ~20 looks at a standard error of
~0.003, a +0.005 "win" is reachable by noise alone. So every choice is made on
the last two training years, and the holdout sees exactly two fits - the winner
and the incumbent.

Everything here is a single seed=0 fit, because a single fit is what
service/precompute.py deploys. The seed spread is reported separately so a gap
smaller than seed noise cannot be read as a win.
"""
import argparse
import sys
import time

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from pipeline.db import init

from .ablation import paired_bootstrap_ci
from .cache import cached_split
from .evaluate import TEST_YEARS, baseline_prior_surv
from .train import CONFIRMED_TRAIN_YEARS, DEPLOY, Encoder, fit_predict

MIN_GAIN = 0.003             # pre-registered: winner - incumbent, holdout AUC
INCUMBENT = "gbm"
INNER_TEST = CONFIRMED_TRAIN_YEARS[-2:]
INNER_TRAIN = CONFIRMED_TRAIN_YEARS[:-2]

# Ordered simplest-first; used only to break an exact AUC+Brier tie.
SIMPLICITY = ["logit", "gbm", "hgb", "et", "rf", "mlp"]

# Hyperparameters are searched here and nowhere else. XGBoost is not installed
# and is deliberately not being installed - it is recorded as an excluded
# candidate so the tournament's coverage is stated rather than implied.
GRID = {
    "logit": [{"C": 0.1}, {"C": 1.0}, {"C": 10.0}],
    "gbm": [{},
            {"n_estimators": 800, "learning_rate": 0.03},
            {"num_leaves": 63, "min_child_samples": 200},
            {"n_estimators": 200, "learning_rate": 0.1}],
    "rf": [{"n_estimators": 300, "min_samples_leaf": 5},
           {"n_estimators": 300, "min_samples_leaf": 20},
           {"n_estimators": 300, "min_samples_leaf": 50}],
    "et": [{"n_estimators": 300, "min_samples_leaf": 5},
           {"n_estimators": 300, "min_samples_leaf": 20},
           {"n_estimators": 300, "min_samples_leaf": 50}],
    "hgb": [{},
            {"learning_rate": 0.03, "max_iter": 800},
            {"max_leaf_nodes": 63, "min_samples_leaf": 200},
            {"learning_rate": 0.1, "max_iter": 200}],
    "mlp": [{"hidden_layer_sizes": (32,), "alpha": 1e-3},
            {"hidden_layer_sizes": (32,), "alpha": 1e-2},
            {"hidden_layer_sizes": (64, 32), "alpha": 1e-3},
            {"hidden_layer_sizes": (64, 32), "alpha": 1e-2}],
}


def deciles(y, p, k=10):
    order = np.argsort(-np.asarray(p))
    y = np.asarray(y)[order]
    n = len(y)
    return [float(y[int(n * i / k):int(n * (i + 1) / k)].mean()) for i in range(k)]


def select(con, cols):
    """Internal validation only. Returns (winner kind, winner params, table)."""
    train, val = cached_split(con, INNER_TRAIN, INNER_TEST, 3)
    enc = Encoder(cols).fit(train[0])
    print(f"내부 검증  train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} (n={len(train[1]):,}) "
          f"/ val {INNER_TEST[0]}-{INNER_TEST[-1]} (n={len(val[1]):,}) · 피처 {len(cols)}개")
    print(f"  {'후보':<8} {'설정':<44} {'AUC':>8} {'Brier':>8} {'초':>6}")

    rows = []
    for kind in SIMPLICITY:
        for params in GRID[kind]:
            t0 = time.time()
            p, _ = fit_predict(kind, train, val, num=cols, seed=0, params=params, enc=enc)
            auc = roc_auc_score(val[1], p)
            br = brier_score_loss(val[1], np.clip(p, 0, 1))
            rows.append({"kind": kind, "params": params, "auc": auc, "brier": br})
            print(f"  {kind:<8} {str(params):<44} {auc:>8.4f} {br:>8.4f} {time.time()-t0:>6.1f}")

    best = {}
    for r in rows:
        b = best.get(r["kind"])
        if not b or r["auc"] > b["auc"]:
            best[r["kind"]] = r
    ranked = sorted(best.values(),
                    key=lambda r: (-round(r["auc"], 4), round(r["brier"], 4),
                                   SIMPLICITY.index(r["kind"])))
    print(f"\n  후보별 최고 (동률 시 Brier -> 단순한 모델 순)")
    for i, r in enumerate(ranked, 1):
        print(f"  {i}. {r['kind']:<6} AUC {r['auc']:.4f}  Brier {r['brier']:.4f}  {r['params']}")
    w = ranked[0]
    print(f"\n  -> 승자 {w['kind']} {w['params']}")
    return w, rows


def seed_spread(train, test, kind, cols, params, enc, seeds=(0, 1, 2, 3, 4)):
    aucs = [roc_auc_score(test[1], fit_predict(kind, train, test, num=cols, seed=s,
                                               params=params, enc=enc)[0]) for s in seeds]
    return float(np.mean(aucs)), float(np.std(aucs)), float(min(aucs)), float(max(aucs))


def confirm(con, cols, winner):
    """The one and only holdout look: winner vs incumbent."""
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, TEST_YEARS, 3)
    enc = Encoder(cols).fit(train[0])
    yte = test[1]
    print(f"\n홀드아웃 확인 {TEST_YEARS[0]}-{TEST_YEARS[-1]} (n={len(yte):,}) — 2회만 본다")

    out = {}
    for tag, kind, params in (("승자", winner["kind"], winner["params"]),
                              ("현행", INCUMBENT, {})):
        p, _ = fit_predict(kind, train, test, num=cols, seed=0, params=params, enc=enc)
        d = deciles(yte, p)
        mono = all(d[i] >= d[i + 1] - 0.02 for i in range(9))
        m, sd, lo, hi = seed_spread(train, test, kind, cols, params, enc)
        out[tag] = {"kind": kind, "params": params, "p": p, "auc": roc_auc_score(yte, p),
                    "brier": brier_score_loss(yte, np.clip(p, 0, 1)), "dec": d, "mono": mono,
                    "seed": (m, sd, lo, hi)}
        r = out[tag]
        print(f"  {tag} {kind:<6} AUC {r['auc']:.4f}  Brier {r['brier']:.4f}  "
              f"상위10% {d[0]*100:.1f}%  하위10% {d[-1]*100:.1f}%  단조 {'O' if mono else 'X'}")
        print(f"       시드 5개 AUC {m:.4f} ± {sd:.4f}  (min {lo:.4f} / max {hi:.4f})")

    prior = roc_auc_score(yte, baseline_prior_surv(train[0], train[1], test[0]))
    print(f"  베이스라인 prior_surv AUC {prior:.4f}")

    if out["승자"]["kind"] == INCUMBENT and out["승자"]["params"] == {}:
        print("\n  승자 = 현행 gbm 기본 설정 — 비교 대상이 같아 부트스트랩 생략")
        return out, False

    point, lo, hi = paired_bootstrap_ci(yte, out["승자"]["p"], out["현행"]["p"])
    seed_gap = out["승자"]["seed"][1] + out["현행"]["seed"][1]
    ok = lo > 0 and point >= MIN_GAIN and out["승자"]["mono"]
    print(f"\n  짝지은 부트스트랩 ΔAUC {point:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
    print(f"  기준: CI 하한 > 0 ({'O' if lo > 0 else 'X'}) · 점추정 >= +{MIN_GAIN} "
          f"({'O' if point >= MIN_GAIN else 'X'}) · 십분위 단조 "
          f"({'O' if out['승자']['mono'] else 'X'})")
    print(f"  참고: 시드 표준편차 합 {seed_gap:.4f} — 격차가 이보다 작으면 시드 노이즈와 구분 안 됨")
    print(f"  -> {'승자 채택' if ok else '기각: 현행 gbm 유지'}")
    return out, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="DEPLOY")
    a = ap.parse_args()
    from .robustness import FEATURE_SETS
    cols = FEATURE_SETS.get(a.features) or [c for c in a.features.split(",") if c]

    con = init()
    print("=" * 78)
    print(f"E-M 모델 토너먼트 — 후보 6종 (XGBoost 미설치로 제외) · 세트 {a.features}")
    print("=" * 78)
    winner, _ = select(con, cols)
    confirm(con, cols, winner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
