"""Contract tests for the operating-capital runway simulation."""

import pytest
from fastapi.testclient import TestClient

from service import runway
from service import runway_params as params
from service.app import app
from service.test_app import _sample_grid


client = TestClient(app)

# Hand-computed base case (만원): steady 1,000 · margin 0.25 · rent 200 ·
# ramp 6 · start 0.45.
# nets: -64.583, -41.667, -18.75, +4.167, +27.083, then +50 flat
# cums: -64.583, -106.25, -125.0, -120.833, -93.75, -43.75, +6.25 ...
# trough month 3 → need 125 · breakeven month 4.
BASE = dict(
    grid_id="1_1",
    uptae="한식",
    upfront=8000,
    rent_monthly=200,
    revenue_monthly=1000,
    margin=0.25,
    ramp_months=6,
)


@pytest.mark.parametrize(
    ("budget", "level", "coverage", "depletion"),
    [
        (8165, "OK", 1.32, None),  # reserve 165 / need 125
        (8145, "WARN", 1.16, None),  # reserve 145
        (8100, "DANGER", 0.8, 2),  # reserve 100, dry at month 2
        (7950, "IMPOSSIBLE", None, 1),  # reserve -50: cannot even sign
    ],
)
def test_verdict_ladder(budget, level, coverage, depletion):
    result = runway.calculate(budget=budget, **BASE)

    assert result["level"] == level
    assert result["working_capital_need"] == pytest.approx(125)
    assert result["trough_month"] == 3
    assert result["breakeven_month"] == 4
    assert result["depletion_month"] == depletion
    if coverage is None:
        assert result["coverage"] is None
    else:
        assert result["coverage"] == pytest.approx(coverage)


def test_matches_economics_steady_month():
    # Same margin concept as economics: steady net = revenue × margin − rent.
    result = runway.calculate(budget=9000, **BASE)
    steady = result["curve"][-1]
    assert steady["net"] == pytest.approx(1000 * 0.25 - 200)


def test_no_working_capital_needed():
    # Strong revenue: positive from month one → nothing to bridge.
    result = runway.calculate(budget=8100, **{**BASE, "revenue_monthly": 2000})

    assert result["working_capital_need"] == 0
    assert result["coverage"] is None
    assert result["level"] == "OK"
    assert result["depletion_month"] is None
    assert result["breakeven_month"] == 1


def test_curve_invariants():
    result = runway.calculate(budget=8100, **BASE)
    curve = result["curve"]

    assert len(curve) == params.HORIZON_MONTHS
    assert [point["month"] for point in curve] == list(
        range(1, params.HORIZON_MONTHS + 1)
    )
    # Ramp reaches steady exactly at ramp_months and stays there.
    for point in curve:
        if point["month"] >= BASE["ramp_months"]:
            assert point["revenue"] == pytest.approx(BASE["revenue_monthly"])
        else:
            assert point["revenue"] < BASE["revenue_monthly"]
    # Depletion implies insufficient coverage — never both "dry" and "covered".
    if result["depletion_month"] is not None and result["coverage"] is not None:
        assert result["coverage"] < params.COVERAGE_DANGER


def test_assumption_rows_only_for_defaults():
    # Everything typed → only the ramp start ratio remains assumed.
    result = runway.calculate(budget=8165, **BASE)
    assert [row["label"] for row in result["assumptions"]] == ["개업 첫 달 매출"]

    # Dropping the typed margin surfaces its assumption row, with a source.
    bare = {key: value for key, value in BASE.items() if key != "margin"}
    result = runway.calculate(budget=8165, **bare)
    labels = [row["label"] for row in result["assumptions"]]
    assert labels == ["마진율", "개업 첫 달 매출"]
    assert all(row["source"] for row in result["assumptions"])


def test_margin_default_matches_economics_default():
    # economics.calculate(margin=0.25) and the runway default must agree, or
    # the money tab contradicts itself between computations.
    import inspect

    from service import economics

    economics_default = inspect.signature(economics.calculate).parameters[
        "margin"
    ].default
    assert params.MARGIN.value == economics_default


def test_http_default_revenue_and_camel_case():
    sample = _sample_grid(sales_available=True)
    response = client.post(
        "/api/runway",
        json={
            "gridId": sample["grid_id"],
            "uptae": sample["uptae"],
            "budget": 15000,
            "upfront": 8000,
            "rentMonthly": 250,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["revenueSource"] in (
        "trade_area_average",
        "seoul_trade_area_average",
    )
    assert body["revenueMonthly"] > 0
    assert len(body["curve"]) == params.HORIZON_MONTHS
    assert body["level"] in ("IMPOSSIBLE", "DANGER", "WARN", "OK")
    assert "workingCapitalNeed" in body
    # Defaulted margin must be visible as a labeled assumption.
    assert any(row["label"] == "마진율" for row in body["assumptions"])


def test_http_unknown_grid_without_revenue_is_404():
    response = client.post(
        "/api/runway",
        json={
            "gridId": "999999_999999",
            "uptae": "한식",
            "budget": 15000,
            "upfront": 8000,
            "rentMonthly": 250,
        },
    )
    assert response.status_code == 404


def test_http_rejects_off_preset_ramp():
    response = client.post(
        "/api/runway",
        json={
            "gridId": "1_1",
            "uptae": "한식",
            "budget": 15000,
            "upfront": 8000,
            "rentMonthly": 250,
            "revenueMonthly": 1000,
            "rampMonths": 5,
        },
    )
    assert response.status_code == 422
