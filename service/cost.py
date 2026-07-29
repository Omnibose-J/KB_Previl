"""Deterministic effective occupancy cost calculations."""

from dataclasses import dataclass
import math

from service.bands import _percentile


@dataclass(frozen=True)
class CostParams:
    opportunity_rate: float = 0.04
    horizon_months: int = 36
    include_maintenance: bool = True

    def __post_init__(self):
        if not math.isfinite(self.opportunity_rate) or self.opportunity_rate < 0:
            raise ValueError("opportunity_rate must be non-negative")
        if self.horizon_months <= 0:
            raise ValueError("horizon_months must be positive")


@dataclass(frozen=True)
class CostBreakdown:
    rent: float
    maintenance: float
    deposit_opportunity: float
    premium_amortized: float
    effective_monthly_cost: float


@dataclass(frozen=True)
class CostBand:
    low: float
    high: float


def effective_monthly_cost(
    deposit: float,
    monthly_rent: float,
    maintenance_fee: float,
    premium: float,
    recovery_prob: float,
    params: CostParams = CostParams(),
) -> CostBreakdown:
    """Return the monthly cost of occupying one candidate property."""

    if not 0 <= recovery_prob <= 1:
        raise ValueError("recovery_prob must be between 0 and 1")

    try:
        maintenance = maintenance_fee if params.include_maintenance else 0
        deposit_opportunity = deposit * params.opportunity_rate / 12
        premium_amortized = (
            premium * (1 - recovery_prob) / params.horizon_months
        )
        total = (
            monthly_rent
            + maintenance
            + deposit_opportunity
            + premium_amortized
        )
    except OverflowError as exc:
        raise ValueError("cost calculation must remain finite") from exc
    if not all(
        math.isfinite(value)
        for value in (
            maintenance,
            deposit_opportunity,
            premium_amortized,
            total,
        )
    ):
        raise ValueError("cost calculation must remain finite")
    return CostBreakdown(
        rent=monthly_rent,
        maintenance=maintenance,
        deposit_opportunity=deposit_opportunity,
        premium_amortized=premium_amortized,
        effective_monthly_cost=total,
    )


def effective_monthly_cost_band(
    deposit: float,
    monthly_rent: float,
    maintenance_fee: float,
    premium: float,
    succession_prob: float | None,
    params: CostParams = CostParams(),
) -> CostBand:
    """Return the 5th/95th percentile across the approved uncertainty grid."""

    if succession_prob is None:
        recovery_grid = {0.0}
    else:
        if not math.isfinite(succession_prob) or not 0 <= succession_prob <= 1:
            raise ValueError("succession_prob must be between 0 and 1")
        recovery_grid = {0.0, succession_prob / 2, succession_prob}
    horizon_grid = {
        max(1, params.horizon_months - 12),
        params.horizon_months,
        params.horizon_months + 12,
    }
    opportunity_grid = {
        max(0.0, params.opportunity_rate - 0.01),
        params.opportunity_rate,
        params.opportunity_rate + 0.01,
    }

    costs = []
    for recovery_prob in sorted(recovery_grid):
        for horizon_months in sorted(horizon_grid):
            for opportunity_rate in sorted(opportunity_grid):
                varied_params = CostParams(
                    opportunity_rate=opportunity_rate,
                    horizon_months=horizon_months,
                    include_maintenance=params.include_maintenance,
                )
                costs.append(
                    effective_monthly_cost(
                        deposit=deposit,
                        monthly_rent=monthly_rent,
                        maintenance_fee=maintenance_fee,
                        premium=premium,
                        recovery_prob=recovery_prob,
                        params=varied_params,
                    ).effective_monthly_cost
                )
    return CostBand(
        low=_percentile(costs, 0.05),
        high=_percentile(costs, 0.95),
    )
