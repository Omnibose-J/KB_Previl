# Compare candidate identity

**Decision:** On 2026-07-28, the compare contract adopted an optional caller
`label` that is echoed on each response item.

**Context:** `gridId` cannot distinguish two candidates in the same building
when they represent different floors. The frontend needs a stable way to join
the returned ranks to the user's candidate cards.

**Why:** Echoing a caller-owned label makes identity explicit without deriving
or guessing a property identifier from coarse grid data. It also remains
correct if ranking logic changes, because ranking annotates items without
reordering or replacing their identity.

**Rejected:** An order-only contract was allowed but rejected because positional
identity is implicit and easier for a future response transformation to break.
Server-generated A/B/C labels were also rejected because the caller already
owns the user-visible candidate name and no fallback was requested.

**Status:** Active
