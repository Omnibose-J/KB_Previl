"""FastAPI HTTP layer for lane B.

Run:  uvicorn service.app:app --reload --port 8000

The database is opened by ``service.api`` in SQLite read-only mode. Public
responses expose observed grade survival, never the model score, and all map
coordinates are WGS84.
"""

from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Path, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from service import api
from service import buildings as buildings_service
from service import economics as economics_service
from service import estimation as estimation_service
from service import goodwill as goodwill_service
from service import reporting


app = FastAPI(title="KB TEO API")

# Vite dev server origin; the built demo is served same-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class ErrorResponse(ApiModel):
    detail: str


class ViewportErrorResponse(ErrorResponse):
    max_cells: int


Grade = Annotated[int, Field(ge=1, le=10)]
Point = tuple[float, float]
UptaeName = Annotated[str, Field(min_length=1, max_length=80)]


class ObservedGrade(ApiModel):
    grade: Grade
    survival: Annotated[float, Field(ge=0, le=1)]
    n: int | None
    ci_low: Annotated[float | None, Field(ge=0, le=1)] = None
    ci_high: Annotated[float | None, Field(ge=0, le=1)] = None


class SurvivalBand(ApiModel):
    band: str
    survival: Annotated[float | None, Field(ge=0, le=1)]
    ci_low: Annotated[float | None, Field(ge=0, le=1)]
    ci_high: Annotated[float | None, Field(ge=0, le=1)]
    n: int | None


class SurvivalPeriod(ApiModel):
    years: Literal[1, 3, 5]
    cohort: str | None
    test_window: str | None
    overall: Annotated[float | None, Field(ge=0, le=1)]
    bench: str | None
    bands: list[SurvivalBand] | None


class GradeArea(ApiModel):
    grade_bands: list[str]
    area_bands: list[str]
    survival: list[list[Annotated[float | None, Field(ge=0, le=1)]]]
    bench: str


class MetaResponse(ApiModel):
    as_of: str | None
    uptae: list[str]
    districts: list[str]
    observed_by_grade: list[ObservedGrade]
    overall_survival: Annotated[float | None, Field(ge=0, le=1)]
    survival_by_period: list[SurvivalPeriod]
    grade_area: GradeArea | None
    grid_count: int
    grade_direction: Literal["1_is_best"]
    caveats: list[str]
    model_note: str
    resolutions: dict[str, str]


class GridCell(ApiModel):
    grid_id: str
    uptae: UptaeName
    grade: Grade
    observed_survival: Annotated[float, Field(ge=0, le=1)]
    confidence: Literal["full", "partial"]
    polygon: list[Point]
    center: Point
    sales_available: bool


class StationAnchor(ApiModel):
    name: str
    distance_m: float | None
    stations_500m: int | None = Field(alias="stations500m")


class Competition(ApiModel):
    shops_here: int | None
    shops_neighbor: int | None
    openings_36m: int | None = Field(alias="openings36m")
    openings_total: int | None
    closures_total: int | None


class AreaSurvival(ApiModel):
    rate: Annotated[float | None, Field(ge=0, le=1)]
    sample: int | None


class Demand(ApiModel):
    day_population: float | None
    night_population: float | None
    businesses: float | None
    workers: float | None
    worker_per_resident: float | None
    population_density: float | None


class Sales(ApiModel):
    quarterly_amount: float | None
    quarterly_count: float | None
    foot_traffic: float | None
    available: bool


class ConceptCount(ApiModel):
    concept: str
    shops: int


class ConceptMix(ApiModel):
    """주변 3x3 링의 상호명 콘셉트 구성. 관측 집계이지 예측이 아니다.

    `available=False` 는 배치 미실행이고 `items=[]` 는 구성이 잡히지 않는
    격자다. 둘을 같은 모양으로 내보내면 화면이 없는 것을 없다고 못 한다.
    """

    available: bool
    items: list[ConceptCount]
    shops: int
    source: str | None
    claim: str | None


class GridDetail(GridCell):
    adm_dong: str | None
    district: str | None
    nearest_station: StationAnchor | None
    competition: Competition
    concept_mix: ConceptMix | None = None
    area_survival: AreaSurvival
    demand: Demand
    sales: Sales
    signal: Literal["verified", "overheated"] | None
    missing_axes: list[str]
    resolutions: dict[str, str]


class RecommendResponse(ApiModel):
    uptae: UptaeName
    districts: list[str]
    total_grids: int
    in_scope: int
    count: int
    items: list[GridDetail]
    resolutions: dict[str, str]


class GridsResponse(ApiModel):
    count: int
    max_cells: int
    items: list[GridCell]
    resolutions: dict[str, str]


class UptaeMix(ApiModel):
    uptae: str | None
    active: int


class BuildingFact(ApiModel):
    jibun: str
    building_name: str | None
    active_shops: int
    openings_total: int
    closures_total: int
    uptae_mix: list[UptaeMix]


class BuildingsResponse(ApiModel):
    grid_id: str
    source: Literal["licence"]
    buildings: list[BuildingFact]
    unparsed_count: int


class EconomicsInput(ApiModel):
    grid_id: Annotated[str, Field(pattern=r"^\d+_\d+$")]
    uptae: UptaeName
    rent_monthly: Annotated[float, Field(ge=0)]
    upfront: Annotated[float, Field(ge=0)]
    revenue_monthly: Annotated[float | None, Field(gt=0)] = None
    margin: Annotated[float, Field(gt=0, le=1)] = 0.25


class GradeComparison(ApiModel):
    grade: Grade
    expected_profit_3y: float = Field(alias="expectedProfit3y")


class EconomicsResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    grade: Grade
    revenue_monthly: float
    revenue_source: Literal["user_input", "seoul_trade_area_average"]
    revenue_as_of_quarter: str | None
    simple_payback_months: float | None
    risk_adjusted_payback_months: int | None
    expected_profit_3y: float = Field(alias="expectedProfit3y")
    monthly_profit: float
    survival_36m: Annotated[
        float,
        Field(ge=0, le=1, alias="survival36m"),
    ]
    used_seoul_average_revenue: bool
    margin: Annotated[float, Field(gt=0, le=1)]
    margin_sensitive: bool
    grade_comparison: list[GradeComparison]


class CostParamsInput(ApiModel):
    opportunity_rate: Annotated[float, Field(ge=0, le=1)] = 0.04
    horizon_months: Annotated[int, Field(ge=1, le=120)] = 36


class CandidateInput(ApiModel):
    grid_id: Annotated[str | None, Field(pattern=r"^\d+_\d+$")] = None
    lon: Annotated[float | None, Field(ge=-180, le=180)] = None
    lat: Annotated[float | None, Field(ge=-90, le=90)] = None
    deposit: Annotated[float, Field(ge=0)]
    monthly_rent: Annotated[float, Field(ge=0)]
    asking_goodwill: Annotated[float, Field(ge=0)]
    area_m2: Annotated[float, Field(gt=0)]
    floor: Annotated[int, Field(ge=-20, le=200)]

    @model_validator(mode="after")
    def validate_location(self):
        has_grid = self.grid_id is not None
        coordinate_count = sum(value is not None for value in (self.lon, self.lat))
        if has_grid and coordinate_count:
            raise ValueError("gridId와 좌표 중 하나만 입력해 주세요.")
        if not has_grid and coordinate_count != 2:
            raise ValueError("gridId 또는 lon과 lat를 함께 입력해 주세요.")
        return self


class EstimateInput(CandidateInput):
    uptae: UptaeName
    cost_params: CostParamsInput = Field(default_factory=CostParamsInput)


class CompareInput(ApiModel):
    uptae: UptaeName
    candidates: Annotated[
        list[CandidateInput],
        Field(min_length=1, max_length=3),
    ]
    cost_params: CostParamsInput = Field(default_factory=CostParamsInput)


class CostBreakdownResponse(ApiModel):
    rent: float
    maintenance: float
    deposit_opportunity: float
    premium_amortized: float
    effective_monthly_cost: float


class EstimateResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    grade: Grade
    deposit: float
    monthly_rent: float
    asking_goodwill: float
    area_m2: float
    floor: int
    recovery_prob: Annotated[float, Field(ge=0, le=1)]
    effective_cost: float
    cost_breakdown: CostBreakdownResponse
    monthly_revenue: float | None
    revenue_as_of_quarter: str | None
    revenue_resolution: Literal["trade_area"]
    burden_rate: float | None
    missing_axes: list[str]
    notice: str


class CompareItemResponse(EstimateResponse):
    rent_rank: int
    teo_rank: int
    revenue_tied: bool


class CompareResponse(ApiModel):
    uptae: UptaeName
    revenue_resolution: Literal["trade_area"]
    items: list[CompareItemResponse]


class TangibleAssetInput(ApiModel):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    acquisition_cost: Annotated[float, Field(ge=0)]
    age_years: Annotated[float, Field(ge=0)]
    useful_life_years: Annotated[float, Field(gt=0)]


class GoodwillInput(ApiModel):
    grid_id: Annotated[str, Field(pattern=r"^\d+_\d+$")]
    uptae: UptaeName
    asking_goodwill: Annotated[float, Field(ge=0)]
    lease_remaining_years: Annotated[float, Field(gt=0, le=50)]
    assets: list[TangibleAssetInput] = Field(default_factory=list, max_length=50)


class TangibleAssetResult(TangibleAssetInput):
    residual_rate: Annotated[float, Field(ge=0, le=1)]
    value: float


class SensitivityRow(ApiModel):
    operating_margin: float
    years: int
    discount_rate: float
    estimated_goodwill: float


class GoodwillDecomposition(ApiModel):
    facility: float
    business: float
    floor_key: float


class GoodwillResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    grade: Grade
    asking_goodwill: float
    monthly_revenue: float
    benchmark_monthly_revenue: float
    benchmark_level: Annotated[int, Field(ge=1, le=4)]
    benchmark_warning: str | None
    operating_margin: float
    operating_margin_basis: Literal["after_rent"]
    operating_margin_source: str
    loan_rate: float
    risk_premium: float
    discount_rate: float
    discount_rate_source: str
    expected_survival_years: float
    valuation_years: int
    lease_remaining_years: float
    intangible_value: float
    tangible_value: float
    tangible_assets: list[TangibleAssetResult]
    decomposition: GoodwillDecomposition
    adjustment_factor: float
    adjustment_reasons: list[str]
    estimated_goodwill: float
    band_low: float
    band_high: float
    asking_gap: float
    asking_gap_rate: float | None
    negotiation_reference: Literal["below_band", "within_band", "above_band"]
    sensitivity: list[SensitivityRow]
    notice: str


class ReportInput(ApiModel):
    grid_id: Annotated[str, Field(pattern=r"^\d+_\d+$")]
    uptae: UptaeName


class ReportResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    sentences: Annotated[list[str], Field(min_length=3, max_length=5)]


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
    return api.meta()


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
    "/api/grid/{grid_id}/buildings",
    response_model=BuildingsResponse,
    responses=NOT_FOUND_DATABASE_ERRORS,
)
def grid_buildings(
    grid_id: Annotated[str, Path(pattern=r"^\d+_\d+$")],
) -> dict:
    return buildings_service.for_grid(grid_id)


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
        values.update(uptae=payload.uptae, cost_params=cost_params)
        evaluated.append(estimation_service.estimate_candidate(**values))
    return {
        "uptae": payload.uptae,
        "revenue_resolution": estimation_service.REVENUE_RESOLUTION,
        "items": estimation_service.rank_candidates(evaluated),
    }


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
