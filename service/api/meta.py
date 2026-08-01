from pipeline.grade_bands import GRADE_COUNT

from . import base
from .base import DatabaseUnavailableError, _at, _csv_floats, _csv_ints, _meta_error, _optional_float, _optional_int
from .cells import RESOLUTION, location_names


SURVIVAL_PERIODS = (1, 2, 3, 5)
GRADE_AREA_KEYS = (
    "gradeband_labels",
    "area_bands",
    "observed_by_grade_area",
    "grade_area_bench",
)


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
    with base.readonly_connection() as con:
        raw_meta = {
            row["k"]: row["v"] for row in con.execute("SELECT k, v FROM score_meta")
        }
        # 가나다순이되 «기타»만 끝으로 — 목록 둘째 칸에 있으면 고를 것으로 읽힌다.
        # 규모순으로 두지 않는 이유는 licence 가 일반음식점만 담아서다: 까페는
        # 대부분 휴게음식점으로 인허가돼 여기서 세면 1,128곳으로 꼴찌가 되는데,
        # 그 순서는 사실과 다르게 읽힌다.
        uptae = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT uptae FROM grid_score "
                "ORDER BY uptae = '기타', uptae"
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
        # 배치 판정이 먼저다. 아래 조회는 배치가 돈 DB 에만 있는 테이블을 읽으므로,
        # 순서를 바꾸면 «배치 미실행» 이라는 정확한 진단이 «조회 실패» 로 뭉개진다.
        if grid_count == 0:
            raise DatabaseUnavailableError("배치 미실행: grid_score가 비어 있습니다.")

        # 서울 전체 개업연도별 3년 생존율. `observable_3y = opened` 로 완결
        # 코호트만 남긴다 — 2023년은 8,762/14,992 만 3년이 지나 부분 관측이고,
        # 그걸 섞으면 마지막 점이 계절 편중된 표본이 된다. succession_excluded=0
        # 은 배포 라벨과 같은 계보다(양도양수 미제외, docs §8-B).
        survival_trend = [
            {"year": row["open_year"], "survival": row["survive_3y"] / 100,
             "opened": row["opened"]}
            for row in con.execute(
                "SELECT open_year, survive_3y, opened FROM cohort_survival "
                "WHERE scope = 'seoul' AND succession_excluded = 0 "
                "  AND survive_3y IS NOT NULL AND observable_3y = opened "
                "ORDER BY open_year"
            )
        ]

    districts = _district_names(area_names)
    if "observed_by_grade" not in raw_meta:
        raise DatabaseUnavailableError(
            "score_meta.observed_by_grade가 없어 등급 실측치를 제공할 수 없습니다."
        )
    observed = _csv_floats(raw_meta.get("observed_by_grade"))
    if len(observed) != GRADE_COUNT:
        _meta_error(
            "observed_by_grade",
            f"1~{GRADE_COUNT}등급 값 {GRADE_COUNT}개가 필요합니다.",
        )
    sample_sizes = _csv_ints(raw_meta.get("observed_by_grade_n"))
    ci_low = _csv_floats(raw_meta.get("observed_by_grade_ci_low"))
    ci_high = _csv_floats(raw_meta.get("observed_by_grade_ci_high"))
    overall = raw_meta.get("overall_survival")

    return {
        "as_of": raw_meta.get("as_of"),
        "uptae": uptae,
        "seoul_survival_trend": survival_trend,
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


def areas():
    """지도 이동용 행정동 목록.

    좌표는 그 동 안 «채점된» 격자 중심의 평균이다 — 값이 아니라 도착 지점이라
    평균으로 충분하고, 채점 안 된 동은 아예 빼야 빈 지도로 날아가지 않는다.
    """
    with base.readonly_connection() as con:
        rows = con.execute(
            "SELECT gs.sgis_adm_nm AS nm, COUNT(*) AS n, "
            "       AVG(g.center_lon) AS lon, AVG(g.center_lat) AS lat "
            "FROM (SELECT DISTINCT grid_id FROM grid_score) s "
            "JOIN grid_sgis gs ON gs.grid_id = s.grid_id "
            "JOIN grid g ON g.grid_id = s.grid_id "
            "GROUP BY gs.sgis_adm_nm"
        ).fetchall()
    if not rows:
        raise DatabaseUnavailableError("배치 미실행: grid_score가 비어 있습니다.")

    items = []
    for row in rows:
        district, adm_dong = location_names(row["nm"])
        if district is None or adm_dong is None:
            continue
        items.append(
            {
                "district": district,
                "adm_dong": adm_dong,
                "center": [round(row["lon"], 6), round(row["lat"], 6)],
                "grid_count": row["n"],
            }
        )
    items.sort(key=lambda item: (item["district"], item["adm_dong"]))
    return {"items": items}
