"""Operating-capital runway: cumulative cash-flow simulation for one spot.

Answers «내 예산으로 이 자리에서 몇 개월 버티는가». Revenue starts below the
steady level and ramps up while rent runs in full from month one, so the money
actually needed is the trough of the cumulative curve, not «고정비 × N개월».

The monthly-profit model is identical to economics.py (revenue × margin −
rent); this module adds only the ramp and the budget verdict on top, so the
steady-state month matches what the profit computation would say.

Units: 만원 throughout, matching economics/estimation.
"""

import math

from service import api
from service import economics
from service import runway_params as params
# Reused deliberately: the runway default revenue must equal the number the
# other money cards show for the same grid, or the screens contradict.
from service.estimation import _trade_area_revenue


def revenue_ramp(steady, month, ramp_months, start_ratio=params.START_RATIO.value):
    """Month-m revenue: linear from start_ratio×steady up to steady."""

    if month >= ramp_months:
        return steady
    return steady * (start_ratio + (1 - start_ratio) * (month / ramp_months))


def cashflow_curve(steady_revenue, margin, rent_monthly, ramp_months):
    """24-month cumulative cash flow. The curve IS the product — never drop it."""

    cumulative = 0.0
    curve = []
    for month in range(1, params.HORIZON_MONTHS + 1):
        revenue = revenue_ramp(steady_revenue, month, ramp_months)
        net = revenue * margin - rent_monthly
        cumulative += net
        curve.append(
            {"month": month, "revenue": revenue, "net": net, "cum": cumulative}
        )
    return curve


def _resolve_revenue(grid_id, uptae, user_value):
    """User input first, this grid's trade-area figure next, Seoul average last.

    Every branch is labeled in the response — the screen must say which one it
    is showing. Unknown grid ids 404 inside _trade_area_revenue.
    """

    if user_value is not None:
        return user_value, "user_input", None
    value, quarter, _trade_area = _trade_area_revenue(grid_id, uptae, True)
    if value is not None:
        return value, "trade_area_average", quarter
    value, quarter = economics.seoul_average_monthly_revenue()
    return value, "seoul_trade_area_average", quarter


def calculate(
    grid_id,
    uptae,
    budget,
    upfront,
    rent_monthly,
    revenue_monthly=None,
    margin=None,
    ramp_months=params.RAMP_MONTHS_DEFAULT,
):
    revenue, revenue_source, revenue_quarter = _resolve_revenue(
        grid_id, uptae, revenue_monthly
    )

    # Assumption rows: one per defaulted value, none for typed values. The
    # screen renders these verbatim as the «우리가 가정한 것» caption list.
    assumptions = []
    if margin is None:
        margin = params.MARGIN.value
        assumptions.append(
            {
                "label": "마진율",
                "value": margin,
                "source": params.MARGIN.source,
            }
        )
    assumptions.append(
        {
            "label": "개업 첫 달 매출",
            "value": params.START_RATIO.value,
            "source": params.START_RATIO.source,
        }
    )

    curve = cashflow_curve(revenue, margin, rent_monthly, ramp_months)

    reserve = budget - upfront
    trough = min(point["cum"] for point in curve)
    need = max(0.0, -trough)
    if need > 0 and reserve >= 0:
        coverage = round(reserve / need, 2)
    else:
        # IMPOSSIBLE (reserve < 0) or no working capital needed — a ratio
        # would mislead either way.
        coverage = None
    depletion_month = next(
        (point["month"] for point in curve if reserve + point["cum"] < 0), None
    )
    breakeven_month = next(
        (point["month"] for point in curve if point["net"] > 0), None
    )
    trough_month = min(curve, key=lambda point: point["cum"])["month"]

    if reserve < 0:
        level = "IMPOSSIBLE"
    elif need > 0 and reserve / need < params.COVERAGE_DANGER:
        level = "DANGER"
    elif need > 0 and reserve / need < params.COVERAGE_WARN:
        level = "WARN"
    else:
        level = "OK"

    if not all(
        math.isfinite(value)
        for value in (reserve, need, curve[-1]["cum"])
    ):
        raise api.ApiInputError("계산이 유한한 값을 벗어났습니다 — 입력을 확인하세요.")

    return {
        "grid_id": grid_id,
        "uptae": uptae,
        "level": level,
        "revenue_monthly": revenue,
        "revenue_source": revenue_source,
        "revenue_as_of_quarter": revenue_quarter,
        "budget": budget,
        "upfront": upfront,
        "reserve": reserve,
        "working_capital_need": need,
        "coverage": coverage,
        "depletion_month": depletion_month,
        "breakeven_month": breakeven_month,
        "trough_month": trough_month,
        "horizon_months": params.HORIZON_MONTHS,
        "ramp_months": ramp_months,
        "curve": curve,
        "assumptions": assumptions,
    }
