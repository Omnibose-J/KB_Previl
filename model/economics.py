"""Payback scenario that prices in the risk of not surviving.

The usual break-even calculation divides upfront cost by monthly profit and
stops there. It implicitly assumes the shop is still open when the money comes
back, which is exactly the assumption this project can test: 3-year survival in
Seoul is 61.7% overall and ranges from 37.7% to 77.0% depending on the location
grade. A 30-month break-even means something very different at each end.

So the expected recovery here is
    Σ_t  S(t) × monthly_profit  −  upfront
where S(t) is the MEASURED survival curve of shops in that location grade, not
an assumed one. Two locations with identical rent and identical sales can differ
by tens of millions in expected recovery purely through S(t).

Rent is a user input rather than a data field: 한국부동산원 publishes rents for
368 nationwide areas, one value covering 200+ of our cells, which is useless at
this resolution. The person asking already knows the rent of the unit they are
looking at, and using their number is both more accurate and more honest than
imputing one.
"""
import argparse
import sys
from collections import defaultdict

import numpy as np

from pipeline.db import init

from .asof import ym
from .evaluate import TEST_YEARS, TRAIN_YEARS, load_split
from .train import NUM, fit_predict

# Margin BEFORE rent, not operating margin. The published 음식점업 operating
# margin (~10-15%) already has rent deducted; subtracting rent again on top of
# it double-counts and turned a viable shop into a loss-maker in the first run
# of this file. Pre-rent margin = 1 − 재료비(~35%) − 인건비(~25%) − 기타(~15%),
# so roughly 25%. Rent is then subtracted explicitly because it is the term
# that varies by location, which is the whole point of the comparison.
DEFAULT_PRE_RENT_MARGIN = 0.25

HORIZON_M = 36


def survival_curve(con, decile_of_interest=None, months=HORIZON_M):
    """Measured S(t): share of a cohort still open t months after opening.

    Computed per location grade using held-out predictions, so the curve for
    "top 10%" reflects shops that a model trained on earlier years would have
    ranked top 10% - not hindsight.
    """
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, 3, verbose=False)
    Xte, yte, mte = test
    loc_cols = [c for c in NUM if c != "site_area"]
    p, _ = fit_predict("gbm", train, test, num=loc_cols)

    order = np.argsort(-p)
    n = len(p)
    grade_of = {}
    edges = []
    for i in range(10):
        seg = order[int(n * i / 10):int(n * (i + 1) / 10)]
        edges.append(p[seg].min())
        for j in seg:
            grade_of[j] = i + 1

    # duration in months for each test shop
    rows = {r["mgtno"]: r for r in ()}
    dur = []
    for i, m in enumerate(mte):
        dur.append(None)
    # recompute durations from the licence table keyed by (grid, open_ym)
    lic = defaultdict(list)
    for r in con.execute(
            "SELECT grid_id, open_y, open_m, close_y, close_m, is_closed "
            "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL"):
        o = ym(r["open_y"], r["open_m"])
        c = ym(r["close_y"], r["close_m"]) if (r["is_closed"] and r["close_y"]) else None
        lic[(r["grid_id"], o)].append(c)

    by_grade = defaultdict(list)
    for i, m in enumerate(mte):
        key = (m["grid_id"], m["open_ym"])
        cands = lic.get(key)
        if not cands:
            continue
        c = cands[0]
        d = (c - m["open_ym"]) if c is not None else None
        by_grade[grade_of[i]].append(d)

    curves = {}
    for g, ds in by_grade.items():
        if len(ds) < 200:
            continue
        tot = len(ds)
        curves[g] = [sum(1 for d in ds if d is None or d > t) / tot
                     for t in range(months + 1)]
    return curves, edges


def scenario(monthly_sales, margin, upfront, monthly_rent, curve, months=HORIZON_M):
    profit = monthly_sales * margin - monthly_rent
    naive_be = (upfront / profit) if profit > 0 else None
    expected = sum(curve[t] * profit for t in range(1, months + 1)) - upfront
    certain = profit * months - upfront
    # month at which cumulative EXPECTED profit covers upfront
    cum = 0.0
    risk_be = None
    for t in range(1, months + 1):
        cum += curve[t] * profit
        if risk_be is None and cum >= upfront:
            risk_be = t
    return {"profit": profit, "naive_be": naive_be, "risk_be": risk_be,
            "expected": expected, "certain": certain,
            "survive_36m": curve[months]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uptae-cd", default="CS100001", help="CS100001 한식 등")
    ap.add_argument("--grade", type=int, help="입지 등급 1(상위10%)~10")
    ap.add_argument("--rent", type=float, required=True, help="월 임대료 (만원)")
    ap.add_argument("--upfront", type=float, required=True,
                    help="초기투자 = 보증금+권리금+인테리어+집기 (만원)")
    ap.add_argument("--sales", type=float, help="월 예상매출 (만원). 생략시 상권평균")
    ap.add_argument("--margin", type=float, default=DEFAULT_PRE_RENT_MARGIN,
                    help="임대료 차감 전 마진 (기본 0.25)")
    a = ap.parse_args()

    con = init()
    if a.sales is None:
        r = con.execute(
            "SELECT AVG(s.sales_amt/NULLIF(t.stor_co,0))/3.0 FROM trdar_sales s "
            "JOIN trdar_store t ON s.trdar_cd=t.trdar_cd AND s.induty_cd=t.induty_cd "
            "AND s.quarter=t.quarter WHERE s.quarter='20261' AND s.induty_cd=? "
            "AND t.stor_co>0", (a.uptae_cd,)).fetchone()[0]
        sales = (r or 0) / 1e4
        print(f"월 예상매출: 서울 상권 평균 {sales:,.0f}만원 ({a.uptae_cd})")
        print("  * 상권별 편차가 크다. 실제 후보지의 값을 알면 --sales 로 넣을 것")
    else:
        sales = a.sales

    curves, _ = survival_curve(con)
    grades = [a.grade] if a.grade else [1, 5, 10]

    print(f"\n조건: 매출 {sales:,.0f}만/월 · 임대료전 마진 {a.margin*100:.0f}% · "
          f"임대료 {a.rent:,.0f}만/월 · 초기투자 {a.upfront:,.0f}만")
    print(f"월 순이익 = {sales:,.0f} x {a.margin:.2f} - {a.rent:,.0f} = "
          f"{sales*a.margin - a.rent:,.0f}만원\n")

    print(f"  {'입지등급':<12} {'36개월 생존':>10} {'단순 회수':>10} "
          f"{'위험반영 회수':>12} {'3년 기대손익':>13}")
    for g in grades:
        c = curves.get(g)
        if not c:
            continue
        s = scenario(sales, a.margin, a.upfront, a.rent, c)
        label = {1: "상위 10%", 5: "중간(5분위)", 10: "하위 10%"}.get(g, f"{g}분위")
        nb = f"{s['naive_be']:.0f}개월" if s["naive_be"] else "회수불가"
        rb = f"{s['risk_be']}개월" if s["risk_be"] else "36개월내 불가"
        print(f"  {label:<12} {s['survive_36m']*100:>9.1f}% {nb:>10} {rb:>12} "
              f"{s['expected']:>+12,.0f}만")

    print("\n읽는 법")
    print(" · 단순 회수: 3년간 계속 영업한다고 가정한 손익분기 시점")
    print(" · 위험반영 회수: 실측 생존곡선 S(t)를 곱한 기대이익 누적이 초기투자를 넘는 시점")
    print(" · 두 값의 차이가 곧 '입지 위험의 가격'이다")
    print(" · 마진은 임대료 '차감 전' 값이다(기본 25%). 공표되는 영업이익률(10~15%)은")
    print("   이미 임대료가 빠진 수치라 그대로 쓰면 임대료를 두 번 빼게 된다")
    print(" · 마진 가정이 결과를 가장 크게 좌우한다(--margin 으로 조정)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
