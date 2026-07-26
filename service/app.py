"""HTTP layer scaffold (lane B) — contract: frontend/design/ui-spec.md §7.

Run:  uvicorn service.app:app --reload --port 8000

Every endpoint is a 501 stub wired to its intended source function; replace the
`_todo` call with the real implementation and a pydantic response model that
matches the schema recorded in lanes/B-backend.md. Rules that survive the
rewrite: read-only DB access (lane A owns writes), `observed` not `score`,
NULL stays null (never 0), WGS84 only (EPSG:5179 never crosses the API).
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="KB TEO API")

# Vite dev server origin; the built demo is served same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _todo(source: str) -> None:
    raise HTTPException(status_code=501, detail=f"TODO: wire to {source}")


@app.get("/api/meta")
def meta() -> None:
    _todo("service.api.meta — include caveats[] (approx-26%, AUC framing) and observed_by_grade with CI")


@app.get("/api/grids")
def grids(uptae: str, bbox: str) -> None:
    _todo("new viewport query over grid_score + grid polygons (cap cell count; pyproj 5179->WGS84)")


@app.get("/api/recommend")
def recommend(uptae: str, districts: str, top: int = 24) -> None:
    _todo("service.api.recommend — districts is comma-separated multi-select")


@app.get("/api/grid/{grid_id}")
def grid_detail(grid_id: str, uptae: str) -> None:
    _todo("service.api.grid_detail")


@app.get("/api/at")
def at_point(lon: float, lat: float, uptae: str) -> None:
    _todo("service.api.at_point — diagnosis mode ('이 자리 어때?')")


@app.post("/api/economics")
def economics() -> None:
    _todo("model.economics.scenario — margin is pre-rent (default 0.25); revenue absent -> Seoul average + usedSeoulAverageRevenue=True")


@app.post("/api/report")
def report() -> None:
    _todo("LLM sentence generation (docs/submission.md §3) — numeric whitelist: reject any number not in the payload")
