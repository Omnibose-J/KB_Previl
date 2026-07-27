"""Service wrapper around the measured-survival economics model."""

from service import api
from service.curve_contract import (
    CURVE_KEY,
    CURVE_MONTHS,
    parse_curve_payload,
)


class EconomicsUnavailableError(RuntimeError):
    """A required measured input could not be produced."""


def grade_survival_curves():
    """Read batch-computed curves; never fit or synthesize them at request time."""

    keys = (
        CURVE_KEY,
        "rank_model",
        "rank_features",
        "rank_train_years",
        "rank_test_years",
    )
    with api.readonly_connection() as con:
        raw = {
            row["k"]: row["v"]
            for row in con.execute(
                "SELECT k, v FROM score_meta WHERE k IN (?, ?, ?, ?, ?)",
                keys,
            )
        }
    if any(key not in raw for key in keys):
        raise EconomicsUnavailableError("배치 미실행: 등급별 실측 생존곡선이 없습니다.")

    try:
        train_years = [int(year) for year in raw["rank_train_years"].split(",")]
        test_years = [int(year) for year in raw["rank_test_years"].split(",")]
        return parse_curve_payload(
            raw[CURVE_KEY],
            raw["rank_model"],
            raw["rank_features"].split(","),
            train_years,
            test_years,
        )
    except (TypeError, ValueError) as exc:
        raise EconomicsUnavailableError(
            "배치 생존곡선 형식 또는 모델 계보가 잘못됐습니다."
        ) from exc


def _scenario(monthly_sales, margin, upfront, monthly_rent, curve):
    profit = monthly_sales * margin - monthly_rent
    naive_break_even = upfront / profit if profit > 0 else None
    expected = (
        sum(curve[month] * profit for month in range(1, CURVE_MONTHS + 1)) - upfront
    )
    cumulative = 0.0
    risk_break_even = None
    for month in range(1, CURVE_MONTHS + 1):
        cumulative += curve[month] * profit
        if risk_break_even is None and cumulative >= upfront:
            risk_break_even = month
    return {
        "profit": profit,
        "naive_be": naive_break_even,
        "risk_be": risk_break_even,
        "expected": expected,
        "survive_36m": curve[CURVE_MONTHS],
    }


def seoul_average_monthly_revenue():
    """Observed Seoul trade-area average per-store monthly revenue, in 만원."""

    with api.readonly_connection() as con:
        quarter = con.execute("SELECT MAX(quarter) FROM trdar_sales").fetchone()[0]
        if quarter is None:
            raise EconomicsUnavailableError("서울 상권 매출 기준 분기가 없습니다.")
        value = con.execute(
            "SELECT AVG(s.sales_amt / NULLIF(t.stor_co, 0)) / 3.0 "
            "FROM trdar_sales s "
            "JOIN trdar_store t "
            "ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd "
            "AND t.quarter = s.quarter "
            "WHERE s.quarter = ? AND t.stor_co > 0",
            (quarter,),
        ).fetchone()[0]
    if value is None:
        raise EconomicsUnavailableError("서울 상권 평균 매출을 계산할 수 없습니다.")
    return value / 10_000, quarter


def calculate(
    grid_id,
    uptae,
    rent_monthly,
    upfront,
    revenue_monthly=None,
    margin=0.25,
):
    detail = api.grid_detail(grid_id, uptae)
    if detail is None:
        raise api.ResourceNotFoundError(api.NOT_EVALUATED_DETAIL)

    used_average = revenue_monthly is None
    revenue_quarter = None
    if used_average:
        revenue_monthly, revenue_quarter = seoul_average_monthly_revenue()

    curves = grade_survival_curves()
    grade = detail["grade"]
    curve = curves[grade]
    result = _scenario(
        revenue_monthly,
        margin,
        upfront,
        rent_monthly,
        curve,
    )

    low_margin = _scenario(revenue_monthly, 0.20, upfront, rent_monthly, curve)[
        "expected"
    ]
    high_margin = _scenario(revenue_monthly, 0.30, upfront, rent_monthly, curve)[
        "expected"
    ]
    margin_sensitive = min(low_margin, high_margin) <= 0 <= max(low_margin, high_margin)

    comparison = []
    for comparison_grade in (1, 5, 10):
        comparison_result = _scenario(
            revenue_monthly,
            margin,
            upfront,
            rent_monthly,
            curves[comparison_grade],
        )
        comparison.append(
            {
                "grade": comparison_grade,
                "expected_profit_3y": comparison_result["expected"],
            }
        )

    return {
        "grid_id": grid_id,
        "uptae": uptae,
        "grade": grade,
        "revenue_monthly": revenue_monthly,
        "revenue_source": (
            "seoul_trade_area_average" if used_average else "user_input"
        ),
        "revenue_as_of_quarter": revenue_quarter,
        "simple_payback_months": result["naive_be"],
        "risk_adjusted_payback_months": result["risk_be"],
        "expected_profit_3y": result["expected"],
        "monthly_profit": result["profit"],
        "survival_36m": result["survive_36m"],
        "used_seoul_average_revenue": used_average,
        "margin": margin,
        "margin_sensitive": margin_sensitive,
        "grade_comparison": comparison,
    }
