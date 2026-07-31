# Findings ??problems found in-flight that are out of the finder's write scope

## F-S1. Pre-submission audit leftovers (2026-08-01) — deferred, not dismissed

Three read-only audits ran before the 08-03 deadline (F-A3 commit review,
`model/`+`pipeline/` dead-code, `service/` stability). Everything judged **safe**
was applied the same day; the rest is listed here so the deadline does not erase
it. Nothing below has a known user-visible symptom today — each is a latent trap.

**Correctness / policy**

| what | where | why deferred |
|---|---|---|
| `.env` parsed inline in 16 places despite `CLAUDE.md` saying "`load_env()` — 직접 파싱 금지" | `model/absa_*`, `model/senti_*`, `pipeline/consistency·geocode·mentions·realprice·sgis*·trend` | 15 files, mechanical but wide |
| `collect.py` derives the `.env` path from `CACHE_DIR`, so `KB_ENV` is ignored and `KB_CACHE` silently redirects it | `pipeline/collect.py:64` | worktree correctness; needs a SEMAS collection run to verify |
| `cohort.compare_probe()` returns `True` when the probe JSON is absent — and the submission allowlist ships `probe/**/*.py` only, never `probe/results/*.json`, so the gate is vacuous in every judge's copy | `pipeline/cohort.py:99-104` | the fix may be the allowlist rather than the code; packaging owner's call |
| `fill_dong` — the retired 75.5% proximity heuristic — is still a live function | `pipeline/features.py:84` | its `__main__` caller was removed and the docstring now says RETIRED; deleting the function itself is a separate call |

**Serving robustness** (none reachable from the UI today)

| what | where | current containment |
|---|---|---|
| permanent condition answered with 503, which the frontend contract reads as "retry" | `service/goodwill.py:42` | `meta.goodwillSupportedUptae` pre-screens it; `estimation.py:101-112` already shows the 200 + `missing_axes` pattern to copy |
| `/api/grid/{id}/changes` returns 200 for a grid that `/api/grid/{id}` 404s | `service/api.py:868` | inconsistent with the §7 "평가 대상 밖" contract |
| no upper bound on rent/upfront/deposit → `ResponseValidationError` 500 on absurd values | `service/app.py:314-316, 355-358` | reachable only by pasting ~1e308 into a number input |
| `/api/goodwill` computes `grid_detail` twice per request | `service/goodwill.py:101, 185` | 38ms measured; cost only |

**Duplication** — `wilson` defined identically 3× (`model/round4·ui_curves`,
`service/precompute`), `deciles` 3× byte-identical (`model/ablation·stage1·tournament`),
and the LLM run scaffolding repeats across 7 `*_run.py` modules. Consolidating
`deciles`/`wilson` moves import paths, so it waits until after the deadline.

**Do not "clean up" `model/asof.py`.** It is listed in `model/cache.py:16`
`SOURCES`, so changing one byte re-keys every split cache (~82MB each) and forces
a rebuild. A ruff pass removed one unused import there on 08-01 and triggered
exactly that. Guards and lists belong in the guard file, as
`model/test_leakage.py:28-30` already says.

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

## F-A3. The leakage guard does not cover newly added feature families (2026-07-30) — resolved 2026-08-01

**Status:** Resolved on 2026-08-01. Coverage is now derived from
`robustness.FEATURE_SETS`, and the two families are registered on opposite
sides of the as-of contract. See the resolution block at the end of this entry.

**Found** while adding OSM (R10-B) and CBD (R11) candidate features.

**Symptom** — `model.test_leakage` reports `검사 대상 40개 (NUM·LOC3·DEPLOY·Tier1~3)`.
The OSM (7) and CBD (4) columns are in neither set, so both families were measured
by `model.feature_gate` without ever passing through the guard that checks a
feature is documented in `asof.FEATURES` and observable at T.

**Why it is not a defect today** — both families were rejected, `DEPLOY` is
unchanged, and neither column reaches `service/precompute.py`. The guard's silence
therefore had no product consequence in this round.

**Why it cannot be left as is** — the guard's coverage list is enumerated, not
derived from "whatever the candidate sets contain". A future family that *passes*
its admission gate would be adopted with no leakage check at all, and the guard
would stay green while doing so. `experiment-plan.md` already warned about exactly
this ("기존 leakage 가드는 기본 NUM 세트만 검사하고 임계도 AUC 0.90이라 신규 피처의
+0.02급 누수를 못 잡는다"); this is the concrete instance.

**Blast radius if a family were adopted unchecked** — the adopted columns would
enter `grid_score` and every downstream survival claim. For OSM specifically the
exposure is real rather than theoretical: OSM is a *current* snapshot, so a road
built in 2015 is credited to a 2010 opening (documented in `model/osm.py`). That
is a genuine anachronism the guard never examined.

**Smallest fix** — make the guard's coverage set the union of every set registered
in `robustness.FEATURE_SETS` rather than a hand-listed five, so adding a candidate
set automatically extends the check. Lane A.

### Resolution (2026-08-01)

Coverage is now `union(robustness.FEATURE_SETS.values()) | RECOVERY_FEATURES |
TIER1..3`, so a family enters the check by being registered where it is
measured. Covered columns went 40 → 51.

Registering the eleven split them, because the two families differ in kind:

- **CBD (4)** — distance to a fixed city-centre coordinate does not move with
  T, so it is a genuine as-of feature. `CBD_FEATURES` already existed in
  `model/asof.py` and was simply missing from the `FEATURES.update` chain.
- **OSM (7)** — a current snapshot. Putting it in `FEATURES` would have turned
  the check green on the exact source it exists to catch, so `model/osm.py`'s
  `COLUMNS` is read as a *second* register: membership there counts as
  documented, and a column reaching `DEPLOY` from it fails the guard. OSM stays
  measurable as a candidate — the anachronism is a reason not to deploy it, not
  a reason to hide it from the ablation table.

Both failure directions were exercised, not asserted:

```text
python -m model.test_leakage            exit 0  — 51 covered, none undocumented, none deployed
python -m model.asof --selftest-cut     exit 0
DEPLOY += osm.COLUMNS                   exit 1  — 배포 세트 침투: osm_* 7
FEATURE_SETS['FAKE'] = [unregistered]   exit 1  — as-of 문서 미등재
```

## F-A4. §4-C lineage table predates the 2026-07-28 retrain (2026-07-30) — resolved 2026-08-01

**Status:** Resolved on 2026-08-01. §4-C itself was already rewritten by the
07-31 source refresh; what still carried the superseded fit was the §9-A
decomposition, now recomputed. See the resolution block at the end.

**Found** while reconciling a reproducible AUC (0.6369) against the documented
0.6392.

**Symptom** — `docs/model-findings.md` §4-C declares lineage ⓪ as "유일한 인용
기준" with 상위 **75.5%** / 하위 **29.2%** / 격차 **46.3%p**. `CLAUDE.md` names
precisely those three values as the marker of a pre-retrain document ("그 이전
값(75.5% / 29.2% / 46.3%p)을 인용한 문서를 발견하면 갱신 누락이다"). The deployed
`score_meta.observed_by_grade` is 0.7686 / 0.2841, i.e. 76.9 / 28.4 / 48.45%p.

So the table that claims to be the single citation standard is itself the stale
copy. The AUC printed in the same sentence (0.6392) belongs to that lineage and,
separately, is a **seed-averaged** figure mislabelled "seed=0 단일 적합" — the
seed=0 fit that `precompute` actually deploys measures 0.6369 (reproduced twice;
`gbm` was deterministic across runs).

**Why it is out of scope here** — R10/R11 measured candidate features; rewriting
§4-C means recomputing the ten per-grade values, their Wilson intervals, the
2x2 decomposition in §9-A, and the derived rows in §7-B, none of which this round
touched. Doing it as a side effect of a feature experiment is how a lineage table
silently acquires a third lineage.

**Blast radius** — anyone citing §4-C as instructed gets pre-retrain numbers.
`README.md`, `CLAUDE.md`, and `docs/기술설명서-작성자료.md` already carry the
current 76.9 / 28.4 values, so the contradiction is visible rather than hidden,
and the AUC line has been corrected in those three plus `lanes/A-algorithm.md`.
§4-C itself is untouched.

### Resolution (2026-08-01)

§4-C is no longer the stale copy: the 07-31 refresh rewrote it to the deployed
내신형 9 grades (1등급 80.1 / 9등급 10.1, AUC 0.6383). The table that still
carried the 0.6392 lineage was **§9-A**, whose 2x2 decomposition this entry
flagged as out of scope at the time. It has now been recomputed on the refreshed
source:

| | AUC | prior_surv | margin | top10 | bot10 | gap |
|---|---|---|---|---|---|---|
| A 2005–2018 / 2019–2022 | 0.5972 | 0.5559 | +0.0413 | 74.5 | 43.9 | 30.6 |
| B 2005–2018 / 2023 | 0.6233 | 0.5664 | +0.0569 | 74.8 | 32.6 | 42.3 |
| D 2005–2022 / 2023 | 0.6383 | 0.5668 | +0.0714 | 76.1 | 28.4 | 47.7 |

**D's AUC reproduces the deployed 0.6383 exactly**, which is what places the
table on the deployed lineage rather than beside it.

The recomputation changed an interpretation, not just digits. The published
split was 검증창 66% / 학습창 34% of a +0.0410 total; it is now **+0.0156 (52%)
/ +0.0145 (48%) of +0.0301**. "Most of the gain came from leaving COVID behind"
is no longer supportable — the two components are effectively equal. §9-A's
narrative paragraph, its 한계 CI, the 채택 justification, and README's COVID
bullet were all updated to match.

Also corrected: the experiment ledger row A1 said "1등급 75.5%", which now reads
as the 내신형 1등급 (80.1%). It was a decile-era figure, so it is labelled 당시
상위10% — the same wording row E1 already used.

```text
model.round4.baseline_report(con, list(DEPLOY), WINNER)   exit 0
  구 홀드아웃 2019–2022  n_te=48,895  AUC 0.5972 (prior 0.5559)
                        상위10% 74.5 [73.3, 75.7]  하위10% 43.9 [42.5, 45.3]  단조 O
  신선 홀드아웃 2023     n_te= 7,915  AUC 0.6383 (prior 0.5668)
                        상위10% 76.1 [73.0, 78.9]  하위10% 28.4 [25.4, 31.6]  단조 O
```

Row B (train 2005–2018 / test 2023) has no entry point in `round4`, so it was
fitted separately with the same `cached_split` + `fit_predict` + `deciles` path.
Nothing was written to any database.

## F-A5. Floor-level survival rates cite a source that cannot produce them (2026-07-30) — resolved 2026-08-01

**Status:** Resolved on 2026-08-01. The unsourceable trio was removed rather than
replaced: re-measurement shows the floor gradient is an area artifact. See the
resolution block at the end of this entry.

**Found** while checking whether floor data exists at all (owner question).

**Symptom** — `docs/goodwill-report-design.md:51` attributes the floor survival
figures (지하 59.8 / 1층 66.2 / 2층 69.9, also in `README.md:198`) to 소상공인
상가업소정보. That table (`store`, 138,558 rows) carries `flr_no` for 66.7% of
rows but **has no open/close dates at all**, so no survival rate can be computed
from it.

Recomputing from the only source that has both — floor tokens parsed out of the
`licence.addr` string, present in 20.4% of rows (109,159/535,603) — reproduces the
*ordering* but not the levels: 지하 70.1% (n=17,643) · 1층 71.2% (n=67,875) ·
2층 75.0% (n=14,405) · 3층+ 72.1% (n=6,584), all-period cohort. Seoul's 3-year
rate falls from 71.3% (2013 openings) to 58.8% (2023), so a recent-cohort
restriction plausibly explains the 10%p gap — but no cohort is stated anywhere.

**Why it is out of scope here** — the fix is a documentation decision (which
cohort, which source) plus possibly a new `licence` floor column, and `pipeline/`
is shared. Also note floor cannot enter the ranking model at all (CLAUDE.md
non-negotiable 5): it is a shop attribute the user chooses, identical across all
candidate cells.

**Blast radius** — an unsourced, uncohorted statistic is quotable from README into
the submission deck. The 20.4% subset additionally carries selection bias in a
known direction: an address states its floor mainly when the shop is *not* on the
ground floor, so 1층 is 62% of the token subset against a much higher true share.
Any conditional display built on it needs that bias stated, exactly as the
등급×면적 table states its legacy bench.

### Resolution (2026-08-01)

Re-measured read-only (`pipeline.db.connect_ro`, `PRAGMA query_only=ON`; no
table was created or altered). Floor tokens come from the existing parser
`pipeline.addr_history._floor_parts`; buckets are 지하 (token contains 지하, or
`B\d+`) / 1층 / 2층 / 3층+ (single numbered floor), with multi-floor spans
(`1,2층`) and bare `층`/`지상` left unclassified. Survival follows CLAUDE.md
rule 4 and `pipeline.cohort`: observation cut = `MAX(open_y*12+open_m)` =
**2026-07**; a row enters the denominator only if `open_ym + 36 <= cut`, and the
numerator is `close_ym - open_ym <= 36`.

**Coverage.** 117,436 of 535,715 licence rows carry a floor token (**21.9%**);
112,743 (21.0%) fall into one of the four buckets. Coverage is not stable in
time — it peaks at 50.5% for 2013 openings and collapses to 9.3% (2023) and
3.3% (2026), so recent cohorts are the thinnest part of the subset.

**All-period cohort (open_y >= 2005, observable at 36m):**

```text
floor        n  closed   surv%           CI95(Wilson)   share
 지하    14,817   4,970   66.5%          65.7-67.2      19.2%
 1층     49,691  15,975   67.9%          67.4-68.3      64.3%
 2층      8,696   2,474   71.6%          70.6-72.5      11.2%
 3층+     4,111   1,163   71.7%          70.3-73.1       5.3%
```

**2023 openings** — the deployed bench's cohort. Only Jan–Jul 2023 is 36 months
past opening under a 2026-07 cut, and the token subset covers 9.3% of that year,
so n collapses:

```text
floor      n  closed   surv%           CI95(Wilson)
 지하     160      82   48.8%          41.1-56.4
 1층      662     243   63.3%          59.6-66.9
 2층      116      35   69.8%          60.9-77.4
 3층+      31      11   64.5%          46.9-78.9
TOTAL     969  (6.5% of the 14,992 licence rows opened in 2023)
```

A 3층+ interval 32 points wide cannot support a published statistic. The widest
cohort that keeps every bucket above n=100 is 2019–2023 (지하 1,601 / 1층 6,284 /
2층 971 / 3층+ 336), but see the confound below — no cohort choice rescues the
claim.

**Selection bias, direction confirmed.** The entry predicted that an address
states its floor mainly when the shop is not on the ground floor. Measured
against `store.flr_no` (present for 92,352/138,558 = 66.7% of rows; `지` and
`B\d+` values counted as basement):

```text
floor    licence addr tokens (n=112,743)    store.flr_no (n=92,348)
 지하                       21.3%                        2.48%
 1층                        61.7%                       80.85%
 2층                        11.6%                       12.19%
 3층+                        5.4%                        4.48%
```

Basement is over-sampled 8.6x and 1층 under-sampled by 19 points, exactly the
predicted direction.

**Why no replacement number was published — the gradient is area.** Median
`site_area` in the observable token subset is 1층 42.2 m2 · 지하 62.7 · 2층 90.0 ·
3층+ 97.5, and CLAUDE.md non-negotiable 5 already names area the single strongest
predictor. Stratifying by area removes the floor ordering and in the smallest
band reverses it:

```text
area band     지하     1층     2층    3층+      (pooled by area)
 <30 m2     49.8%  59.8%  54.7%  56.0%           57.9%  n=19,093
 30-50      63.2%  66.8%  64.9%  67.7%           66.2%  n=17,561
 50-90      68.8%  74.1%  69.8%  69.1%           72.2%  n=18,554
 90+        76.9%  75.7%  76.4%  77.2%           76.3%  n=21,205
```

At 90 m2+ the four floors span 1.5 points and overlap; area alone spans 18.4
points. The raw "higher floor survives better" ordering is 2층/3층+ shops being
twice the size of 1층 shops, not a floor effect. Publishing 66.5/67.9/71.6/71.7
would have repeated the original defect with a new source, so both documents now
state the absence and its reason instead.

**The entry's own recomputation is not reproducible.** This round could not
reproduce 70.1 / 71.2 / 75.0 / 72.1 (n 17,643 / 67,875 / 14,405 / 6,584) or the
20.4% coverage figure under either the censored or the uncensored definition
(uncensored gives 66.3 / 68.2 / 71.8 / 71.9). The 2026-07-31 licence refresh does
not explain it: the pre-refresh snapshot `kb-pre-coldswap-20260729.db` (535,603
rows, same 2026-07 cut) yields 21.9% token coverage and 66.5 / 67.9 / 71.6 /
71.7 with n 14,817 / 49,692 / 8,697 / 4,111 — the same values as the current
database. The earlier figures' method was not recorded; the numbers above are the
ones with a stated definition.

One parser artifact was found and is harmless here: `_floor_parts` returns a bare
`지상` token for addresses containing 단지상가 (e.g. `개포주공7단지상가 102-1호`).
Bare `지상` is unclassified, so those rows never enter a bucket. Reported rather
than fixed — `pipeline/` is shared and `addr_history` uses the token only for
chain keys.

**Documents changed:** `README.md` §5 and `docs/goodwill-report-design.md` §5
(the ladder rung, the building card, and the data bullet). Both now carry the
source, the 21.9% subset share, the bias direction, and the area confound.

**Blast radius — closed the same day.** Two further copies carried the removed
trio and were cleaned up after this brief: `docs/ui-data-contract.md:59` (지하
59.8 ↔ 2층 69.9) and `docs/tracking/criteria-backend-teo-v1.md:78`, where the
trio backed a "do not multiply floor into 매출" rule — the rule survives and is
now stronger, since there is no validated floor multiplier for 매출 *or*
survival. `docs/experiment-plan.md:68`, which pointed at "README의 층별 수치" as
a post-submission task, was repointed at this entry.

---

## F-C3. 화면이 클래스별 정밀도를 병기하지 않는다 — 검토 후 반려 (2026-07-30)

**제기**: 외부 리뷰(Codex, 2026-07-30). `service/api.py` 의 `PARTY_PRECISION` 은
`family` 0.633 · `work` 0.700 을 항목마다 실어 보내는데,
`frontend/app/src/components/VisitorPartyCard.tsx` 는 둘 중 **최솟값 하나**로
「10건 중 4건쯤은 틀려요」 문장을 만들고 각 행에는 값을 적지 않는다. 두 클래스의
서로 다른 검정 결과가 화면에서 사라진다는 지적.

**반려. 근거 셋.**

1. **계약이 보내는 필드를 화면이 전부 그려야 하는 것은 아니다.** 같은 응답의
   `source`·`unit`·`claim` 도 그리지 않는다. 계약은 무엇을 줄 수 있는지를 정하지
   무엇을 그려야 하는지를 정하지 않는다.
2. **최솟값 사용은 보수적인 방향이다.** 좋은 쪽(`work` 0.700)을 나쁜 쪽 기준으로
   말하므로 정확도가 **과장되는 경우가 없다.** 반대 방향이었다면 반려하지 않았다.
3. **0.633 과 0.700 의 차이는 창업자의 판단을 바꾸지 않는다.** 둘 다 «열 번에
   서너 번 틀린다»이고, 화면에 «63.3%»를 적는 것은 고객 카피 규칙(기술 설명 0,
   `frontend/design/ui-spec.md`)에 걸린다.

**다시 열어야 하는 조건**: 승인 클래스가 셋 이상이 되거나 클래스 간 정밀도 차가
0.15 를 넘으면 «하나의 문장»이 어느 쪽도 대표하지 못한다. 그때는 행별 표기로
바꾼다.

**반려했다고 없어지는 문제는 아니다** — 정밀도는 `docs/unstructured-plan.md`
§J-1 파일럿 결과에 클래스별로 남아 있고, 재검정 시 그 표가 기준이다.

---

## F-A6. Offline economics curve collapses duplicate cohort keys (2026-07-31)

**Found** while regenerating post-refresh documentation inputs.

**Symptom:** `model/economics.py:67-71` indexes licence rows only by
`(grid_id, open_ym)` and then selects `cands[0]`. The key omits `uptae`, and
multiple shops can share a grid and opening month. This both attaches an
arbitrary closure to a holdout row and discards the remaining shops. Running
`python -m model.ui_inputs` therefore produced 3-year economics values that do
not match the deployed batch curve.

**Verified serving contrast:** `service/precompute.py:218` uses
`(grid_id, uptae, open_ym)`, checks that each key has one grade, and extends the
curve with every matching licence duration. `service/economics.py` consumes
that precomputed curve rather than fitting on an HTTP request. The refreshed
canonical scenario is grade 1 `+360`, grade 9 `-5,638`, a `5,998` difference
in ten-thousand won units; the offline script printed a different lineage.

**Why it is out of scope here:** The requested work refreshes the licence
source and every deployed downstream artifact. Changing the offline analysis
implementation would be a separate model-code correction and is not required
to restore the source-count gate. The serving path is unaffected.

**Blast radius:** `model.ui_inputs` must not be used to refresh economics
documentation until its cohort identity and duplicate handling match
`service.precompute`. Current documentation uses the deployed `score_meta`
curve and `service.economics` calculation instead.

---

## F-A7. Source refresh was not self-invalidating (2026-07-31) — resolved

**Status:** Resolved on 2026-07-31. Found while reviewing the completed
licence refresh.

**Symptom 1:** `pipeline.bootstrap --refresh collect` sets the orchestration
`force` flag, but `pipeline/seoul_api.py:94` returns an existing JSONL cache
before any HTTP request. The flag is not passed into `fetch_all`, so a command
named refresh can silently reuse the old raw source.

**Symptom 2:** `model/cache.py:43` keys split caches by years, horizon,
options, and source-code fingerprint only. It does not include a database or
licence-data fingerprint. A refreshed database can therefore reuse a split
built from the previous source snapshot.

**Historical mitigation:** The 535,603-row raw JSONL was archived before
collection, forcing a fresh 535,715-row download. Existing split caches were
also moved out of the active cache directory before `precompute` and
`ui_curves`. Independent refits reproduce the deployed AUC and grade metrics,
so the current artifacts are not stale.

**Resolution:** `bootstrap --refresh collect` now passes its force policy
through `collect_seoul` to every `fetch_all` call. Forced collection ignores
both a completed JSONL and an interrupted partial cache; ordinary collection
still returns the completed cache without an HTTP call.

`model.cache.cached_split` now adds a one-scan licence fingerprint containing
row count plus `is_closed`, opening year/month, and closing year/month
aggregates. A changed outcome therefore selects a new cache path even when the
row count is unchanged. Unchanged data still selects and reuses the same path.

Regression tests cover force propagation, complete/partial raw-cache bypass,
outcome-only invalidation, row-count invalidation, and unchanged-data reuse.
The new key component intentionally invalidates existing split caches once;
the next model command rebuilds them, then later unchanged runs reuse them.

**Blast radius after resolution:** A future source refresh no longer depends
on an operator remembering to archive either cache. The added licence scan
runs once per split-cache request and is small relative to rebuilding a
multi-year split.
