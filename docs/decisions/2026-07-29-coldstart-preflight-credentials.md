# Lazy credential loading for cold-start preflight

**Decision:** On 2026-07-29, load `SEOUL_OPEN_API_KEY` only when a Seoul API
network request starts; local quota inspection remains credential-independent.

**Context:** `pipeline.bootstrap --preflight` must call
`pipeline.seoul_api.remaining()` without network access and must honor
`KB_ENV`. The prior module-level key load read a fixed root `.env`, so importing
the local quota function could reject a valid custom environment file.

**Why:** `remaining()` reads only the local `api_log`. Delaying credential
loading until `_get()` preserves fail-loud behavior at the actual trust
boundary, honors the shared `load_env()` path contract, and exposes no fallback.

**Rejected:** Keeping module-level key loading was rejected because it couples
local quota inspection to unrelated credentials and ignores `KB_ENV`. A dummy
key or import-time monkeypatch was rejected because either would mask missing
credentials.

**Status:** Active
