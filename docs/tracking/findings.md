# Findings ??problems found in-flight that are out of the finder's write scope

## F-A1. ~~`pipeline.consistency` is 15/17~~ ??RESOLVED 2026-07-27 (`_ENV_PATH` NameError)

**Symptom**
```
$ python -m pipeline.consistency
[district]     ERROR NameError: name '_ENV_PATH' is not defined  -> FAIL
[dongaccuracy] ERROR NameError: name '_ENV_PATH' is not defined  -> FAIL
15/17 PASS  FAILED: ['district', 'dongaccuracy']   (exit 1)
```

**Cause** ??`pipeline/consistency.py:152` imports `ENV_PATH` from `.config` but lines 154 and
321 dereference `_ENV_PATH`. Unconditional NameError, so both reverse-geocoding checks have
never run in this checkout. Introduced when `config.py` gained the `KB_ENV` worktree override
(`ENV_PATH`) and these two call sites kept the old private name.

**Resolution** ??the owner authorised the edit on 2026-07-27 and it is applied. It was three
tokens, not two: `c_district` already imported `ENV_PATH` and only needed the dereference
fixed, but `c_dongaccuracy` imported `ROOT` alone, so its import line needed `ENV_PATH` added
as well. Both functions keep their own inline .env parse, matching the surrounding style.

```
$ python -m pipeline.consistency
[district]     ????ㅼ퐫???쒕낯 200嫄?쨌 ?먯튂援??쇱튂 200 / 遺덉씪移?0 (100.0%)  -> PASS
[dongaccuracy] ?쒕낯 200嫄??쇱튂 200 / 遺덉씪移?0 (100.0%) ?ㅽ뙣 0              -> PASS
17/17 PASS   (exit 0)
```

The CRS and dong assignments were sound all along ??what was missing was the guard, not the
correctness. Both checks now make live Kakao calls, so 17/17 requires `KAKAO_REST_API_KEY`
and network; without either they return `None` and are skipped rather than failing.

**Blast radius** ??the two dead checks are the *external* CRS witnesses (Kakao reverse-geocode
of stored lon/lat vs the row's own address). Their silence is exactly the failure mode
`CLAUDE.md` rule 2 was written about: an EPSG mix-up passes every internal check while
displacing every point 1?? cells. Everything else (15 internal checks) passes, and
`probe/p8_crs.py` measured the CRS empirically, so there is no evidence of an actual
displacement ??the loss is the standing guard, not a known defect.

**Note** ??after the fix these two checks make live Kakao API calls, so 17/17 additionally
requires `KAKAO_REST_API_KEY` and network.

(Before the fix was authorised, both checks had been replicated read-only at n=60/80 with the
same 100.0% result, which is what made the repair a known-safe two-line change rather than a
gamble.)

## F-C1. ~~Goodwill report has no honest caller~~ — RESOLVED 2026-07-27 (goodwill-report-design §8-A slim input; lane B moved benchmark/r/d server-side, card shipped)

**Found** 2026-07-27 (lane C, while wiring remaining P1 screens).

**Problem** ??`POST /api/goodwill` requires `benchmarkMonthlyRevenue` + `benchmarkLevel`
in the request, and lanes/B-backend.md explicitly forbids the frontend from computing or
inventing these ("C????媛믪쓣 怨꾩궛?섍굅??吏?대궡吏 ?딅뒗??). No endpoint serves the
Level-4 benchmark (?쒖슱 ?꾩껜 x ?숈씪 ?낆쥌 ?됯퇏 留ㅼ텧), so the frontend cannot construct a
valid request without fabricating the benchmark ??which the no-mock rule forbids.

**Why it cannot be solved now** ??producing the benchmark is lane A/B territory: the
value already exists server-side (economics uses the contracted Seoul trade-area
average) but is not exposed. Blast radius: the 沅뚮━湲??묒긽 由ы룷??card (P1) stays
unbuilt; everything else ships. Fix is small: expose per-uptae benchmark revenue
(+ level + as-of) on /meta or a dedicated endpoint, then lane C builds the card.

## F-C2. ~~/goodwill: two uptae have no benchmark mapping and fail as 503 "retry"~~ — RESOLVED 2026-07-29

**Resolved** — `meta.goodwillSupportedUptae` (557e9c9) exposes the 10 mapped
uptae; S4 uses it to replace the goodwill entry button with a "제공 불가"
pre-state before any request is sent (3ce822a). That closes (b) outright and
makes (a) unreachable from the UI.

The optional 422 was **not** taken: `/goodwill` still answers 503 for the two
uptae, kept deliberately as a direct-call defense. The mapping itself was not
extended — Seoul's food taxonomy has only two unused codes and neither
corresponds to a catch-all bucket ("기타") or to 인도·태국 cuisine, so any
mapping would be the cross-industry borrow `goodwill.py` explicitly refuses.
**The absence is real; refusing is correct.**

The three "minor deviations" below were noted in the same audit. All three were
worked on 2026-07-29; see the resolution block after them.

**Found** 2026-07-27 (lane C, design-vs-implementation audit of goodwill).

**Problem** — `service/goodwill.py` UPTAE_INDUTY maps 10 of the 12 served uptae;
"기타" and "외국음식전문점(인도,태국등)" have no Seoul commercial-taxonomy
counterpart, so `/goodwill` raises GoodwillUnavailableError → **503**. Two issues:
(a) 503 semantics say "temporarily unavailable" and the frontend renders a retry
button, but this failure is permanent — retry can never succeed; (b) no field on
GridDetail/meta lets the frontend pre-detect it, so the user types inputs first
and then hits the error (unlike 상권 밖, which is pre-screened via sales.available).

**Why not solved here** — the mapping and the status-code choice are lane B's
contract. Smallest fix: expose supported-uptae (or per-uptae goodwillAvailable)
so lane C can render the same "제공 불가" pre-state it uses for 상권 밖; optionally
422 instead of 503 for the permanent case. Blast radius: 2/12 uptae see a dead-end
retry inside the goodwill dialog; valuation itself is unaffected.

**Minor deviations noted in the same audit (design-conformant enough to ship, lane B aware):**
- operating margin is a single 음식점업-wide 0.15 labelled "v1 고정"; design §6 said
  per-uptae values from 소상공인실태조사. Honest label, weaker claim.
- benchmark M̄ averages per-trade-area per-store sales with equal weight per trade
  area (AVG of ratios), not store-weighted (Σsales/Σstores). Design wording is
  ambiguous; small trade areas are overweighted.
- expected survival comes from the 36-month curves, so valuation N is capped at 3
  years regardless of lease — a consequence of design §2 reusing the economics
  curves, stated nowhere in doc or UI.

### Resolution of the three deviations (2026-07-29)

**(3) valuation horizon — RESOLVED.** Three changes closed it. `e3f14e0` removed
the whole-year `floor`, so N is now the measured fraction (grade 1: 2.651y, was
truncated to 2y, +29% on the reference value) and a 1.5-year lease is valued as
1.5 years. `6f4ef98` states on screen which constraint bound — remaining lease
or the 36-month record — and, when the record binds, that the true value is
therefore higher than shown. `c8c7123` replaced the lease number input with a
0.5–3.0 year slider, so the cap is structural rather than something the user
learns only by reading a footnote. `fdfeea4` dropped the meaningless 0-year
sensitivity column that short leases produced.

**(2) benchmark weighting — MEASURED; the description above is stale, and the
magnitude was understated.** The code has used a *median* of per-trade-area
per-store sales since the owner call of 2026-07-27, not an average, and design
§24 specifies 중앙값, so the implementation conforms. But the underlying choice
of weighting is not minor. Measured on quarter 20261:

```text
uptae   trade areas  median-of-trade-areas  store-weighted   gap
한식           1,405              1,739만          2,763만  -37.1%
중국식           445              1,403만          2,236만  -37.3%
일식             332              1,423만          2,188만  -34.9%
경양식           330              1,051만          1,990만  -47.2%
통닭(치킨)       443              1,188만          2,149만  -44.7%
분식             781                775만          1,340만  -42.2%
호프/통닭        880                941만          1,846만  -49.0%
까페           1,061                554만          1,390만  -60.1%
```

Store-weighted is far higher because trade areas with many stores also have
higher per-store sales. Switching would raise the benchmark, shrink excess
profit, and for 한식 move the share of grids valued at zero intangible from
42.3% to 65.8% and the median reference value from 1,427만 to 0만 (10,879
grids). A single spot: 여의동 at 4,095만 goes from 9,754만 to 5,513만, -43%.

No recompute was made. The design says 중앙값, an owner call is on record, and
the counterfactual the report answers — "compared with opening somewhere else" —
is a choice among *locations*, which uniform-over-trade-areas represents. The
2026-07-27 call did compare median against the mean of the same ratios
(2,226만 for 한식); it did not have the store-weighted figure in front of it.
The number above is recorded so a future change is a decision, not a discovery.
See `docs/decisions/2026-07-29-goodwill-benchmark-weighting.md`.

What was fixed instead is the label, which did misstate the unit: the report
said 서울 중간 월매출, which reads as the median Seoul *store*. It is now
서울 상권 중간값 / 같은 업종 상권들의 점포당 매출 중 가운데 값, and the
paired row is 이 상권 점포당 월매출, so both sides of the comparison name the
same unit.

**(1) single operating margin — RESOLVED, but not the way the audit expected.**
The data acquisition was carried out on 2026-07-29 and turned up two defects
larger than the missing per-uptae split.

First, the cited source does not publish the cited figure. 소상공인실태조사
reports operating profit across eleven industry divisions only, with
숙박·음식점업 as one bucket; there is no 음식점업 rate in it to quote. Second,
15.0% is the 2019 level — the KREI series runs 2019 15.0 → 2020 12.1 → 2021 11.2
→ 2022 11.6 → 2023 8.9 → 2024 8.7. The report was multiplying 2026 Q1 trade-area
revenue by a pre-COVID margin.

The constant is now 0.0701, from the Seoul subsample (n=491, weighted by `WT`)
of the 2025 외식업체 경영실태조사 microdata: revenue 31,062.8만, operating profit
2,177.1만. Validation before use: the weighted aggregation reproduces all
sixteen published industry rows of 표 95 and 표 104 to a maximum relative error
of 0.0030% (unweighted is off by 68%), the four 한식 subclass rows reproduce
exactly, and the Seoul row matches the published 31,062.8 / 2,177.1 to the
decimal. 임차료 sits inside 영업비용 (표 99), so `after_rent` still holds.

**The per-uptae split the audit asked for was rejected on measurement.**
Bootstrap 95% intervals for Seoul × uptae cells are 3.05%p to 8.60%p wide while
the entire between-uptae spread nationally is 2.96%p — even the narrowest cell
(까페, n=52) is wider than the whole signal. 호프/통닭 has n=13 and an interval
reaching −1.65%. Rescaling national per-uptae rates to the Seoul level assumes no
region-by-uptae interaction, which the data contradicts: 한식 is lower in Seoul
than nationally (6.21 vs 8.83) while 식육 is higher (10.67 vs 9.31).

```text
uptae              Seoul n   Seoul     95% CI          width   national
한식                   134    6.21%   3.83 ~  9.02    5.19%p    8.83%
까페                    52    7.13%   5.67 ~  8.72    3.05%p    8.88%
정종/대포집/소주방          45    7.74%   5.04 ~  9.83    4.80%p    9.01%
식육(숯불구이)             34   10.67%   7.44 ~ 14.12    6.67%p    9.31%
분식                    33    9.33%   6.24 ~ 12.15    5.91%p    9.30%
경양식                   26    6.73%   2.95 ~ 10.44    7.48%p    7.56%
중국식                   25    8.59%   3.72 ~ 12.12    8.39%p   10.52%
통닭(치킨)                20   10.26%   6.18 ~ 14.78    8.60%p    9.25%
일식                    18    8.77%   4.22 ~ 12.27    8.05%p    8.12%
호프/통닭                 13    2.55%  -1.65 ~  6.35    8.00%p    8.33%
Seoul, all uptae       491    7.01%   5.73 ~  8.25    2.52%p    8.74%
```

Reference values fall 53.3% uniformly; 여의동 한식 at 4,095만 goes from 9,754만
to 4,559만. The sensitivity margin axis narrowed from ±0.03 to ±0.015. See
`docs/decisions/2026-07-29-goodwill-operating-margin-seoul.md`.

The average-margin-on-marginal-revenue approximation is unchanged and still
understates excess profit at a site whose fixed costs are already covered.


---

## `score_meta.text_profile_exposure_note` 가 §I-23 이후 사실과 다르다 (2026-07-28)

현재 값은 `I-20:gripe reject(precision 0.087-0.167) · guest:precision untested`.
§I-23 이 `guest.purpose` positive precision 을 실제로 쟀고 3클래스 전부 기각했다
(meal 0.583 · cafe 0.600 · drink 0.533, κ 0.48~0.76). `untested` 는 더 이상
맞지 않는다.

**여기서 못 고치는 이유** — 이 키는 `model/profile_build.py` 가 쓰고, 그 모듈은
`text_profile` 을 삭제·재생성하며 공유 `kb.db` 쓰기는 레인 A 전용이다. 문서 갱신
목적으로 공유 DB에 profile_build 를 돌리는 것은 §9.1 이 금지한 동작이다.

**영향 범위** — 노출 판정에는 영향이 없다(`text_profile_exposed` 는 빈 값이고
`guest` 는 어차피 비노출). 잘못된 방향은 한 가지뿐이다: 이 note 만 읽은 사람이
"guest 는 아직 기회가 있다"고 오해할 수 있다. 정확한 상태는
`docs/unstructured-plan.md` §I-23 과 `docs/model-findings.md` 에 있다.

**가장 작은 수정** — 레인 A 가 다음 `profile_build` 실행 시 note 를
`guest.purpose:reject(0.533-0.600)` 로 갱신한다.

## F-A2. RESOLVED — read-only gates mutated the shared `kb.db` (2026-07-29)

**Symptom (historical)** — the canonical gate chain changed the main DB file
bytes and created `kb.db-wal` / `kb.db-shm`, despite every predicate being
read-only. File-byte hashes are now retired as a WAL database invariant; they
were only the signal that led to the writer-path diagnosis below.

**Cause** — `pipeline.verify`, `pipeline.consistency`, `model.test_leakage`,
and the two `model.asof` self-test paths previously called
`pipeline.db.init()`. That function executes the full `SCHEMA` and commits,
while `SCHEMA` starts with `PRAGMA journal_mode=WAL`. The verification
entrypoints were therefore writers even when every predicate only read data.

**Resolution** — `pipeline.db.connect_ro()` now opens `KB_DB` through a
`mode=ro` URI and sets `PRAGMA query_only=ON`. The five read-only gate call
sites use that connection: `pipeline.verify`, `pipeline.consistency`,
`model.test_leakage`, and the two `model.asof` self-test paths. The writer
entrypoint `init()` and every feature-building path remain unchanged.

**Verification** — the full gate returned `8/8 PASS`, `17/17 PASS`, leakage
guard `PASS`, and `<=T` invariance `PASS` with exit `0`. Before and after the
gate, the SHA-256 over sorted canonical JSON containing all 39 non-internal
table row counts, the four ranking metadata values, and `PRAGMA quick_check`
was identical:

```text
content_fingerprint_before=1aff0f9062ad9d3f7d7d1969330d1e15a66377358ea6c6c10d47bec12a44111a
content_fingerprint_after=1aff0f9062ad9d3f7d7d1969330d1e15a66377358ea6c6c10d47bec12a44111a
quick_check=ok
rank_model=gbm
rank_features=open_cnt,open_cnt_r1,same_uptae_cnt,same_uptae_r1,openings_36m,closures_36m,churn_36m,growth_36m,prior_surv_3y,prior_surv_n,median_area,open_month,prior_surv_1y,same_group_r1,other_group_r1,group_share_r1,median_tenure_r1,veteran_share_r1,uptae_entropy_r1,close_accel_r1
rank_train_years=2005,2006,2007,2008,2009,2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022
rank_test_years=2023
```

**Remaining limitation** — a read-only WAL connection may still create or
touch `kb.db-shm`; its bytes and timestamps are not content invariants.

## W5 recovery baseline (2026-07-28)

Before W5, the approved recovery database was created from the current
`kb.db` with SQLite's online compaction path, not by copying the file:

```text
sqlite3 kb.db "VACUUM INTO 'kb-baseline-20260728.db'"
exit 0
```

The source and backup have the same content fingerprint. The fingerprint is
defined as all non-internal table row counts, the four ranking metadata values,
and `PRAGMA quick_check`; it does not include database-file bytes. The
SHA-256 below is over the sorted canonical JSON of those fields.

```text
content_fingerprint_sha256=a10ff8a8e64fcc83c4ffc1e9a7d6475e0488ad1c43be13b4c84670a475bd3de1
quick_check=ok
rank_model=gbm
rank_features=open_cnt,open_cnt_r1,same_uptae_cnt,same_uptae_r1,openings_36m,closures_36m,churn_36m,growth_36m,prior_surv_3y,prior_surv_n,median_area,open_month,prior_surv_1y,same_group_r1,other_group_r1,group_share_r1,median_tenure_r1,veteran_share_r1,uptae_entropy_r1,close_accel_r1
rank_train_years=2005,2006,2007,2008,2009,2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022
rank_test_years=2023
```

| table | rows | table | rows |
|---|---:|---|---:|
| absa_label | 6,004 | absa_post | 40,665 |
| api_log | 5 | cohort_survival | 44 |
| demand_label | 5,332 | grid | 21,544 |
| grid_access | 21,544 | grid_concept | 142,402 |
| grid_feature | 21,544 | grid_place | 21,529 |
| grid_score | 229,356 | grid_sgis | 21,529 |
| gripe_label | 24,704 | guest_label | 0 |
| licence | 535,603 | licence_rest | 146,184 |
| lvpop_profile | 10,176 | mention | 297,850 |
| mention_shop | 17,056 | merit_label | 0 |
| price_label | 21,552 | realprice | 178,095 |
| realprice_done | 3,600 | score_meta | 47 |
| sgis_dong | 426 | sgis_jipgyegu | 19,097 |
| shop_concept | 477,361 | station | 784 |
| station_ride | 48,313 | store | 138,558 |
| text_profile | 8,122 | trdar_area | 1,650 |
| trdar_flpop | 1,649 | trdar_sales | 6,573 |
| trdar_store | 12,204 | trend | 27,848 |
| uptae_label | 16,276 |  |  |

Recomputed independently against `kb.db` and
`kb-baseline-20260728.db`: `fingerprints_equal=true`, exit 0. This backup is
the recovery point for W5; development must use a separate database selected
through `KB_DB`.

## W5 address-history result (2026-07-28)

All development and the full regression gate used
`KB_DB=...\kb-w5-work.db`. The work database differs from the recovery
baseline only by `addr_tenancy` (+535,375 rows) and four `score_meta` rows;
the four ranking metadata values are unchanged and both databases return
`quick_check=ok`.

The floor-marker subset contains 117,433 of 535,603 licence rows
(21.925%). On that same subset, the observed succession rate is 5.176% when
floor is ignored and 3.828% when the observed floor token is retained, a
change of -1.348 percentage points. Because the effect is material relative
to the rate, the active policy is:

- preserve a floor token when the source address contains one;
- never infer, distribute, or allocate a missing floor;
- keep floor-missing rows at their observed address grain and expose the
  missingness to later modelling.

The month-grain positive label contains all 32,237 legacy
`succession_suspect` rows. It adds 2,608 rows at exactly three months:

```text
new_positive=34,845
legacy_positive=32,237
both_positive=32,237
new_only=2,608
legacy_only=0
```

Current work-copy proof:

```text
python -m pipeline.addr_history --selftest
exit 0 — 535,375 rows, chain errors 0, label errors 0

grep -n "월 단위" pipeline/addr_history.py
exit 0 — persistent metadata and code comment both present

python -m pipeline.addr_history --floor-impact
exit 0 — 117,433/535,603, rate difference -1.348 percentage points

python -m pipeline.addr_history --diff-legacy
exit 0 — 34,845/32,237/32,237/2,608/0
```

After the work-copy gates and independent review passed, W5 was rebuilt on the
original database with an explicit `KB_DB=...\kb.db`:

```text
python -m pipeline.addr_history --build
exit 0 — 535,375 rows
```

The post-apply source and gated work copy have the same content fingerprint:
`dd22fcb380d697f38c9e4c1a05210b3b0309eac7631b36505c5eab15c859a06d`.
The recovery database remains at
`a10ff8a8e64fcc83c4ffc1e9a7d6475e0488ad1c43be13b4c84670a475bd3de1`.
All three return `quick_check=ok`; the ranking metadata values remain
unchanged.

## W6-W7 succession model and serving result (2026-07-28)

W6 uses closure-year cohorts, with 2005-2021 for training, 2022 for calibration,
and 2023 as the untouched holdout. The adopted M2 result is AUC 0.7474 versus
0.6140 for the train-only industry baseline. Its 2022-bin calibrated Brier is
0.1140 versus 0.1296 for the previous-year observed-rate constant. The absolute
rate still drifts from 11.12% in 2022 to 15.08% in 2023; W7 therefore exposes
the source and does not present the output as a goodwill payment ratio.

The work and source databases have a `succession_score` serving table with 229,356
grid-industry rows, ten calibrated observed rates, observation month 202607,
and model version `m2-gbm-close-2005-2021-cal-2022-v1`. Request handling only
reads this table; it does not import or execute `model.*`. `KB_RECOVERY_SOURCE`
selects `constant`, `survival_curve_proxy`, or `m2`; missing or invalid selected
sources fail with 503 rather than falling through. The request path rejects a
different M2 model version or observation month, and the writer refuses to
replace the serving table when the holdout adoption gate fails.

After explicit approval on 2026-07-29, `python -m model.recovery
--build-serving` wrote the table to the original `kb.db`. Source and gated work
copy have the same content fingerprint
`bba2451701d1477e01807bfd4b712a31309e9d02bafe025ea4e710b18a9d8759`;
both return `quick_check=ok`, contain 229,356 non-NULL M2 rows and ten distinct
calibrated rates, and retain the four ranking metadata values. The recovery
baseline remains unchanged and returns `quick_check=ok`.

The W7 verifier now selects a real contract test. It sends the same candidate
first with `KB_RECOVERY_SOURCE=constant`, then with `m2`, checks public
`successionProb` and `recoverySource`, and compares the M2 value with the actual
`succession_score` row. The command exits 0 with one selected test. The stale
`recoveryProb` assertion was updated to the owner-approved W7 contract; the
full cost and API suite exits 0 with 66 passing tests.
