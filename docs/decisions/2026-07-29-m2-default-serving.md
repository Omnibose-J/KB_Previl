# M2 as the default succession source

**Decision:** On 2026-07-29, serve `m2` as the default succession-probability source while retaining `constant` only as an explicit `KB_RECOVERY_SOURCE` rollback.

**Context:** The production SQLite database now contains 229,356 lineage-checked `succession_score` rows. The former default of `constant=0.4` materially understated goodwill-loss cost compared with the measured M2 probabilities.

**Why:** Both `/estimate` and `/compare` already share the same source-selection boundary. Changing that boundary's default activates the measured source without duplicating endpoint logic, while existing M2 table and lineage checks continue to fail loudly.

**Rejected:** Keeping `constant` as the implicit default was rejected because it silently serves an unvalidated mock value. Falling back from missing or invalid M2 data to `constant` was rejected because it would conceal source and lineage failures.

**Status:** Active
