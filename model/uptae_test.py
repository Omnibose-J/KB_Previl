"""I-13 검정 — 텍스트 업종 예측 vs 인허가 uptae. 임계는 §I-13.

점포 단위로 채점한다. 글 단위로 채점하면 글이 많은 가게가 점수를 지배하고,
그것은 §13에서 확인한 존재량 편향이 그대로 들어오는 것이다.

    python -m model.uptae_test
"""
import argparse
import sqlite3
import sys
from collections import Counter, defaultdict

from model.uptae_run import CLASSES, truth
from pipeline.config import DB_PATH

MIN_SHOPS = 500      # §I-13
MIN_PER_CLASS = 20   # §I-13
F1_MIN = 0.40        # §I-13


def main():
    argparse.ArgumentParser().parse_args()
    con = sqlite3.connect(DB_PATH)
    gt = truth(con)

    votes = defaultdict(Counter)
    for place, mg, k in con.execute(
            "SELECT place, mgtno, kind FROM uptae_label WHERE kind IS NOT NULL"):
        votes[(place, mg)][k] += 1
    con.close()

    pairs = []          # (정답, 예측)
    ties = 0
    for key, c in votes.items():
        if key not in gt:
            continue
        top = c.most_common()
        # §I-13 — 동률이면 기권. 기권은 오답으로 처리한다(예측 없음 = 못 맞힘)
        pred = None if (len(top) > 1 and top[0][1] == top[1][1]) else top[0][0]
        if pred is None:
            ties += 1
        pairs.append((gt[key], pred))

    n = len(pairs)
    print(f"채점 점포 {n:,}곳 · 다수결 동률 기권 {ties:,}곳")
    per_class = Counter(t for t, _ in pairs)
    print("\n정답 분포")
    for c in CLASSES:
        print(f"  {c:<10s}{per_class[c]:>6,}")

    short = [c for c in CLASSES if per_class[c] < MIN_PER_CLASS]
    if n < MIN_SHOPS or short:
        why = []
        if n < MIN_SHOPS:
            why.append(f"점포 {n:,} < {MIN_SHOPS}")
        if short:
            why.append(f"클래스당 {MIN_PER_CLASS}곳 미달: {' · '.join(short)}")
        print(f"\n§I-13 최소 표본 미달 — {' / '.join(why)}. 판정 보류")
        return 1

    print(f"\n{'클래스':<10s}{'정밀도':>8s}{'재현율':>8s}{'F1':>8s}{'n':>7s}")
    f1s = []
    for c in CLASSES:
        tp = sum(1 for t, p in pairs if t == c and p == c)
        fp = sum(1 for t, p in pairs if t != c and p == c)
        fn = sum(1 for t, p in pairs if t == c and p != c)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        f1s.append(f1)
        print(f"{c:<10s}{prec:>8.3f}{rec:>8.3f}{f1:>8.3f}{per_class[c]:>7,}")

    macro = sum(f1s) / len(f1s)
    acc = sum(1 for t, p in pairs if t == p) / n
    print(f"\nmacro-F1 {macro:.4f} · accuracy {acc:.4f} · n={n:,}")
    print("참고 베이스라인 — 무작위 0.143 · 최빈(전부 korean) 약 0.06")

    ok = macro >= F1_MIN
    print("\n" + "=" * 60)
    print(f"§I-13 기준 macro-F1 >= {F1_MIN} → {'통과' if ok else '미달'} ({macro:.4f})")
    if ok:
        print("=> 추출 도구가 정답 있는 문제를 푼다. §I-9·§I-11의 정확도 주장에")
        print("   근거로 인용한다. 제품에는 넣지 않는다 — 업태는 인허가에 이미 있다.")
    else:
        print("=> §I-13 대로 §I-9·§I-11 결과에 이 미달을 함께 적는다.")
        print("   같은 도구가 정답 있는 문제에서 실패했다면 정확도 주장이 성립하지 않는다.")
    # 0=통과 · 3=미달 · 1=표본 미달
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
