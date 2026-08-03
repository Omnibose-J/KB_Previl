"""Wire models for the HTTP layer.

Declarations only: field names, types, and validation. No queries, no routing.
Every model camel-cases its aliases so the UI sees `gridId`, not `grid_id`.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

from pipeline.grade_bands import GRADE_COUNT


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


Grade = Annotated[int, Field(ge=1, le=GRADE_COUNT)]
Point = tuple[float, float]
UptaeName = Annotated[str, Field(min_length=1, max_length=80)]
RecoverySource = Literal["constant", "survival_curve_proxy", "m2"]


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
    years: Literal[1, 2, 3, 5]
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


class SurvivalYear(ApiModel):
    year: int
    survival: Annotated[float, Field(ge=0, le=1)]
    opened: int


class MetaResponse(ApiModel):
    as_of: str | None
    uptae: list[str]
    goodwill_supported_uptae: list[str]
    districts: list[str]
    observed_by_grade: list[ObservedGrade]
    overall_survival: Annotated[float | None, Field(ge=0, le=1)]
    survival_by_period: list[SurvivalPeriod]
    grade_area: GradeArea | None
    grid_count: int
    grade_direction: Literal["1_is_best"]
    seoul_survival_trend: list[SurvivalYear]
    caveats: list[str]
    model_note: str
    resolutions: dict[str, str]


class AreaItem(ApiModel):
    district: str
    adm_dong: str
    center: Point
    grid_count: int


class AreasResponse(ApiModel):
    items: list[AreaItem]


class GridAddressResponse(ApiModel):
    grid_id: str
    district: str | None
    adm_dong: str | None
    jibun: str | None
    label: str | None
    #  jibun = 인허가 주소의 본번까지, dong = 행정동까지밖에 못 좁힌 칸
    precision: Literal["jibun", "dong"] | None
    records: int
    agree: int


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
    same_uptae_here: int | None
    same_uptae_neighbor: int | None
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
    #: 선택한 업태 기준. available 은 «상권 안이냐», 아래 둘은 «그 안에서 그
    #: 업종의 매출이 공표됐느냐» 다. 상권 안에서도 31.1% 가 미공표인데, 원인은
    #: 표본 부족 비공개다 — 점포 1곳이면 공표율 9.7%, 20곳 이상이면 99.2%.
    uptae_stores: float | None
    uptae_published: bool


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


class PartyCount(ApiModel):
    party: Literal["family", "work"]
    label: str
    posts: int
    share: float | None
    precision: float | None


class VisitorParty(ApiModel):
    """방문객이 쓴 블로그 글에서 뽑은 «누구와 왔는가». 관측 집계이지 예측이 아니다.

    검정은 `docs/unstructured-plan.md` §J-1. 표기 문턱을 통과한 두 클래스만
    나간다 — `alone`·`couple`·`friend` 는 정밀도 미달로 서빙되지 않는다.

    `precision` 은 지금 **항상 null** 이다. 파일럿이 잰 0.633·0.700 은 단일
    라벨러 코퍼스의 값인데 §J-1 재판정에서 코퍼스가 섞였고, 그 수치가 전체를
    설명하지 못하게 됐다. 검정되지 않은 정확도를 숫자로 실으면 «쟀다» 가
    «맞다» 로 읽히므로, 되살리기 전까지는 값을 내지 않는다. 필드는 계약에
    남겨 둔다 — 재검정이 끝나면 서버만 채우면 된다.

    `labelled` 는 **서빙하는 두 클래스의 합**이다. «누구와 왔는지 적힌 글 수»
    가 아니다 — 기각된 셋도 원문에는 있다.

    `available=False` 는 배치 미실행, 빈 `items` 는 글이 모자라 판단 불가다.
    """

    available: bool
    items: list[PartyCount]
    posts_scanned: int
    labelled: int
    unit: str
    source: str | None
    claim: str | None


class SalesMixCount(ApiModel):
    induty: str
    amount: int
    count: int
    share: float | None


class SalesMix(ApiModel):
    """상권의 업종별 결제 구성. 카드 결제 실측 집계이지 추정이 아니다.

    `concept_mix`(상호명으로 센 «어떤 가게가 있나»)의 짝이고, 둘은 실제로
    다르다 — 커피는 가게 27.8% / 결제 24.7%, 한식은 가게 31.8% / 결제 55.1%.

    `available=False` 는 상권 밖(격자의 49.5%)이거나 표가 없는 상태이고, 빈
    `items` 는 상권 안인데 공표된 요식 업종이 없는 경우다.
    """

    available: bool
    items: list[SalesMixCount]
    quarter: str | None
    total_amount: int | None
    unit: str


class GridDetail(GridCell):
    adm_dong: str | None
    district: str | None
    nearest_station: StationAnchor | None
    competition: Competition
    concept_mix: ConceptMix | None = None
    visitor_party: VisitorParty | None = None
    sales_mix: SalesMix | None = None
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


class ChangeEvent(ApiModel):
    kind: str
    grid_id: str
    uptae: str
    before_run: str
    after_run: str
    before_as_of: str
    after_as_of: str
    before_grade: int | None
    after_grade: int | None
    score_shift: float | None


class ChangeHistoryBucket(ApiModel):
    from_month: str = Field(alias="from")
    to: str
    opened: Annotated[int, Field(ge=0)]
    closed: Annotated[int, Field(ge=0)]


class ChangeHistoryRun(ApiModel):
    as_of: str


class ChangeHistory(ApiModel):
    unit: str
    bucket_months: Literal[6]
    buckets: list[ChangeHistoryBucket]
    runs: list[ChangeHistoryRun]


class ChangesResponse(ApiModel):
    """available=False 는 «변동 없음»이 아니라 «견줄 이전 판이 아직 없음»이다.
    둘을 한 모양으로 답하면 화면이 구분할 수 없다."""

    available: bool
    reason: str | None = None
    baseline_run: str | None = None
    current_run: str | None = None
    baseline_as_of: str | None = None
    current_as_of: str | None = None
    event: ChangeEvent | None = None
    sentence: str | None = None
    history: ChangeHistory | None


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


class BuildingFootprint(ApiModel):
    name: str | None
    floors: int | None
    # 바깥 링만. [[lon, lat], ...] 이고 첫 점과 끝 점이 같다.
    rings: list[list[list[float]]]


class FootprintsResponse(ApiModel):
    grid_id: str
    source: Literal["vworld"]
    buildings: list[BuildingFootprint]
    # 이 응답이 캐시에서 나왔는지. 상류 쿼터를 아끼는 것이 눈에 보여야 한다.
    cached: bool


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


class CandidateValues(ApiModel):
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


class CandidateInput(CandidateValues):
    label: Annotated[str | None, Field(min_length=1, max_length=80)] = None


class EstimateInput(CandidateValues):
    uptae: UptaeName
    cost_params: CostParamsInput = Field(default_factory=CostParamsInput)


class CompareInput(ApiModel):
    uptae: UptaeName
    candidates: Annotated[
        list[CandidateInput],
        Field(min_length=1, max_length=3),
    ]
    cost_params: CostParamsInput = Field(default_factory=CostParamsInput)

    @model_validator(mode="after")
    def validate_labels(self):
        labels = [
            candidate.label
            for candidate in self.candidates
            if candidate.label is not None
        ]
        if len(labels) != len(set(labels)):
            raise ValueError("후보 label은 서로 달라야 합니다.")
        return self


class CostBreakdownResponse(ApiModel):
    rent: float
    maintenance: float
    deposit_opportunity: float
    premium_amortized: float
    effective_monthly_cost: float


class ValueBandResponse(ApiModel):
    low: float
    high: float


# 아래 셋은 전부 부동산원 참고값이다. 공간단위가 시도·상권이라 격자에 붙이지
# 않고 표기만 하며, 원천이 없으면 필드가 통째로 null 이 된다(합성 금지).
class MarketAnchorResponse(ApiModel):
    region: str
    industry: str
    period: str
    source: str
    median: float
    mean: float
    per_m2: float
    has_goodwill_rate: float


class FloorReferenceResponse(ApiModel):
    floor: str
    utility_ratio: float
    first_floor_rent: float
    unit: str
    period: str
    source: str


class MarketRentResponse(ApiModel):
    # 화면이 임대료÷면적을 다시 셈하면 서버 산식의 사본이 생긴다. 단위 환산이
    # 한쪽만 바뀌는 순간 두 값이 갈리므로 환산도 서버가 한다.
    user_per_m2: float | None
    seoul_avg: float
    vacancy: float | None
    period: str
    unit: str
    area_count: Annotated[int, Field(ge=1)]
    min: float
    max: float
    percentile: Annotated[
        float | None,
        Field(
            ge=0,
            le=100,
            description=(
                "입력 임대료가 조사 상권 분포에서 서는 위치. 조사 대상은 "
                "부동산원이 고른 주요 상권이라 서울 전체의 대표 표본이 아닙니다."
            ),
        ),
    ]
    source: str


class EstimateResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    grade: Grade
    deposit: float
    monthly_rent: float
    asking_goodwill: float
    area_m2: float
    floor: int
    succession_prob: Annotated[
        float | None,
        Field(
            ge=0,
            le=1,
            description=(
                "폐업 뒤 다음 영업자가 이어받을 승계 확률. 권리금 지불비율이나 "
                "회수확률이 아니며, 지불비율 원천은 확보되지 않았습니다."
            ),
        ),
    ]
    recovery_source: Annotated[
        RecoverySource,
        Field(description="승계 확률에 실제 사용한 원천"),
    ]
    effective_cost: float
    effective_cost_band: ValueBandResponse
    cost_breakdown: CostBreakdownResponse
    monthly_revenue: float | None
    revenue_as_of_quarter: str | None
    revenue_resolution: Literal["trade_area"]
    burden_rate: float | None
    burden_rate_band: ValueBandResponse | None
    missing_axes: list[str]
    params_used: CostParamsInput
    floor_reference: FloorReferenceResponse | None
    market_rent: MarketRentResponse | None
    notice: str


class CompareItemResponse(EstimateResponse):
    label: str | None
    rent_rank: int
    teo_rank: int
    revenue_tied: bool


class CompareResponse(ApiModel):
    uptae: UptaeName
    revenue_resolution: Literal["trade_area"]
    recovery_source: RecoverySource
    params_used: CostParamsInput
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
    years: float
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
    valuation_years: float
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
    market_anchor: MarketAnchorResponse | None
    notice: str


class ReportInput(ApiModel):
    grid_id: Annotated[str, Field(pattern=r"^\d+_\d+$")]
    uptae: UptaeName


class ReportResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    sentences: Annotated[list[str], Field(min_length=3, max_length=5)]


class RunwayInput(ApiModel):
    grid_id: Annotated[str, Field(pattern=r"^\d+_\d+$")]
    uptae: UptaeName
    budget: Annotated[float, Field(ge=0)]
    upfront: Annotated[float, Field(ge=0)]
    rent_monthly: Annotated[float, Field(ge=0)]
    revenue_monthly: Annotated[float | None, Field(gt=0)] = None
    margin: Annotated[float | None, Field(gt=0, le=1)] = None
    ramp_months: Literal[3, 6, 9] = 6


class RunwayMonth(ApiModel):
    month: Annotated[int, Field(ge=1)]
    revenue: float
    net: float
    cum: float


class RunwayAssumption(ApiModel):
    label: str
    value: float
    source: str


class RunwayResponse(ApiModel):
    grid_id: str
    uptae: UptaeName
    level: Literal["IMPOSSIBLE", "DANGER", "WARN", "OK"]
    revenue_monthly: float
    revenue_source: Literal[
        "user_input", "trade_area_average", "seoul_trade_area_average"
    ]
    revenue_as_of_quarter: str | None
    budget: float
    upfront: float
    reserve: float
    working_capital_need: float
    coverage: float | None
    depletion_month: int | None
    breakeven_month: int | None
    trough_month: int
    horizon_months: int
    ramp_months: int
    curve: list[RunwayMonth]
    assumptions: list[RunwayAssumption]
