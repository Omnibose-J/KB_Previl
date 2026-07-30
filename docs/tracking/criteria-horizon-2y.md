# Two-year horizon decision preregistration

Status: **measured and REJECTED 2026-07-31.** Three of the four predicates
failed; the three-year headline is retained. The outcome is recorded in
`## Result` at the bottom of this file. The predicates below are reproduced
exactly as they were committed before measurement (5fb197e) — nothing in the
frozen section was edited afterwards.

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

## Result — measured 2026-07-31, REJECTED

| horizon | test window | n | overall | AUC | best baseline | margin | monotonic | districts |
|---|---|---:|---:|---:|---:|---:|:-:|---:|
| 3 years (frozen) | 2023-01–07 | 7,915 | 58.6% | 0.6369 | 0.5669 (`prior_surv_3y`) | **+0.0700** | O | 24/25 |
| 2 years (measured) | 2023-01–2024-07 | 21,391 | 68.7% | 0.6507 | 0.5937 (`prior_surv_1y`) | **+0.0571** | X (1) | 21/25 |

- **A — FAIL.** 0.65070636 − 0.59365224 = **+0.05705** < +0.0700.
- **B — FAIL.** One adjacent inversion: grade 3 76.1% < grade 4 77.3%.
- **C — FAIL.** 21/25 districts with lift > 1.0 (강북 0.921 · 동대문 0.961 ·
  성북 0.989 · 종로 0.966 fail).
- **D — PASS.** Train 2005-01–2022-12, test 2023-01–2024-07, zero cohort-key
  overlap.

Two-year survival by grade (school-shaped nine-grade boundaries):

| grade | share | n | 2y survival | Wilson 95% CI |
|---:|---:|---:|---:|---|
| 1 | 4.0% | 856 | 84.9% | 82.4–87.2% |
| 2 | 7.0% | 1,497 | 79.8% | 77.6–81.7% |
| 3 | 12.0% | 2,567 | 76.1% | 74.4–77.7% |
| 4 | 17.0% | 3,636 | **77.3%** | 75.9–78.6% |
| 5 | 20.0% | 4,279 | 72.3% | 70.9–73.6% |
| 6 | 17.0% | 3,637 | 69.8% | 68.2–71.2% |
| 7 | 12.0% | 2,567 | 62.7% | 60.8–64.5% |
| 8 | 7.0% | 1,496 | 42.4% | 39.9–44.9% |
| 9 | 4.0% | 856 | 15.4% | 13.2–18.0% |

### Why this experiment existed, and what it settled

The two-year horizon was proposed for three reasons: users of this service are
about to sign a *first* lease rather than renew, the two-year column has a
fully-judged 2023 cohort where the three-year one is only half-judged, and the
raw AUC is visibly higher. The third reason was openly cosmetic, which is
precisely why the predicates were frozen before measurement.

The measurement settled it in the direction the cosmetic reason could not see:
**raw AUC did rise (0.6369 → 0.6507) while the margin over the baseline fell
(+0.0700 → +0.0571).** The two-year task is easier — overall survival is 68.7%
against 58.6% — so the naive "look at how shops did here before" predictor gets
better too, and it gains more than the model does. Quoting 0.6507 as an
improvement would have advertised a *weaker* result with a *larger* number.

The label-overlap diagnostic clears the priors of blame: dropping both
`prior_surv_1y` and `prior_surv_3y` moved the two-year AUC to 0.65076 and the
margin to +0.05711 — marginally *up*, not down. The two-year shortfall is real,
not an artefact of features that overlap the label.

Note also that the two-year grade curve is not monotonic while the three-year
one is, and district lift drops from 24/25 to 21/25. The horizon that looked
better on the headline number is worse on every structural check.

**Decision: retain the three-year horizon.** `docs/model-findings.md` §23-B
("horizon 간 AUC 를 비교하지 말 것") stands unchanged and is now backed by a
measurement rather than by reasoning alone.
