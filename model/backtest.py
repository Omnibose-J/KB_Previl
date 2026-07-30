"""If we had run this recommender in the past, would the shops that followed it
have survived more often?

evaluate.py reports AUC/Brier/lift, which are the right technical measures but
do not answer the question a judge will ask. This restates the same held-out
predictions as the decision they imply: rank every held-out opening
(train.CONFIRMED_TEST_YEARS) by the model, then read off what actually happened
in each served grade.

Nothing new is fitted here - it consumes the same time-split predictions - so it
cannot be more optimistic than the headline numbers. It is a translation, not a
second experiment.
"""
import argparse
import sys

import numpy as np

from pipeline.db import init
from pipeline.grade_bands import GRADE_COUNT, grade_edges, grade_numbers

from .cache import cached_split
from .robustness import FEATURE_SETS
from .train import CONFIRMED_TEST_YEARS, CONFIRMED_TRAIN_YEARS, fit_predict


def grades(y, p):
    y = np.asarray(y)
    assigned = grade_numbers(p, grade_edges(p))
    out = []
    for grade in range(1, GRADE_COUNT + 1):
        segment = assigned == grade
        if not segment.any():
            raise ValueError(f"{grade}등급 표본이 없습니다.")
        out.append((grade, int(segment.sum()), y[segment].mean()))
    return out


def deciles(y, p, k=10):
    """Equal-width rank bins retained for historical recency diagnostics."""
    order = np.argsort(-np.asarray(p))
    y = np.asarray(y)[order]
    n = len(y)
    out = []
    for i in range(k):
        segment = y[int(n * i / k):int(n * (i + 1) / k)]
        out.append((i + 1, len(segment), segment.mean()))
    return out


def calibration(y, p, bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.quantile(p, np.linspace(0, 1, bins + 1))
    rows = []
    for i in range(bins):
        m = (p >= edges[i]) & (p <= edges[i + 1] if i == bins - 1 else p < edges[i + 1])
        if m.sum() < 20:
            continue
        rows.append((p[m].mean(), y[m].mean(), int(m.sum())))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gbm")
    ap.add_argument("--features", default="NUM",
                    help="피처셋 이름 또는 쉼표구분 컬럼명. 헤드라인 계보①는 LOC3")
    a = ap.parse_args()

    cols = FEATURE_SETS.get(a.features) or [c for c in a.features.split(",") if c]
    con = init()
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS, 3)
    Xte, yte, mte = test
    p, _ = fit_predict(a.model, train, test, num=cols)

    overall = yte.mean()
    # 실제로 도는 것은 CONFIRMED_TEST_YEARS 다. evaluate.TEST_YEARS 는 폐기된
    # 2019-2022 legacy 창이라 그걸 찍으면 출력이 코호트를 거짓말한다.
    span = (f"{CONFIRMED_TEST_YEARS[0]}~{CONFIRMED_TEST_YEARS[-1]}"
            if len(CONFIRMED_TEST_YEARS) > 1 else f"{CONFIRMED_TEST_YEARS[0]}")
    print(f"검증 대상: {span}년 개업 {len(yte):,}건 "
          f"· 모델 {a.model} · 피처셋 {a.features}({len(cols)})")
    print(f"실제 3년 생존율(전체): {overall*100:.1f}%\n")

    print("모델 점수 등급별 실제 생존율")
    print(f"  {'등급':<8} {'건수':>7} {'실제 생존율':>12} {'전체 대비':>10}")
    ds = grades(yte, p)
    for i, n, r in ds:
        tag = (
            " ← 1등급"
            if i == 1
            else (f" ← {GRADE_COUNT}등급" if i == GRADE_COUNT else "")
        )
        print(f"  {i:>2}등급   {n:>7,} {r*100:>11.1f}% {r/overall:>9.2f}x{tag}")

    top, bot = ds[0][2], ds[-1][2]
    print(f"\n1등급 {top*100:.1f}%  vs  {GRADE_COUNT}등급 {bot*100:.1f}%"
          f"   격차 {(top-bot)*100:.1f}%p")

    # what a user actually experiences: pick from the top N% of locations
    print("\n실제 사용 시나리오 — 상위 X% 자리에서만 창업했다면")
    for q in (0.05, 0.10, 0.20, 0.30):
        k = int(len(yte) * q)
        idx = np.argsort(-p)[:k]
        r = np.asarray(yte)[idx].mean()
        print(f"  상위 {int(q*100):>2}% ({k:,}건): 생존율 {r*100:.1f}% "
              f"(전체 {overall*100:.1f}% 대비 {(r-overall)*100:+.1f}%p)")

    print("\n확률 보정 — 예측값이 실제와 얼마나 맞는가")
    print(f"  {'예측 평균':>10} {'실제':>10} {'차이':>8} {'건수':>8}")
    for pm, ym_, n in calibration(yte, p):
        print(f"  {pm*100:>9.1f}% {ym_*100:>9.1f}% {(ym_-pm)*100:>+7.1f}%p {n:>8,}")

    print(
        f"\n읽는 법: 1등급이 {GRADE_COUNT}등급보다 높으면 순위가 유효하다. "
        "보정표에서"
    )
    print("        예측 평균과 실제가 벌어지면 확률 절대값은 신뢰하지 말 것.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
