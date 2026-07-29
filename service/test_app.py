"""HTTP contract tests for lane B."""

from contextlib import contextmanager
import json
import sqlite3
import shutil
import statistics

import numpy as np
import pytest
from fastapi.testclient import TestClient

from service import api
from service import economics as economics_service
from service import estimation as estimation_service
from service import goodwill as goodwill_service
from service import precompute
from service import reporting
from service.app import app


client = TestClient(app)


def _hide_meta_keys(monkeypatch, *hidden_keys):
    original_connection = api.readonly_connection

    class FilteredConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, parameters=()):
            rows = self.connection.execute(statement, parameters)
            if statement == "SELECT k, v FROM score_meta":
                return [row for row in rows if row["k"] not in hidden_keys]
            return rows

    @contextmanager
    def filtered_connection():
        with original_connection() as connection:
            yield FilteredConnection(connection)

    monkeypatch.setattr(api, "readonly_connection", filtered_connection)


def _assert_score_hidden(value):
    if isinstance(value, dict):
        assert "score" not in value
        for child in value.values():
            _assert_score_hidden(child)
    elif isinstance(value, list):
        for child in value:
            _assert_score_hidden(child)


def _sample_grid(sales_available=None):
    where = ""
    if sales_available is True:
        where = " AND f.has_sales_data = 1"
    elif sales_available is False:
        where = " AND f.has_sales_data = 0"
    with api.readonly_connection() as con:
        row = con.execute(
            "SELECT f.grid_id, f.center_lon, f.center_lat, s.uptae "
            "FROM grid_feature f "
            "JOIN grid_score s ON s.grid_id = f.grid_id "
            "WHERE 1 = 1" + where + " LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _sample_goodwill_grid():
    with api.readonly_connection() as con:
        row = con.execute(
            "SELECT f.grid_id, '한식' uptae "
            "FROM grid_feature f "
            "JOIN grid_score g ON g.grid_id = f.grid_id AND g.uptae = '한식' "
            "JOIN trdar_sales s ON s.trdar_cd = f.trdar_cd "
            "AND s.induty_cd = 'CS100001' "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE f.has_sales_data = 1 AND t.stor_co > 0 "
            "AND s.quarter = (SELECT MAX(quarter) FROM trdar_sales) "
            "LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _sample_grid_by_grade(grade):
    with api.readonly_connection() as con:
        row = con.execute(
            "SELECT f.grid_id, s.uptae, s.observed "
            "FROM grid_feature f "
            "JOIN grid_score s ON s.grid_id = f.grid_id "
            "WHERE s.grade = ? LIMIT 1",
            (grade,),
        ).fetchone()
    assert row is not None
    return dict(row)


def _constant_curves():
    return {grade: [1.0] * 37 for grade in range(1, 11)}


def _create_score_meta_db(path, values=()):
    with sqlite3.connect(path) as con:
        con.execute("CREATE TABLE score_meta (k TEXT PRIMARY KEY, v TEXT)")
        con.executemany("INSERT INTO score_meta VALUES (?, ?)", values)


def test_meta_contract_uses_observed_rates_and_current_caveat():
    response = client.get("/api/meta")

    assert response.status_code == 200
    payload = response.json()
    assert payload["gradeDirection"] == "1_is_best"
    assert len(payload["districts"]) == 25
    assert len(payload["observedByGrade"]) == 10
    assert all(0 <= row["survival"] <= 1 for row in payload["observedByGrade"])
    closure_percent = round((1 - payload["observedByGrade"][0]["survival"]) * 100)
    assert any(
        f"1등급 자리의 실측 3년 내 폐업률은 약 {closure_percent}%" in caveat
        for caveat in payload["caveats"]
    )
    assert all("상위 10%" not in caveat for caveat in payload["caveats"])
    _assert_score_hidden(payload)


def test_meta_exposes_goodwill_supported_uptae_from_mapping():
    response = client.get("/api/meta")

    assert response.status_code == 200
    supported = response.json()["goodwillSupportedUptae"]
    assert supported == list(goodwill_service.UPTAE_INDUTY)
    assert len(supported) == len(goodwill_service.UPTAE_INDUTY)
    assert "기타" not in supported
    assert "외국음식전문점(인도,태국등)" not in supported


def test_meta_exposes_period_and_grade_area_values_from_score_meta():
    with api.readonly_connection() as con:
        raw = {row["k"]: row["v"] for row in con.execute("SELECT k, v FROM score_meta")}

    response = client.get("/api/meta")

    assert response.status_code == 200
    payload = response.json()
    periods = payload["survivalByPeriod"]
    assert [period["years"] for period in periods] == [1, 3, 5]
    for period in periods:
        years = period["years"]
        cells = [
            cell.split(":")
            for cell in raw[f"observed_by_gradeband_{years}y"].split(",")
        ]
        assert period["testWindow"] == raw[f"test_window_{years}y"]
        assert period["overall"] == float(raw[f"overall_survival_{years}y"])
        assert period["bench"] == raw[f"bench_{years}y"]
        assert [band["band"] for band in period["bands"]] == raw[
            "gradeband_labels"
        ].split(",")
        assert [band["survival"] for band in period["bands"]] == [
            float(cell[0]) for cell in cells
        ]
        assert [band["ciLow"] for band in period["bands"]] == [
            float(cell[1]) for cell in cells
        ]
        assert [band["ciHigh"] for band in period["bands"]] == [
            float(cell[2]) for cell in cells
        ]
        assert [band["n"] for band in period["bands"]] == [
            int(cell[3]) for cell in cells
        ]

    assert periods[0]["cohort"] == "2023"
    assert periods[1]["cohort"] == "2023"
    assert periods[2]["cohort"] == "2019-2021 (코로나기)"

    grade_area = payload["gradeArea"]
    expected_matrix = [
        [None if not cell else float(cell.split(":")[0]) for cell in row.split("|")]
        for row in raw["observed_by_grade_area"].split(";")
    ]
    assert grade_area == {
        "gradeBands": raw["gradeband_labels"].split(","),
        "areaBands": raw["area_bands"].split(","),
        "survival": expected_matrix,
        "bench": raw["grade_area_bench"],
    }
    _assert_score_hidden(payload)


@pytest.mark.parametrize(
    "missing_key",
    (
        "gradeband_labels",
        "area_bands",
        "observed_by_grade_area",
        "grade_area_bench",
    ),
)
def test_meta_returns_null_for_grade_area_when_a_source_key_is_missing(
    monkeypatch,
    missing_key,
):
    _hide_meta_keys(monkeypatch, missing_key)

    response = client.get("/api/meta")

    assert response.status_code == 200
    assert response.json()["gradeArea"] is None


def test_grade_area_preserves_an_unobserved_cell_as_null():
    parsed = api._grade_area(
        {
            "gradeband_labels": "grade band",
            "area_bands": "small,large",
            "observed_by_grade_area": "0.5:0.4:0.6:100|",
            "grade_area_bench": "source bench",
        }
    )

    assert parsed["survival"] == [[0.5, None]]


def test_meta_returns_503_when_observed_by_grade_is_missing(monkeypatch):
    _hide_meta_keys(monkeypatch, "observed_by_grade")

    response = client.get("/api/meta")

    assert response.status_code == 503


@pytest.mark.parametrize(
    ("missing_key", "field"),
    (
        ("observed_by_gradeband_3y", "bands"),
        ("overall_survival_3y", "overall"),
        ("test_window_3y", "testWindow"),
        ("bench_3y", "bench"),
    ),
)
def test_meta_preserves_missing_period_fields_as_null(
    monkeypatch,
    missing_key,
    field,
):
    _hide_meta_keys(monkeypatch, missing_key)

    response = client.get("/api/meta")

    assert response.status_code == 200
    period = next(
        item for item in response.json()["survivalByPeriod"] if item["years"] == 3
    )
    assert period[field] is None
    if missing_key == "test_window_3y":
        assert period["cohort"] is None


def test_empty_grid_score_returns_batch_not_run_503(monkeypatch, tmp_path):
    empty_db = tmp_path / "empty.db"
    with sqlite3.connect(empty_db) as con:
        con.executescript(
            """
            CREATE TABLE score_meta (k TEXT PRIMARY KEY, v TEXT);
            CREATE TABLE grid_score (
              uptae TEXT, grid_id TEXT, score REAL, grade INTEGER, observed REAL
            );
            CREATE TABLE grid_sgis (grid_id TEXT, sgis_adm_nm TEXT);
            """
        )
    monkeypatch.setattr(api, "DB_PATH", empty_db)

    meta_response = client.get("/api/meta")
    recommend_response = client.get(
        "/api/recommend",
        params={"uptae": "한식", "top": 1},
    )

    assert meta_response.status_code == 503
    assert recommend_response.status_code == 503
    assert meta_response.json()["detail"].startswith("배치 미실행")
    assert recommend_response.json()["detail"].startswith("배치 미실행")


def test_recommend_grid_and_at_share_the_same_real_cell():
    metadata = client.get("/api/meta").json()
    uptae = metadata["uptae"][0]
    district = metadata["districts"][0]
    all_districts = client.get(
        "/api/recommend",
        params={"uptae": uptae, "top": 1},
    )
    assert all_districts.status_code == 200
    assert all_districts.json()["inScope"] == all_districts.json()["totalGrids"]

    recommendation = client.get(
        "/api/recommend",
        params={"uptae": uptae, "districts": district, "top": 2},
    )

    assert recommendation.status_code == 200
    body = recommendation.json()
    assert body["count"] == 2
    assert all(item["district"] == district for item in body["items"])
    item = body["items"][0]

    detail = client.get(
        f"/api/grid/{item['gridId']}",
        params={"uptae": uptae},
    )
    at_point = client.get(
        "/api/at",
        params={
            "lon": item["center"][0],
            "lat": item["center"][1],
            "uptae": uptae,
        },
    )

    assert detail.status_code == 200
    assert at_point.status_code == 200
    assert detail.json()["gridId"] == item["gridId"]
    assert at_point.json()["gridId"] == item["gridId"]
    resolutions = detail.json()["resolutions"]
    assert all(
        resolutions[f"demand.{field}"] == "행정동"
        for field in (
            "dayPopulation",
            "nightPopulation",
            "businesses",
            "workers",
            "workerPerResident",
            "populationDensity",
        )
    )
    _assert_score_hidden(body)
    _assert_score_hidden(detail.json())


def test_trade_area_coverage_and_sales_value_availability_are_distinct():
    with api.readonly_connection() as con:
        sample = con.execute(
            "SELECT f.grid_id, s.uptae FROM grid_feature f "
            "JOIN grid_score s ON s.grid_id = f.grid_id "
            "WHERE f.has_sales_data = 1 "
            "AND f.sales_amt IS NULL AND f.flpop IS NOT NULL LIMIT 1"
        ).fetchone()
    assert sample is not None

    response = client.get(
        f"/api/grid/{sample['grid_id']}",
        params={"uptae": sample["uptae"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["salesAvailable"] is True
    sales = payload["sales"]
    assert sales["quarterlyAmount"] is None
    assert sales["quarterlyCount"] is None
    assert sales["footTraffic"] is not None
    assert sales["available"] is False
    assert "sales" in payload["missingAxes"]
    assert "footTraffic" not in payload["missingAxes"]


def test_same_uptae_count_tracks_the_requested_uptae():
    """업태를 바꾸면 «같은 업종 가게 수»가 실제로 달라져야 한다.

    화면이 이 값으로 `food_store_cnt`(업태 무관 음식점 전체)를 쓰고 있었다.
    한식을 골라도 까페를 골라도 같은 숫자가 나왔고, 응답 자체는 200이라
    스키마 검사로는 잡히지 않았다. 값이 «달라진다»는 것이 이 필드의 계약이다.
    """
    with api.readonly_connection() as con:
        # 두 업태가 서로 다른 수로 들어 있는 칸을 원천에서 직접 고른다.
        rows = con.execute(
            "SELECT f.grid_id, f.competitor_same_uptae, f.food_store_cnt "
            "FROM grid_feature f WHERE f.food_store_cnt > 30"
        ).fetchall()
    sample = None
    for row in rows:
        counts = json.loads(row["competitor_same_uptae"])
        pair = sorted(counts.items(), key=lambda kv: -kv[1])[:2]
        if len(pair) == 2 and pair[0][1] != pair[1][1]:
            sample = (row["grid_id"], row["food_store_cnt"], pair)
            break
    assert sample is not None
    grid_id, total, ((first, first_n), (second, second_n)) = sample

    payloads = {}
    for uptae in (first, second):
        response = client.get(f"/api/grid/{grid_id}", params={"uptae": uptae})
        assert response.status_code == 200
        payloads[uptae] = response.json()["competition"]

    assert payloads[first]["sameUptaeHere"] == first_n
    assert payloads[second]["sameUptaeHere"] == second_n
    assert payloads[first]["sameUptaeHere"] != payloads[second]["sameUptaeHere"]

    # 업태별 수는 전체 음식점 수의 부분이고, 링은 중심을 포함하므로 그 이상이다.
    # shopsHere 는 food_store_cnt «이상»이다 — 휴게음식점 음식점류를 함께 세므로
    # 같지 않다(그 전에는 같았고, 그래서 카페 골목이 텅 빈 것처럼 보였다).
    for uptae in (first, second):
        cell = payloads[uptae]
        assert cell["shopsHere"] >= total
        assert cell["sameUptaeHere"] <= cell["shopsHere"]
        assert cell["sameUptaeNeighbor"] >= cell["sameUptaeHere"]


def test_cafe_count_comes_from_the_rest_licence_table():
    """카페는 «휴게음식점»으로 인허가돼 licence 테이블에 거의 없다.

    licence 의 까페는 영업 중 1,239곳뿐이고 licence_rest 의 커피숍 계열은
    14,366곳이다. 까페를 고르면 후자에서 세야 한다 — 전자로 세면 카페
    창업자가 보는 경쟁 수가 실제의 9% 가 된다.
    """
    with api.readonly_connection() as con:
        sample = con.execute(
            "SELECT r.grid_id, COUNT(*) n FROM licence_rest r "
            "JOIN grid_score g ON g.grid_id = r.grid_id AND g.uptae = '까페' "
            "WHERE r.is_closed = 0 AND r.uptae IN "
            "  ('커피숍', '다방', '전통찻집', '떡카페', '키즈카페') "
            "GROUP BY r.grid_id ORDER BY n DESC LIMIT 1"
        ).fetchone()
        legacy = con.execute(
            "SELECT competitor_same_uptae FROM grid_feature WHERE grid_id = ?",
            (sample["grid_id"],),
        ).fetchone()
    assert sample is not None

    response = client.get(f"/api/grid/{sample['grid_id']}", params={"uptae": "까페"})
    assert response.status_code == 200
    cell = response.json()["competition"]

    assert cell["sameUptaeHere"] == sample["n"]
    assert cell["sameUptaeNeighbor"] >= cell["sameUptaeHere"]
    # 옛 경로(일반음식점 까페)보다 반드시 크다. 같아지면 보강이 죽은 것이다.
    assert cell["sameUptaeHere"] > json.loads(legacy[0] or "{}").get("까페", 0)


def test_shop_counts_include_the_rest_licence_eateries():
    """«영업 중인 음식점»에 휴게음식점(카페·베이커리·패스트푸드)이 들어가야 한다.

    서울 영업 중 음식업 131,153곳 중 22,108곳(16.9%)이 휴게음식점이다. 빼고
    세면 카페 골목이 텅 빈 것처럼 보인다. 편의점·백화점처럼 «음식점»이 아닌
    휴게음식점은 여전히 빠진다.
    """
    with api.readonly_connection() as con:
        sample = con.execute(
            "SELECT r.grid_id, SUM(1 - r.is_closed) alive, COUNT(*) opened "
            "FROM licence_rest r "
            "JOIN grid_score g ON g.grid_id = r.grid_id AND g.uptae = '한식' "
            "WHERE r.uptae IN ('커피숍','일반조리판매','다방','패스트푸드','과자점',"
            "                  '푸드트럭','아이스크림','전통찻집','떡카페','키즈카페') "
            "GROUP BY r.grid_id ORDER BY alive DESC LIMIT 1"
        ).fetchone()
        base = con.execute(
            "SELECT food_store_cnt, hist_open_cnt FROM grid_feature WHERE grid_id = ?",
            (sample["grid_id"],),
        ).fetchone()
    assert sample is not None and sample["alive"] > 0

    response = client.get(f"/api/grid/{sample['grid_id']}", params={"uptae": "한식"})
    assert response.status_code == 200
    cell = response.json()["competition"]

    assert cell["shopsHere"] == base["food_store_cnt"] + sample["alive"]
    assert cell["openingsTotal"] == base["hist_open_cnt"] + sample["opened"]
    # 컬럼 자체는 건드리지 않는다 — consistency 의 cellsum 이 원천과 대조한다.
    assert cell["shopsHere"] > base["food_store_cnt"]


def test_convenience_stores_are_not_counted_as_restaurants():
    """편의점은 휴게음식점 인허가를 받지만 경쟁 음식점이 아니다."""
    with api.readonly_connection() as con:
        sample = con.execute(
            "SELECT r.grid_id, COUNT(*) n FROM licence_rest r "
            "JOIN grid_score g ON g.grid_id = r.grid_id AND g.uptae = '한식' "
            "WHERE r.uptae = '편의점' AND r.is_closed = 0 "
            "GROUP BY r.grid_id ORDER BY n DESC LIMIT 1"
        ).fetchone()
        base = con.execute(
            "SELECT food_store_cnt FROM grid_feature WHERE grid_id = ?",
            (sample["grid_id"],),
        ).fetchone()
        eatery = con.execute(
            "SELECT COALESCE(SUM(1 - is_closed), 0) n FROM licence_rest "
            "WHERE grid_id = ? AND uptae IN ('커피숍','일반조리판매','다방',"
            "  '패스트푸드','과자점','푸드트럭','아이스크림','전통찻집','떡카페','키즈카페')",
            (sample["grid_id"],),
        ).fetchone()
    assert sample is not None and sample["n"] > 0

    response = client.get(f"/api/grid/{sample['grid_id']}", params={"uptae": "한식"})
    cell = response.json()["competition"]
    # 편의점 n 곳이 있는 칸인데도 그만큼은 더해지지 않았다.
    assert cell["shopsHere"] == base["food_store_cnt"] + eatery["n"]


def test_other_uptae_still_count_from_the_general_licence_table():
    """까페 말고는 원천을 바꾸지 않는다.

    통닭(치킨)은 «누락»이 아니라 분류 경계 차이다 — 인허가는 통닭(치킨)과
    호프/통닭으로 갈라 놓고 합이 10,435 인데 상가업소는 7,849 로 오히려 적다.
    여기에 다른 표를 붙이면 지금 맞는 값에 없던 오차가 들어간다.
    """
    with api.readonly_connection() as con:
        row = con.execute(
            "SELECT f.grid_id, f.competitor_same_uptae FROM grid_feature f "
            "JOIN grid_score g ON g.grid_id = f.grid_id AND g.uptae = '한식' "
            "WHERE f.food_store_cnt > 20 LIMIT 1"
        ).fetchone()
    counts = json.loads(row["competitor_same_uptae"] or "{}")

    for uptae in ("한식", "통닭(치킨)", "호프/통닭", "기타"):
        response = client.get(f"/api/grid/{row['grid_id']}", params={"uptae": uptae})
        assert response.status_code == 200
        cell = response.json()["competition"]
        assert cell["sameUptaeHere"] == counts.get(uptae, 0), uptae


def test_changes_endpoint_separates_no_baseline_from_no_change():
    """견줄 판이 없는 것과 변동이 없는 것은 다른 상태다.

    둘 다 «event: null» 로 답하면 화면이 «아직 못 잽니다»와 «그대로예요»를
    구분할 수 없고, 사용자는 알림이 도는 줄 알고 기다린다.
    """
    sample = _sample_grid()
    response = client.get(
        f"/api/grid/{sample['grid_id']}/changes",
        params={"uptae": sample["uptae"]},
    )
    assert response.status_code == 200
    body = response.json()

    with api.readonly_connection() as con:
        has_baseline = con.execute(
            "SELECT 1 FROM score_run WHERE is_current = 0 LIMIT 1"
        ).fetchone()

    assert body["available"] is bool(has_baseline)
    if has_baseline:
        assert body["baselineAsOf"] and body["currentAsOf"]
        # 변동이 있으면 문장이 함께 나오고, 없으면 둘 다 비어 있다.
        assert (body["event"] is None) == (body["sentence"] is None)
    else:
        assert body["reason"]


def test_grids_returns_closed_wgs84_polygons_and_caps_large_viewports():
    sample = _sample_grid()
    lon = sample["center_lon"]
    lat = sample["center_lat"]
    bbox = f"{lon - 0.002},{lat - 0.002},{lon + 0.002},{lat + 0.002}"

    response = client.get(
        "/api/grids",
        params={"uptae": sample["uptae"], "bbox": bbox},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["items"]
    polygon = body["items"][0]["polygon"]
    assert len(polygon) == 5
    assert polygon[0] == polygon[-1]
    assert all(126.73 < point[0] < 127.27 for point in polygon)
    assert all(37.41 < point[1] < 37.72 for point in polygon)
    _assert_score_hidden(body)

    too_large = client.get(
        "/api/grids",
        params={
            "uptae": sample["uptae"],
            "bbox": "126.731,37.411,127.269,37.719",
        },
    )
    assert too_large.status_code == 413
    assert too_large.json()["maxCells"] == api.MAX_GRID_CELLS


def test_missing_grid_is_not_found_across_detail_and_post_routes():
    uptae = client.get("/api/meta").json()["uptae"][0]
    missing_grid = "0_0"
    requests = [
        client.get(
            f"/api/grid/{missing_grid}",
            params={"uptae": uptae},
        ),
        client.post(
            "/api/economics",
            json={
                "gridId": missing_grid,
                "uptae": uptae,
                "rentMonthly": 100,
                "upfront": 1_000,
                "revenueMonthly": 1_000,
            },
        ),
        client.post(
            "/api/goodwill",
            json={
                "gridId": missing_grid,
                "uptae": uptae,
                "askingGoodwill": 500,
                "leaseRemainingYears": 5,
            },
        ),
        client.post(
            "/api/report",
            json={"gridId": missing_grid, "uptae": uptae},
        ),
    ]

    assert all(response.status_code == 404 for response in requests)
    assert all(
        response.json()["detail"].startswith(api.NOT_EVALUATED_DETAIL)
        for response in requests
    )


def test_excluded_grid_returns_the_not_evaluated_404_contract():
    uptae = client.get("/api/meta").json()["uptae"][0]
    with api.readonly_connection() as con:
        excluded = con.execute(
            "SELECT f.grid_id FROM grid_feature f "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM grid_score s "
            "WHERE s.grid_id = f.grid_id AND s.uptae = ?"
            ") LIMIT 1",
            (uptae,),
        ).fetchone()
    assert excluded is not None

    response = client.get(
        f"/api/grid/{excluded['grid_id']}",
        params={"uptae": uptae},
    )

    assert response.status_code == 404
    assert response.json()["detail"].startswith("이웃 이력 부족으로 평가하지 않음")


def test_recommend_rejects_unknown_and_wildcard_districts():
    uptae = client.get("/api/meta").json()["uptae"][0]

    for district in ("없는구", "%", "_"):
        response = client.get(
            "/api/recommend",
            params={"uptae": uptae, "districts": district, "top": 1},
        )
        assert response.status_code == 422


def test_economics_calls_scenario_with_the_grade_curve(monkeypatch):
    sample = _sample_grid()
    monkeypatch.setattr(
        economics_service,
        "grade_survival_curves",
        _constant_curves,
    )

    response = client.post(
        "/api/economics",
        json={
            "gridId": sample["grid_id"],
            "uptae": sample["uptae"],
            "rentMonthly": 100,
            "upfront": 1_000,
            "revenueMonthly": 1_000,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["usedSeoulAverageRevenue"] is False
    assert body["revenueSource"] == "user_input"
    assert body["simplePaybackMonths"] == pytest.approx(1_000 / 150)
    assert body["riskAdjustedPaybackMonths"] == 7
    assert body["expectedProfit3y"] == pytest.approx(4_400)
    assert [row["grade"] for row in body["gradeComparison"]] == [1, 5, 10]


def test_economics_reads_curves_with_matching_batch_lineage(monkeypatch, tmp_path):
    curve_value = json.dumps(
        {
            "rankModel": "gbm",
            "rankFeatures": ["feature_a", "feature_b"],
            "trainYears": [2005, 2022],
            "testYears": [2023],
            "horizonMonths": 36,
            "curves": [
                {
                    "grade": grade,
                    "n": 200,
                    "survival": [1 - grade / 100] * 37,
                }
                for grade in range(1, 11)
            ],
        }
    )
    batch_db = tmp_path / "batch.db"
    _create_score_meta_db(
        batch_db,
        (
            ("rank_model", "gbm"),
            ("rank_features", "feature_a,feature_b"),
            ("rank_train_years", "2005,2022"),
            ("rank_test_years", "2023"),
            ("survival_curves_36m", curve_value),
        ),
    )
    monkeypatch.setattr(api, "DB_PATH", batch_db)

    curves = economics_service.grade_survival_curves()

    assert set(curves) == set(range(1, 11))
    assert all(len(curve) == 37 for curve in curves.values())
    assert curves[1][0] == pytest.approx(0.99)
    assert curves[10][36] == pytest.approx(0.90)


def test_current_grid_scoring_reuses_the_calibration_ranker(monkeypatch):
    probabilities = np.linspace(0.99, 0.01, 20)
    train = ([{"feature": 1}], np.array([1]), None)
    test = (
        [{"feature": index} for index in range(20)],
        np.array([index % 2 for index in range(20)]),
        [
            {"grid_id": str(index), "uptae": "한식", "open_ym": index}
            for index in range(20)
        ],
    )

    class Encoder:
        def __init__(self):
            self.calls = []

        def transform(self, features, scale):
            self.calls.append((features, scale))
            return np.array([[3.0]])

    class Ranker:
        def __init__(self):
            self.encoded = None

        def predict_proba(self, encoded):
            self.encoded = encoded
            return np.array([[0.25, 0.75]])

    encoder = Encoder()
    ranker = Ranker()
    fitted_ranker = (ranker, encoder)
    monkeypatch.setattr(precompute, "cached_split", lambda *_args: (train, test))
    monkeypatch.setattr(
        precompute,
        "fit_predict",
        lambda *_args, **_kwargs: (probabilities, fitted_ranker),
    )

    calibration = precompute.calibration(object(), ["feature"], "gbm")
    returned_ranker = calibration[-1]
    scores = precompute.predict_with_fitted_ranker(
        returned_ranker,
        "gbm",
        [{"feature": 3}],
    )

    assert returned_ranker is fitted_ranker
    assert scores.tolist() == [0.75]
    assert encoder.calls == [([{"feature": 3}], False)]
    assert ranker.encoded.tolist() == [[3.0]]


def test_batch_curve_uses_every_licence_in_a_duplicate_cohort_key():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE licence ("
        "mgtno TEXT PRIMARY KEY, grid_id TEXT, uptae TEXT, "
        "open_y INTEGER, open_m INTEGER, close_y INTEGER, close_m INTEGER, "
        "is_closed INTEGER)"
    )
    metadata = []
    grade_by_index = []
    rows = []
    opened = precompute.ym(2023, 1)
    for grade in range(1, 11):
        unique_count = 198 if grade == 1 else 200
        for index in range(unique_count):
            grid_id = f"{grade}_{index}"
            rows.append(
                (
                    f"{grade}-{index}",
                    grid_id,
                    "한식",
                    2023,
                    1,
                    None,
                    None,
                    0,
                )
            )
            metadata.append({"grid_id": grid_id, "uptae": "한식", "open_ym": opened})
            grade_by_index.append(grade)
        if grade == 1:
            for suffix, closed in (("open", False), ("closed", True)):
                rows.append(
                    (
                        f"duplicate-{suffix}",
                        "duplicate",
                        "한식",
                        2023,
                        1,
                        2024 if closed else None,
                        1 if closed else None,
                        int(closed),
                    )
                )
                metadata.append(
                    {
                        "grid_id": "duplicate",
                        "uptae": "한식",
                        "open_ym": opened,
                    }
                )
                grade_by_index.append(grade)
    con.executemany("INSERT INTO licence VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)

    curves, sample_sizes = precompute.measured_survival_curves(
        con,
        metadata,
        grade_by_index,
    )

    assert sample_sizes[1] == 200
    assert sum(sample_sizes.values()) == 2_000
    assert curves[1][12] == pytest.approx(199 / 200)


@pytest.mark.parametrize(
    ("payload_model", "payload_train_years"),
    [
        ("rf", [2005, 2022]),
        ("gbm", [1900]),
    ],
)
def test_economics_rejects_curve_lineage_mismatch(
    monkeypatch,
    tmp_path,
    payload_model,
    payload_train_years,
):
    curve_value = json.dumps(
        {
            "rankModel": payload_model,
            "rankFeatures": ["feature_a"],
            "trainYears": payload_train_years,
            "testYears": [2023],
            "horizonMonths": 36,
            "curves": [
                {"grade": grade, "n": 200, "survival": [0.5] * 37}
                for grade in range(1, 11)
            ],
        }
    )
    batch_db = tmp_path / "mismatch.db"
    _create_score_meta_db(
        batch_db,
        (
            ("rank_model", "gbm"),
            ("rank_features", "feature_a"),
            ("rank_train_years", "2005,2022"),
            ("rank_test_years", "2023"),
            ("survival_curves_36m", curve_value),
        ),
    )
    monkeypatch.setattr(api, "DB_PATH", batch_db)

    with pytest.raises(
        economics_service.EconomicsUnavailableError,
        match="계보",
    ):
        economics_service.grade_survival_curves()


def test_economics_has_no_curve_fallback_when_batch_value_is_missing(
    monkeypatch,
    tmp_path,
):
    batch_db = tmp_path / "no-curve.db"
    _create_score_meta_db(
        batch_db,
        (
            ("rank_model", "gbm"),
            ("rank_features", "feature_a,feature_b"),
            ("rank_train_years", "2005,2022"),
            ("rank_test_years", "2023"),
        ),
    )
    monkeypatch.setattr(api, "DB_PATH", batch_db)

    with pytest.raises(
        economics_service.EconomicsUnavailableError,
        match="배치 미실행",
    ):
        economics_service.grade_survival_curves()


def test_goodwill_slim_input_uses_server_sources_and_after_rent_margin(monkeypatch):
    sample = _sample_goodwill_grid()
    monkeypatch.setattr(
        "service.goodwill.grade_survival_curves",
        _constant_curves,
    )

    with api.readonly_connection() as con:
        quarter = con.execute("SELECT MAX(quarter) FROM trdar_sales").fetchone()[0]
        trade_area = con.execute(
            "SELECT f.trdar_cd FROM grid_feature f WHERE f.grid_id = ?",
            (sample["grid_id"],),
        ).fetchone()[0]
        expected_monthly = con.execute(
            "SELECT s.sales_amt / t.stor_co / 3.0 / 10000.0 "
            "FROM trdar_sales s JOIN trdar_store t "
            "ON t.trdar_cd = s.trdar_cd AND t.induty_cd = s.induty_cd "
            "AND t.quarter = s.quarter "
            "WHERE s.quarter = ? AND s.trdar_cd = ? "
            "AND s.induty_cd = 'CS100001' AND t.stor_co > 0",
            (quarter, trade_area),
        ).fetchone()[0]
        # Median benchmark (원안 §5-3, owner call 2026-07-27) — mirror the
        # serving query row-for-row, then take the median in Python.
        expected_benchmark = statistics.median(
            row[0]
            for row in con.execute(
                "SELECT s.sales_amt / t.stor_co / 3.0 / 10000.0 "
                "FROM trdar_sales s JOIN trdar_store t "
                "ON t.trdar_cd = s.trdar_cd AND t.induty_cd = s.induty_cd "
                "AND t.quarter = s.quarter "
                "WHERE s.quarter = ? AND s.induty_cd = 'CS100001' "
                "AND t.stor_co > 0",
                (quarter,),
            ).fetchall()
            if row[0] is not None
        )

    response = client.post(
        "/api/goodwill",
        json={
            "gridId": sample["grid_id"],
            "uptae": sample["uptae"],
            "askingGoodwill": 500,
            "leaseRemainingYears": 5,
            "assets": [],
        },
    )

    assert response.status_code == 200
    body = response.json()
    annual_excess = max(
        0, (expected_monthly - expected_benchmark) * 0.0701 * 12
    )
    expected = sum(annual_excess / 1.08**year for year in range(1, 4))
    assert body["valuationYears"] == 3
    assert body["monthlyRevenue"] == pytest.approx(expected_monthly)
    assert body["benchmarkMonthlyRevenue"] == pytest.approx(expected_benchmark)
    assert body["intangibleValue"] == pytest.approx(expected)
    assert body["estimatedGoodwill"] == pytest.approx(expected)
    assert body["operatingMargin"] == 0.0701
    assert body["operatingMarginBasis"] == "after_rent"
    assert body["operatingMarginSource"] == (
        "외식업체 경영실태조사(농림축산식품부·KREI) 2025년 조사 "
        "서울 외식업체 영업이익률 7.01% (2024년 실적, n=491, 임대료 차감 후)"
    )
    assert body["loanRate"] == 0.05
    assert body["riskPremium"] == 0.03
    assert body["discountRate"] == 0.08
    assert "5%" in body["discountRateSource"]
    assert "3%" in body["discountRateSource"]
    assert body["benchmarkLevel"] == 4
    assert body["benchmarkWarning"]
    assert body["adjustmentFactor"] == 1
    assert body["adjustmentReasons"] == ["v1 미적용 — 데이터 기반 조정 항은 로드맵"]
    assert {row["years"] for row in body["sensitivity"]} == {2, 3}
    assert {row["operatingMargin"] for row in body["sensitivity"]} == {
        0.0551,
        0.0701,
        0.0851,
    }
    assert len(body["sensitivity"]) == 18
    assert body["bandLow"] <= body["estimatedGoodwill"] <= body["bandHigh"]


def test_goodwill_preserves_partial_valuation_years(monkeypatch, tmp_path):
    source_db = tmp_path / "partial-year-goodwill.db"
    with sqlite3.connect(source_db) as con:
        con.execute("CREATE TABLE grid_feature (grid_id TEXT, trdar_cd TEXT)")
        con.execute("INSERT INTO grid_feature VALUES ('1_1', 'A_TARGET')")
        con.execute(
            "CREATE TABLE trdar_sales ("
            "quarter TEXT, trdar_cd TEXT, induty_cd TEXT, sales_amt REAL)"
        )
        con.executemany(
            "INSERT INTO trdar_sales VALUES (?, ?, ?, ?)",
            [
                ("20261", "A_TARGET", "CS100001", 300_000_000),
                ("20261", "A_BENCH", "CS100001", 150_000_000),
            ],
        )
        con.execute(
            "CREATE TABLE trdar_store ("
            "quarter TEXT, trdar_cd TEXT, induty_cd TEXT, stor_co REAL)"
        )
        con.executemany(
            "INSERT INTO trdar_store VALUES (?, ?, ?, ?)",
            [
                ("20261", "A_TARGET", "CS100001", 5),
                ("20261", "A_BENCH", "CS100001", 5),
            ],
        )
    partial_curve = [1.0] + [1.0] * 31 + [0.8] + [0.0] * 4
    monkeypatch.setattr(api, "DB_PATH", source_db)
    monkeypatch.setattr(
        api,
        "grid_detail",
        lambda _grid_id, _uptae: {"grade": 1, "sales_available": True},
    )
    monkeypatch.setattr(
        "service.goodwill.grade_survival_curves",
        lambda: {grade: partial_curve for grade in range(1, 11)},
    )

    def post(lease_years):
        return client.post(
            "/api/goodwill",
            json={
                "gridId": "1_1",
                "uptae": "한식",
                "askingGoodwill": 8_000,
                "leaseRemainingYears": lease_years,
            },
        )

    long_lease = post(10)
    assert long_lease.status_code == 200
    long_body = long_lease.json()
    annual_excess = (
        long_body["monthlyRevenue"] - long_body["benchmarkMonthlyRevenue"]
    ) * long_body["operatingMargin"] * 12
    two_year_value = sum(annual_excess / 1.08**year for year in range(1, 3))
    expected_long = two_year_value + annual_excess * 0.65 / 1.08**3
    assert long_body["valuationYears"] == pytest.approx(2.65)
    assert long_body["estimatedGoodwill"] == pytest.approx(expected_long)
    assert long_body["estimatedGoodwill"] / two_year_value - 1 == pytest.approx(
        0.29, abs=0.01
    )
    long_sensitivity_years = {row["years"] for row in long_body["sensitivity"]}
    assert long_body["valuationYears"] in long_sensitivity_years
    assert max(long_sensitivity_years) == 3

    short_lease = post(1.5)
    assert short_lease.status_code == 200
    short_body = short_lease.json()
    expected_short = annual_excess / 1.08 + annual_excess * 0.5 / 1.08**2
    assert short_body["valuationYears"] == 1.5
    assert short_body["estimatedGoodwill"] == pytest.approx(expected_short)
    assert max(row["years"] for row in short_body["sensitivity"]) == 1.5

    for lease_years in (0.5, 1):
        response = post(lease_years)
        assert response.status_code == 200
        body = response.json()
        sensitivity_years = {row["years"] for row in body["sensitivity"]}
        assert body["valuationYears"] == lease_years
        assert sensitivity_years == {lease_years}
        assert all(year > 0 for year in sensitivity_years)


def test_goodwill_rejects_removed_caller_owned_inputs():
    sample = _sample_goodwill_grid()

    response = client.post(
        "/api/goodwill",
        json={
            "gridId": sample["grid_id"],
            "uptae": sample["uptae"],
            "askingGoodwill": 500,
            "leaseRemainingYears": 5,
            "monthlyRevenue": 200,
        },
    )

    assert response.status_code == 422
    assert any(
        error["type"] == "extra_forbidden" and error["loc"][-1] == "monthlyRevenue"
        for error in response.json()["detail"]
    )


def test_goodwill_returns_422_outside_a_trade_area(monkeypatch):
    sample = _sample_grid(sales_available=False)
    monkeypatch.setattr(
        "service.goodwill.grade_survival_curves",
        _constant_curves,
    )

    response = client.post(
        "/api/goodwill",
        json={
            "gridId": sample["grid_id"],
            "uptae": sample["uptae"],
            "askingGoodwill": 500,
            "leaseRemainingYears": 5,
        },
    )

    assert response.status_code == 422
    assert "상권 매출 근거가 없는 격자" in response.json()["detail"]


def test_goodwill_returns_503_when_benchmark_source_rows_are_missing(
    monkeypatch,
    tmp_path,
):
    source_db = tmp_path / "missing-goodwill-source.db"
    with sqlite3.connect(source_db) as con:
        con.execute("CREATE TABLE grid_feature (grid_id TEXT, trdar_cd TEXT)")
        con.execute("INSERT INTO grid_feature VALUES ('1_1', 'A_TEST_TRADE_AREA')")
        con.execute(
            "CREATE TABLE trdar_sales ("
            "quarter TEXT, trdar_cd TEXT, induty_cd TEXT, sales_amt REAL)"
        )
        con.execute(
            "CREATE TABLE trdar_store ("
            "quarter TEXT, trdar_cd TEXT, induty_cd TEXT, stor_co REAL)"
        )
    monkeypatch.setattr(api, "DB_PATH", source_db)
    monkeypatch.setattr(
        api,
        "grid_detail",
        lambda _grid_id, _uptae: {"grade": 1, "sales_available": True},
    )
    monkeypatch.setattr(
        "service.goodwill.grade_survival_curves",
        _constant_curves,
    )

    response = client.post(
        "/api/goodwill",
        json={
            "gridId": "1_1",
            "uptae": "한식",
            "askingGoodwill": 500,
            "leaseRemainingYears": 5,
        },
    )

    assert response.status_code == 503
    assert "벤치마크 원천" in response.json()["detail"]


def test_goodwill_uses_latest_common_sales_and_store_quarter(monkeypatch, tmp_path):
    source_db = tmp_path / "goodwill-quarter-mismatch.db"
    with sqlite3.connect(source_db) as con:
        con.execute("CREATE TABLE grid_feature (grid_id TEXT, trdar_cd TEXT)")
        con.execute("INSERT INTO grid_feature VALUES ('1_1', 'A_TARGET')")
        con.execute(
            "CREATE TABLE trdar_sales ("
            "quarter TEXT, trdar_cd TEXT, induty_cd TEXT, sales_amt REAL)"
        )
        con.executemany(
            "INSERT INTO trdar_sales VALUES (?, ?, ?, ?)",
            [
                ("20261", "A_TARGET", "CS100001", 300_000_000),
                ("20261", "A_BENCH", "CS100001", 150_000_000),
                ("20262", "A_STALE", "CS100001", 900_000_000),
            ],
        )
        con.execute(
            "CREATE TABLE trdar_store ("
            "quarter TEXT, trdar_cd TEXT, induty_cd TEXT, stor_co REAL)"
        )
        con.executemany(
            "INSERT INTO trdar_store VALUES (?, ?, ?, ?)",
            [
                ("20261", "A_TARGET", "CS100001", 5),
                ("20261", "A_BENCH", "CS100001", 5),
            ],
        )
    monkeypatch.setattr(api, "DB_PATH", source_db)
    monkeypatch.setattr(
        api,
        "grid_detail",
        lambda _grid_id, _uptae: {"grade": 1, "sales_available": True},
    )
    monkeypatch.setattr(
        "service.goodwill.grade_survival_curves",
        _constant_curves,
    )

    response = client.post(
        "/api/goodwill",
        json={
            "gridId": "1_1",
            "uptae": "한식",
            "askingGoodwill": 500,
            "leaseRemainingYears": 5,
        },
    )

    assert response.status_code == 200
    assert response.json()["monthlyRevenue"] == pytest.approx(2000)
    assert response.json()["benchmarkMonthlyRevenue"] == pytest.approx(1500)


def test_goodwill_has_no_cross_industry_fallback(monkeypatch):
    monkeypatch.setattr(
        api,
        "grid_detail",
        lambda _grid_id, _uptae: {"grade": 1, "sales_available": True},
    )

    response = client.post(
        "/api/goodwill",
        json={
            "gridId": "1_1",
            "uptae": "기타",
            "askingGoodwill": 500,
            "leaseRemainingYears": 5,
        },
    )

    assert response.status_code == 503
    assert "동일 업종 벤치마크 원천" in response.json()["detail"]


def test_goodwill_openapi_exposes_only_slim_input():
    schema = app.openapi()["components"]["schemas"]["GoodwillInput"]

    assert set(schema["properties"]) == {
        "gridId",
        "uptae",
        "askingGoodwill",
        "leaseRemainingYears",
        "assets",
    }
    assert set(schema["required"]) == {
        "gridId",
        "uptae",
        "askingGoodwill",
        "leaseRemainingYears",
    }


def test_report_renders_only_known_placeholders_and_rejects_numeric_glyphs():
    evidence = {"grade": "1", "observedSurvivalPercent": "73.1"}
    rendered = reporting.render_evidence_placeholders(
        ["{{grade}}등급의 실측 생존율은 {{observedSurvivalPercent}}%입니다."],
        evidence,
    )
    assert rendered == ["1등급의 실측 생존율은 73.1%입니다."]

    for expression in (
        "99",
        "1/3",
        "1e3",
        "1-3",
        "1.0",
        "½",
        "1−3",
        "1∕3",
        "1⁄3",
    ):
        with pytest.raises(reporting.UnapprovedNumberError):
            reporting.render_evidence_placeholders(
                [f"새 수치는 {expression}입니다."],
                evidence,
            )
    with pytest.raises(reporting.ReportGenerationError):
        reporting.render_evidence_placeholders(
            ["{{unknown}} 값입니다."],
            evidence,
        )
    for expression in (
        "{{grade}}{{horizonYears}}",
        "{{grade}}+{{horizonYears}}",
        "{{grade}}e{{horizonYears}}",
    ):
        with pytest.raises(reporting.ReportGenerationError):
            reporting.render_evidence_placeholders(
                [expression],
                {"grade": "1", "horizonYears": "3"},
            )


def test_openapi_declares_runtime_error_contract():
    paths = app.openapi()["paths"]
    expected = {
        "/api/meta": {"200", "503"},
        "/api/grids": {"200", "413", "422", "503"},
        "/api/recommend": {"200", "422", "503"},
        "/api/grid/{grid_id}": {"200", "404", "422", "503"},
        "/api/grid/{grid_id}/buildings": {"200", "404", "422", "503"},
        "/api/at": {"200", "404", "422", "503"},
        "/api/economics": {"200", "404", "422", "503"},
        "/api/goodwill": {"200", "404", "422", "503"},
        "/api/report": {"200", "404", "422", "502", "503"},
    }

    for path, statuses in expected.items():
        operation = (
            "get"
            if path
            in {
                "/api/meta",
                "/api/grids",
                "/api/recommend",
                "/api/grid/{grid_id}",
                "/api/grid/{grid_id}/buildings",
                "/api/at",
            }
            else "post"
        )
        assert set(paths[path][operation]["responses"]) == statuses
    building_parameters = paths["/api/grid/{grid_id}/buildings"]["get"]["parameters"]
    assert [parameter["name"] for parameter in building_parameters] == ["grid_id"]


def test_report_omits_nullable_overall_survival_from_evidence(monkeypatch):
    sample = _sample_grid()
    monkeypatch.setattr(
        reporting.api,
        "meta",
        lambda: {"overall_survival": None},
    )

    evidence = reporting.build_evidence(sample["grid_id"], sample["uptae"])

    assert "overallSurvivalPercent" not in evidence
    assert "gradeTopPercent" not in evidence


@pytest.mark.parametrize("grade", (1, 10))
def test_report_appends_observed_grade_risk_after_whitelist(monkeypatch, grade):
    sample = _sample_grid_by_grade(grade)

    def generated(_evidence):
        return [
            "{{grade}}등급 자리입니다.",
            "이 등급의 실측 생존율은 {{observedSurvivalPercent}}%입니다.",
        ]

    monkeypatch.setattr(reporting, "_generate_sentences", generated)
    monkeypatch.setattr(
        reporting.api,
        "meta",
        lambda: {
            "overall_survival": 0.01,
            "observed_by_grade": [0.99] * 10,
        },
    )
    response = client.post(
        "/api/report",
        json={"gridId": sample["grid_id"], "uptae": sample["uptae"]},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["sentences"]) == 3
    expected_closure = round((1 - sample["observed"]) * 100)
    assert body["sentences"][-1].startswith(
        f"이 등급 자리의 실측 3년 내 폐업률은 약 {expected_closure}%"
    )


def test_report_has_no_fallback_when_api_key_is_missing(monkeypatch):
    sample = _sample_grid()
    monkeypatch.setattr(reporting, "load_env", lambda: {})

    response = client.post(
        "/api/report",
        json={"gridId": sample["grid_id"], "uptae": sample["uptae"]},
    )

    assert response.status_code == 503


def test_report_returns_bad_gateway_for_an_unapproved_generated_number(
    monkeypatch,
):
    sample = _sample_grid()
    monkeypatch.setattr(
        reporting,
        "_generate_sentences",
        lambda _evidence: ["999점입니다.", "근거를 확인하세요."],
    )

    response = client.post(
        "/api/report",
        json={"gridId": sample["grid_id"], "uptae": sample["uptae"]},
    )

    assert response.status_code == 502


def _create_building_facts_db(path, licence_rows):
    with sqlite3.connect(path) as con:
        con.executescript(
            """
            CREATE TABLE grid (grid_id TEXT PRIMARY KEY);
            CREATE TABLE licence (
              addr TEXT,
              uptae TEXT,
              is_closed INTEGER,
              grid_id TEXT
            );
            CREATE INDEX ix_licence_grid ON licence(grid_id);
            INSERT INTO grid VALUES ('1_1');
            INSERT INTO grid VALUES ('2_2');
            """
        )
        con.executemany(
            "INSERT INTO licence(addr, uptae, is_closed, grid_id) "
            "VALUES (?, ?, ?, ?)",
            licence_rows,
        )


def test_buildings_returns_parcel_facts_without_guessing_unparsed_rows(
    monkeypatch,
    tmp_path,
):
    source_db = tmp_path / "building-facts.db"
    _create_building_facts_db(
        source_db,
        [
            ("서울특별시 영등포구 여의도동 22 TP Tower, 101호", "한식", 0, "1_1"),
            ("서울특별시 영등포구 여의도동 22 TP Tower, 202호", "일식", 0, "1_1"),
            ("서울특별시 영등포구 여의도동 22 Old Name, 301호", "한식", 1, "1_1"),
            ("서울특별시 영등포구 여의도동 22 TP Tower, 401호", "한식", 0, "1_1"),
            ("서울특별시 영등포구 여의도동 22 TP Tower, 402호", "분식", 0, "1_1"),
            ("서울특별시 영등포구 여의도동 22 TP Tower, 403호", "경양식", 0, "1_1"),
            ("서울특별시 영등포구 여의도동 산 23", None, 0, "1_1"),
            ("서울특별시 영등포구 여의도동 주소미상", "분식", 0, "1_1"),
        ],
    )
    monkeypatch.setattr(api, "DB_PATH", source_db)

    response = client.get("/api/grid/1_1/buildings")

    assert response.status_code == 200
    assert response.json() == {
        "gridId": "1_1",
        "source": "licence",
        "buildings": [
            {
                "jibun": "서울특별시 영등포구 여의도동 22",
                "buildingName": "TP Tower",
                "activeShops": 5,
                "openingsTotal": 6,
                "closuresTotal": 1,
                "uptaeMix": [
                    {"uptae": "한식", "active": 2},
                    {"uptae": "경양식", "active": 1},
                    {"uptae": "분식", "active": 1},
                ],
            },
            {
                "jibun": "서울특별시 영등포구 여의도동 산 23",
                "buildingName": None,
                "activeShops": 1,
                "openingsTotal": 1,
                "closuresTotal": 0,
                "uptaeMix": [{"uptae": None, "active": 1}],
            },
        ],
        "unparsedCount": 1,
    }


def test_buildings_distinguishes_empty_and_unknown_grids(monkeypatch, tmp_path):
    source_db = tmp_path / "building-empty.db"
    _create_building_facts_db(source_db, [])
    monkeypatch.setattr(api, "DB_PATH", source_db)

    empty = client.get("/api/grid/2_2/buildings")
    unknown = client.get("/api/grid/9_9/buildings")

    assert empty.status_code == 200
    assert empty.json() == {
        "gridId": "2_2",
        "source": "licence",
        "buildings": [],
        "unparsedCount": 0,
    }
    assert unknown.status_code == 404


def test_buildings_caps_factual_sort_at_fifty(monkeypatch, tmp_path):
    source_db = tmp_path / "building-cap.db"
    rows = [
        (f"서울특별시 종로구 청운동 {number}", "한식", 0, "1_1")
        for number in range(1, 52)
    ]
    _create_building_facts_db(source_db, rows)
    monkeypatch.setattr(api, "DB_PATH", source_db)

    response = client.get("/api/grid/1_1/buildings")

    assert response.status_code == 200
    buildings = response.json()["buildings"]
    assert len(buildings) == 50
    assert all(building["activeShops"] == 1 for building in buildings)


def _sample_grid_with_concepts():
    with api.readonly_connection() as connection:
        return connection.execute(
            "SELECT grid_id FROM grid_concept GROUP BY grid_id "
            "ORDER BY SUM(n) DESC LIMIT 1"
        ).fetchone()["grid_id"]


def test_concept_mix_counts_are_observations_not_predictions():
    grid_id = _sample_grid_with_concepts()

    response = client.get(f"/api/grid/{grid_id}", params={"uptae": "한식"})

    assert response.status_code == 200
    mix = response.json()["conceptMix"]
    assert mix["available"] is True
    assert mix["items"], "표본 격자에 구성이 있어야 한다"
    assert mix["shops"] == sum(item["shops"] for item in mix["items"])
    assert all(item["shops"] >= 1 for item in mix["items"])
    # 개수는 내림차순이라 화면이 다시 정렬하지 않는다
    counts = [item["shops"] for item in mix["items"]]
    assert counts == sorted(counts, reverse=True)
    # 관측이라는 선언이 응답에 남아 있어야 한다
    assert mix["claim"] == "observation_only:not_predictive"
    # 원천이 두 표다. 일반음식점만 읽던 시절에는 사전에 «커피»·«카페»가 있어도
    # 걸릴 상호가 없어 카페가 통째로 안 잡혔다(30,801 -> 79,693 으로 늘었다).
    # 한쪽으로 되돌아가면 여기서 걸린다.
    assert mix["source"] == "licence+licence_rest.bplcnm:open_only"


def test_concept_mix_reports_unavailable_when_batch_missing(monkeypatch, tmp_path):
    """배치 미실행은 빈 구성이 아니다 — 없는 것을 없다고 말해야 한다."""
    grid_id = _sample_grid_with_concepts()
    stripped = tmp_path / "no-concept.db"

    with api.readonly_connection() as connection:
        source_path = connection.execute("PRAGMA database_list").fetchone()["file"]
    shutil.copy(source_path, stripped)
    with sqlite3.connect(stripped) as connection:
        connection.execute("DROP TABLE grid_concept")
    monkeypatch.setattr(api, "DB_PATH", stripped)

    response = client.get(f"/api/grid/{grid_id}", params={"uptae": "한식"})

    assert response.status_code == 200
    mix = response.json()["conceptMix"]
    assert mix["available"] is False
    assert mix["items"] == []


def test_recommend_carries_concept_mix_without_extra_round_trips():
    """S3 는 후보 20여 개를 한 번에 그린다 — 격자마다 조회하면 N+1 이 된다."""
    queries = []
    original_connection = api.readonly_connection

    class CountingConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, statement, parameters=()):
            if "grid_concept" in statement:
                queries.append(statement)
            return self.connection.execute(statement, parameters)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    @contextmanager
    def counting():
        with original_connection() as connection:
            yield CountingConnection(connection)

    def count_for(top):
        queries.clear()
        api.readonly_connection = counting
        try:
            return api.recommend("한식", top=top), len(queries)
        finally:
            api.readonly_connection = original_connection

    _, few = count_for(3)
    body, many = count_for(20)

    # 후보가 늘어도 조회 수가 그대로여야 한다 — 격자마다 도는 순간 여기서 깨진다.
    assert few == many, f"후보 수에 비례해 조회가 늘었다: {few} -> {many}"
    assert body["count"] == 20
    assert all(item["concept_mix"] is not None for item in body["items"])
    assert any(item["concept_mix"]["items"] for item in body["items"])


def _estimate_payload(sample, **overrides):
    payload = {
        "gridId": sample["grid_id"],
        "uptae": sample["uptae"],
        "deposit": 5_000,
        "monthlyRent": 250,
        "askingGoodwill": 12_000,
        "areaM2": 45,
        "floor": 1,
    }
    payload.update(overrides)
    return payload


def test_estimate_returns_cost_for_grid_and_coordinates(monkeypatch):
    sample = _sample_goodwill_grid()
    monkeypatch.setenv("KB_RECOVERY_SOURCE", "constant")

    by_grid = client.post("/api/estimate", json=_estimate_payload(sample))

    assert by_grid.status_code == 200
    body = by_grid.json()
    assert body["gridId"] == sample["grid_id"]
    assert body["effectiveCost"] == pytest.approx(600)
    assert (
        body["effectiveCostBand"]["low"]
        <= body["effectiveCost"]
        <= body["effectiveCostBand"]["high"]
    )
    assert body["successionProb"] == 0.4
    assert body["recoverySource"] == "constant"
    assert "recoveryProb" not in body
    assert "recoveryRange" not in body
    assert body["monthlyRevenue"] > 0
    assert body["revenueResolution"] == "trade_area"
    assert body["burdenRate"] == pytest.approx(
        body["effectiveCost"] / body["monthlyRevenue"]
    )
    assert body["burdenRateBand"] == {
        "low": pytest.approx(
            body["effectiveCostBand"]["low"] / body["monthlyRevenue"]
        ),
        "high": pytest.approx(
            body["effectiveCostBand"]["high"] / body["monthlyRevenue"]
        ),
    }
    assert "burdenRate" not in body["missingAxes"]

    detail = client.get(
        f"/api/grid/{sample['grid_id']}",
        params={"uptae": sample["uptae"]},
    ).json()
    by_coordinates = client.post(
        "/api/estimate",
        json=_estimate_payload(
            sample,
            gridId=None,
            lon=detail["center"][0],
            lat=detail["center"][1],
            costParams={"opportunityRate": 0.12, "horizonMonths": 12},
        ),
    )

    assert by_coordinates.status_code == 200
    coordinate_body = by_coordinates.json()
    assert coordinate_body["gridId"] == sample["grid_id"]
    assert coordinate_body["effectiveCost"] == pytest.approx(1_300)


def test_recovery_source_defaults_to_m2_and_constant_rolls_back(monkeypatch):
    sample = _sample_goodwill_grid()
    payload = _estimate_payload(sample)
    candidate = dict(payload)
    candidate.pop("uptae")

    with api.readonly_connection() as con:
        expected = con.execute(
            "SELECT succession_prob FROM succession_score "
            "WHERE grid_id = ? AND uptae = ?",
            (sample["grid_id"], sample["uptae"]),
        ).fetchone()
    assert expected is not None

    monkeypatch.delenv("KB_RECOVERY_SOURCE", raising=False)
    estimate = client.post("/api/estimate", json=payload)
    compare = client.post(
        "/api/compare",
        json={"uptae": sample["uptae"], "candidates": [candidate]},
    )
    assert estimate.status_code == compare.status_code == 200
    assert estimate.json()["successionProb"] == pytest.approx(expected[0])
    assert estimate.json()["recoverySource"] == "m2"
    assert compare.json()["items"][0]["successionProb"] == pytest.approx(expected[0])
    assert compare.json()["recoverySource"] == "m2"

    monkeypatch.setenv("KB_RECOVERY_SOURCE", "constant")
    estimate = client.post("/api/estimate", json=payload)
    compare = client.post(
        "/api/compare",
        json={"uptae": sample["uptae"], "candidates": [candidate]},
    )
    assert estimate.json()["successionProb"] == 0.4
    assert estimate.json()["recoverySource"] == "constant"
    assert compare.json()["items"][0]["successionProb"] == 0.4
    assert compare.json()["recoverySource"] == "constant"


@pytest.mark.parametrize(
    ("table_exists", "row_overrides", "detail"),
    [
        (None, {}, "원천 테이블"),
        ((1,), None, "원천 행"),
        ((1,), {"recovery_source": "constant"}, "계보"),
        ((1,), {"model_version": "wrong-version"}, "모델 버전 또는 관측시점"),
        ((1,), {"as_of_ym": 202606}, "모델 버전 또는 관측시점"),
    ],
)
def test_m2_source_failures_return_503_without_constant_fallback(
    monkeypatch, table_exists, row_overrides, detail
):
    sample = _sample_goodwill_grid()
    payload = _estimate_payload(sample)
    original_connection = api.readonly_connection
    row = None
    if row_overrides is not None:
        row = {
            "succession_prob": 0.2,
            "recovery_source": "m2",
            "as_of_ym": estimation_service.M2_AS_OF_YM,
            "model_version": estimation_service.M2_MODEL_VERSION,
            **row_overrides,
        }

    class Cursor:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

    class RecoveryConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params=()):
            if "name='succession_score'" in query:
                return Cursor(table_exists)
            if "FROM succession_score" in query:
                return Cursor(row)
            return self.connection.execute(query, params)

    @contextmanager
    def recovery_connection():
        with original_connection() as connection:
            yield RecoveryConnection(connection)

    monkeypatch.delenv("KB_RECOVERY_SOURCE", raising=False)
    monkeypatch.setattr(api, "readonly_connection", recovery_connection)
    response = client.post("/api/estimate", json=payload)

    assert response.status_code == 503
    assert detail in response.json()["detail"]
    assert "successionProb" not in response.json()


def test_missing_succession_probability_serves_conservative_band(
    monkeypatch,
):
    sample = _sample_goodwill_grid()
    payload = _estimate_payload(sample)
    original_connection = api.readonly_connection
    row = {
        "succession_prob": None,
        "recovery_source": "m2",
        "as_of_ym": estimation_service.M2_AS_OF_YM,
        "model_version": estimation_service.M2_MODEL_VERSION,
    }

    class Cursor:
        def fetchone(self):
            return row

    class RecoveryConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, query, params=()):
            if "name='succession_score'" in query:
                return Cursor()
            if "FROM succession_score" in query:
                return Cursor()
            return self.connection.execute(query, params)

    @contextmanager
    def recovery_connection():
        with original_connection() as connection:
            yield RecoveryConnection(connection)

    monkeypatch.delenv("KB_RECOVERY_SOURCE", raising=False)
    monkeypatch.setattr(api, "readonly_connection", recovery_connection)
    response = client.post("/api/estimate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["successionProb"] is None
    assert body["recoverySource"] == "m2"
    assert body["costBreakdown"]["premiumAmortized"] == pytest.approx(
        payload["askingGoodwill"] / body["paramsUsed"]["horizonMonths"]
    )
    assert (
        body["effectiveCostBand"]["low"]
        <= body["effectiveCost"]
        <= body["effectiveCostBand"]["high"]
    )
    assert (
        body["effectiveCostBand"]["low"]
        < body["effectiveCostBand"]["high"]
    )
    assert "recoveryProb" not in body
    assert "recoveryRange" not in body


def test_estimate_not_evaluated():
    sample = _sample_goodwill_grid()

    response = client.post(
        "/api/estimate",
        json=_estimate_payload(sample, gridId="0_0"),
    )

    assert response.status_code == 404
    assert response.json()["detail"].startswith(
        "이웃 이력 부족으로 평가하지 않음"
    )


def test_estimate_outside_trade_area(monkeypatch):
    sample = _sample_grid(sales_available=False)
    payload = _estimate_payload(sample)
    monkeypatch.delenv("KB_RECOVERY_SOURCE", raising=False)

    response = client.post("/api/estimate", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["recoverySource"] == "m2"
    assert body["successionProb"] != 0.4
    params = body["paramsUsed"]
    expected_cost = (
        payload["monthlyRent"]
        + payload["deposit"] * params["opportunityRate"] / 12
        + payload["askingGoodwill"]
        / params["horizonMonths"]
    )
    assert body["effectiveCost"] == pytest.approx(expected_cost)
    assert body["monthlyRevenue"] is None
    assert body["burdenRate"] is None
    assert body["burdenRateBand"] is None
    assert body["revenueAsOfQuarter"] is None
    assert body["revenueResolution"] == "trade_area"
    assert {"revenue", "burdenRate"} <= set(body["missingAxes"])


def test_estimate_rejects_non_finite_calculation():
    sample = _sample_goodwill_grid()

    response = client.post(
        "/api/estimate",
        json=_estimate_payload(
            sample,
            deposit=1.79e308,
            monthlyRent=1.79e308,
            askingGoodwill=1.79e308,
        ),
    )

    assert response.status_code == 422
    assert "유한 범위" in response.json()["detail"]


def _compare_candidate(sample, **overrides):
    candidate = _estimate_payload(sample, **overrides)
    candidate.pop("uptae")
    return candidate


def _two_goodwill_trade_areas():
    with api.readonly_connection() as con:
        rows = con.execute(
            "SELECT MIN(f.grid_id) grid_id, '한식' uptae, f.trdar_cd, "
            "s.sales_amt / t.stor_co / 3.0 / 10000.0 monthly_revenue "
            "FROM grid_feature f "
            "JOIN grid_score g ON g.grid_id = f.grid_id AND g.uptae = '한식' "
            "JOIN trdar_sales s ON s.trdar_cd = f.trdar_cd "
            "AND s.induty_cd = 'CS100001' "
            "JOIN trdar_store t ON t.trdar_cd = s.trdar_cd "
            "AND t.induty_cd = s.induty_cd AND t.quarter = s.quarter "
            "WHERE t.stor_co > 0 AND s.sales_amt > 0 "
            "AND s.quarter = (SELECT MAX(quarter) FROM trdar_sales) "
            "GROUP BY f.trdar_cd, s.sales_amt, t.stor_co "
            "ORDER BY monthly_revenue LIMIT 2"
        ).fetchall()
    assert len(rows) == 2
    return [dict(row) for row in rows]


def test_compare_returns_both_ranks():
    sample = _sample_goodwill_grid()
    candidates = [
        _compare_candidate(
            sample,
            deposit=5_000,
            monthlyRent=250,
            askingGoodwill=12_000,
        ),
        _compare_candidate(
            sample,
            deposit=3_000,
            monthlyRent=380,
            askingGoodwill=2_000,
        ),
        _compare_candidate(
            sample,
            deposit=4_000,
            monthlyRent=310,
            askingGoodwill=6_000,
        ),
    ]

    response = client.post(
        "/api/compare",
        json={"uptae": sample["uptae"], "candidates": candidates},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert sorted(item["rentRank"] for item in items) == [1, 2, 3]
    assert sorted(item["teoRank"] for item in items) == [1, 2, 3]


def test_compare_tiebreak():
    low, high = _two_goodwill_trade_areas()
    assert low["monthly_revenue"] < high["monthly_revenue"]
    candidates = [
        _compare_candidate(
            high,
            deposit=0,
            monthlyRent=high["monthly_revenue"],
            askingGoodwill=0,
        ),
        _compare_candidate(
            low,
            deposit=0,
            monthlyRent=low["monthly_revenue"],
            askingGoodwill=0,
        ),
    ]

    response = client.post(
        "/api/compare",
        json={"uptae": "한식", "candidates": candidates},
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert all(item["burdenRate"] == pytest.approx(1) for item in items)
    by_grid = {item["gridId"]: item for item in items}
    assert by_grid[low["grid_id"]]["teoRank"] == 1
    assert by_grid[high["grid_id"]]["teoRank"] == 2

    crafted = [
        (
            {
                "grid_id": "burden-first",
                "uptae": "한식",
                "monthly_rent": 1,
                "burden_rate": 0.2,
                "effective_cost": 1,
                "recovery_prob": 1,
                "monthly_revenue": 5,
            },
            "trade-a",
        ),
        (
            {
                "grid_id": "lower-recovery",
                "uptae": "한식",
                "monthly_rent": 100,
                "burden_rate": 0.1,
                "effective_cost": 100,
                "recovery_prob": 0.1,
                "monthly_revenue": 1_000,
            },
            "trade-b",
        ),
        (
            {
                "grid_id": "higher-recovery",
                "uptae": "한식",
                "monthly_rent": 100,
                "burden_rate": 0.1,
                "effective_cost": 100,
                "recovery_prob": 0.9,
                "monthly_revenue": 1_000,
            },
            "trade-c",
        ),
    ]
    ranked = estimation_service.rank_candidates(crafted)
    assert [
        item["grid_id"] for item in sorted(ranked, key=lambda item: item["teo_rank"])
    ] == ["higher-recovery", "lower-recovery", "burden-first"]

    missing_burden = estimation_service.rank_candidates(
        [
            (
                {
                    "grid_id": "missing",
                    "uptae": "한식",
                    "monthly_rent": 0,
                    "burden_rate": None,
                    "effective_cost": 0,
                    "recovery_prob": 1,
                    "monthly_revenue": None,
                },
                None,
            ),
            (
                {
                    "grid_id": "observed",
                    "uptae": "한식",
                    "monthly_rent": 100,
                    "burden_rate": 0.9,
                    "effective_cost": 100,
                    "recovery_prob": 0,
                    "monthly_revenue": 111,
                },
                "trade-d",
            ),
        ]
    )
    by_grid = {item["grid_id"]: item for item in missing_burden}
    assert by_grid["observed"]["teo_rank"] == 1
    assert by_grid["missing"]["teo_rank"] == 2


def test_compare_same_trade_area_ties():
    sample = _sample_goodwill_grid()

    response = client.post(
        "/api/compare",
        json={
            "uptae": sample["uptae"],
            "candidates": [
                _compare_candidate(sample, monthlyRent=250),
                _compare_candidate(sample, monthlyRent=300),
            ],
        },
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert all(item["revenueTied"] is True for item in items)
    assert len({item["monthlyRevenue"] for item in items}) == 1


def test_goodwill_decomposition():
    sample = _sample_goodwill_grid()
    monkeypatch_target = "service.goodwill.grade_survival_curves"

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(monkeypatch_target, _constant_curves)
        response = client.post(
            "/api/goodwill",
            json={
                "gridId": sample["grid_id"],
                "uptae": sample["uptae"],
                "askingGoodwill": 500,
                "leaseRemainingYears": 5,
                "assets": [
                    {
                        "name": "주방설비",
                        "acquisitionCost": 100,
                        "ageYears": 2,
                        "usefulLifeYears": 5,
                    }
                ],
            },
        )

    assert response.status_code == 200
    body = response.json()
    decomposition = body["decomposition"]
    assert decomposition["facility"] == body["tangibleValue"]
    assert decomposition["business"] == body["intangibleValue"]
    assert decomposition["floorKey"] == pytest.approx(
        body["askingGoodwill"]
        - decomposition["facility"]
        - decomposition["business"]
    )


def test_floor_key_negative():
    sample = _sample_goodwill_grid()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "service.goodwill.grade_survival_curves",
            _constant_curves,
        )
        response = client.post(
            "/api/goodwill",
            json={
                "gridId": sample["grid_id"],
                "uptae": sample["uptae"],
                "askingGoodwill": 0,
                "leaseRemainingYears": 5,
                "assets": [
                    {
                        "name": "신규설비",
                        "acquisitionCost": 1_000,
                        "ageYears": 0,
                        "usefulLifeYears": 5,
                    }
                ],
            },
        )

    assert response.status_code == 200
    floor_key = response.json()["decomposition"]["floorKey"]
    assert floor_key < 0
    assert floor_key <= -1_000
