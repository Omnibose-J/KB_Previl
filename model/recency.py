"""Does the grade still work on the newest cohorts, and at shorter horizons?

The confirmed benchmark verifies one cell: 3-year survival of 2023 openings.
That cell throws away 5,540 of the 13,455 shops that opened in 2023 - they have
not had three years yet - and it cannot see 2024 or 2025 at all. A judge asking
"you trained on a decade that includes COVID; does this still hold now?" has no
answer in the current evidence.

Shortening the horizon is what unlocks those cohorts, because the observable
denominator moves with it: a 2024 opening has a 1-year verdict but not a 3-year
one. The same shift also lets the training window advance, since time separation
is a constraint between train and test years, not an absolute date.

This is a stability check, not a tuning knob. The horizons are not compared to
pick a winner - each is judged on its own pre-registered predicates, and a cell
that fails is reported as failed. Nothing here changes the deployed model or the
headline 3-year numbers.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .backtest import deciles
from .cache import cached_split
from .evaluate import baseline_prior_surv
from .horizon import grades
from .train import DEPLOY, WINNER, fit_predict

# (label, horizon, train years, test years). Train always ends before test.
# 2005 is the confirmed start (E1); the end moves with the test cohort.
CELLS = [
    ("H3-2023", 3, range(2005, 2023), [2023]),   # confirmed headline cell
    ("H2-2023", 2, range(2005, 2023), [2023]),
    ("H2-2024", 2, range(2005, 2024), [2024]),
    ("H1-2024", 1, range(2005, 2024), [2024]),
    ("H1-2025", 1, range(2005, 2025), [2025]),
]

BOOT = 400
SEED = 20260730

# Pre-registered predicates, fixed before the first run.
MONO_TOL = 0.02          # a decile may sit 2%p below its neighbour without breaking monotonicity


def decile_gap(y, p, k=10):
    ds = deciles(y, p, k)
    return ds[0][2] - ds[-1][2], ds


def boot_gap_ci(y, p, k=10, n=BOOT, seed=SEED):
    """Percentile CI for the top-minus-bottom decile gap.

    Deciles are recut inside every resample: the cut points are part of the
    statistic, so holding them fixed would understate the spread.
    """
    rng = np.random.default_rng(seed)
    y, p = np.asarray(y), np.asarray(p)
    gaps = np.empty(n)
    for b in range(n):
        idx = rng.integers(0, len(y), len(y))
        gaps[b] = decile_gap(y[idx], p[idx], k)[0]
    return float(np.percentile(gaps, 2.5)), float(np.percentile(gaps, 97.5))


def run_cell(con, label, h, train_years, test_years, cols, model):
    train, test = cached_split(con, list(train_years), list(test_years), h, verbose=False)
    y = test[1]
    p, _ = fit_predict(model, train, test, num=cols)

    auc = roc_auc_score(y, p)
    prior = roc_auc_score(y, baseline_prior_surv(train[0], train[1], test[0]))
    k = 10 if len(y) >= 5000 else 5
    gap, ds = decile_gap(y, p, k)
    lo, hi = boot_gap_ci(y, p, k)
    g = grades(p, k)
    obs = [float(y[g == i].mean()) for i in range(1, k + 1)]
    mono = all(obs[i] >= obs[i + 1] - MONO_TOL for i in range(k - 1))

    passed = auc > prior and mono and lo > 0
    print(f"  {label:<9} h={h}y  train {min(train_years)}-{max(train_years)} "
          f"({len(train[1]):,})  test {test_years[0]} ({len(y):,})")
    print(f"            전체생존 {y.mean()*100:.1f}%  AUC {auc:.4f} "
          f"(prior_surv {prior:.4f})  {k}분위 단조 {'O' if mono else 'X'}")
    print(f"            상위 {ds[0][2]*100:.1f}%  하위 {ds[-1][2]*100:.1f}%  "
          f"격차 {gap*100:.1f}%p  95% CI [{lo*100:.1f}, {hi*100:.1f}]  "
          f"→ {'통과' if passed else '기각'}")
    return {"label": label, "h": h, "auc": auc, "prior": prior, "gap": gap,
            "ci": (lo, hi), "mono": mono, "n": len(y), "obs": obs,
            "overall": float(y.mean()), "passed": passed}


def main():
    ap = argparse.ArgumentParser(
        description="horizon × 최신 코호트 안정성 검정")
    ap.add_argument("--model", default=WINNER)
    ap.add_argument("--features", default="DEPLOY")
    ap.add_argument("--only", help="쉼표구분 셀 라벨 (예: H1-2024)")
    a = ap.parse_args()

    from .robustness import FEATURE_SETS
    cols = FEATURE_SETS.get(a.features) or [c for c in a.features.split(",") if c]
    cells = CELLS
    if a.only:
        want = {s.strip() for s in a.only.split(",")}
        cells = [c for c in CELLS if c[0] in want]

    con = init()
    print(f"horizon × 최신 코호트 — 모델 {a.model} · 세트 {a.features}({len(cols)})")
    print(f"사전 등록 판정: AUC > prior_surv · 십분위 단조(허용 {MONO_TOL*100:.0f}%p) "
          f"· 격차 부트스트랩 95% CI 하한 > 0\n")

    res = [run_cell(con, *c, cols, a.model) for c in cells]

    print(f"\n  요약")
    print(f"  {'셀':<9} {'n':>7} {'전체':>7} {'AUC':>7} {'격차':>8} {'판정':>6}")
    for r in res:
        print(f"  {r['label']:<9} {r['n']:>7,} {r['overall']*100:>6.1f}% "
              f"{r['auc']:>7.4f} {r['gap']*100:>7.1f}%p {'통과' if r['passed'] else '기각':>6}")

    n_pass = sum(r["passed"] for r in res)
    print(f"\n  {n_pass}/{len(res)} 셀 통과")
    fails = [r["label"] for r in res if not r["passed"]]
    if fails:
        print(f"  기각된 셀: {', '.join(fails)} — 해당 조합은 등급을 제시하지 않는다.")
    elif len(res) < len(CELLS):
        # a partial run cannot license the whole-grid claim; say only what was run
        skipped = ", ".join(c[0] for c in CELLS if c[0] not in {r["label"] for r in res})
        print(f"  부분 실행 — 미실행 셀: {skipped}. 전체 판정은 --only 없이 재실행해야 한다.")
    else:
        print("  등급은 horizon 1·2·3년과 2023~2025 코호트 전부에서 유효하다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
