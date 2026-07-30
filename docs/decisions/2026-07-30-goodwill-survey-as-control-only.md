# Published goodwill survey is a control for the estimate, not an input to it

**Decision (2026-07-30):** the 서울시 상가임대차 실태조사 goodwill figures are used
only to check `service/goodwill.py` from outside. They do not become a model
feature, a served number, or a headline in the technical deck.

**Context.** The valuation produced an estimate, a band and a sensitivity table
all out of one formula, with nothing outside that formula ever checking it.
`pipeline/sftc.py` now extracts the survey's published goodwill (2023 district
table, 125/145 rows; 2022 industry table, 10/10 rows), so for the first time
there is an external number to compare against. Results are in
`docs/model-findings.md` §27.

**Why control-only.** Four gaps, none of them closeable:

1. **Resolution.** The published values are aggregates over commercial districts
   and industries. Pushing them onto the 100m grid is exactly what
   `decision_spatial_resolution_no_disaggregation_20260726` forbids — every cell
   in a district would tie, so the feature cannot rank, and if it appeared to
   rank it would be carrying something other than the survey.
2. **Population.** The survey covers ground-floor shops (2023: 145 districts,
   12,531 first-floor stores). Our estimate has no floor concept, and ground
   floor is the expensive end.
3. **Definition.** Published goodwill is the total paid — 바닥 + 영업 + 시설.
   We count excess profit only, and tangible assets are a user input defaulting
   to zero. The same edition reports that 42.3% of payers paid *without* taking
   over any fixtures, so 바닥권리금 is real and we do not model it.
4. **Denominator.** The published averages are conditional on having paid
   anything at all — 3,258 of 12,296 surveyed shops, 26.5%. Our estimate is
   produced for every location.

**What it did buy.** Matching the denominator (our top 26.5% against their
payers) puts the ratio at **0.92 / 1.13 / 1.15 / 1.39** across the four food
industries. The order of magnitude holds. That is the first external
confirmation the valuation has had, and it is worth exactly one sentence in the
deck — not a number on screen.

It also exposed a weakness that only an external control could show: our
estimates span 5% across industries where the published medians span 33%
(rho 0.400, n=4). We can claim the overall level is right. We cannot claim we
tell industries apart.

**Rejected.**

- *Add published goodwill as a grid feature.* Fails (1). It would also be
  circular in the served product, where goodwill is an output.
- *Show the published average next to our estimate in S4.* Fails (2)(3)(4) —
  two numbers side by side read as comparable, and these are not. A user would
  take the gap as a discount or a markup.
- *Calibrate the formula to close the gap.* This is the one that would have been
  tempting and is the worst. The gap is mostly definitional; scaling our output
  to match would encode 바닥권리금 as a multiplier without measuring it, and
  would destroy the only independent check we have.

**Status:** Active.
