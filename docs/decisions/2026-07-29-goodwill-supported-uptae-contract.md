# Goodwill supported-uptae discovery contract

**Decision:** On 2026-07-29, expose the keys of `service.goodwill.UPTAE_INDUTY` as `goodwillSupportedUptae` in `/api/meta`, while retaining the existing 503 rejection for unsupported direct `/api/goodwill` calls.

**Context:** Two licensed-food categories have no same-industry Seoul benchmark mapping. A permanent unsupported condition currently appears to the frontend only after a 503 response, which is presented as retryable.

**Why:** Publishing the existing mapping keys lets clients prevent unsupported entry without adding a query, duplicating the list, or weakening server-side defense.

**Rejected:** Adding approximate mappings was rejected because the remaining Seoul food codes do not represent the unsupported categories. Returning an empty or estimated goodwill result was rejected because it would conceal the missing benchmark source.

**Status:** Active
