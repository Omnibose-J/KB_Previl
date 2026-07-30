"""A2 — margin sensitivity. Contract: docs/experiment-plan.md A1·A2.

The expected-profit number in section 6-C is dominated by one assumption nobody
can measure per shop: the pre-rent margin. This prints the 3x3 the UI needs to
be honest about that - three margins against three location grades - so cells
whose SIGN flips between margins can be badged "assumption-sensitive" rather
than shown as a figure.

A1 (Wilson intervals per grade) is not here on purpose: it is computed inside
service/precompute.py off the same grade segmentation that produces the point
estimate, so a rate and its interval cannot come from different splits.
"""
import argparse
import sys

from pipeline.db import init
from pipeline.grade_bands import GRADE_COUNT

from .economics import DEFAULT_PRE_RENT_MARGIN, survival_curve, scenario

MARGINS = (0.20, 0.25, 0.30)
GRADES = {grade: f"{grade}등급" for grade in (1, 5, GRADE_COUNT)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sales", type=float, default=2226, help="월 매출 (만원)")
    ap.add_argument("--rent", type=float, default=300)
    ap.add_argument("--upfront", type=float, default=8000)
    a = ap.parse_args()

    con = init()
    curves, _ = survival_curve(con)
    print(f"A2 마진 민감도 — 매출 {a.sales:,.0f}만/월 · 임대료 {a.rent:,.0f}만 · "
          f"초기투자 {a.upfront:,.0f}만 (기본 마진 {DEFAULT_PRE_RENT_MARGIN:.0%})")
    print("  3년 기대손익 (만원) — 실측 생존곡선 S(t) 적용\n")
    print(f"  {'입지등급':<14} " + " ".join(f"{m:>12.0%}" for m in MARGINS) + "   36개월 생존")
    flip = []
    for g, label in GRADES.items():
        c = curves.get(g)
        if not c:
            continue
        vals = [scenario(a.sales, m, a.upfront, a.rent, c)["expected"] for m in MARGINS]
        signs = {v > 0 for v in vals}
        if len(signs) > 1:
            flip.append(label)
        print(f"  {label:<14} " + " ".join(f"{v:>+12,.0f}" for v in vals)
              + f"   {c[-1]*100:>9.1f}%")
    print("\n  부호가 바뀌는 등급 (UI '가정에 민감' 배지 대상): "
          + (", ".join(flip) or "없음"))
    print("  * 마진은 임대료 차감 전 값. 공표 영업이익률(10~15%)은 임대료가 이미 빠져 있어")
    print("    그대로 넣으면 임대료를 두 번 빼게 된다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
