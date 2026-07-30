# School-shaped nine-grade bands

**Decision:** On 2026-07-30, serving and current offline grade analyses adopted
nine fixed shares: `4 / 7 / 12 / 17 / 20 / 17 / 12 / 7 / 4%`.

**Context:** Three shapes were fixed and compared on the same gbm · LOC2 ·
train 2005–2022 / test 2023 scores: equal-decile 10, standard-normal 10, and
school-shaped 9. The model, features, scores, AUC, and ordering were held
constant.

**Why:** Both alternative shapes remove the adjacent-grade reversal in the
flat middle of the holdout. The school-shaped nine-grade schedule also keeps
317 observations in each tail, compared with 180 and 177 under the
standard-normal ten-grade schedule. Its observed survival is monotonic from
80.1% in grade 1 to 11.0% in grade 9. The 69.1 percentage-point endpoint gap
is a segmentation consequence, not a model-performance improvement. AUC
remains 0.6369, and score rank and recommendation order remain unchanged.
The pure boundary contract lives in `pipeline.grade_bands`, so serving and
offline analysis share one implementation without importing `model.*` on an
HTTP request path.

**Recommendation cutoff:** Keep the UI recommendation cutoff at grades 1–2.
With the new absolute boundaries, Korean cuisine has at least 20 grade-1 cells
in only 7 of 25 districts; grade 1 alone would force padding in the other 18.

**Rejected:** Equal-decile 10 retains the middle reversal. Standard-normal 10
removes the reversal but leaves substantially smaller tail samples and wider
tail uncertainty. Historical top-decile diagnostics remain valid ranking
diagnostics; they are not serving-grade labels.

**Status:** Active
