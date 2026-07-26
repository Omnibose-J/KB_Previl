"""Feature-group ablation scaffold (lane A) — contract: docs/experiment-plan.md E-A.

Deliberately unimplemented: every function raises so a half-built run cannot
produce a table that looks finished. Fill in against the pre-registered rules
(paired bootstrap, seed-averaged predictions, G0 always included) — do not
change thresholds here; they live in the plan.
"""

# Group definitions mirror docs/experiment-plan.md E-A. G0 is never ablated;
# full = LOC3 exactly (train.LOC3), NOT the union of G1..G5.
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


def leave_one_group_out(group: str, seeds: tuple[int, ...] = (0, 1, 2, 3, 4)):
    """delta-AUC of full-minus-group vs full, on seed-averaged predictions."""
    raise NotImplementedError("see docs/experiment-plan.md E-A method step 2")


def only_one_group_in(group: str, seeds: tuple[int, ...] = (0, 1, 2, 3, 4)):
    """standalone AUC of the group alone (plus G0)."""
    raise NotImplementedError("see docs/experiment-plan.md E-A method step 3")


def paired_bootstrap_ci(pred_full, pred_ablated, y, n_resamples: int = 200):
    """95% CI of the AUC difference; SAME resample indices for both models."""
    raise NotImplementedError("see docs/experiment-plan.md E-A method step 4")


if __name__ == "__main__":
    raise SystemExit("not implemented — run after E-M fixes the winner model")
