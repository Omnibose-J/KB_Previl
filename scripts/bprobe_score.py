"""§I-21 B1 채점 — 확장 스니펫에 실제로 그 측면의 불만이 담겨 있는가.

밀도 = 그 측면 확장 스니펫 중 **두 판정자가 모두 불만이라 한 비율** (§I-20 과 같은
보수적 추정량). 기준 0.30.

    python scripts/bprobe_score.py
"""
import json
import math
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
D = Path(__file__).resolve().parent.parent / "scratch_bprobe"
CATS = ("wait", "seat", "service", "clean", "price", "noise", "parking")
PASSED = ("seat", "service", "clean", "price", "noise", "parking")
DENS_MIN = 0.30


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


def load(t):
    o = {}
    for b in (1, 2, 3):
        f = D / f"b1_out_b{b}_{t}.json"
        if f.exists():
            o.update(json.loads(f.read_text(encoding="utf-8-sig")))
    return o


def main():
    key = json.loads((D / "b1_key.json").read_text(encoding="utf-8"))
    A, B = load("A"), load("B")
    have = set(A) & set(B) & set(key)
    print(f"두 판정자 모두 판정한 글 {len(have)}/{len(key)}")
    if len(have) < len(key):
        print("  부분 집계 — 미완 배치 있음")

    print(f"\n{'측면':<10}{'n':>5}{'밀도':>9}{'Wilson95':>17}"
          f"{'A만':>7}{'B만':>7}{'kappa':>8}  판정")
    passed = []
    for asp in PASSED:
        sub = [i for i in have if key[i] == asp]
        if not sub:
            continue
        ca = [1 if A[i].get(asp) else 0 for i in sub]
        cb = [1 if B[i].get(asp) else 0 for i in sub]
        both = sum(1 for x, y in zip(ca, cb) if x and y)
        n = len(sub)
        lo, hi = wilson(both, n)
        k = kappa(ca, cb)
        ok = both / n >= DENS_MIN
        if ok:
            passed.append(asp)
        print(f"{asp:<10}{n:>5}{both/n:>9.1%}  [{lo:>5.1%},{hi:>6.1%}]"
              f"{sum(ca)/n:>7.0%}{sum(cb)/n:>7.0%}{k:>8.2f}  "
              f"{'PASS' if ok else 'FAIL'}")

    # --- 대조군: 기준선 스니펫에서 아무 측면이나 불만이 잡히는 비율
    base = [i for i in have if key[i] == "_base"]
    if base:
        both = sum(1 for i in base
                   if any(A[i].get(c) and B[i].get(c) for c in CATS))
        lo, hi = wilson(both, len(base))
        print(f"\n대조군(기준선 쿼리) {len(base)}건 — 아무 측면이나 불만: "
              f"{both/len(base):.1%} [{lo:.1%},{hi:.1%}]")
        print("  현재 코퍼스 `gripe_label` 의 불만 있는 글 비율은 4.2% 다")

    print(f"\n§I-21 B1 통과 측면 {len(passed)}개: {' · '.join(passed) or '없음'}")
    print("등록된 조건: 통과 2개 미만이면 arm B 폐기 → "
          + ("계속" if len(passed) >= 2 else "arm B 폐기"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
