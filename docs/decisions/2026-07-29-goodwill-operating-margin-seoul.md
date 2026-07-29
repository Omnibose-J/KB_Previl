# Goodwill operating margin: Seoul measured 7.01%, not split by uptae

**Decision:** On 2026-07-29, replace the goodwill operating margin constant
0.15 with 0.0701, measured from the Seoul subsample of the 2025 외식업체
경영실태조사 microdata. Do not split the rate by uptae.

**Context — why 0.15 had to go.** Two independent defects. First, the cited
source does not publish the cited figure: 소상공인실태조사 reports operating
profit only across eleven industry divisions, with 숙박·음식점업 as a single
bucket, so no 음식점업 rate exists there to quote. Second, 15.0% is the 2019
level. The KREI series runs 2019 15.0 → 2020 12.1 → 2021 11.2 → 2022 11.6 →
2023 8.9 → 2024 8.7. The report was multiplying 2026 Q1 trade-area revenue by a
pre-COVID margin.

**Source and validation.** 외식업체 경영실태조사 (농림축산식품부·한국농촌경제
연구원), 2025 survey, 2024 results, published microdata, n=3,138. Aggregating
`a4a1='서울'` (n=491) with the survey weight `WT` gives revenue 31,062.8만 and
operating profit 2,177.1만, so 7.01%. Three checks passed before the number was
used: the weighted aggregation reproduces all sixteen published industry rows of
표 95 and 표 104 to a maximum relative error of 0.0030% (unweighted is off by
68%); the four 한식 subclass rows of 표 95 reproduce exactly; and the Seoul row
reproduces the published 31,062.8 / 2,177.1 to the decimal. 임차료 is a
component of 영업비용 (표 99), so the rate is after rent and
`operating_margin_basis` stays `after_rent`.

**Why Seoul rather than national.** Seoul is 7.01% [5.73, 8.25] against 8.74%
nationally, on n=491 — measurably lower, consistent with higher rent, and the
service only serves Seoul.

**Why not split by uptae — rejected on measurement.** Bootstrap 95% intervals
for each Seoul × uptae cell are 3.05%p to 8.60%p wide, while the entire
between-uptae spread nationally is 2.96%p. Even the narrowest cell (까페,
n=52, 3.05%p) is wider than the whole signal, so Seoul samples cannot
distinguish one uptae from another. 호프/통닭 has n=13 and an interval reaching
−1.65%. Rescaling national per-uptae rates to the Seoul level was also rejected:
it assumes no region-by-uptae interaction, and the data contradicts that —
한식 is lower in Seoul than nationally (6.21 vs 8.83) while 식육 is higher
(10.67 vs 9.31).

**Consequences.** Reference values fall 53.3% uniformly. 여의동 한식 at 4,095만
goes from 9,754만 to 4,559만; the 한식 grid median from 1,427만 to 667만. The
sensitivity margin axis narrows from ±0.03 to ±0.015 (5.51 / 7.01 / 8.51%),
because ±0.03 around 7.01% would span ±43% of the base assumption.

**Known limitation.** The rate is an average margin applied to *excess* revenue.
At a site whose fixed costs are already covered, the marginal margin is normally
higher than the average, so this understates excess profit. The approximation is
unchanged from v1 and is inherited from design §6; only the level and the source
changed.

**Status:** Active
