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

# --- selection criteria -------------------------------------------------------
# "auc" is round 2's pre-registration (docs/experiment-plan.md E-M) and is kept so
# that result stays reproducible. "decile" is round 3's, registered 2026-07-27
# BEFORE it was run, because round 2 exposed a mis-specification: the gate scored
# AUC while the product consumes the top decile, so a winner can clear the gate
# without moving the number anyone sees (rf did exactly that: +0.0043 AUC,
# 75.0% -> 74.9% top decile).
#
# decile criterion, in full:
#   선발 (내부 검증)  1순위 상위10% 실측 생존율 · 동률 시 십분위 격차 → Brier → 단순한 모델
#   채택 (홀드아웃)   짝지은 부트스트랩 Δ(상위10%) 95% CI 하한 > 0
#                     그리고 점추정 >= +0.5%p  그리고 십분위 단조
# +0.5%p is not invented here: it is the same top-decile movement the extension
# gate already treats as meaningful (docs/experiment-plan.md E-A 편입 기준 3).
MIN_GAIN = 0.003             # criterion "auc": winner - incumbent, holdout AUC
DECILE_MIN_GAIN = 0.005      # criterion "decile": winner - incumbent, holdout top decile
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


def top_decile(y, p):
    o = np.argsort(-np.asarray(p))
    k = max(1, len(y) // 10)
    return float(np.asarray(y)[o[:k]].mean())


def decile_ci(y, p, n_resamples=400, seed=0):
    """Bootstrap band on the top-decile rate. Printed next to the point estimate
    because this metric is far noisier than AUC - it reads one tenth of the rows
    where AUC reads every pair, and a selection made inside the noise band is a
    coin flip wearing a decimal point."""
    rng = np.random.default_rng(seed)
    n = len(y)
    vals = [top_decile(y[i], p[i]) for i in (rng.integers(0, n, n) for _ in range(n_resamples))]
    lo, hi = np.percentile(vals, [2.5, 97.5])
    return float(lo), float(hi)


def paired_bootstrap_decile(y, p_a, p_b, n_resamples=400, seed=0):
    """(point, lo, hi) for topdecile(a) - topdecile(b) on identical resamples."""
    y = np.asarray(y)
    point = top_decile(y, p_a) - top_decile(y, p_b)
    rng = np.random.default_rng(seed)
    n = len(y)
    d = []
    for _ in range(n_resamples):
        i = rng.integers(0, n, n)
        d.append(top_decile(y[i], p_a[i]) - top_decile(y[i], p_b[i]))
    lo, hi = np.percentile(d, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def _key(r, criterion):
    """Sort key. Lower is better; every term is rounded first so a tie is a real
    tie and falls through to the declared tie-breaks rather than to float dust."""
    if criterion == "auc":
        return (-round(r["auc"], 4), round(r["brier"], 4), SIMPLICITY.index(r["kind"]))
    return (-round(r["top"], 4), -round(r["gap"], 4), round(r["brier"], 4),
            SIMPLICITY.index(r["kind"]))


def select(con, cols, criterion):
    """Internal validation only. Returns (winner row, all rows)."""
    train, val = cached_split(con, INNER_TRAIN, INNER_TEST, 3)
    enc = Encoder(cols).fit(train[0])
    yv = val[1]
    print(f"내부 검증  train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} (n={len(train[1]):,}) "
          f"/ val {INNER_TEST[0]}-{INNER_TEST[-1]} (n={len(yv):,}) · 피처 {len(cols)}개")
    print(f"  선발 기준: {'AUC' if criterion == 'auc' else '상위10% 실측 생존율 (동률 시 십분위 격차)'}")
    print(f"  {'후보':<8} {'설정':<44} {'상위10%':>8} {'십분위격차':>10} {'AUC':>8} {'Brier':>8} {'초':>6}")

    rows = []
    for kind in SIMPLICITY:
        for params in GRID[kind]:
            t0 = time.time()
            p, _ = fit_predict(kind, train, val, num=cols, seed=0, params=params, enc=enc)
            d = deciles(yv, p)
            r = {"kind": kind, "params": params, "auc": roc_auc_score(yv, p),
                 "brier": brier_score_loss(yv, np.clip(p, 0, 1)),
                 "top": d[0], "gap": d[0] - d[-1], "p": p}
            rows.append(r)
            print(f"  {kind:<8} {str(params):<44} {r['top']*100:>7.1f}% {r['gap']*100:>9.1f}%p "
                  f"{r['auc']:>8.4f} {r['brier']:>8.4f} {time.time()-t0:>6.1f}", flush=True)

    best = {}
    for r in rows:
        b = best.get(r["kind"])
        if not b or _key(r, criterion) < _key(b, criterion):
            best[r["kind"]] = r
    ranked = sorted(best.values(), key=lambda r: _key(r, criterion))

    print(f"\n  후보별 최고 — 선발 기준 순 (상위10%는 부트스트랩 95% 밴드 동반)")
    for i, r in enumerate(ranked, 1):
        lo, hi = decile_ci(yv, r["p"])
        r["ci"] = (lo, hi)
        print(f"  {i}. {r['kind']:<6} 상위10% {r['top']*100:.1f}% [{lo*100:.1f}, {hi*100:.1f}]  "
              f"격차 {r['gap']*100:.1f}%p  AUC {r['auc']:.4f}  Brier {r['brier']:.4f}  {r['params']}")

    w = ranked[0]
    overlap = [r["kind"] for r in ranked[1:] if r["ci"][1] >= w["ci"][0]]
    print(f"\n  -> 승자 {w['kind']} {w['params']}")
    if overlap:
        print(f"  [검정력 주의] 승자의 95% 밴드와 겹치는 후보: {', '.join(overlap)}")
        print(f"     상위10%는 검증 표본의 1/10(n≈{len(yv)//10:,})만 읽으므로 표준오차가 "
              f"약 {((w['top']*(1-w['top'])/(len(yv)//10))**0.5)*100:.2f}%p다. "
              f"이 밴드 안의 순위는 재현되지 않을 수 있다.")
    return w, rows


def seed_spread(train, test, kind, cols, params, enc, seeds=(0, 1, 2, 3, 4)):
    aucs = [roc_auc_score(test[1], fit_predict(kind, train, test, num=cols, seed=s,
                                               params=params, enc=enc)[0]) for s in seeds]
    return float(np.mean(aucs)), float(np.std(aucs)), float(min(aucs)), float(max(aucs))


def confirm(con, cols, winner, criterion="auc"):
    """The holdout look: winner vs incumbent."""
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

    seed_gap = out["승자"]["seed"][1] + out["현행"]["seed"][1]
    if criterion == "decile":
        point, lo, hi = paired_bootstrap_decile(yte, out["승자"]["p"], out["현행"]["p"])
        thr, unit = DECILE_MIN_GAIN, "%p"
        print(f"\n  짝지은 부트스트랩 Δ상위10% {point*100:+.2f}{unit}  "
              f"95% CI [{lo*100:+.2f}, {hi*100:+.2f}]{unit}")
        print(f"  기준: CI 하한 > 0 ({'O' if lo > 0 else 'X'}) · 점추정 >= +{thr*100:.1f}{unit} "
              f"({'O' if point >= thr else 'X'}) · 십분위 단조 "
              f"({'O' if out['승자']['mono'] else 'X'})")
        aucd, alo, ahi = paired_bootstrap_ci(yte, out["승자"]["p"], out["현행"]["p"])
        print(f"  (참고) 같은 쌍의 ΔAUC {aucd:+.4f} [{alo:+.4f}, {ahi:+.4f}]")
    else:
        point, lo, hi = paired_bootstrap_ci(yte, out["승자"]["p"], out["현행"]["p"])
        thr = MIN_GAIN
        print(f"\n  짝지은 부트스트랩 ΔAUC {point:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
        print(f"  기준: CI 하한 > 0 ({'O' if lo > 0 else 'X'}) · 점추정 >= +{thr} "
              f"({'O' if point >= thr else 'X'}) · 십분위 단조 "
              f"({'O' if out['승자']['mono'] else 'X'})")
    ok = lo > 0 and point >= thr and out["승자"]["mono"]
    print(f"  참고: 시드 AUC 표준편차 합 {seed_gap:.4f}")
    print(f"  -> {'승자 채택' if ok else f'기각: 현행 {INCUMBENT} 유지'}")
    return out, ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="DEPLOY")
    ap.add_argument("--criterion", default="auc", choices=("auc", "decile"),
                    help="auc = 라운드 2 사전 등록 / decile = 라운드 3 사전 등록")
    ap.add_argument("--no-holdout", action="store_true",
                    help="선발만 하고 홀드아웃은 열지 않는다 (승자가 이미 측정된 모델일 때)")
    a = ap.parse_args()
    from .robustness import FEATURE_SETS
    cols = FEATURE_SETS.get(a.features) or [c for c in a.features.split(",") if c]

    con = init()
    print("=" * 78)
    print(f"E-M 모델 토너먼트 — 후보 6종 (XGBoost 미설치로 제외) · 세트 {a.features} "
          f"· 기준 {a.criterion}")
    print("=" * 78)
    winner, _ = select(con, cols, a.criterion)
    if a.no_holdout:
        print("\n홀드아웃 조회 생략 (--no-holdout)")
        return 0
    confirm(con, cols, winner, a.criterion)
    return 0


if __name__ == "__main__":
    sys.exit(main())
