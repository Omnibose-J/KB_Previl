# Adopt refreshed licence source lineage

**Decision:** On 2026-07-31, adopt the metrics and serving artifacts rebuilt
from 535,715 Seoul general-restaurant licence rows.

**Context:** The live source advanced by 112 rows from the previous 535,603-row
snapshot and corrected model-relevant fields on existing records. Although most
new rows were 2026 registrations, the normalized training split changed from
193,095 to 193,107 rows. The 2023 holdout membership and labels remained fixed
at 7,915 rows.

**Why:** The refresh restores the mandatory `pipeline.verify` source-count
gate and keeps every downstream table on one source lineage. The rebuilt
holdout AUC is 0.638256. Grade 1 remains 80.1% (n=317,
CI 75.4–84.2%); grade 9 becomes 10.1% (n=317, CI 7.2–13.9%); the endpoint
gap becomes 70.0 percentage points. Scored coverage remains 20,148 grids and
`grid_score` remains 241,776 rows, while the full grid inventory increases by
one to 23,573.

The downstream M2 succession model also remains adopted after rebuilding:
holdout AUC 0.7443 versus the 0.6139 industry baseline, and calibrated Brier
0.1140 versus the 0.1295 previous-year rate constant.

**Rejected:** Rolling back to the stale source was rejected because it would
make the live-count gate fail again. Filtering corrected historical rows,
changing the split, moving grade shares, or changing the seed to recover the
old headline was rejected because each would tune the process to a desired
answer instead of preserving the source-of-truth rebuild.

**Consequence:** Current documents cite AUC 0.6383, grade 9 at 10.1% with its
confidence interval, and a 70.0-point endpoint gap. Historical experiment
records retain their original snapshot values and point to the refreshed
lineage in `docs/model-findings.md` §29.

**Status:** Active
