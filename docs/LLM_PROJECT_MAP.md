# KB TEO Project Map

Refresh this ownership map when architecture or module ownership changes, not
on every commit. Keep it bounded to entry points and cross-module boundaries.

## Entry points

- FastAPI application: `service/app.py`; run with
  `uvicorn service.app:app`.
- React application: `frontend/app/src/main.tsx`; build from `frontend/app/`.
- Batch data and feature jobs: executable modules under `pipeline/`.
- Model experiments and batch scoring: executable modules under `model/`.
- Durable verification helpers: `scripts/`.

## Cross-module boundaries

- `pipeline/` owns source normalization, SQLite schema, feature construction,
  and batch-written tables.
- `model/` owns time-split experiments, leakage controls, calibration, and
  model-derived batch tables. It may read pipeline data and write only through
  explicit batch commands.
- `service/` owns the public HTTP contract and request-time arithmetic. Request
  handlers read SQLite with `mode=ro`; they do not train or import model code.
- `frontend/app/` owns the user experience and consumes the camelCase service
  contract. It must not recreate server formulas or replace `null` with zero.
- `docs/tracking/criteria-backend-teo-v1.md` is the acceptance contract for the
  candidate-cost backend work.

## Pipeline ownership

- Database configuration and schema: `pipeline/config.py`, `pipeline/db.py`.
- Licence normalization and cohort labels: `pipeline/normalize.py`,
  `pipeline/cohort.py`.
- Address-level tenancy chains and succession labels:
  `pipeline/addr_history.py`.
- Feature verification and consistency gates: `pipeline/verify.py`,
  `pipeline/consistency.py`.
- Shared served-grade shares and cumulative boundaries:
  `pipeline/grade_bands.py`; both offline analysis and service contracts import
  this pure module.
- Cached source material and generated runtime data stay outside tracked source.

## Model ownership

- Point-in-time feature replay: `model/asof.py`.
- Survival datasets, fitting, and established holdouts:
  `model/dataset.py`, `model/train.py`, `model/evaluate.py`.
- Split caching: `model/cache.py`; derived files live in ignored
  `model/.cache/`.
- Succession M2 experiment, observed-bin calibration, and batch serving table:
  `model/recovery.py`.
- Leakage and source-activation gate: `model/test_leakage.py`.
- Model experiments not named above remain offline research assets and do not
  enter request handling automatically.

## Service ownership

- FastAPI models, routes, errors, and camelCase serialization:
  `service/app.py`.
- Read-only grid and score lookup: `service/api.py`.
- Candidate estimate and comparison orchestration:
  `service/estimation.py`.
- Pure effective-cost arithmetic: `service/cost.py`.
- Building-level factual rows and a grid's approximate address:
  `service/buildings.py`.
- Goodwill, economics, and report adapters:
  `service/goodwill.py`, `service/economics.py`, `service/reporting.py`.
- Batch-only score production: `service/precompute.py`; this is the sole
  service module allowed to import model code.
- Grid change classification between two scoring runs: `service/alerts.py`
  (read-only; it never sends anything).
- Submission database extraction: `service/demo_db.py`. Its `TABLES` list is
  hand-maintained but gate-verified: `--audit` re-derives the tables `service/*.py`
  actually queries and refuses to build when the two disagree.

## Frontend ownership

- API client and contract types: `frontend/app/src/api/`.
- Screen composition and routing: `frontend/app/src/App.tsx`,
  `frontend/app/src/screens/`.
- Reusable product cards and states: `frontend/app/src/components/`.
- Formatting helpers and shared styling: `frontend/app/src/lib/` and local
  CSS modules.

## Runtime and recovery data

- `kb.db` is the active SQLite database and is ignored by Git.
- `KB_DB` selects a development or verification copy.
- `kb-baseline-20260728.db` is the VACUUM-created recovery baseline and is
  ignored by Git.
- Database truth is checked by content fingerprint: table row counts, four
  ranking metadata values, and `PRAGMA quick_check`, not file bytes.

## Verification

- Pipeline integrity: `python -m pipeline.verify` and
  `python -m pipeline.consistency`.
- Temporal leakage: `python -m model.test_leakage` and
  `python -m model.asof --selftest-cut`.
- Succession experiment: `python -m model.recovery --holdout` and
  `python -m model.recovery --calibration`.
- W7 public contract: `python scripts/verify_recovery_contract.py`.
- API behavior: `python -m pytest service/ -q`.
- Submission artefacts: `python build.py --rehearse`. Runs the ship gates
  (`tools/audit.py`), rebuilds the frontend when stale, writes the three
  artefacts to `SUBMISSION/`, then unpacks them into a scratch folder and boots
  the service there through `run.py` in a fresh virtualenv.
- Ship set: `tools/manifest.py` is the single source of truth for what goes in
  the code zip. Comments and docstrings are stripped at build time
  (`tools/strip.py`); the repository sources keep theirs.
