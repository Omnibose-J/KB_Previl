"""Does location matter independently of shop size?

Shop area alone reaches AUC 0.6227, so any headline number that mixes the two
is really reporting "bigger shops last longer". The question that decides
whether a location recommender has a reason to exist is narrower:

    among shops of the SAME size, does the location ranking still separate
    survivors from failures?

That is a stratified comparison - hold the confounder fixed, vary the thing
being tested. If the lift survives inside every size band, location carries
information size does not, and the weights are worth something. If it collapses
in the bands, the model was a proxy for capital all along.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .cache import cached_split
from .evaluate import TEST_YEARS
from .train import CONFIRMED_TRAIN_YEARS, DEPLOY, WINNER, fit_predict

BANDS = [(0, 25), (25, 37), (37, 56), (56, 90), (90, 10**6)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--q", type=float, default=0.20, help="상위 몇 %를 볼지")
    a = ap.parse_args()

    con = init()
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, TEST_YEARS, 3)
    Xte, yte, _ = test

    # rank on location only - size is the variable being controlled, not used
    loc_cols = list(DEPLOY)
    p, _ = fit_predict(WINNER, train, test, num=loc_cols)

    areas = np.array([f["site_area"] or 0 for f in Xte], dtype=float)

    print(f"변인통제: 점포 면적을 구간으로 고정하고, 그 안에서 입지 순위만으로 비교")
    print(f"순위 피처: 면적 제외 {len(loc_cols)}개\n")
    print(f"  {'면적 구간':<14} {'건수':>7} {'구간 생존율':>11} "
          f"{'상위'+str(int(a.q*100))+'% 생존':>12} {'차이':>8} {'AUC':>8}")

    gains = []
    for lo, hi in BANDS:
        m = (areas >= lo) & (areas < hi)
        if m.sum() < 300:
            continue
        yy, pp = yte[m], p[m]
        k = max(1, int(len(yy) * a.q))
        idx = np.argsort(-pp)[:k]
        top = yy[idx].mean()
        base = yy.mean()
        auc = roc_auc_score(yy, pp) if len(set(yy.tolist())) > 1 else float("nan")
        gains.append(top - base)
        label = f"{lo}~{hi}㎡" if hi < 10**6 else f"{lo}㎡ 이상"
        print(f"  {label:<14} {m.sum():>7,} {base*100:>10.1f}% {top*100:>11.1f}% "
              f"{(top-base)*100:>+7.1f}%p {auc:>8.4f}")

    print(f"\n  구간별 개선폭 평균 {np.mean(gains)*100:+.1f}%p · "
          f"최소 {min(gains)*100:+.1f}%p · 최대 {max(gains)*100:+.1f}%p")
    if min(gains) > 0.02:
        print("  -> 모든 면적 구간에서 입지 순위가 작동한다. 입지는 규모와 독립적으로")
        print("     정보를 갖는다 — 가중치는 자본력의 대리변수가 아니다.")
    else:
        print("  -> 일부 구간에서 개선이 사라진다. 그 구간에서는 입지 신호가 약하다.")

    # same test, but sliced by 업태 as a second control
    print(f"\n업태를 고정했을 때 (2차 통제)")
    print(f"  {'업태':<16} {'건수':>7} {'생존율':>9} {'상위'+str(int(a.q*100))+'%':>9} {'차이':>8}")
    from collections import defaultdict
    by_u = defaultdict(list)
    for i, f in enumerate(Xte):
        by_u[f["uptae"]].append(i)
    for u, idxs in sorted(by_u.items(), key=lambda kv: -len(kv[1]))[:6]:
        idx = np.array(idxs)
        yy, pp = yte[idx], p[idx]
        k = max(1, int(len(yy) * a.q))
        top = yy[np.argsort(-pp)[:k]].mean()
        print(f"  {u:<16} {len(idx):>7,} {yy.mean()*100:>8.1f}% {top*100:>8.1f}% "
              f"{(top-yy.mean())*100:>+7.1f}%p")

    # size x location interaction: is a good location worth more when small?
    print(f"\n면적 x 입지 상호작용 — 작은 가게일수록 입지가 더 중요한가")
    for lo, hi in BANDS:
        m = (areas >= lo) & (areas < hi)
        if m.sum() < 300:
            continue
        yy, pp = yte[m], p[m]
        k = max(1, int(len(yy) * 0.10))
        top = yy[np.argsort(-pp)[:k]].mean()
        bot = yy[np.argsort(pp)[:k]].mean()
        label = f"{lo}~{hi}㎡" if hi < 10**6 else f"{lo}㎡ 이상"
        print(f"  {label:<14} 상위10% {top*100:>5.1f}%  하위10% {bot*100:>5.1f}%  "
              f"격차 {(top-bot)*100:>5.1f}%p")
    return 0


if __name__ == "__main__":
    sys.exit(main())
