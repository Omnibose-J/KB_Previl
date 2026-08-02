"""Operating-capital runway parameters.

The simulation reuses the product's existing margin concept (margin before
rent, default 0.25 — must stay equal to economics.calculate's default so the
two computations never disagree about steady-state monthly profit).

Ramp-up has no public source (trade-area sales are aggregates, not per-store
trajectories), so it ships as an interview-pending assumption; the screen
exposes ramp_months as a 3/6/9 preset so the user owns that choice.

Units: 만원. `source` strings are user-facing (Korean) — they render in the
assumption captions on screen.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Param:
    value: float
    source: str


# Same semantics and default as economics.calculate(margin=0.25): revenue ×
# margin − rent = monthly profit. Do not put a gross margin (재료비만 뺀 값,
# ~0.63) here — it would overstate profit by the labor/utility share.
MARGIN = Param(
    value=0.25,
    source="기본 마진율 — 임대료 빼기 전, 손익 계산과 같은 값",
)

START_RATIO = Param(
    value=0.45,
    source="가정 — 첫 달 매출을 안정기의 45%로 시작 (인터뷰 확보 전)",
)
RAMP_MONTHS_DEFAULT = 6
RAMP_MONTHS_CHOICES = (3, 6, 9)

HORIZON_MONTHS = 24

# Policy thresholds (spec): coverage = 여유자금 ÷ 필요 운전자본.
COVERAGE_WARN = 1.3
COVERAGE_DANGER = 1.0
