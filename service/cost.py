"""Deterministic effective occupancy cost calculations."""

from dataclasses import dataclass
import math


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
