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
    "competition.currentStoresHere": "격자 100m",
    "competition.currentStoresNeighbor": "격자 3x3 (300m)",
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

# 우리 업태 -> SEMAS(소상공인시장진흥공단 상가업소) 분류.
#
# 인허가 테이블은 «일반음식점»만 담는다. 카페와 테이크아웃 치킨은 대부분
# «휴게음식점»으로 등록되므로 통째로 안 보인다 — 실측으로 까페 1,239 vs
# SEMAS 21,619(17.4배), 통닭(치킨) 1,630 vs 5,206(3.2배). 카페 창업자가 보는
# 경쟁 수가 실제의 5.7%였다.
#
# 나머지 열 업태는 «누락»이 아니다. 분식 1.0배·일식 1.0배·중국식 1.1배로
# 이미 맞고, 호프/통닭 0.3배·정종/대포집 7.3배·식육 5.5배는 SEMAS 가 [주점]과
# [한식] 중분류를 우리와 다르게 자른 «경계 차이»다. 억지로 붙이면 지금 맞는
# 값에 없던 오차가 들어간다. 그래서 여기 없는 업태는 NULL 로 남는다 —
# 매핑을 «채우지» 말 것.
SEMAS_UPTAE = {
    "까페": ("inds_scls_nm", ("카페",)),
    "통닭(치킨)": ("inds_scls_nm", ("치킨",)),
}
SEMAS_SOURCE = "소상공인시장진흥공단 상가업소"

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


def _grid_detail(row, uptae, same_uptae, semas):
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
            "competition": {
                "shops_here": row["food_store_cnt"],
                "shops_neighbor": row["food_store_cnt_r1"],
                "same_uptae_here": same_uptae["here"],
                "same_uptae_neighbor": same_uptae["r1"],
                "current_stores_here": semas["here"],
                "current_stores_neighbor": semas["r1"],
                "current_stores_source": (
                    SEMAS_SOURCE if semas["here"] is not None else None
                ),
                # Lane A has not landed the trailing-36-month feature yet.
                "openings_36m": None,
                "openings_total": row["hist_open_cnt"],
                "closures_total": row["hist_close_cnt"],
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
        semas = _semas_batch(con, grid_ids, uptae)

    items = []
    for row in rows:
        item = _grid_detail(row, uptae, same[row["grid_id"]], semas[row["grid_id"]])
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
        semas = _semas_batch(con, [grid_id], uptae)
    item = _grid_detail(row, uptae, same[grid_id], semas[grid_id])
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

    S3 는 후보를 한 번에 그리므로 격자마다 조회하면 N+1 이 된다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}

    wanted = list({cell for gid in ids for cell in neighbors(gid, 1)})
    counts = {}
    # SQLite 의 바인드 변수 상한(기본 999)에 걸리지 않게 끊어 묻는다.
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        placeholders = ",".join("?" * len(chunk))
        for row in con.execute(
            f"SELECT grid_id, competitor_same_uptae FROM grid_feature "
            f"WHERE grid_id IN ({placeholders})",
            chunk,
        ):
            counts[row["grid_id"]] = json.loads(
                row["competitor_same_uptae"] or "{}"
            ).get(uptae, 0)

    return {
        gid: {
            "here": counts.get(gid),
            "r1": sum(counts[cell] for cell in neighbors(gid, 1) if cell in counts),
        }
        for gid in ids
    }


def _semas_batch(con, grid_ids, uptae):
    """SEMAS 상가업소 기준 «현재 영업 중» 점포 수 — 이 칸과 3x3 링.

    매핑이 없는 업태는 전부 None 이다(SEMAS_UPTAE 주석 참조). 0 이 아니라
    None 인 이유: 그 업태의 SEMAS 대응을 «모른다»는 뜻이지 그 칸에 점포가
    없다는 뜻이 아니다.

    이 값은 표시 전용이다. SEMAS 는 개·폐업 이력이 없는 현재 스냅샷이라
    개업 시점의 상태를 복원할 수 없고, 그대로 모델에 넣으면 결과를 이미 아는
    시점의 정보가 된다(model/asof.py LEAKY 가 food_store_cnt 를 막는 것과
    같은 이유). 등급은 이 값을 보지 않는다.
    """
    ids = list(dict.fromkeys(grid_ids))
    if not ids:
        return {}
    mapping = SEMAS_UPTAE.get(uptae)
    if mapping is None:
        return {gid: {"here": None, "r1": None} for gid in ids}

    column, names = mapping
    wanted = list({cell for gid in ids for cell in neighbors(gid, 1)})
    counts = {}
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        cells = ",".join("?" * len(chunk))
        kinds = ",".join("?" * len(names))
        for row in con.execute(
            f"SELECT grid_id, COUNT(*) n FROM store "
            f"WHERE grid_id IN ({cells}) AND {column} IN ({kinds}) "
            "GROUP BY grid_id",
            [*chunk, *names],
        ):
            counts[row["grid_id"]] = row["n"]

    # 격자에 한 곳도 없으면 조회 결과에 안 나온다. SEMAS 는 서울 음식업 전수
    # 스냅샷이므로 그 없음은 «모름»이 아니라 0 이다.
    return {
        gid: {
            "here": counts.get(gid, 0),
            "r1": sum(counts.get(cell, 0) for cell in neighbors(gid, 1)),
        }
        for gid in ids
    }


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
