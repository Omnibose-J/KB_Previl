# Standard-normal grade bands

> **SUPERSEDED, same day, by `2026-07-30-school-nine-grade-bands.md`.** This
> shape was never served. It was replaced because its tail bins held only ~180
> holdout rows each (CI 11.5pp on grade 1, 7.6pp on grade 10), while the
> school-shaped nine-grade split gives 317 per tail at the same zero-reversal
> property. Kept because the comparison it records is what justified the shape
> that did ship — read it as the runner-up, not as the rule.

**Decision:** On 2026-07-30, serving and current offline grade analyses adopted
ten fixed standard-normal shares cut at 0.5 z-score intervals:
`2.28 / 4.40 / 9.19 / 15.00 / 19.15 / 19.15 / 15.00 / 9.19 / 4.40 / 2.28%`.

**Context:** Equal deciles split a flat 59–60% part of the 2023 holdout into
small adjacent bins and produced a 5th-to-6th grade reversal. Before reading
the comparison outcomes, three candidate shapes were frozen: equal deciles,
the school-style `4-7-12-17-10-10-17-12-7-4`, and the standard-normal
schedule. The deployed model, scores, AUC, and ordering were held constant.

**Why:** The standard-normal schedule removes the observed adjacent-grade
reversal while retaining all 7,915 holdout rows. It yields grade 1 at
80.6% survival (n=180, 95% CI 74.2–85.7%) and grade 10 at 6.8% (n=177,
95% CI 3.9–11.5%). The wider 73.8 percentage-point endpoint gap is a
segmentation consequence, not a model-performance improvement. AUC remains
0.6369, and score rank and recommendation order remain unchanged.

**Rejected:** Equal deciles were rejected for serving labels because they
retain the flat-region reversal. The school-style schedule was compared but
not selected: unlike the standard-normal schedule, it adds a domain-specific
shape without a stronger stated basis. Top-decile lift remains valid only as a
ranking diagnostic in historical and robustness analyses; it is not a serving
grade label.

**Status:** Superseded by [[2026-07-30-school-nine-grade-bands]]
