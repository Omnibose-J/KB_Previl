# Address tenancy grain and missing-floor policy

**Decision:** On 2026-07-28, `addr_tenancy` adopted the observed
`licence.addr × licence.uptae` grain, month-level intervals, and no inferred
floor for addresses without a floor token.

**Context:** The existing `flag_succession` positive proxy uses the same
address and industry. Licence dates are available only as year and month, and
only 117,433 of 535,603 rows (21.9%) carry an observable floor marker.

**Why:** Keeping the legacy grain makes the new positive label directly
comparable while extending it with explicit negatives and an excluded 4–5
month band. Retaining the source address preserves observed floor detail.
Leaving an absent floor absent avoids assigning a permit to an invented unit.

**Rejected:** Address-only chains across industries were rejected because they
would change the legacy label's entity definition. Daily thresholds were
rejected because the source has no day observations. Parcel/base-address
merging and floor imputation were rejected because neither has a verified
source mapping.

**Status:** Active
