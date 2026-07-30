# Grade-band migration acceptance criteria

Status: complete with one pre-existing verification concern.

## Goal

Use one fixed school-shaped nine-grade share schedule for both serving
precomputation and offline UI analysis without changing scores, rank order,
AUC, or recommendation ordering.

## Proof checklist

- [x] `pipeline/grade_bands.py` owns the nine grade shares and cumulative
  boundaries. Verify with its behavioral unit tests and call-site inventory.
- [x] Serving precomputation and offline UI analysis both use the shared helper.
  Verify with focused tests and repository search.
- [x] Equal scores remain in one grade even when that shifts a cumulative target
  by one or two rows. Verify with the explicit tied-score failure test and the
  duplicate-cohort curve test.
- [x] Public three-band labels use grade numbers rather than percentile claims.
  Verify with service regression tests and repository search.
- [x] Named documentation and analysis surfaces explain the fixed-before-results
  comparison of equal-decile 10, standard-normal 10, and school-shaped 9;
  reversal removal plus tail sample size; unchanged model/ranking; and endpoint
  uncertainty.
  Verify with scoped contract searches.
- [ ] Non-database gates pass.
  Verify with `python -m pytest service -q`,
  `python -m service.demo_db --audit`, `python -m pipeline.verify`,
  `python -m pipeline.consistency`, `python -m model.test_leakage`, and scoped
  `ruff check`.
- [x] Only after explicit approval: create a recoverable backup, regenerate
  `grid_score` and `score_meta`, then verify row counts, grade shares,
  monotonic observed survival, and the number of districts with at least 20
  Korean-cuisine grade-1 cells, plus database integrity.

## Pre-write evidence from a database copy

- `service.precompute` regenerated 241,776 rows and `model.ui_curves --write`
  regenerated the 20 UI metadata keys without touching the shared database.
- The deployed tie-preserving holdout counts are
  `317,554,951,1344,1584,1345,949,554,317`; the two-row shifts from the direct
  share table change only grade 6 from 57.9% to 58.0% at one-decimal
  precision. Intervals, monotonicity, and the 69.1-point endpoint gap remain.
- Current-grid absolute-boundary shares are
  `4.5,8.2,13.5,20.8,21.2,18.1,10.0,3.3,0.4%`, not the holdout target shares.
  This is population shift under fixed holdout thresholds, not a re-ranking.
- Korean cuisine has at least 20 grade-1 cells in 7 of 25 districts. The user
  chose to continue and retain the existing grade 1–2 recommendation cutoff.
- The copied database passes 115 service tests, the demo audit, consistency
  17/17, leakage checks, and scoped Ruff. `pipeline.verify` remains 7/8 because
  its pre-existing source-count check compares 535,603 licence rows with the
  upstream API count 535,715; this is outside the grade-band change.
- After explicit approval, the shared database was backed up to
  `backups/kb-before-grade9-20260731-000521.db`, regenerated, and checked
  again. It has 241,776 score rows, nine observed grades, monotonic survival,
  a 69.1-point endpoint gap, `quick_check=ok`, and an empty WAL.

## Scope boundaries

- Do not modify `frontend/`, model fitting, ranks, recommendation ordering, or
  the supplied share schedule.
- Do not write `kb.db` before explicit user approval.
- Preserve unrelated work and do not weaken existing tests.
