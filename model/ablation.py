"""Feature-group ablation programme (lane A) — contract: docs/experiment-plan.md E-A.

Two measurements that disagree on purpose: leave-one-group-out says what is lost
when an information source disappears, only-one-group-in says what that source
knows on its own. With overlapping sources the two rank groups differently, and
reporting only one of them is how a redundant feature gets called important.

Thresholds are not here - they live in the plan. What is here is the machinery
that makes the numbers comparable: the same seed-averaged prediction vector, and
a bootstrap that resamples full and ablated models on IDENTICAL indices. Drawing
separate resamples inflates the interval enough to mark every group
"indistinguishable", which reads as a finding and is an artefact.
"""
import numpy as np
from sklearn.metrics import roc_auc_score

from .train import DETERMINISTIC, Encoder, fit_predict

# Group definitions mirror docs/experiment-plan.md E-A. G0 is never ablated;
# the full bench is the confirmed deploy set (train.DEPLOY), NOT the union of
# G1..G5 - that is what keeps every delta on the same footing as the headline.
GROUPS = {
    "G1_competition": ["open_cnt", "open_cnt_r1", "same_uptae_cnt", "same_uptae_r1",
                        "same_group_r1", "other_group_r1", "group_share_r1", "uptae_entropy_r1"],
    "G2_dynamics": ["openings_36m", "closures_36m", "churn_36m", "growth_36m", "close_accel_r1"],
    "G3_prior_survival": ["prior_surv_3y", "prior_surv_1y", "prior_surv_n",
                           "median_tenure_r1", "veteran_share_r1"],
    "G4_access": ["station_dist_m", "stations_500m", "stations_1km", "transfer_dist_m"],
    "G5_grid_physical": ["median_area"],
    "G6_store_attrs": ["site_area"],  # measurement bench only — never in the ranking model
    # G7 trend runs on the 2017-2018 sub-bench only (coverage starts 2016-01).
    "G7_trend": ["trend_12m", "trend_growth"],
}


SEEDS = (0, 1, 2, 3, 4)


def seed_avg_predict(kind, train, test, cols, seeds=SEEDS, params=None):
    """Mean predicted probability over `seeds`. One encoder fit, reused - the
    imputer/scaler does not depend on the model seed."""
    enc = Encoder(cols).fit(train[0])
    use = (0,) if kind in DETERMINISTIC else seeds
    ps = [fit_predict(kind, train, test, seed=s, params=params, enc=enc)[0] for s in use]
    return np.mean(ps, axis=0)


def paired_bootstrap_ci(y, p_full, p_ablated, n_resamples=200, seed=0):
    """(point delta, lo, hi) for AUC(full) - AUC(ablated).

    The point estimate is the full-sample difference; the interval comes from
    resampling. Both models are scored on the same drawn indices, so the shared
    sampling noise cancels instead of being counted twice.
    """
    y = np.asarray(y)
    point = roc_auc_score(y, p_full) - roc_auc_score(y, p_ablated)
    rng = np.random.default_rng(seed)
    n = len(y)
    diffs = []
    for _ in range(n_resamples):
        idx = rng.integers(0, n, n)
        yy = y[idx]
        if yy.min() == yy.max():
            continue                      # degenerate draw carries no AUC
        diffs.append(roc_auc_score(yy, p_full[idx]) - roc_auc_score(yy, p_ablated[idx]))
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return float(point), float(lo), float(hi)


def leave_one_group_out(cols, group):
    """The bench minus one group's columns. Columns the bench does not carry are
    simply absent, so a group defined outside the deploy set drops out cleanly."""
    drop = set(GROUPS[group])
    return [c for c in cols if c not in drop]


def only_one_group_in(cols, group):
    """Just this group's columns (the categorical 업태 encoding rides along in
    Encoder regardless, which is G0 and never ablated)."""
    keep = set(GROUPS[group])
    return [c for c in cols if c in keep]
