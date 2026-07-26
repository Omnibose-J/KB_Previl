"""Stage 1 — fix the data before anything else. Contract: docs/experiment-plan.md E1·E2.

E1 asks whether reaching back to 2005 buys anything; E2 asks whether dropping
suspected handovers cleans the label. Both are judged with the CURRENT gbm as a
probe, never with a new model - moving the data and the model at once makes the
result unattributable.

Pre-registered thresholds live in the plan and are echoed here as constants so a
reader can see what the run was judged against without leaving the file. They are
not to be edited after a run.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .cache import cached_split
from .evaluate import TEST_YEARS, TRAIN_YEARS, baseline_prior_surv
from .train import LOC2, LOC3, fit_predict

E1_MIN_GAIN = 0.005          # LOC2(2005-) - LOC2(2013-), holdout AUC
E2_MIN_EDGE = 0.0350         # (model - prior_surv) AUC edge must not fall below this
EARLY_YEARS = list(range(2005, 2019))
PROBE = "gbm"

# Internal validation = the last two years of train. The plan forbids settling the
# "wide period without access" vs "current period with access" choice on the
# holdout: that choice is a selection, and selections made on the holdout turn it
# into a validation set. Both candidates are scored on the SAME 2017-2018 rows.
INNER_TEST = [2017, 2018]
INNER_TRAIN_WIDE = list(range(2005, 2017))
INNER_TRAIN_CUR = list(range(2013, 2017))


def deciles(y, p, k=10):
    order = np.argsort(-np.asarray(p))
    y = np.asarray(y)[order]
    n = len(y)
    return [float(y[int(n * i / k):int(n * (i + 1) / k)].mean()) for i in range(k)]


def run(con, train_years, cols, exclude_succession=False, label="", test_years=None):
    """Fit the probe on one (period, feature set, label) and report its scores."""
    train, test = cached_split(con, train_years, test_years or TEST_YEARS, 3,
                               exclude_succession=exclude_succession)
    p, _ = fit_predict(PROBE, train, test, num=cols)
    yte = test[1]
    d = deciles(yte, p)
    auc = roc_auc_score(yte, p)
    prior = roc_auc_score(yte, baseline_prior_surv(train[0], train[1], test[0]))
    mono = all(d[i] >= d[i + 1] - 0.02 for i in range(9))
    print(f"  {label:<34} AUC {auc:.4f}  상위10% {d[0]*100:.1f}%  하위10% {d[-1]*100:.1f}%  "
          f"prior_surv {prior:.4f}  단조 {'O' if mono else 'X'}  n_tr={len(train[1]):,}")
    return {"auc": auc, "top": d[0], "bot": d[-1], "prior": prior,
            "edge": auc - prior, "mono": mono, "dec": d}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="e1 | e2 | combo")
    a = ap.parse_args()
    con = init()
    want = a.only or "e1,e2,combo"

    res = {}
    if "e1" in want or "combo" in want:
        print("\n" + "=" * 78)
        print("E1. 학습 기간 확대 2013->2005 — 비교는 LOC2끼리 (접근성 제외)")
        print("    이유: asof.py에 노선 개통일 처리가 없어 2005년 개업 점포에 미래 역이 샌다")
        res["e1_base"] = run(con, TRAIN_YEARS, LOC2, label="LOC2 · train 2013-2018 (기준)")
        res["e1_wide"] = run(con, EARLY_YEARS, LOC2, label="LOC2 · train 2005-2018 (확대)")
        g = res["e1_wide"]["auc"] - res["e1_base"]["auc"]
        drop = res["e1_wide"]["top"] - res["e1_base"]["top"]
        ok = g >= E1_MIN_GAIN and drop >= 0
        print(f"\n  ΔAUC {g:+.4f} (요구 +{E1_MIN_GAIN})  ·  상위10% {drop*100:+.1f}%p (요구 하락 없음)")
        print(f"  -> E1 {'채택' if ok else '기각'}")
        res["e1_ok"] = ok

        if ok:
            print("\n  세트 선택 (내부 검증 2017-2018 — 홀드아웃으로 고르지 않는다)")
            w = run(con, INNER_TRAIN_WIDE, LOC2, test_years=INNER_TEST,
                    label="LOC2 · train 2005-2016")
            c = run(con, INNER_TRAIN_CUR, LOC3, test_years=INNER_TEST,
                    label="LOC3 · train 2013-2016")
            res["pick"] = "LOC2_WIDE" if w["auc"] > c["auc"] else "LOC3_CUR"
            print(f"\n  내부검증 ΔAUC {w['auc'] - c['auc']:+.4f} -> Stage 2 확정 세트: {res['pick']}")

    if "e2" in want or "combo" in want:
        print("\n" + "=" * 78)
        print("E2. 승계(양도양수) 제외 라벨 — succession_suspect 행 삭제")
        print("    2x2 중 신라벨 위 비교만 유효. 베이스라인 동반 재계산.")
        res["e2_old"] = run(con, TRAIN_YEARS, LOC3, label="구라벨 · LOC3 (기준)")
        res["e2_new"] = run(con, TRAIN_YEARS, LOC3, exclude_succession=True,
                            label="신라벨 · LOC3")
        e = res["e2_new"]["edge"]
        ok = e >= E2_MIN_EDGE and res["e2_new"]["mono"]
        print(f"\n  신라벨 (모델 - prior_surv) 격차 {e:.4f} (요구 >= {E2_MIN_EDGE})"
              f"  ·  구라벨 격차 {res['e2_old']['edge']:.4f}")
        print(f"  -> E2 {'채택' if ok else '기각'}")
        res["e2_ok"] = ok

    if "combo" in want and res.get("e1_ok") and res.get("e2_ok"):
        print("\n" + "=" * 78)
        print("E1+E2 결합 확인 — 개별 통과 둘이 결합 개선을 보장하지 않는다")
        res["combo"] = run(con, EARLY_YEARS, LOC2, exclude_succession=True,
                           label="LOC2 · 2005-2018 · 신라벨")
    elif "combo" in want:
        print("\n결합 확인 생략 — E1·E2 중 하나 이상 기각")
    return 0


if __name__ == "__main__":
    sys.exit(main())
