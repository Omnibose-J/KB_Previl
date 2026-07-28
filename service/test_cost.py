"""Contract tests for deterministic occupancy cost calculations."""

import pytest

from service.cost import CostParams, effective_monthly_cost


SPEC_CASES = {
    "A": {
        "deposit": 50_000_000,
        "monthly_rent": 2_500_000,
        "premium": 120_000_000,
        "recovery_prob": 0.25,
        "expected": 5_166_667,
    },
    "B": {
        "deposit": 30_000_000,
        "monthly_rent": 3_800_000,
        "premium": 20_000_000,
        "recovery_prob": 0.60,
        "expected": 4_122_222,
    },
    "C": {
        "deposit": 40_000_000,
        "monthly_rent": 3_100_000,
        "premium": 60_000_000,
        "recovery_prob": 0.40,
        "expected": 4_233_333,
    },
}


@pytest.mark.parametrize("case", SPEC_CASES.values(), ids=SPEC_CASES)
def test_spec_case(case):
    result = effective_monthly_cost(
        deposit=case["deposit"],
        monthly_rent=case["monthly_rent"],
        maintenance_fee=0,
        premium=case["premium"],
        recovery_prob=case["recovery_prob"],
    )

    assert result.effective_monthly_cost == pytest.approx(
        case["expected"],
        abs=1,
    )


def test_rank_reversal():
    rows = {
        name: effective_monthly_cost(
            deposit=case["deposit"],
            monthly_rent=case["monthly_rent"],
            maintenance_fee=0,
            premium=case["premium"],
            recovery_prob=case["recovery_prob"],
        )
        for name, case in SPEC_CASES.items()
    }

    assert sorted(rows, key=lambda name: rows[name].rent) == ["A", "C", "B"]
    assert sorted(
        rows,
        key=lambda name: rows[name].effective_monthly_cost,
    ) == ["B", "C", "A"]


@pytest.mark.parametrize(
    ("deposit", "premium", "recovery_prob", "expected"),
    (
        (0, 0, 0, 1_000_000),
        (10_000_000, 0, 0, 1_033_333.333333),
        (0, 36_000_000, 0, 2_000_000),
        (0, 36_000_000, 1, 1_000_000),
    ),
)
def test_boundary(deposit, premium, recovery_prob, expected):
    result = effective_monthly_cost(
        deposit=deposit,
        monthly_rent=1_000_000,
        maintenance_fee=0,
        premium=premium,
        recovery_prob=recovery_prob,
    )

    assert result.effective_monthly_cost == pytest.approx(expected)


def test_boundary_rejects_non_finite_result():
    with pytest.raises(ValueError, match="finite"):
        effective_monthly_cost(
            deposit=1.79e308,
            monthly_rent=1.79e308,
            maintenance_fee=0,
            premium=1.79e308,
            recovery_prob=0.4,
        )


def test_cost_params_can_be_overridden():
    result = effective_monthly_cost(
        deposit=12_000_000,
        monthly_rent=1_000_000,
        maintenance_fee=100_000,
        premium=12_000_000,
        recovery_prob=0,
        params=CostParams(
            opportunity_rate=0.12,
            horizon_months=12,
            include_maintenance=False,
        ),
    )

    assert result.deposit_opportunity == 120_000
    assert result.premium_amortized == 1_000_000
    assert result.maintenance == 0
    assert result.effective_monthly_cost == 2_120_000
