# Embed a filtered environment file in the submission archive

**Decision:** 2026-08-03. `KB_Previl.zip` contains `previl/.env`, generated
from the repository-root `.env` with only the keys referenced by shipped
Python code. The zip gate compares that payload byte-for-byte with a fresh
generation from the current source and environment file.

**Context:** The submission must run immediately after extraction, so the
environment file cannot remain a separate manual step. The root `.env` also
contains credentials and local settings used by unrelated projects.

**Why:** This keeps the one-archive execution path while applying least
privilege to the credentials being submitted. Deriving the key set from the
same shipped source used by the package avoids a second hand-maintained list,
and byte comparison prevents a stale or manually altered environment payload
from passing the submission gate.

**Rejected:**
- *Copy the complete root `.env`* — it would disclose unrelated credentials
  and local configuration without helping KB Previl run.
- *Keep `.env` beside the zip* — extraction would not be sufficient to run the
  service and the required manual placement could be missed by a reviewer.
- *Ship an example or empty environment file* — it would look complete while
  failing the requested ready-to-run contract.

**Status:** Active. Related context: [[submission]].
