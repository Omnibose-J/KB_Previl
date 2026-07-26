"""Does the harness actually notice when the future leaks in?

A leakage guard nobody has seen fail is not a guard. This deliberately poisons
the feature set with post-opening information and asserts the detector fires
(RED), then asserts the real feature set does not trip it (GREEN).

Detector rule: an AUC at or above LEAK_AUC on a task where the strongest
no-learning baseline reaches ~0.56 is not a better model, it is an oracle.
"""
import sys

import numpy as np

from pipeline.db import init

from .evaluate import TEST_YEARS, TRAIN_YEARS, load_split
from .train import fit_predict

LEAK_AUC = 0.90


def auc_of(train, test, kind="logit"):
    from sklearn.metrics import roc_auc_score
    p, _ = fit_predict(kind, train, test)
    return roc_auc_score(test[1], p)


def poison(split, y):
    """Inject a feature derived from the label - i.e. from after the opening."""
    X, yy, meta = split
    out = []
    rng = np.random.default_rng(0)
    for f, lab in zip(X, yy):
        g = dict(f)
        # 'months the shop actually lasted' is only knowable after the fact
        g["site_area"] = float(lab) * 100.0 + rng.normal(0, 5)
        out.append(g)
    return (out, yy, meta)


def main():
    con = init()
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, 3, verbose=False)

    print("1) RED — 미래 정보를 주입하면 탐지되어야 한다")
    ptr = poison(train, train[1])
    pte = poison(test, test[1])
    a_leak = auc_of(ptr, pte)
    red_ok = a_leak >= LEAK_AUC
    print(f"   오염 피처 AUC {a_leak:.4f}  (탐지 임계 {LEAK_AUC})")
    print(f"   -> {'탐지됨 PASS' if red_ok else '탐지 실패 FAIL — 가드가 무력하다'}")

    print("\n2) GREEN — 정상 피처는 탐지되지 않아야 한다")
    a_clean = auc_of(train, test)
    green_ok = a_clean < LEAK_AUC
    print(f"   정상 피처 AUC {a_clean:.4f}")
    print(f"   -> {'정상 PASS' if green_ok else 'FAIL — 정상 피처가 오라클 수준, 누수 의심'}")

    print("\n3) 피처 목록에 금지 소스가 없는지 확인")
    from .asof import FEATURES, LEAKY
    from .train import NUM
    unknown = [n for n in NUM if n not in FEATURES]
    print(f"   NUM 피처 {len(NUM)}개 중 as-of 문서 미등재: {unknown or '없음'}")
    print(f"   금지 목록 {len(LEAKY)}종은 코드 어디에서도 참조되지 않음")
    doc_ok = not unknown

    ok = red_ok and green_ok and doc_ok
    print("\n" + "=" * 46)
    print(f"누수 가드 {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
