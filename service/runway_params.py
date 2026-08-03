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

import json
from dataclasses import dataclass
from pathlib import Path


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

# ── 공정위 창업비용 힌트 (scripts/franchise_costs.py --fetch 가 생성) ────────
# 값 = 가맹비+교육비+기타(인테리어 등). 가맹보증금은 이중계상이라, 임대보증금·
# 권리금은 통계 범위 밖이라 빠져 있다 — 라벨이 반드시 «보증금·권리금 제외»를
# 함께 말한다. 계산에는 절대 섞이지 않는 표시 전용 참고값이다.
UPFRONT_HELPER_PATH = Path(__file__).resolve().parent / "data" / "franchise_costs.json"


def upfront_helper():
    """{uptae: {value, year, label, proxy}} 또는 (파일 없음) 빈 dict.

    파일 부재는 «아직 안 받은 상태»라는 정상 답이라 조용히 빈 힌트가 된다.
    있는데 깨졌으면 그대로 예외를 올린다 — 손상은 침묵으로 덮지 않는다."""
    try:
        payload = json.loads(UPFRONT_HELPER_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    year = payload["year"]
    out = {}
    for uptae, h in payload["helpers"].items():
        label = f"공정위 {year} 가맹 평균 · 보증금·권리금 제외"
        if h["proxy"]:
            label += f" · {h['sourceIndustry']} 업종으로 대신 봄"
        out[uptae] = {
            "value": float(h["value"]),
            "year": int(year),
            "label": label,
            "proxy": bool(h["proxy"]),
        }
    return out
