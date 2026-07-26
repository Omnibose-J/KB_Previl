# Findings — problems found in-flight that are out of the finder's write scope

## F-A1. `pipeline.consistency` is 15/17, not 17/17 — `_ENV_PATH` NameError (2026-07-27, lane A)

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

**Why it is not fixed here** — lane A's write scope is `model/` · `service/precompute.py` ·
`kb.db`; `pipeline/` is explicitly change-forbidden. The fix is 2 tokens (`_ENV_PATH` →
`ENV_PATH` on both lines) and belongs to whoever owns `pipeline/`.

**Blast radius** — the two dead checks are the *external* CRS witnesses (Kakao reverse-geocode
of stored lon/lat vs the row's own address). Their silence is exactly the failure mode
`CLAUDE.md` rule 2 was written about: an EPSG mix-up passes every internal check while
displacing every point 1–2 cells. Everything else (15 internal checks) passes, and
`probe/p8_crs.py` measured the CRS empirically, so there is no evidence of an actual
displacement — the loss is the standing guard, not a known defect.

**Note** — after the fix these two checks make live Kakao API calls, so 17/17 additionally
requires `KAKAO_REST_API_KEY` and network.
