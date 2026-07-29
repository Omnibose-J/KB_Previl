"""Read-only query layer for the UI.

All scoring happens in ``service.precompute``. This module only reads indexed
SQLite tables and never exposes the model score: users see the survival rate
observed for each grade on held-out data.
"""

import json
import sqlite3
from contextlib import contextmanager

from pyproj import Transformer

from pipeline.config import CRS_GRID, CRS_WGS84, DB_PATH, GRID_SIZE_M
from pipeline.grid import in_seoul, neighbors, to_grid_id
from service import alerts


class ApiInputError(ValueError):
    """The caller supplied a value outside the public API contract."""


class ResourceNotFoundError(LookupError):
    """A syntactically valid public resource does not exist."""


class DatabaseUnavailableError(RuntimeError):
    """The read-only SQLite dependency could not serve a query."""


class ViewportTooLargeError(ApiInputError):
    """The requested viewport contains more cells than the API cap."""

    def __init__(self, max_cells):
        super().__init__(
            f"격자 수가 상한 {max_cells}개를 넘습니다. 지도를 확대해 주세요."
        )
        self.max_cells = max_cells


MAX_GRID_CELLS = 2_000

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
    "nearestStation": "지점 실측",
}

# 까페만 다른 표에서 센다.
#
# `licence` 는 «일반음식점»만 담는다. 카페는 대부분 «휴게음식점»으로 인허가돼
# 통째로 안 보인다 — 실측으로 licence 까페는 영업 중 1,239곳인데 휴게음식점
# 표(`licence_rest`)의 커피숍 계열은 14,366곳이다. 카페 창업자가 보던 경쟁
# 수가 실제의 9% 였다는 뜻이다.
#
# 다른 열한 업태는 손대지 않는다. 특히 통닭(치킨)은 «누락»이 아니라 분류 경계
# 차이다 — 인허가는 통닭(치킨) 1,630 과 호프/통닭 8,805 로 갈라 놓고 합이
# 10,435 인데, 상가업소는 치킨 5,206 + 생맥주 2,643 = 7,849 로 오히려 적다.
# 상호에 «치킨»이 든 영업 점포도 대부분(1,435)이 호프/통닭에 있다. 여기에
# 다른 원천을 붙이면 지금 맞는 값에 없던 오차가 들어간다.
#
# 휴게음식점을 쓰는 이유가 «더 많아서»만은 아니다. 같은 인허가 계열이라
# 개·폐업 시점과 좌표계 처리가 `licence` 와 동일하고(model/tier2.py),
# 그래서 화면의 다른 숫자들과 뜻이 어긋나지 않는다. 상가업소(SEMAS)는 21,619
# 곳으로 더 크지만 개·폐업 이력이 없어 «영업 중»의 정의부터 다르다.
REST_UPTAE = {
    "까페": ("커피숍", "다방", "전통찻집", "떡카페", "키즈카페"),
}

# «영업 중인 음식점»에 함께 세는 휴게음식점. 서울 영업 중 음식업 131,153곳 중
# 22,108곳(16.9%)이 여기 있는데 화면은 일반음식점 109,045곳만 세고 있었다.
#
# 휴게음식점 전부는 아니다. 편의점 5,917 · 백화점 527 · 철도역구내 105 처럼
# 인허가는 휴게음식점이지만 «경쟁 음식점»이 아닌 것들은 뺀다.
# «기타 휴게음식점» 7,353 도 뺐다 — 상호를 보면 GS25·씨유 같은 편의점과
# 카페·도넛이 섞여 있어 어느 쪽으로도 셀 수 없다. 모르는 것을 넣어 숫자를
# 키우지 않는다.
REST_EATERY = (
    "커피숍", "일반조리판매", "다방", "패스트푸드", "과자점",
    "푸드트럭", "아이스크림", "전통찻집", "떡카페", "키즈카페",
)

NOT_EVALUATED_DETAIL = "이웃 이력 부족으로 평가하지 않음"
SURVIVAL_PERIODS = (1, 3, 5)
GRADE_AREA_KEYS = (
    "gradeband_labels",
    "area_bands",
    "observed_by_grade_area",
    "grade_area_bench",
)

_from_grid = Transformer.from_crs(CRS_GRID, CRS_WGS84, always_xy=True)


@contextmanager
def readonly_connection():
    """Open the shared database in SQLite's enforced read-only mode."""

    uri = f"{DB_PATH.resolve().as_uri()}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(
            f"읽기 전용 DB를 열 수 없습니다: {DB_PATH}"
        ) from exc
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only=ON")
        yield con
    except sqlite3.Error as exc:
        raise DatabaseUnavailableError(
            f"읽기 전용 DB 조회에 실패했습니다: {DB_PATH}"
        ) from exc
    finally:
        con.close()


def _csv_floats(value):
    if not value:
        return []
    return [float(item) for item in value.split(",") if item]


def _csv_ints(value):
    if not value:
        return []
    return [int(item) for item in value.split(",") if item]


def _at(values, index):
    return values[index] if index < len(values) else None


def _district_names(area_names):
    return sorted(
        {
            parts[1]
            for name in area_names
            if len(parts := name.split()) >= 2 and parts[1].endswith("구")
        }
    )


def _caveats(observed):
    # AUC caveat removed by owner call 2026-07-27; the closure-rate line stays.
    grade_one_closure = round((1 - observed[0]) * 100)
    return [
        (f"1등급 자리의 실측 3년 내 폐업률은 약 {grade_one_closure}%입니다."),
    ]


def _meta_error(key, reason):
    raise DatabaseUnavailableError(f"score_meta.{key} 형식이 잘못됐습니다: {reason}")


def _optional_float(value, key):
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        _meta_error(key, "실수가 아닙니다.")


def _optional_int(value, key):
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        _meta_error(key, "정수가 아닙니다.")


def _stat_cell(value, key):
    if value == "":
        return None
    parts = value.split(":")
    if len(parts) != 4:
        _meta_error(key, "생존율:CI하한:CI상한:표본수 4개 값이 필요합니다.")
    survival, ci_low, ci_high, sample_size = parts
    return {
        "survival": _optional_float(survival or None, key),
        "ci_low": _optional_float(ci_low or None, key),
        "ci_high": _optional_float(ci_high or None, key),
        "n": _optional_int(sample_size, key),
    }


def _cohort(test_window, years):
    if test_window is None:
        return None
    bounds = test_window.split("-")
    if len(bounds) != 2 or not all(bound.isdigit() for bound in bounds):
        _meta_error(f"test_window_{years}y", "연도-연도 형식이 아닙니다.")
    cohort = bounds[0] if bounds[0] == bounds[1] else test_window
    return f"{cohort} (코로나기)" if years == 5 else cohort


def _survival_by_period(raw_meta):
    labels_value = raw_meta.get("gradeband_labels")
    labels = labels_value.split(",") if labels_value is not None else None
    periods = []
    for years in SURVIVAL_PERIODS:
        stats_key = f"observed_by_gradeband_{years}y"
        stats_value = raw_meta.get(stats_key)
        bands = None
        if stats_value is not None and labels is not None:
            cells = [_stat_cell(value, stats_key) for value in stats_value.split(",")]
            if len(cells) != len(labels):
                _meta_error(stats_key, "gradeband_labels와 개수가 다릅니다.")
            bands = [
                {
                    "band": label,
                    "survival": cell["survival"] if cell else None,
                    "ci_low": cell["ci_low"] if cell else None,
                    "ci_high": cell["ci_high"] if cell else None,
                    "n": cell["n"] if cell else None,
                }
                for label, cell in zip(labels, cells)
            ]

        test_window = raw_meta.get(f"test_window_{years}y")
        periods.append(
            {
                "years": years,
                "cohort": _cohort(test_window, years),
                "test_window": test_window,
                "overall": _optional_float(
                    raw_meta.get(f"overall_survival_{years}y"),
                    f"overall_survival_{years}y",
                ),
                "bench": raw_meta.get(f"bench_{years}y"),
                "bands": bands,
            }
        )
    return periods


def _grade_area(raw_meta):
    if any(key not in raw_meta for key in GRADE_AREA_KEYS):
        return None

    grade_bands = raw_meta["gradeband_labels"].split(",")
    area_bands = raw_meta["area_bands"].split(",")
    rows = raw_meta["observed_by_grade_area"].split(";")
    if len(rows) != len(grade_bands):
        _meta_error(
            "observed_by_grade_area",
            "gradeband_labels와 행 개수가 다릅니다.",
        )

    survival = []
    for row in rows:
        cells = row.split("|")
        if len(cells) != len(area_bands):
            _meta_error(
                "observed_by_grade_area",
                "area_bands와 열 개수가 다릅니다.",
            )
        parsed_row = []
        for cell in cells:
            parsed = _stat_cell(cell, "observed_by_grade_area")
            parsed_row.append(parsed["survival"] if parsed else None)
        survival.append(parsed_row)

    return {
        "grade_bands": grade_bands,
        "area_bands": area_bands,
        "survival": survival,
        "bench": raw_meta["grade_area_bench"],
    }


def meta():
    with readonly_connection() as con:
        raw_meta = {
            row["k"]: row["v"] for row in con.execute("SELECT k, v FROM score_meta")
        }
        uptae = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT uptae FROM grid_score ORDER BY uptae"
            )
        ]
        area_names = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT sgis_adm_nm FROM grid_sgis "
                "WHERE sgis_adm_nm IS NOT NULL"
            )
        ]
        grid_count = con.execute(
            "SELECT COUNT(DISTINCT grid_id) FROM grid_score"
        ).fetchone()[0]

    districts = _district_names(area_names)
    if grid_count == 0:
        raise DatabaseUnavailableError("배치 미실행: grid_score가 비어 있습니다.")
    if "observed_by_grade" not in raw_meta:
        raise DatabaseUnavailableError(
            "score_meta.observed_by_grade가 없어 등급 실측치를 제공할 수 없습니다."
        )
    observed = _csv_floats(raw_meta.get("observed_by_grade"))
    if len(observed) != 10:
        _meta_error("observed_by_grade", "1~10등급 값 10개가 필요합니다.")
    sample_sizes = _csv_ints(raw_meta.get("observed_by_grade_n"))
    ci_low = _csv_floats(raw_meta.get("observed_by_grade_ci_low"))
    ci_high = _csv_floats(raw_meta.get("observed_by_grade_ci_high"))
    overall = raw_meta.get("overall_survival")

    return {
        "as_of": raw_meta.get("as_of"),
        "uptae": uptae,
        "districts": districts,
        "observed_by_grade": [
            {
                "grade": index + 1,
                "survival": value,
                "n": _at(sample_sizes, index),
                "ci_low": _at(ci_low, index),
                "ci_high": _at(ci_high, index),
            }
            for index, value in enumerate(observed)
        ],
        "overall_survival": float(overall) if overall is not None else None,
        "survival_by_period": _survival_by_period(raw_meta),
        "grade_area": _grade_area(raw_meta),
        "grid_count": grid_count,
        "grade_direction": "1_is_best",
        "caveats": _caveats(observed),
        "model_note": "순위는 입지 피처만 사용하며 점포 면적과 층은 제외합니다.",
        "resolutions": RESOLUTION,
    }


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


def _location_names(name):
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


def _plus(value, extra):
    """NULL 은 NULL 로 둔다 — 모르는 값에 아는 값을 더하면 «안다»가 된다."""
    return None if value is None else value + extra


def _grid_detail(row, uptae, same_uptae, rest_food):
    district, adm_dong = _location_names(row["sgis_adm_nm"])
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


def _ensure_uptae(con, uptae):
    if not con.execute("SELECT 1 FROM grid_score LIMIT 1").fetchone():
        raise DatabaseUnavailableError("배치 미실행: grid_score가 비어 있습니다.")
    found = con.execute(
        "SELECT 1 FROM grid_score WHERE uptae = ? LIMIT 1", (uptae,)
    ).fetchone()
    if not found:
        raise ApiInputError("지원하지 않는 업태입니다.")


def _ensure_districts(con, districts):
    if not districts:
        return
    known = _district_names(
        row[0]
        for row in con.execute(
            "SELECT DISTINCT sgis_adm_nm FROM grid_sgis WHERE sgis_adm_nm IS NOT NULL"
        )
    )
    unknown = sorted(set(districts) - set(known))
    if unknown:
        raise ApiInputError("지원하지 않는 자치구입니다: " + ", ".join(unknown))


def _district_filter(districts):
    cleaned = list(dict.fromkeys(value.strip() for value in districts if value.strip()))
    if not cleaned:
        return "", [], cleaned
    clause = " AND (" + " OR ".join("gs.sgis_adm_nm LIKE ?" for _ in cleaned) + ")"
    return clause, [f"% {district} %" for district in cleaned], cleaned


def recommend(uptae, districts=(), top=24):
    district_sql, district_args, cleaned = _district_filter(districts)
    with readonly_connection() as con:
        _ensure_uptae(con, uptae)
        _ensure_districts(con, cleaned)
        total_grids = con.execute(
            "SELECT COUNT(*) FROM grid_score WHERE uptae = ?", (uptae,)
        ).fetchone()[0]
        in_scope = con.execute(
            "SELECT COUNT(*) FROM grid_score s "
            "LEFT JOIN grid_sgis gs ON gs.grid_id = s.grid_id "
            "WHERE s.uptae = ?" + district_sql,
            [uptae, *district_args],
        ).fetchone()[0]
        rows = con.execute(
            GRID_SELECT
            + " WHERE 1 = 1"
            + district_sql
            + " ORDER BY s.score DESC LIMIT ?",
            [uptae, *district_args, top],
        ).fetchall()
        grid_ids = [row["grid_id"] for row in rows]
        mix = _concept_mix_batch(con, grid_ids)
        same = _same_uptae_batch(con, grid_ids, uptae)
        rest = _rest_food_batch(con, grid_ids)

    items = []
    for row in rows:
        item = _grid_detail(row, uptae, same[row["grid_id"]], rest[row["grid_id"]])
        item["concept_mix"] = mix.get(row["grid_id"])
        items.append(item)

    return {
        "uptae": uptae,
        "districts": cleaned,
        "total_grids": total_grids,
        "in_scope": in_scope,
        "count": len(rows),
        "items": items,
        "resolutions": RESOLUTION,
    }


def grid_detail(grid_id, uptae):
    with readonly_connection() as con:
        _ensure_uptae(con, uptae)
        row = con.execute(
            GRID_SELECT + " WHERE f.grid_id = ?", (uptae, grid_id)
        ).fetchone()
        if row is None:
            return None
        mix = _concept_mix_batch(con, [grid_id])
        same = _same_uptae_batch(con, [grid_id], uptae)
        rest = _rest_food_batch(con, [grid_id])
    item = _grid_detail(row, uptae, same[grid_id], rest[grid_id])
    item["concept_mix"] = mix.get(grid_id)
    return item


def _same_uptae_batch(con, grid_ids, uptae):
    """업태별 «영업 중» 점포 수 — 이 칸과 3x3 링.

    화면이 «같은 업종 가게 수»라 부르던 값은 `food_store_cnt`, 즉 업태를 가리지
    않은 음식점 전체였다. 한식을 고르든 중국식을 고르든 같은 숫자가 나왔다.
    업태별 수는 `grid_feature.competitor_same_uptae`(json: 업태 -> 수)에 이미
    있고, 그 합이 `food_store_cnt` 와 전 격자에서 일치한다 — 즉 그 칸의 전수
    집계다. 그래서 키가 없으면 «모름»이 아니라 진짜 0이다.

    링 합은 `food_store_cnt_r1` 과 같은 정의를 쓴다(중심 포함 3x3). 이웃 중
    grid_feature 에 없는 칸은 데이터가 닿지 않은 칸이라 합에서 빠진다.

    까페만 `licence_rest`(휴게음식점)에서 센다 — REST_UPTAE 주석 참조.
    두 경로 모두 «그 업태로 인허가된 영업 중 점포»를 세므로 화면에서는 한
    가지 뜻의 한 숫자다. 원천이 갈린다는 것을 사용자가 알 필요는 없다.

    S3 는 후보를 한 번에 그리므로 격자마다 조회하면 N+1 이 된다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    wanted = list({cell for gid in ids for cell in neighbors(gid, 1)})
    counts = {}
    rest = REST_UPTAE.get(uptae)
    # SQLite 의 바인드 변수 상한(기본 999)에 걸리지 않게 끊어 묻는다.
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        cells = ",".join("?" * len(chunk))
        if rest is None:
            for row in con.execute(
                f"SELECT grid_id, competitor_same_uptae FROM grid_feature "
                f"WHERE grid_id IN ({cells})",
                chunk,
            ):
                counts[row["grid_id"]] = json.loads(
                    row["competitor_same_uptae"] or "{}"
                ).get(uptae, 0)
        else:
            kinds = ",".join("?" * len(rest))
            # 조회에 안 잡힌 칸은 «모름»이 아니라 0 이다 — licence_rest 는 서울
            # 휴게음식점 전수라 그 칸에 커피숍이 없다는 뜻이다. 아래에서 0 으로
            # 채우되, grid_feature 에 아예 없는 칸과는 구분해 둔다.
            present = set()
            for row in con.execute(
                f"SELECT grid_id FROM grid_feature WHERE grid_id IN ({cells})", chunk
            ):
                present.add(row["grid_id"])
            for gid in present:
                counts[gid] = 0
            for row in con.execute(
                f"SELECT grid_id, COUNT(*) n FROM licence_rest "
                f"WHERE grid_id IN ({cells}) AND uptae IN ({kinds}) AND is_closed = 0 "
                "GROUP BY grid_id",
                [*chunk, *rest],
            ):
                if row["grid_id"] in present:
                    counts[row["grid_id"]] = row["n"]

    return {
        gid: {
            "here": counts.get(gid),
            "r1": sum(counts[cell] for cell in neighbors(gid, 1) if cell in counts),
        }
        for gid in ids
    }


def _rest_food_batch(con, grid_ids):
    """휴게음식점 중 «음식점»에 해당하는 것의 칸별 집계 — 영업 중 / 개업 누계 /
    폐업 누계, 그리고 3x3 링의 영업 중.

    `grid_feature.food_store_cnt` 계열은 일반음식점만 센다. 그 컬럼은 그대로
    둔다 — `pipeline.consistency` 의 cellsum 이 원천 licence 와 대조하는
    값이라 여기서 바꾸면 교차검증이 무의미해진다. 대신 API 가 응답을 만들 때
    더한다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    wanted = list({cell for gid in ids for cell in neighbors(gid, 1)})
    stats = {}
    kinds = ",".join("?" * len(REST_EATERY))
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        cells = ",".join("?" * len(chunk))
        for row in con.execute(
            f"SELECT grid_id, "
            f"       SUM(1 - is_closed) alive, "
            f"       COUNT(*) opened, "
            f"       SUM(is_closed) closed "
            f"FROM licence_rest "
            f"WHERE grid_id IN ({cells}) AND uptae IN ({kinds}) "
            "GROUP BY grid_id",
            [*chunk, *REST_EATERY],
        ):
            stats[row["grid_id"]] = (
                row["alive"] or 0,
                row["opened"] or 0,
                row["closed"] or 0,
            )

    def at(gid, index):
        return stats[gid][index] if gid in stats else 0

    return {
        gid: {
            "alive": at(gid, 0),
            "opened": at(gid, 1),
            "closed": at(gid, 2),
            "alive_r1": sum(at(cell, 0) for cell in neighbors(gid, 1)),
        }
        for gid in ids
    }


def grid_changes(grid_id, uptae):
    """이 칸이 직전 채점 판과 견주어 무엇이 달라졌는가.

    견줄 판이 없으면 «변동 없음»이 아니라 available=False 다. 둘을 같은 모양으로
    답하면 사용자는 알림이 도는 줄 알고 기다린다.
    """
    with readonly_connection() as con:
        _ensure_uptae(con, uptae)
        try:
            return {"available": True, **alerts.changes_for(con, grid_id, uptae)}
        except alerts.NoBaselineError as exc:
            return {"available": False, "reason": str(exc)}


def _concept_mix_batch(con, grid_ids):
    """격자별 주변 3x3 링의 상호명 콘셉트 구성. 추론이 아니라 집계다
    (`model/concept_mix.py`).

    S3 는 후보 20여 개를 한 번에 그리므로 격자마다 조회하면 N+1 이 된다.
    한 번의 IN 조회로 모아서 돌려준다.

    배치가 아직 안 돌았으면 `available=False` 로 알린다. 빈 구성과 미실행은
    다른 상태이므로 빈 배열로 뭉개지 않는다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    # 테이블 유무를 직접 묻는다. 조회를 try 로 감싸면 SQL 오류·DB 손상까지
    # "배치 미실행" 으로 위장되고, readonly_connection 이 503 으로 올릴 실패가
    # 200 으로 내려간다.
    if not con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'grid_concept'"
    ).fetchone():
        return {
            gid: {"available": False, "items": [], "shops": 0,
                  "source": None, "claim": None}
            for gid in ids
        }

    placeholders = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT grid_id, concept, n FROM grid_concept "
        f"WHERE grid_id IN ({placeholders}) "
        "ORDER BY grid_id, n DESC, concept",
        ids,
    ).fetchall()

    meta = dict(
        con.execute(
            "SELECT k, v FROM score_meta WHERE k LIKE 'concept_mix\\_%' ESCAPE '\\'"
        ).fetchall()
    )
    by_grid = {}
    for row in rows:
        by_grid.setdefault(row["grid_id"], []).append(
            {"concept": row["concept"], "shops": row["n"]}
        )
    return {
        gid: {
            "available": True,
            "items": by_grid.get(gid, []),
            "shops": sum(item["shops"] for item in by_grid.get(gid, [])),
            "source": meta.get("concept_mix_source"),
            "claim": meta.get("concept_mix_claim"),
        }
        for gid in ids
    }


def at_point(lon, lat, uptae):
    if not in_seoul(lon, lat):
        raise ApiInputError("서울 범위의 WGS84 좌표를 입력해 주세요.")
    return grid_detail(to_grid_id(lon, lat), uptae)


def grids(uptae, bbox, max_cells=MAX_GRID_CELLS):
    lon_min, lat_min, lon_max, lat_max = bbox
    if lon_min >= lon_max or lat_min >= lat_max:
        raise ApiInputError("bbox는 lon_min,lat_min,lon_max,lat_max 순서여야 합니다.")
    if not in_seoul(lon_min, lat_min) or not in_seoul(lon_max, lat_max):
        raise ApiInputError("bbox는 서울 범위의 WGS84 좌표여야 합니다.")

    with readonly_connection() as con:
        _ensure_uptae(con, uptae)
        rows = con.execute(
            GRID_SELECT
            + " WHERE f.center_lon BETWEEN ? AND ?"
            + " AND f.center_lat BETWEEN ? AND ?"
            + " ORDER BY f.grid_id LIMIT ?",
            (uptae, lon_min, lon_max, lat_min, lat_max, max_cells + 1),
        ).fetchall()

    if len(rows) > max_cells:
        raise ViewportTooLargeError(max_cells)
    return {
        "count": len(rows),
        "max_cells": max_cells,
        "items": [_grid_cell(row, uptae) for row in rows],
        "resolutions": {
            "grade": "격자 100m",
            "observedSurvival": "등급별 홀드아웃 실측",
            "salesAvailable": "상권 포함 여부",
        },
    }


if __name__ == "__main__":
    print(json.dumps(meta(), ensure_ascii=False, indent=2)[:1_400])
