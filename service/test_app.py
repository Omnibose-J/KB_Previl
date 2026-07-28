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
    annual_excess = max(0, (expected_monthly - expected_benchmark) * 0.15 * 12)
    expected = sum(annual_excess / 1.08**year for year in range(1, 4))
    assert body["valuationYears"] == 3
    assert body["monthlyRevenue"] == pytest.approx(expected_monthly)
    assert body["benchmarkMonthlyRevenue"] == pytest.approx(expected_benchmark)
    assert body["intangibleValue"] == pytest.approx(expected)
    assert body["estimatedGoodwill"] == pytest.approx(expected)
    assert body["operatingMargin"] == 0.15
    assert body["operatingMarginBasis"] == "after_rent"
    assert "소상공인실태조사" in body["operatingMarginSource"]
    assert body["loanRate"] == 0.05
    assert body["riskPremium"] == 0.03
    assert body["discountRate"] == 0.08
    assert "5%" in body["discountRateSource"]
    assert "3%" in body["discountRateSource"]
    assert body["benchmarkLevel"] == 4
    assert body["benchmarkWarning"]
    assert body["adjustmentFactor"] == 1
    assert body["adjustmentReasons"] == ["v1 미적용 — 데이터 기반 조정 항은 로드맵"]
    assert len(body["sensitivity"]) == 27
    assert body["bandLow"] <= body["estimatedGoodwill"] <= body["bandHigh"]


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
    assert mix["source"] == "licence.bplcnm:open_only"


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

    api.readonly_connection = counting
    try:
        body = api.recommend("한식", top=20)
    finally:
        api.readonly_connection = original_connection

    assert len(queries) == 1, "콘셉트 구성은 한 번의 배치 조회여야 한다"
    assert body["items"], "후보가 있어야 한다"
    assert all(item["concept_mix"] is not None for item in body["items"])
    assert any(item["concept_mix"]["items"] for item in body["items"])
