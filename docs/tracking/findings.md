# Findings — problems found in-flight that are out of the finder's write scope

## F-A1. ~~`pipeline.consistency` is 15/17~~ — RESOLVED 2026-07-27 (`_ENV_PATH` NameError)

**Symptom**
```
$ python -m pipeline.consistency
[district]     ERROR NameError: name '_ENV_PATH' is not defined  -> FAIL
[dongaccuracy] ERROR NameError: name '_ENV_PATH' is not defined  -> FAIL
15/17 PASS  FAILED: ['district', 'dongaccuracy']   (exit 1)
```

**Cause** — `pipeline/consistency.py:152` imports `ENV_PATH` from `.config` but lines 154 and
321 dereference `_ENV_PATH`. Unconditional NameError, so both reverse-geocoding checks have
never run in this checkout. Introduced when `config.py` gained the `KB_ENV` worktree override
(`ENV_PATH`) and these two call sites kept the old private name.

**Resolution** — the owner authorised the edit on 2026-07-27 and it is applied. It was three
tokens, not two: `c_district` already imported `ENV_PATH` and only needed the dereference
fixed, but `c_dongaccuracy` imported `ROOT` alone, so its import line needed `ENV_PATH` added
as well. Both functions keep their own inline .env parse, matching the surrounding style.

```
$ python -m pipeline.consistency
[district]     역지오코딩 표본 200건 · 자치구 일치 200 / 불일치 0 (100.0%)  -> PASS
[dongaccuracy] 표본 200건 일치 200 / 불일치 0 (100.0%) 실패 0              -> PASS
17/17 PASS   (exit 0)
```

The CRS and dong assignments were sound all along — what was missing was the guard, not the
correctness. Both checks now make live Kakao calls, so 17/17 requires `KAKAO_REST_API_KEY`
and network; without either they return `None` and are skipped rather than failing.

**Blast radius** — the two dead checks are the *external* CRS witnesses (Kakao reverse-geocode
of stored lon/lat vs the row's own address). Their silence is exactly the failure mode
`CLAUDE.md` rule 2 was written about: an EPSG mix-up passes every internal check while
displacing every point 1–2 cells. Everything else (15 internal checks) passes, and
`probe/p8_crs.py` measured the CRS empirically, so there is no evidence of an actual
displacement — the loss is the standing guard, not a known defect.

**Note** — after the fix these two checks make live Kakao API calls, so 17/17 additionally
requires `KAKAO_REST_API_KEY` and network.

(Before the fix was authorised, both checks had been replicated read-only at n=60/80 with the
same 100.0% result, which is what made the repair a known-safe two-line change rather than a
gamble.)
