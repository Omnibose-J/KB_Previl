# A printed checksum is not enough to trust a vision-extracted table

**Decision (2026-07-30):** extracting numeric tables from image PDFs requires
three gates, not one — the document's own checksum, agreement across independent
re-reads, and page slicing. Table classification is never delegated to the model.

**Context.** `pipeline/sftc.py` reads goodwill tables out of the 서울시 상가임대차
실태조사. The reports are pure images (`pdftotext -layout` returns 280 bytes for
the 44-page 2023 edition), so a vision model is the only route. The tables print
their own arithmetic — 「초기투자비 = 보증금 + 권리금 + 시설투자비」, and the
industry table's bands must sum to 100 — which looked like a complete answer to
extraction trust.

**Why one gate was not enough.** The checksum catches a misread digit: it
rejected 학동역 with 시설투자비 5,264 against a printed 5,254, off by ten. It does
**not** catch a row the model invented. Sending 2023 p.27 whole produced rows for
성동구, 영등포구 and 용산구 — districts printed on p.28, not p.27 — and every one
of those rows added up, because a model that fabricates a row fabricates a
consistent one. Self-consistency is the cheapest property to fake.

The two gates that do catch it:

- **Agreement across independent passes.** Printed numbers repeat; invented ones
  do not. p.27 agreed on 21 of 77 rows, which is what exposed the problem.
- **Block slicing.** A page of ~66 rows across three side-by-side blocks gets
  downsampled by the vision API. Rendering each block separately at native
  220 ppi took p.27 from 21 to 60 agreed rows, and the whole table from 85 to
  125 accepted.

Structural confirmation: after slicing, the districts on p.27 and p.28 no longer
intersect (강남~서대문 / 서초~중구), matching the printed alphabetical layout.

**Classification stays in code.** Asked to judge whether a page held a district
table or an industry table, the model labelled the district table "uptae", and on
a second run returned null for every page in an eight-image batch. It now
transcribes only what is printed — caption, headers, first row labels — and
`classify()` decides. The caption has to be read too: the industry table's
columns are money bands, so 「권리금」 appears only in its title.

**Rejected.**

- *Trust the checksum alone.* Measured false-negative on fabrication.
- *Raise DPI instead of slicing.* The embedded images are 220 ppi
  (`pdfimages -list`); rendering above that interpolates. The constraint is the
  API's downsampling of a large image, not the source resolution.
- *Repair rows that fail a gate.* A repaired row is indistinguishable from a
  correct one downstream. Failing rows are dropped and named.
- *Fill the 20 missing districts by hand.* They stay missing. A control set with
  hand-entered rows is no longer independent of the person checking it.

**Status:** Active.
