from pyproj import Transformer

from pipeline.config import CRS_GRID, CRS_WGS84, GRID_SIZE_M

from .base import ApiInputError, _plus


# The response includes this map wherever the fields occur. Coarse source data
# stays coarse; the UI must not present an administrative-dong value as 100 m.
RESOLUTION = {
    "competition.shopsHere": "격자 100m",
    "competition.shopsNeighbor": "격자 3x3 (300m)",
    "competition.sameUptaeHere": "격자 100m",
    "competition.sameUptaeNeighbor": "격자 3x3 (300m)",
    "competition.openingsTotal": "격자 100m",
    "competition.closuresTotal": "격자 100m",
    "areaSurvival": "격자 3x3 (300m)",
    "demand.dayPopulation": "행정동",
    "demand.nightPopulation": "행정동",
    "demand.businesses": "행정동",
    "demand.workers": "행정동",
    "demand.workerPerResident": "행정동",
    "demand.populationDensity": "행정동",
    "sales.quarterlyAmount": "상권 (중앙값 반경 151m)",
    "sales.quarterlyCount": "상권 (중앙값 반경 151m)",
    "sales.footTraffic": "상권 (중앙값 반경 151m)",
    "visitorParty": "상권",
    "salesMix": "상권 (중앙값 반경 151m)",
    "nearestStation": "지점 실측",
}


NOT_EVALUATED_DETAIL = "이웃 이력 부족으로 평가하지 않음"


_from_grid = Transformer.from_crs(CRS_GRID, CRS_WGS84, always_xy=True)


GRID_SELECT = """
SELECT f.grid_id, f.center_lon, f.center_lat, f.confidence,
       f.has_sales_data,
       f.food_store_cnt, f.food_store_cnt_r1,
       f.hist_open_cnt, f.hist_close_cnt,
       f.survive_3y_local, f.survive_3y_n,
       f.lvpop_day, f.lvpop_night, f.corp_cnt, f.tot_worker,
       f.worker_per_resident, f.ppltn_dnsty,
       f.sales_amt, f.sales_cnt, f.flpop,
       s.grade, s.observed,
       gs.sgis_adm_nm,
       a.station_dist_m, a.station_name, a.stations_500m
FROM grid_feature f
JOIN grid_score s ON s.grid_id = f.grid_id AND s.uptae = ?
LEFT JOIN grid_sgis gs ON gs.grid_id = f.grid_id
LEFT JOIN grid_access a ON a.grid_id = f.grid_id
"""


def _grid_polygon(grid_id):
    try:
        gx, gy = (int(value) for value in grid_id.split("_"))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ApiInputError("grid_id 형식이 올바르지 않습니다.") from exc

    x0 = gx * GRID_SIZE_M
    y0 = gy * GRID_SIZE_M
    corners = (
        (x0, y0),
        (x0 + GRID_SIZE_M, y0),
        (x0 + GRID_SIZE_M, y0 + GRID_SIZE_M),
        (x0, y0 + GRID_SIZE_M),
        (x0, y0),
    )
    return [
        [round(lon, 6), round(lat, 6)]
        for lon, lat in (_from_grid.transform(x, y) for x, y in corners)
    ]


def location_names(name):
    parts = name.split() if name else []
    district = parts[1] if len(parts) >= 2 else None
    adm_dong = parts[-1] if len(parts) >= 3 else None
    return district, adm_dong


def _grid_cell(row, uptae):
    return {
        "grid_id": row["grid_id"],
        "uptae": uptae,
        "grade": row["grade"],
        "observed_survival": row["observed"],
        "confidence": row["confidence"],
        "polygon": _grid_polygon(row["grid_id"]),
        "center": [
            round(row["center_lon"], 6),
            round(row["center_lat"], 6),
        ],
        "sales_available": bool(row["has_sales_data"]),
    }


def _grid_detail(row, uptae, same_uptae, rest_food, uptae_sales):
    district, adm_dong = location_names(row["sgis_adm_nm"])
    item = _grid_cell(row, uptae)
    item.update(
        {
            "adm_dong": adm_dong,
            "district": district,
            "nearest_station": (
                {
                    "name": row["station_name"],
                    "distance_m": row["station_dist_m"],
                    "stations_500m": row["stations_500m"],
                }
                if row["station_name"] is not None
                else None
            ),
            # 음식점 수·개폐업 누계에 휴게음식점(카페·베이커리·패스트푸드 등)을
            # 함께 센다. 그 전에는 서울 영업 중 음식업의 16.9% 가 빠진 값이었다.
            "competition": {
                "shops_here": _plus(row["food_store_cnt"], rest_food["alive"]),
                "shops_neighbor": _plus(row["food_store_cnt_r1"], rest_food["alive_r1"]),
                "same_uptae_here": same_uptae["here"],
                "same_uptae_neighbor": same_uptae["r1"],
                # Lane A has not landed the trailing-36-month feature yet.
                "openings_36m": None,
                "openings_total": _plus(row["hist_open_cnt"], rest_food["opened"]),
                "closures_total": _plus(row["hist_close_cnt"], rest_food["closed"]),
            },
            "area_survival": {
                # grid_feature stores this legacy field as 0..100 percent;
                # the HTTP contract consistently uses 0..1 rates.
                "rate": (
                    row["survive_3y_local"] / 100
                    if row["survive_3y_local"] is not None
                    else None
                ),
                "sample": row["survive_3y_n"],
            },
            "demand": {
                "day_population": row["lvpop_day"],
                "night_population": row["lvpop_night"],
                "businesses": row["corp_cnt"],
                "workers": row["tot_worker"],
                "worker_per_resident": row["worker_per_resident"],
                "population_density": row["ppltn_dnsty"],
            },
            "sales": {
                "quarterly_amount": row["sales_amt"],
                "quarterly_count": row["sales_cnt"],
                "foot_traffic": row["flpop"],
                "available": row["sales_amt"] is not None,
                # 아래 둘은 «선택한 업태» 기준이다. available 은 격자에 매출
                # 값이 있느냐(상권 안이냐)이고, 이것은 그 안에서 «그 업종의»
                # 매출이 공표됐느냐다 — 상권 안에서도 31.1% 가 미공표다.
                "uptae_stores": uptae_sales["stores"],
                "uptae_published": uptae_sales["published"],
            },
            # The verified/overheated thresholds are not in score_meta yet.
            "signal": None,
            "missing_axes": _missing_axes(row),
            "resolutions": RESOLUTION,
        }
    )
    return item


def _missing_axes(row):
    missing = []
    if row["sales_amt"] is None:
        missing.append("sales")
    if row["flpop"] is None:
        missing.append("footTraffic")
    if row["sgis_adm_nm"] is None:
        missing.append("administrativeArea")
    if row["survive_3y_local"] is None:
        missing.append("areaSurvival")
    if row["station_name"] is None:
        missing.append("stationAccess")
    return missing
