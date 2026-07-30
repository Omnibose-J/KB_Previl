# Two-year horizon decision preregistration

Status: preregistered before measurement.

Date: 2026-07-31

## Goal

Decide whether the product's primary survival horizon should move from three
years to two years. This experiment measures only; it does not change serving,
`kb.db`, grade labels, or public documentation.

## Frozen comparison

The existing three-year reference is copied without recomputation:

| horizon | test window | model AUC | best `prior_surv` baseline | margin | districts improved |
|---|---|---:|---:|---:|---:|
| 3 years | 2023 observable cohort | 0.6369 | 0.5669 | +0.0700 | 24/25 |

Absolute AUC values across horizons are not interpreted as improvement because
the labels, base rates, and observable test windows differ.

## Frozen two-year measurement

- Model: `gbm`
- Features: `DEPLOY` (20 columns)
- Training opening years: 2005–2022
- Test opening years: 2023–2024, restricted by the existing two-year
  observable-denominator rule. With database as-of `2026-07`, the expected
  last eligible opening month is `2024-07`; the actual metadata range and row
  count must be reported.
- Model fitting and split construction must reuse the
  `model.recency` path: `cached_split` plus `fit_predict`.
- Use a dedicated empty model-cache directory for this experiment so an older
  split cannot be reused.

The baseline denominator is frozen as the higher test AUC of
`prior_surv_1y` and `prior_surv_3y`. For either feature, missing values are
replaced by the training-label mean, matching the existing
`baseline_prior_surv` policy. Report both baseline AUCs and which one wins.

The two-year margin is:

`AUC(gbm, DEPLOY) - max(AUC(prior_surv_1y), AUC(prior_surv_3y))`.

## Adoption predicates

All four predicates must pass. One failure means retain the three-year
headline.

- [ ] **A — Relative discrimination:** the unrounded two-year margin is at
  least `+0.0700`.
- [ ] **B — Grade monotonicity:** assign the two-year holdout with the shared
  school-shaped nine-grade boundaries from `pipeline.grade_bands`.
  Tie-preserving deployed assignment is authoritative. Observed survival must
  be non-increasing from grade 1 through grade 9 with zero adjacent
  inversions; no tolerance is allowed.
- [ ] **C — District robustness:** reproduce `model.robustness.lift` within
  each district: compare the top 10% of that district's model scores with the
  district's overall survival, using its existing minimum-size and
  non-degenerate-label rules. At least 24 of 25 districts must have lift
  strictly greater than `1.0`.
- [ ] **D — Temporal separation:** training and test opening-year sets are
  disjoint, the maximum training `open_ym` is earlier than the minimum test
  `open_ym`, and no test metadata cohort key appears in training.

## Required output

Report:

1. The frozen three-year row and measured two-year row:
   `horizon | test window | n | overall survival | AUC | baseline | margin |
   monotonic | districts`.
2. For each of the nine grades:
   `grade | target share | actual n | two-year survival | Wilson 95% CI`.
3. The exact adjacent inversion count and all 25 district lift results.
4. The actual train/test metadata ranges and overlap count.

## Label-overlap diagnostics

These diagnostics do not add or remove an adoption predicate; they qualify the
interpretation of predicate A.

1. On both the two-year experimental split and the current three-year
   diagnostic split, fit the full `DEPLOY` model and four single-feature-drop
   models. Define contribution as
   `AUC(full) - AUC(without feature)` for:
   `prior_surv_1y`, `prior_surv_3y`, `churn_36m`, and `growth_36m`.
   The three-year contribution run is diagnostic only and does not replace
   the frozen three-year headline row above.
2. On the two-year split, fit once without both `prior_surv_1y` and
   `prior_surv_3y`. Compare its AUC with the same frozen best two-year
   `prior_surv` baseline. If its margin falls below `+0.0700`, explicitly state
   that the full model's apparent advantage does not survive removal of the
   label-overlapping prior-survival features.

## Verification contract

- `python -m model.test_leakage`
- `python -m model.asof --selftest-cut`
- `python -m pytest model -q`
- SHA-256 of `kb.db` must be identical before and after the measurement, and
  no `kb.db-wal` or `kb.db-shm` may remain.

## Scope boundaries

- Do not modify or regenerate `kb.db`, `grid_score`, `score_meta`, service
  output, frontend code, or public metric documents.
- Do not alter the thresholds, windows, feature sets, seed, grade shares,
  missing-value policy, or district definition after measurement starts.
- Do not adopt or deploy a two-year horizon without a separate instruction.
- Preserve all pre-existing working-tree changes and commit only this
  preregistration before running the experiment.
