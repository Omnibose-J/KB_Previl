"""Goodwill reference valuation from docs/goodwill-report-design.md §6."""

import math
import statistics

from pipeline.config import UPTAE_INDUTY
from service import api
from service.bands import _percentile
from service.economics import grade_survival_curves


BENCHMARK_LEVEL = 4
OPERATING_MARGIN = 0.0701
OPERATING_MARGIN_SOURCE = (
    "외식업체 경영실태조사(농림축산식품부·KREI) 2025년 조사 "
    "서울 외식업체 영업이익률 7.01% (2024년 실적, n=491, 임대료 차감 후)"
)
LOAN_RATE = 0.05
RISK_PREMIUM = 0.03
DISCOUNT_RATE_SOURCE = "소상공인 대출금리 5% + 사업위험 프리미엄 3% (v1 고정)"
ADJUSTMENT_FACTOR = 1.0
ADJUSTMENT_REASONS = ["v1 미적용 — 데이터 기반 조정 항은 로드맵"]

# The licensing taxonomy is more granular than Seoul's commercial-analysis
# taxonomy. Only mappings that preserve the same food-service category are
# served; unsupported categories fail instead of borrowing another benchmark.


class GoodwillUnavailableError(RuntimeError):
    """A required server-owned valuation source is unavailable."""


def _server_owned_inputs(grid_id, uptae):
    detail = api.grid_detail(grid_id, uptae)
    if detail is None:
        raise api.ResourceNotFoundError(api.NOT_EVALUATED_DETAIL)
    if not detail["sales_available"]:
        raise api.ApiInputError("무형재산을 계산할 상권 매출 근거가 없는 격자입니다.")

    induty_code = UPTAE_INDUTY.get(uptae)
    if induty_code is None:
        raise GoodwillUnavailableError(
            f"서울 동일 업종 벤치마크 원천이 없는 업태입니다: {uptae}"
        )

    with api.base.readonly_connection() as con:
        quarter = con.execute(
            "SELECT MAX(s.quarter) "
            "FROM trdar_sales s "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE s.induty_cd = ? AND t.stor_co > 0",
            (induty_code,),
        ).fetchone()[0]
        if quarter is None:
            raise GoodwillUnavailableError(
                "서울 동일 업종 벤치마크 원천 행이 없습니다."
            )
        # Median, not mean (원안 §5-3): trade-area sales are right-tailed, so a
        # mean benchmark is dragged up by the top districts and understates
        # everyone else's excess profit. Owner call 2026-07-27.
        benchmark_rows = con.execute(
            "SELECT s.sales_amt / t.stor_co / 3.0 / 10000.0 "
            "FROM trdar_sales s "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE s.quarter = ? AND s.induty_cd = ? AND t.stor_co > 0",
            (quarter, induty_code),
        ).fetchall()
        values = [row[0] for row in benchmark_rows if row[0] is not None]
        benchmark = statistics.median(values) if values else None
        if benchmark is None or benchmark <= 0:
            raise GoodwillUnavailableError(
                "서울 동일 업종 벤치마크 원천 행이 없습니다."
            )
        monthly_revenue = con.execute(
            "SELECT s.sales_amt / t.stor_co / 3.0 / 10000.0 "
            "FROM grid_feature f "
            "JOIN trdar_sales s ON s.trdar_cd = f.trdar_cd "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE f.grid_id = ? AND s.quarter = ? "
            "AND s.induty_cd = ? AND t.stor_co > 0",
            (grid_id, quarter, induty_code),
        ).fetchone()
    if monthly_revenue is None or monthly_revenue[0] is None or monthly_revenue[0] <= 0:
        raise GoodwillUnavailableError(
            "해당 상권 동일 업종의 월매출 원천 행이 없습니다."
        )
    return monthly_revenue[0], benchmark


def calculate_from_sources(
    *,
    grid_id,
    uptae,
    asking_goodwill,
    lease_remaining_years,
    assets,
):
    monthly_revenue, benchmark_monthly_revenue = _server_owned_inputs(grid_id, uptae)
    return calculate(
        grid_id=grid_id,
        uptae=uptae,
        asking_goodwill=asking_goodwill,
        lease_remaining_years=lease_remaining_years,
        monthly_revenue=monthly_revenue,
        benchmark_monthly_revenue=benchmark_monthly_revenue,
        benchmark_level=BENCHMARK_LEVEL,
        operating_margin=OPERATING_MARGIN,
        operating_margin_source=OPERATING_MARGIN_SOURCE,
        loan_rate=LOAN_RATE,
        risk_premium=RISK_PREMIUM,
        discount_rate_source=DISCOUNT_RATE_SOURCE,
        adjustment_factor=ADJUSTMENT_FACTOR,
        adjustment_reasons=ADJUSTMENT_REASONS,
        assets=assets,
    )


def _intangible_value(
    monthly_revenue,
    benchmark_monthly_revenue,
    operating_margin,
    discount_rate,
    years,
):
    annual_excess = max(
        0.0,
        (monthly_revenue - benchmark_monthly_revenue) * operating_margin * 12,
    )
    full_years = math.floor(years)
    value = sum(
        annual_excess / (1 + discount_rate) ** year
        for year in range(1, full_years + 1)
    )
    partial_year = years - full_years
    if partial_year:
        value += (
            annual_excess
            * partial_year
            / (1 + discount_rate) ** (full_years + 1)
        )
    return value


def _tangible_values(assets):
    values = []
    for asset in assets:
        residual_rate = max(
            0.0,
            1 - asset["age_years"] / asset["useful_life_years"],
        )
        values.append(
            {
                "name": asset["name"],
                "acquisition_cost": asset["acquisition_cost"],
                "age_years": asset["age_years"],
                "useful_life_years": asset["useful_life_years"],
                "residual_rate": residual_rate,
                "value": asset["acquisition_cost"] * residual_rate,
            }
        )
    return values


def calculate(
    *,
    grid_id,
    uptae,
    asking_goodwill,
    lease_remaining_years,
    monthly_revenue,
    benchmark_monthly_revenue,
    benchmark_level,
    operating_margin,
    operating_margin_source,
    loan_rate,
    risk_premium,
    discount_rate_source,
    adjustment_factor,
    adjustment_reasons,
    assets,
):
    detail = api.grid_detail(grid_id, uptae)
    if detail is None:
        raise api.ResourceNotFoundError(api.NOT_EVALUATED_DETAIL)
    if not detail["sales_available"]:
        raise api.ApiInputError("무형재산을 계산할 상권 매출 근거가 없는 격자입니다.")

    grade = detail["grade"]
    curve = grade_survival_curves()[grade]
    expected_survival_years = sum(curve[1:]) / 12
    curve_horizon_years = (len(curve) - 1) / 12
    years = min(
        expected_survival_years,
        lease_remaining_years,
        curve_horizon_years,
    )
    discount_rate = loan_rate + risk_premium

    intangible = _intangible_value(
        monthly_revenue,
        benchmark_monthly_revenue,
        operating_margin,
        discount_rate,
        years,
    )
    tangible_assets = _tangible_values(assets)
    tangible = sum(asset["value"] for asset in tangible_assets)
    decomposition = {
        "facility": tangible,
        "business": intangible,
        "floor_key": asking_goodwill - tangible - intangible,
    }
    estimated = (intangible + tangible) * adjustment_factor

    year_cap = min(lease_remaining_years, curve_horizon_years)
    candidate_years = {
        min(year_cap, years + offset) for offset in (-1, 0, 1)
    }
    sensitivity_years = sorted(
        candidate_year for candidate_year in candidate_years if candidate_year > 0
    )
    if not sensitivity_years:
        sensitivity_years = [years]
    sensitivity = []
    estimates = []
    for margin in (
        round(operating_margin - 0.015, 4),
        operating_margin,
        round(operating_margin + 0.015, 4),
    ):
        for sensitivity_year in sensitivity_years:
            for rate in (
                max(0.0, discount_rate - 0.02),
                discount_rate,
                discount_rate + 0.02,
            ):
                value = (
                    _intangible_value(
                        monthly_revenue,
                        benchmark_monthly_revenue,
                        margin,
                        rate,
                        sensitivity_year,
                    )
                    + tangible
                ) * adjustment_factor
                estimates.append(value)
                sensitivity.append(
                    {
                        "operating_margin": margin,
                        "years": sensitivity_year,
                        "discount_rate": rate,
                        "estimated_goodwill": value,
                    }
                )

    band_low = _percentile(estimates, 0.05)
    band_high = _percentile(estimates, 0.95)
    if asking_goodwill < band_low:
        negotiation_reference = "below_band"
    elif asking_goodwill > band_high:
        negotiation_reference = "above_band"
    else:
        negotiation_reference = "within_band"

    if benchmark_level == 4:
        benchmark_warning = (
            "동급 상권 비교가 아닌 서울 전체 동일 업종 상권 중앙값 대비입니다."
        )
    elif benchmark_level == 3:
        benchmark_warning = "표본 부족으로 인접 군집을 통합한 벤치마크입니다."
    else:
        benchmark_warning = None

    asking_gap = asking_goodwill - estimated
    return {
        "grid_id": grid_id,
        "uptae": uptae,
        "grade": grade,
        "asking_goodwill": asking_goodwill,
        "monthly_revenue": monthly_revenue,
        "benchmark_monthly_revenue": benchmark_monthly_revenue,
        "benchmark_level": benchmark_level,
        "benchmark_warning": benchmark_warning,
        "operating_margin": operating_margin,
        # This margin already includes rent; no second rent subtraction occurs.
        "operating_margin_basis": "after_rent",
        "operating_margin_source": operating_margin_source,
        "loan_rate": loan_rate,
        "risk_premium": risk_premium,
        "discount_rate": discount_rate,
        "discount_rate_source": discount_rate_source,
        "expected_survival_years": expected_survival_years,
        "valuation_years": years,
        "lease_remaining_years": lease_remaining_years,
        "intangible_value": intangible,
        "tangible_value": tangible,
        "tangible_assets": tangible_assets,
        "decomposition": decomposition,
        "adjustment_factor": adjustment_factor,
        "adjustment_reasons": adjustment_reasons,
        "estimated_goodwill": estimated,
        "band_low": band_low,
        "band_high": band_high,
        "asking_gap": asking_gap,
        "asking_gap_rate": asking_gap / estimated if estimated > 0 else None,
        "negotiation_reference": negotiation_reference,
        "sensitivity": sensitivity,
        "notice": (
            "서울시 상권분석서비스 최신 분기 점포당 추정매출을 사용한 "
            "공개 데이터 기반 참고용 추정치이며 감정평가가 아닙니다."
        ),
    }
