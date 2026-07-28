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

## F-C2. /goodwill: two uptae have no benchmark mapping and fail as 503 "retry"

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

## F-A2. Read-only gates mutate the shared `kb.db` (2026-07-28)

**Symptom** — running the canonical gate chain changed the shared DB SHA-256
from `69747C235957C0BA4C2387E1A39E0D0ECFD39C0160E4ED09DAE48C6F96BA6705`
to `32C651A81F320C11A9318E328DFBC88BA668148815678C88D1799A7C4E6BF6DB`
and created `kb.db-wal` / `kb.db-shm`, despite W1-W4 being read-only work.
An independent repeat of the same gate changed the hash again to
`0D0BBB8E3259B73F911B228E7B76CF04FE73B680F632199B10E9CC5E31F9AA8B`,
which reproduces the mutation.

**Cause** — `pipeline.verify`, `pipeline.consistency`, `model.test_leakage`,
and `model.asof --selftest-cut` call `pipeline.db.init()`.
`pipeline/db.py:192-195` executes the full `SCHEMA` and commits, while
`SCHEMA` starts with `PRAGMA journal_mode=WAL`. The verification entrypoint is
therefore a writer even when every predicate only reads data.

**Why it cannot be solved here** — `pipeline/` and shared DB writes belong to
lane A and require owner approval. Reverting journal mode or deleting WAL/SHM
would be another unapproved write while a live read-only API process holds the
database.

**Blast radius** — any lane B/C agent following the documented full-gate
command can violate the shared-DB immutability boundary before W5. This run
found no `addr_tenancy` table and `PRAGMA quick_check` returned `ok`, so there
is no evidence of W5 data landing; the byte-level baseline is nevertheless
lost. The smallest durable fix is a read-only gate connection that never calls
schema initialization, followed by a fresh-copy hash regression.
