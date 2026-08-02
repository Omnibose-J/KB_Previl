"""FastAPI HTTP layer for lane B.

Run:  uvicorn service.app:app --reload --port 8000

The database is opened by ``service.api`` in SQLite read-only mode. Public
responses expose observed grade survival, never the model score, and all map
coordinates are WGS84.
"""

import math
import mimetypes
import pathlib                    # not `from pathlib import Path` - fastapi.Path is taken
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from service import api
from service import buildings as buildings_service
from service import economics as economics_service
from service import estimation as estimation_service
from service import footprints as footprints_service
from service import goodwill as goodwill_service
from service import reporting
from service import runway as runway_service

from .schemas import (
    AreasResponse,
    BuildingsResponse,
    ChangesResponse,
    CompareInput,
    CompareResponse,
    EconomicsInput,
    EconomicsResponse,
    ErrorResponse,
    EstimateInput,
    EstimateResponse,
    FootprintsResponse,
    GoodwillInput,
    GoodwillResponse,
    GridAddressResponse,
    GridDetail,
    GridsResponse,
    MetaResponse,
    RecommendResponse,
    ReportInput,
    ReportResponse,
    RunwayInput,
    RunwayResponse,
    ViewportErrorResponse,
)


app = FastAPI(title="KB Previl API")

# Vite dev server origin; the built demo is served same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(api.ViewportTooLargeError)
async def viewport_too_large(
    _request: Request, exc: api.ViewportTooLargeError
) -> JSONResponse:
    return JSONResponse(
        status_code=413,
        content={"detail": str(exc), "maxCells": exc.max_cells},
    )


@app.exception_handler(api.ApiInputError)
async def invalid_api_input(_request: Request, exc: api.ApiInputError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


def _finite_detail(value):
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: _finite_detail(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_detail(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def invalid_request_body(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    # 본문에 NaN/Infinity 리터럴이 오면 pydantic 은 거부하지만, 거부 상세에 그
    # 값이 그대로 실려 422 응답 자체의 직렬화가 터진다(= 500). JSON 이 못 싣는
    # 값은 글자로 바꿔 422 를 지킨다.
    return JSONResponse(
        status_code=422,
        content={"detail": _finite_detail(jsonable_encoder(exc.errors()))},
    )


@app.exception_handler(api.ResourceNotFoundError)
async def resource_not_found(
    _request: Request, exc: api.ResourceNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(api.DatabaseUnavailableError)
async def database_unavailable(
    _request: Request, exc: api.DatabaseUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(economics_service.EconomicsUnavailableError)
async def economics_unavailable(
    _request: Request, exc: economics_service.EconomicsUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(estimation_service.EstimationUnavailableError)
async def estimation_unavailable(
    _request: Request, exc: estimation_service.EstimationUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(footprints_service.FootprintsUnavailableError)
async def footprints_unavailable(
    _request: Request, exc: footprints_service.FootprintsUnavailableError
) -> JSONResponse:
    # 형제들은 503(우리 데이터가 없다)인데 이것만 502 다 — 실패한 곳이 우리가
    # 아니라 상류(VWORLD)라서, 둘을 같은 코드로 내면 원인 구분이 안 된다.
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(goodwill_service.GoodwillUnavailableError)
async def goodwill_unavailable(
    _request: Request, exc: goodwill_service.GoodwillUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(reporting.ReportUnavailableError)
async def report_unavailable(
    _request: Request, exc: reporting.ReportUnavailableError
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(reporting.ReportGenerationError)
async def invalid_report(
    _request: Request, exc: reporting.ReportGenerationError
) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


DATABASE_ERROR = {503: {"model": ErrorResponse}}
NOT_FOUND_DATABASE_ERRORS = {
    404: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@app.get(
    "/api/meta",
    response_model=MetaResponse,
    responses=DATABASE_ERROR,
)
def meta() -> dict:
    return {
        **api.meta(),
        "goodwill_supported_uptae": list(goodwill_service.UPTAE_INDUTY),
    }


@app.get(
    "/api/areas",
    response_model=AreasResponse,
    responses=DATABASE_ERROR,
)
def areas() -> dict:
    return api.areas()


@app.get(
    "/api/grids",
    response_model=GridsResponse,
    responses={
        413: {"model": ViewportErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def grids(
    uptae: Annotated[str, Query(min_length=1, max_length=80)],
    bbox: Annotated[str, Query(max_length=200)],
) -> dict:
    try:
        values = tuple(float(value.strip()) for value in bbox.split(","))
    except ValueError as exc:
        raise api.ApiInputError("bbox는 숫자 4개의 쉼표 구분값이어야 합니다.") from exc
    if len(values) != 4:
        raise api.ApiInputError(
            "bbox는 lon_min,lat_min,lon_max,lat_max 4개 값이어야 합니다."
        )
    return api.grids(uptae, values)


@app.get(
    "/api/recommend",
    response_model=RecommendResponse,
    responses=DATABASE_ERROR,
)
def recommend(
    uptae: Annotated[str, Query(min_length=1, max_length=80)],
    districts: Annotated[str, Query(max_length=500)] = "",
    top: Annotated[int, Query(ge=1, le=100)] = 24,
) -> dict:
    selected = [value for value in districts.split(",") if value.strip()]
    if len(selected) > 25:
        raise api.ApiInputError("districts는 최대 25개까지 지정할 수 있습니다.")
    return api.recommend(uptae, selected, top)


@app.get(
    "/api/grid/{grid_id}",
    response_model=GridDetail,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def grid_detail(
    grid_id: Annotated[str, Path(pattern=r"^\d+_\d+$")],
    uptae: Annotated[str, Query(min_length=1, max_length=80)],
) -> dict:
    item = api.grid_detail(grid_id, uptae)
    if item is None:
        raise HTTPException(status_code=404, detail=api.NOT_EVALUATED_DETAIL)
    return item


@app.get(
    "/api/grid/{grid_id}/changes",
    response_model=ChangesResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def grid_changes(
    grid_id: Annotated[str, Path(pattern=r"^\d+_\d+$")],
    uptae: Annotated[str, Query(min_length=1, max_length=80)],
) -> dict:
    return api.grid_changes(grid_id, uptae)


@app.get(
    "/api/grid/{grid_id}/address",
    response_model=GridAddressResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def grid_address(
    grid_id: Annotated[str, Path(pattern=r"^\d+_\d+$")],
) -> dict:
    return buildings_service.address_for_grid(grid_id)


@app.get(
    "/api/grid/{grid_id}/buildings",
    response_model=BuildingsResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def grid_buildings(
    grid_id: Annotated[str, Path(pattern=r"^\d+_\d+$")],
) -> dict:
    return buildings_service.for_grid(grid_id)


@app.get(
    "/api/grid/{grid_id}/footprints",
    response_model=FootprintsResponse,
    responses={
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def grid_footprints(
    grid_id: Annotated[str, Path(pattern=r"^\d+_\d+$")],
) -> dict:
    return footprints_service.for_grid(grid_id)


@app.get(
    "/api/at",
    response_model=GridDetail,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def at_point(
    lon: Annotated[float, Query(ge=-180, le=180)],
    lat: Annotated[float, Query(ge=-90, le=90)],
    uptae: Annotated[str, Query(min_length=1, max_length=80)],
) -> dict:
    item = api.at_point(lon, lat, uptae)
    if item is None:
        raise HTTPException(status_code=404, detail=api.NOT_EVALUATED_DETAIL)
    return item


@app.post(
    "/api/economics",
    response_model=EconomicsResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def economics(payload: EconomicsInput) -> dict:
    return economics_service.calculate(**payload.model_dump())


@app.post(
    "/api/estimate",
    response_model=EstimateResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def estimate(payload: EstimateInput) -> dict:
    values = payload.model_dump()
    values["cost_params"] = payload.cost_params.model_dump()
    result, _trade_area_code = estimation_service.estimate_candidate(**values)
    return result


@app.post(
    "/api/compare",
    response_model=CompareResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def compare(payload: CompareInput) -> dict:
    cost_params = payload.cost_params.model_dump()
    evaluated = []
    for candidate in payload.candidates:
        values = candidate.model_dump()
        label = values.pop("label")
        values.update(uptae=payload.uptae, cost_params=cost_params)
        result, trade_area_code = estimation_service.estimate_candidate(**values)
        result["label"] = label
        evaluated.append((result, trade_area_code))
    return {
        "uptae": payload.uptae,
        "revenue_resolution": estimation_service.REVENUE_RESOLUTION,
        "recovery_source": evaluated[0][0]["recovery_source"],
        "params_used": cost_params,
        "items": estimation_service.rank_candidates(evaluated),
    }


@app.post(
    "/api/runway",
    response_model=RunwayResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def runway(payload: RunwayInput) -> dict:
    return runway_service.calculate(**payload.model_dump())


@app.post(
    "/api/goodwill",
    response_model=GoodwillResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def goodwill(payload: GoodwillInput) -> dict:
    values = payload.model_dump()
    values["assets"] = [asset.model_dump() for asset in payload.assets]
    return goodwill_service.calculate_from_sources(**values)


@app.post(
    "/api/report",
    response_model=ReportResponse,
    responses={
        404: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
def report(payload: ReportInput) -> dict:
    return reporting.generate(
        payload.grid_id,
        payload.uptae,
    )


# --- built frontend --------------------------------------------------------
# 맨 마지막에 마운트한다. "/" 마운트가 앞에 오면 /api 를 통째로 삼킨다. 이 덕에
# .mjs 가 text/plain 으로 나가면 브라우저가 지도 워커를 실행하지 않는다.
mimetypes.add_type("application/javascript", ".mjs")

_ROOT = pathlib.Path(__file__).resolve().parent.parent
for _candidate in (_ROOT / "web", _ROOT / "frontend" / "app" / "dist"):
    if (_candidate / "index.html").is_file():
        app.mount("/", StaticFiles(directory=_candidate, html=True), name="ui")
        break
