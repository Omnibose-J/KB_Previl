# Goodwill benchmark stays the median trade area, not the average store

**Decision:** On 2026-07-29, keep the goodwill benchmark M̄ as the median of
per-trade-area per-store sales. Do not switch to store-weighted Seoul sales
(Σsales / Σstores).

**Context:** A design-vs-implementation audit listed the weighting as a minor
deviation. Measurement showed it is not minor. On quarter 20261 the median of
trade areas runs 35–60% below the store-weighted figure across all eight served
industry codes, because trade areas holding many stores also earn more per
store. For 한식 the choice moves the share of grids with zero intangible value
from 42.3% to 65.8% of 10,879 grids, the median reference value from 1,427만 to
0만, and a single spot (여의동, 4,095만) from 9,754만 to 5,513만.

**Why:** Design §24 specifies 중앙값 and the implementation conforms. The
question the report answers is "what is this location worth compared with
opening somewhere else" — a choice among locations, which uniform weighting over
trade areas represents. Store-weighting answers a different question, "compared
with the average existing store", and would report no intangible value for two
thirds of grids, which is a harsher baseline rather than a more truthful one.

**Rejected:** Store-weighted Σsales/Σstores, for the reason above. Also rejected
was exposing both figures in the report; two benchmarks with a 40% gap and no
stated rule for choosing between them would move the judgement onto the reader.

**Caveat on the prior owner call:** the 2026-07-27 call that chose median did so
against the *mean of the same per-trade-area ratios* (2,226만 for 한식). The
store-weighted figure (2,763만) was not part of that comparison. This decision
records it so any future change is made with the number in hand.

**Consequence for the report:** the label did misstate the unit. 서울 중간
월매출 reads as the median Seoul store; it is now 서울 상권 중간값 with the unit
named in the caption, and the paired row reads 이 상권 점포당 월매출.

**Status:** Active
