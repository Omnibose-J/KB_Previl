"""Single source of truth for what ships. audit.py gates it, package.py builds it."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Entry points the shipped tree must be reachable from.
ENTRY_IMPORT = ("service.app", "pipeline.bootstrap")

# Modules bootstrap runs as `python -m X` — invisible to an import walk.
ENTRY_CLI = (
    "model.tier2", "model.concept", "model.concept_mix", "model.ui_curves",
    "model.recovery", "model.party", "model.test_leakage", "model.asof",
    "pipeline.sgis", "pipeline.sgis_match", "pipeline.access",
    "pipeline.addr_history", "pipeline.verify", "pipeline.consistency",
    "service.precompute", "service.demo_db",
)

SHIP_PKGS = ("service", "model", "pipeline")

# 코드 zip 이 이 폴더 하나로 풀린다. DB zip 은 kb-demo.db 단일 항목이라
# 이 폴더 «안에» 풀어야 한다 — README 가 그렇게 안내한다.
ZIP_ROOT = "previl"

# 합본 zip 과 DB zip 이 담는 유일한 데이터 파일.
DB_NAME = "kb-demo.db"

# 서빙이 이 두 표를 읽는다. 비어 있으면 화면은 뜨지만 추천이 나오지 않는다.
DB_TABLES = ("grid_score", "score_meta")

# Non-Python payload. (source, arcname)
SHIP_FILES = (
    ("tools/submission-README.md", "README.md"),
    ("run.py", "run.py"),
    # 더블클릭 실행 입구 — run.py 를 감싸는 얇은 배치다. 로직은 전부 run.py 에.
    ("run.bat", "run.bat"),
    ("verify.ipynb", "verify.ipynb"),
    ("requirements.txt", "requirements.txt"),
    ("requirements-full.txt", "requirements-full.txt"),
    # main.tsx 가 직접 부른다. 이것 없이는 프론트 소스가 빌드되지 않는다.
    ("frontend/design/tokens/tokens.css", "frontend/design/tokens/tokens.css"),
)

# (source dir, arcname). web = 서버가 서빙하는 빌드본, frontend = 그 소스.
#
# 소스는 저장소 레이아웃 그대로 싣는다. `main.tsx` 가
# `../../design/tokens/tokens.css` 를 부르므로 `frontend/app` 을 `frontend` 로
# 옮기면 깊이가 한 칸 어긋나 빌드가 깨진다.
SHIP_TREES = (
    ("frontend/app/dist", "web"),
    ("frontend/app", "frontend/app"),
)

TREE_EXCLUDE_DIRS = {"node_modules", "dist", "__pycache__", ".vite",
                     ".ruff_cache", ".pytest_cache", ".mypy_cache"}
TREE_EXCLUDE_FILES = {".gitignore", "README.md", "tsconfig.tsbuildinfo"}
TREE_EXCLUDE = TREE_EXCLUDE_DIRS | TREE_EXCLUDE_FILES

# Anything else in the code zip is a mistake we have not thought of yet.
ALLOWED_SUFFIXES = {".py", ".ts", ".tsx", ".css", ".json", ".html", ".md",
                    ".txt", ".ipynb", ".js", ".mjs", ".map", ".png", ".webp",
                    ".svg", ".ico", ".woff", ".woff2", ".ttf", ".bat"}

MAX_LINES = 400

# Over MAX_LINES but single-purpose. The gate still catches anything new, so a
# file only lands here with a reason someone can argue with.
SIZE_EXEMPT = {
    "service/schemas.py":
        "wire model declarations only — splitting adds imports, not clarity",
    "frontend/app/src/api/types.ts":
        "type declarations only — same reason as service/schemas.py",
    "frontend/app/src/screens/S4Detail.tsx":
        "one screen composing already-separate cards; no test net to split behind",
    "frontend/app/src/screens/S5Compare.tsx":
        "one screen composing already-separate cards; no test net to split behind",
    "frontend/app/src/components/GoodwillCard.tsx":
        "one card, one calculation it explains",
    "model/asof.py": "as-of reconstruction is one algorithm",
    # 정직하게: 이것은 단일 책임이 아니다. 수집·LLM 추출·파일럿·적재·판정·kappa
    # 검정이 한 파일에 있다. 서빙 경로에 없는 오프라인 일회성 도구라 마감 전
    # 분해 위험을 지지 않기로 한 것이지, 구조가 옳아서가 아니다.
    "model/party.py": "offline one-shot tool, not on the serving path; split deferred",
    "model/recovery.py": "one model with its calibration",
    "pipeline/bootstrap.py": "one ordered step list plus its CLI",
    "pipeline/addr_history.py": "tenancy chain construction is one pass",
    "service/precompute.py": "one batch: fit, score, write",
}
MAX_COMMENT_RUN = 2
MAX_MODULE_DOC = 1
MAX_DEF_DOC = 2

# Comment content that is narrative, not function.
BANNED_COMMENT = (
    "§", "docs/", "CLAUDE.md", "model-findings", "findings.md", "lanes/",
    "기각", "채택", "실험", "negative result", "커밋", "레인", "R14", "AUC",
    "심사", "제출", "판정", "시행착오", "예전", "원래는", "이전에는", "옛날",
    "했었", "바꿨", "고쳤", "이었다", "쟀다", "측정했", "probe/",
)

# The only thing that survives stripping: one functional line per module.
HEADERS = {
    "run.py": "Set up, check the database, backfill if needed, serve.",

    "model/ablation.py": "Feature-group ablation comparison.",
    "model/asof.py": "Reconstruct a grid cell as of a past point in time.",
    "model/cache.py": "Disk cache for built training splits.",
    "model/concept.py": "Shop-name concept clustering (char n-gram TF-IDF + KMeans).",
    "model/concept_mix.py": "Concept composition over a 3x3 grid ring.",
    "model/dataset.py": "Build (features at opening, survived N years) rows.",
    "model/evaluate.py": "Model evaluation harness.",
    "model/extend.py": "Candidate feature extension screening.",
    "model/feature_gate.py": "Admission criteria for a candidate feature family.",
    "model/osm.py": "OSM road adjacency and junction density features.",
    "model/party.py": "Visitor party composition counted from reviews.",
    "model/recommend.py": "Turn the survival model into a ranked recommendation.",
    "model/recovery.py": "Succession probability model and calibration.",
    "model/robustness.py": "Usefulness checks on the recommendation.",
    "model/test_leakage.py": "Guard against future information leaking in.",
    "model/tier2.py": "Load the second licensing source (rest-type eateries).",
    "model/train.py": "Models fitted on the training years only.",
    "model/ui_curves.py": "Survival curves by grade and the grade x area table.",

    "pipeline/access.py": "Transit accessibility per grid cell.",
    "pipeline/addr_history.py": "Address-level tenancy chains and succession labels.",
    "pipeline/bootstrap.py": "Cold start: empty database to a serving one.",
    "pipeline/cohort.py": "Cohort survival by opening year.",
    "pipeline/collect.py": "Collect source APIs into the local cache.",
    "pipeline/config.py": "Pipeline constants: coordinate systems, APIs, units.",
    "pipeline/consistency.py": "Logical consistency checks over loaded data.",
    "pipeline/db.py": "SQLite schema.",
    "pipeline/features.py": "Build the grid and its features.",
    "pipeline/geocode.py": "Reverse geocode grid centres to administrative dong.",
    "pipeline/grade_bands.py": "Grade segmentation shared by serving and analysis.",
    "pipeline/grid.py": "100m grid over Seoul in EPSG:5179.",
    "pipeline/normalize.py": "Raw cache to normalized tables.",
    "pipeline/seoul_api.py": "Seoul Open Data client with a hard call budget.",
    "pipeline/sgis.py": "SGIS census demand features.",
    "pipeline/sgis_match.py": "Match grid cells to dong polygons.",
    "pipeline/verify.py": "Load verification.",

    "service/alerts.py": "Classify grid changes between two scoring runs.",
    "service/api/base.py": "Error contract, read-only connection, value coercions.",
    "service/api/cells.py": "One grid cell: select, polygon, detail payload.",
    "service/api/changes.py": "What moved between two scoring runs.",
    "service/api/context.py": "Batch context for a set of cells: neighbours, party, sales mix, concepts.",
    "service/api/meta.py": "City-wide tables: districts, survival benchmarks, grade x area.",
    "service/api/search.py": "Entry points that take user input and return cells.",
    "service/app.py": "FastAPI HTTP layer.",
    "service/bands.py": "Percentile bands for publicly shown values.",
    "service/buildings.py": "Building-level facts derived from licence records.",
    "service/cost.py": "Occupancy cost calculations.",
    "service/curve_contract.py": "Storage contract for grade survival curves.",
    "service/demo_db.py": "Extract the serving subset into a lightweight database.",
    "service/economics.py": "Wrapper around the measured-survival economics model.",
    "service/estimation.py": "Occupancy cost estimation for a candidate site.",
    "service/goodwill.py": "Goodwill reference valuation.",
    "service/precompute.py": "Precompute location grades for every (uptae, cell).",
    "service/reporting.py": "LLM sentences under a strict numeric whitelist.",
    "service/schemas.py": "Wire models for the HTTP layer: fields, types, validation.",
}

FORBIDDEN_NAMES = {".env", ".env.bak", ".env.example",
                   "kb.db", "kb.db-shm", "kb.db-wal", "kb-demo.db"}
FORBIDDEN_DIRS = {"cache", "node_modules", "__pycache__", ".git", ".venv",
                  "docs", "lanes", "probe", "scripts", "tools"}
