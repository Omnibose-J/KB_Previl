# Recovery model evaluation boundary

**Decision:** On 2026-07-28, M2 adopted a three-way chronological evaluation
by observed closure year: train on 2005–2021, derive calibration bins on 2022,
and open 2023 once as the final holdout.

**Context:** The target is succession within three months after a closure, so
opening year is not the event-time boundary. Observed succession also has
strong base-rate drift, which makes a random split and same-cohort calibration
optimistic.

**Why:** A separate calibration year prevents holdout labels from setting the
probabilities later scored on that holdout. Features are reconstructed at
`close_ym - 1` and limited to the existing observable `LOC2` location features
except `open_month`, which is not part of the W7 candidate contract. M2 is
adopted only if holdout AUC exceeds the train-only industry baseline by at
least 0.005 and its calibrated Brier score is no worse than the previous-year
observed-rate constant.

**Rejected:** Random splitting was rejected because neighboring records and
calendar regimes would cross the boundary. Calibrating and scoring on 2023 was
rejected because it would reuse holdout outcomes. Opening-year splitting was
rejected because the target event begins at closure. Post-closure fields,
tenure, chain sequence, and candidate-only area were rejected because they
either leak the target or cannot be reproduced by the W7 request contract.

**Status:** Active
