"""§I-19 PR 1 채점 — gripe positive precision.

정확 = `visit and target and <해당 범주 true>`. 세 조건을 모두 만족해야 1차가
붙인 그 라벨이 맞았다고 본다. 주 추정량은 **두 판정자가 모두 정확이라고 한 비율**
(§I-19, 보수적인 쪽).

    python scripts/precision_score.py
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

D = Path(__file__).resolve().parent.parent / "scratch_precision"
CATS = ("wait", "seat", "service", "clean", "price", "noise", "parking")
P_MIN, WILSON_MIN, KAPPA_MIN = 0.70, 0.50, 0.40      # §I-19


def wilson(k, n, z=1.96):
    if not n:
        return 0.0, 1.0
    p, d = k / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - h) / d, (c + h) / d


def kappa(a, b):
    n = len(a)
    if not n:
        return float("nan")
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else float("nan")


def load(tag):
    out = {}
    for b in (1, 2, 3, 4):
        f = D / f"out_b{b}_{tag}.json"
        if f.exists():
            out.update(json.loads(f.read_text(encoding="utf-8-sig")))
    return out


def correct(j, cat):
    """정확 판정. target 이 null 이면 대상 확인 실패로 본다."""
    return bool(j.get("visit")) and bool(j.get("target")) and bool(j.get(cat))


def main():
    truth = json.loads((D / "truth.json").read_text(encoding="utf-8"))
    A, B = load("A"), load("B")
    have = set(A) & set(B)
    pairs = [(pid, c) for pid, cs in truth.items() if pid in have for c in cs]
    n_reg = sum(len(v) for v in truth.values())
    print(f"등록 표본 {n_reg}쌍 · 두 판정자 모두 판정한 글 {len(have)}/{len(truth)} "
          f"→ 채점 가능 {len(pairs)}쌍")
    missing = sorted(set(truth) - have)
    if missing:
        print(f"  미판정 글 {len(missing)}건 — 부분 집계")

    print(f"\n{'범주':<9}{'n':>5}{'정밀도':>9}{'Wilson95':>16}"
          f"{'A만':>7}{'B만':>7}{'kappa':>8}  판정")
    rows = {}
    for c in CATS:
        sub = [p for p in pairs if p[1] == c]
        if not sub:
            continue
        ca = [1 if correct(A[p], c) else 0 for p, _ in sub]
        cb = [1 if correct(B[p], c) else 0 for p, _ in sub]
        both = sum(1 for x, y in zip(ca, cb) if x and y)
        n = len(sub)
        p = both / n
        lo, hi = wilson(both, n)
        k = kappa(ca, cb)
        measurable = not math.isnan(k) and k >= KAPPA_MIN
        ok = measurable and p >= P_MIN and lo >= WILSON_MIN
        verdict = "PASS" if ok else ("측정못함" if not measurable else "FAIL")
        rows[c] = dict(n=n, prec=p, lo=lo, hi=hi, kappa=k, verdict=verdict,
                       a=sum(ca) / n, b=sum(cb) / n)
        print(f"{c:<9}{n:>5}{p:>9.1%}  [{lo:>5.1%},{hi:>6.1%}]"
              f"{sum(ca)/n:>7.0%}{sum(cb)/n:>7.0%}{k:>8.2f}  {verdict}")

    # --- 왜 틀렸나 (A 기준). 세 실패 원인을 분리한다
    why = Counter()
    for pid, c in pairs:
        j = A[pid]
        if not j.get("visit"):
            why["음식점 글이 아님"] += 1
        elif not j.get("target"):
            why["대상 점포가 아님"] += 1
        elif not j.get(c):
            why["범주가 틀림"] += 1
        else:
            why["정확"] += 1
    print("\n실패 원인 (판정자 A 기준, 전체 쌍):")
    for k_, v in why.most_common():
        print(f"  {k_:<16}{v:>5}  {v/len(pairs):>6.1%}")

    ok_cats = [c for c, r in rows.items() if r["verdict"] == "PASS"]
    print(f"\n§I-19 통과 범주 {len(ok_cats)}개: {' · '.join(ok_cats) or '없음'}")
    print("등록된 중단 조건: 통과 범주 2개 미만이면 제품 코드를 만들지 않는다 → "
          + ("계속" if len(ok_cats) >= 2 else "중단"))
    (D / "score.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
