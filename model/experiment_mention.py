"""Pilot: do blog mentions of EXISTING neighbours predict a new shop's survival?

Same fair-comparison discipline as the trend experiment: one dataset built once
with the mention fields attached, both arms trained on identical rows, only the
feature list differs. Restricted to 마포구, where mentions were collected.

Why this could work where search trends did not: trend data is 행정동-level, so
every cell in a dong shares one value and cell ranking is impossible. Mentions
are collected per shop and aggregated up to the 3x3 ring, so neighbouring cells
genuinely differ. If the resolution argument is right, this is where it shows.

If it does not help, that is the finding - the same as the trend result.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import brier_score_loss, roc_auc_score

from pipeline.db import init

from .evaluate import BASELINES, lift_at_decile, load_split
from .train import NUM, fit_predict

MENTION = ["mention_r1_12m", "famous_r1", "mentioned_shops_r1"]
TRAIN_YEARS = [2013, 2014, 2015, 2016, 2017, 2018]
TEST_YEARS = [2019, 2020, 2021, 2022]
GU = "마포구"


def report(name, y, p):
    auc = roc_auc_score(y, p)
    br = brier_score_loss(y, np.clip(p, 0, 1))
    lf = lift_at_decile(y, p)
    print(f"  {name:<26} AUC {auc:.4f}   Brier {br:.4f}   lift@10% {lf:.3f}")
    return auc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--gu", default=GU)
    ap.add_argument("--min-gain", type=float, default=0.005)
    a = ap.parse_args()

    con = init()
    n_sh = con.execute("SELECT count(*) FROM mention_shop").fetchone()[0]
    print(f"{a.gu} 파일럿 · 언급 수집된 점포 {n_sh:,}개")
    print(f"train {TRAIN_YEARS}  test {TEST_YEARS}\n")

    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, 3, verbose=True,
                             with_mention=True, gu=a.gu)
    Xtr, ytr, _ = train
    Xte, yte, _ = test
    if len(yte) < 500:
        print(f"\n검증 표본이 {len(yte)}건으로 너무 작다 — 결론을 내리지 않는다.")
        return 1

    cov = sum(1 for f in Xte if f.get("mention_r1_12m") is not None) / len(Xte)
    nz = sum(1 for f in Xte if (f.get("mention_r1_12m") or 0) > 0) / len(Xte)
    print(f"\n언급 피처 보유율 {cov*100:.1f}% · 언급>0 비율 {nz*100:.1f}%")

    print(f"\n베이스라인 (test n={len(yte):,}, 실제 생존율 {yte.mean()*100:.1f}%)")
    for nm, fn in BASELINES.items():
        report(nm, yte, fn(Xtr, ytr, Xte))

    print("\n동일 표본 · 동일 모델 · 피처셋만 다름")
    res = {}
    for kind in ("logit", "gbm"):
        for label, cols in (("without mention", NUM), ("with mention", NUM + MENTION)):
            p, _ = fit_predict(kind, train, test, num=cols)
            res[(kind, label)] = report(f"{kind} {label}", yte, p)

    print("\n언급 피처 추가 효과")
    ok = False
    for kind in ("logit", "gbm"):
        d = res[(kind, "with mention")] - res[(kind, "without mention")]
        print(f"  {kind:<6} AUC {res[(kind,'without mention')]:.4f} -> "
              f"{res[(kind,'with mention')]:.4f}   ({d:+.4f})")
        ok = ok or d >= a.min_gain

    print()
    if ok:
        print(f"-> 점포 단위 언급이 예측력을 높였다 (기준 +{a.min_gain}). "
              "해상도 가설이 지지된다.")
    else:
        print(f"-> 유의한 개선 없음 (기준 +{a.min_gain}). 트렌드와 동일하게 기록한다 "
              "— 튜닝으로 뒤집지 않는다.")

    from .train import weights
    pairs, _, _ = weights(train, top=60, num=NUM + MENTION)
    mt = [(n, c) for n, c in pairs if n in MENTION]
    if mt:
        print("\n언급 피처 계수 (양수=생존↑)")
        for n, c in mt:
            print(f"  {n:<22} {c:>+8.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
