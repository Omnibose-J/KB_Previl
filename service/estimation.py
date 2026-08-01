"""Candidate-level occupancy cost estimation from read-only sources."""

from dataclasses import asdict
import math
import os

from service import api
from service.cost import (CostParams, effective_monthly_cost,
                          effective_monthly_cost_band)
from pipeline.config import UPTAE_INDUTY


DEFAULT_SUCCESSION_PROB = 0.4
DEFAULT_RECOVERY_SOURCE = "m2"
RECOVERY_SOURCES = {"constant", "survival_curve_proxy", "m2"}
M2_MODEL_VERSION = "m2-gbm-close-2005-2021-cal-2022-v1"
M2_AS_OF_YM = 202607
REVENUE_RESOLUTION = "trade_area"
ESTIMATE_NOTICE = (
    "상권×동일 업종의 최신 분기 점포당 추정매출을 사용한 참고용 계산이며, "
    "개별 매물의 매출을 예측하거나 배분한 값이 아닙니다. 승계 확률은 "
    "권리금 지불비율이 아니며, 지불비율 원천은 확보되지 않았습니다. "
    "대표 점유비용은 권리금 회수율 0의 보수적 기준선이며, 비용 밴드는 "
    "승계 확률을 회수율 상한으로만 사용합니다."
)


class EstimationUnavailableError(RuntimeError):
    """A required source for candidate estimation is unavailable."""


def _succession_probability(detail, uptae):
    source = os.environ.get(
        "KB_RECOVERY_SOURCE",
        DEFAULT_RECOVERY_SOURCE,
    )
    if source not in RECOVERY_SOURCES:
        raise EstimationUnavailableError(
            f"지원하지 않는 KB_RECOVERY_SOURCE입니다: {source}"
        )

    if source == "constant":
        return DEFAULT_SUCCESSION_PROB, source

    if source == "survival_curve_proxy":
        probability = detail["observed_survival"]
    else:
        with api.base.readonly_connection() as con:
            table_exists = con.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='succession_score'"
            ).fetchone()
            if table_exists is None:
                raise EstimationUnavailableError(
                    "M2 승계 확률 원천 테이블이 없습니다."
                )
            row = con.execute(
                "SELECT succession_prob, recovery_source, as_of_ym, model_version "
                "FROM succession_score "
                "WHERE grid_id = ? AND uptae = ?",
                (detail["grid_id"], uptae),
            ).fetchone()
        if row is None:
            raise EstimationUnavailableError(
                "해당 격자·업태의 M2 승계 확률 원천 행이 없습니다."
            )
        if row["recovery_source"] != "m2":
            raise EstimationUnavailableError(
                "M2 승계 확률 원천 계보가 일치하지 않습니다."
            )
        if (
            row["model_version"] != M2_MODEL_VERSION
            or row["as_of_ym"] != M2_AS_OF_YM
        ):
            raise EstimationUnavailableError(
                "M2 승계 확률 모델 버전 또는 관측시점이 일치하지 않습니다."
            )
        probability = row["succession_prob"]

    if probability is None:
        return None, source
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise EstimationUnavailableError(
            f"{source} 승계 확률 원천값이 유효하지 않습니다."
        )
    return float(probability), source


def _trade_area_revenue(grid_id, uptae, sales_available):
    with api.base.readonly_connection() as con:
        grid = con.execute(
            "SELECT trdar_cd FROM grid_feature WHERE grid_id = ?",
            (grid_id,),
        ).fetchone()
        if grid is None:
            raise api.ResourceNotFoundError(api.NOT_EVALUATED_DETAIL)
        trade_area_code = grid["trdar_cd"]
        if not sales_available:
            return None, None, trade_area_code

        # 아래 세 갈래는 «원천이 그 조합을 안 담고 있다»는 사실이지 장애가 아니다.
        # 예전에는 여기서 예외를 올려 «다시 시도» 버튼이 떴는데, 다시 눌러도 없는
        # 행은 생기지 않는다. 실측(2026-07-30)으로 기타·외국음식전문점은 100%,
        # 경양식 62.5% · 일식 60% · 통닭 57.5% 가 이 경로였고, 추천 상위 20곳에서도
        # 경양식 8/20 이 오류 화면이었다.
        induty_code = UPTAE_INDUTY.get(uptae)
        if induty_code is None:
            return None, None, trade_area_code
        quarter = con.execute(
            "SELECT MAX(s.quarter) "
            "FROM trdar_sales s "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE s.induty_cd = ? AND t.stor_co > 0",
            (induty_code,),
        ).fetchone()[0]
        if quarter is None:
            return None, None, trade_area_code
        source = con.execute(
            "SELECT s.sales_amt / t.stor_co / 3.0 / 10000.0 "
            "FROM trdar_sales s "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE s.quarter = ? AND s.trdar_cd = ? "
            "AND s.induty_cd = ? AND t.stor_co > 0",
            (quarter, trade_area_code, induty_code),
        ).fetchone()

    if (
        source is None
        or source[0] is None
        or not math.isfinite(source[0])
        or source[0] <= 0
    ):
        return None, None, trade_area_code
    return source[0], quarter, trade_area_code


def estimate_candidate(
    *,
    grid_id,
    lon,
    lat,
    uptae,
    deposit,
    monthly_rent,
    asking_goodwill,
    area_m2,
    floor,
    cost_params,
):
    detail = (
        api.grid_detail(grid_id, uptae)
        if grid_id is not None
        else api.at_point(lon, lat, uptae)
    )
    if detail is None:
        raise api.ResourceNotFoundError(api.NOT_EVALUATED_DETAIL)

    monthly_revenue, quarter, trade_area_code = _trade_area_revenue(
        detail["grid_id"],
        uptae,
        detail["sales_available"],
    )
    succession_prob, recovery_source = _succession_probability(detail, uptae)
    try:
        params = CostParams(**cost_params)
        breakdown = effective_monthly_cost(
            deposit=deposit,
            monthly_rent=monthly_rent,
            maintenance_fee=0,
            premium=asking_goodwill,
            recovery_prob=0.0,
            params=params,
        )
        effective_cost_band = effective_monthly_cost_band(
            deposit=deposit,
            monthly_rent=monthly_rent,
            maintenance_fee=0,
            premium=asking_goodwill,
            succession_prob=succession_prob,
            params=params,
        )
    except ValueError as exc:
        raise api.ApiInputError(
            "비용 입력의 계산 결과가 유한 범위를 벗어납니다."
        ) from exc
    burden_rate = (
        breakdown.effective_monthly_cost / monthly_revenue
        if monthly_revenue is not None
        else None
    )
    burden_rate_band = (
        {
            "low": effective_cost_band.low / monthly_revenue,
            "high": effective_cost_band.high / monthly_revenue,
        }
        if monthly_revenue is not None
        else None
    )
    burden_values = (
        [burden_rate, *burden_rate_band.values()]
        if burden_rate_band is not None
        else []
    )
    if not all(math.isfinite(value) for value in burden_values):
        raise api.ApiInputError(
            "부담률 계산 결과가 유한 범위를 벗어납니다."
        )
    missing_axes = (
        [] if monthly_revenue is not None else ["revenue", "burdenRate"]
    )
    result = {
        "grid_id": detail["grid_id"],
        "uptae": uptae,
        "grade": detail["grade"],
        "deposit": deposit,
        "monthly_rent": monthly_rent,
        "asking_goodwill": asking_goodwill,
        "area_m2": area_m2,
        "floor": floor,
        "succession_prob": succession_prob,
        "recovery_source": recovery_source,
        "effective_cost": breakdown.effective_monthly_cost,
        "effective_cost_band": asdict(effective_cost_band),
        "cost_breakdown": asdict(breakdown),
        "monthly_revenue": monthly_revenue,
        "revenue_as_of_quarter": quarter,
        "revenue_resolution": REVENUE_RESOLUTION,
        "burden_rate": burden_rate,
        "burden_rate_band": burden_rate_band,
        "missing_axes": missing_axes,
        "params_used": cost_params,
        "notice": ESTIMATE_NOTICE,
    }
    return result, trade_area_code


def rank_candidates(evaluated):
    results = [dict(result) for result, _trade_area_code in evaluated]
    for result in results:
        if "succession_prob" not in result and "recovery_prob" in result:
            # Internal W1-W4 fixtures use the former key. Public serialization
            # remains successionProb; this adapter does not invent a value.
            result["succession_prob"] = result.pop("recovery_prob")

    rent_order = sorted(
        range(len(results)),
        key=lambda index: (results[index]["monthly_rent"], index),
    )
    for rank, index in enumerate(rent_order, start=1):
        results[index]["rent_rank"] = rank

    def teo_key(index):
        result = results[index]
        burden = result["burden_rate"]
        succession = result["succession_prob"]
        return (
            burden is None,
            burden if burden is not None else 0,
            result["effective_cost"],
            succession is None,
            -(succession if succession is not None else 0),
            index,
        )

    teo_order = sorted(range(len(results)), key=teo_key)
    for rank, index in enumerate(teo_order, start=1):
        results[index]["teo_rank"] = rank

    trade_area_counts = {}
    for result, trade_area_code in evaluated:
        key = (result["uptae"], trade_area_code)
        if trade_area_code is not None and result["monthly_revenue"] is not None:
            trade_area_counts[key] = trade_area_counts.get(key, 0) + 1
    for index, (result, trade_area_code) in enumerate(evaluated):
        key = (result["uptae"], trade_area_code)
        results[index]["revenue_tied"] = trade_area_counts.get(key, 0) > 1

    return results
