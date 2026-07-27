"""I-9 검정 — 텍스트 1인당 지출 vs 정형 객단가. 설계는 §I-9, 단위는 §I-10-⑥.

정형 객단가(`sales_amt/sales_cnt`)는 상권 안 51.4% 격자에만 있다. **상권 안에서
텍스트와 맞는지 먼저 확인하고, 맞을 때만 상권 밖 48.6%에 쓴다.** 순서를 뒤집으면
검증 없이 결측을 메우는 것이 된다.

단위는 **지명**이다. r1은 창이 겹치고 대조군이 상권 단위라 CI가 좁아진다
(§I-10-⑥ 실측). r1은 통과했을 때 화면에 내보내는 단위로만 쓴다.

    python -m model.price_test
"""
import argparse
import sqlite3
import sys
from collections import defaultdict

import numpy as np

from pipeline.config import DB_PATH

SEED = 0
NBOOT = 2000
MIN_MENTION = 10   # §I-9 — 지명당 금액 추출 최소
MIN_PLACES = 30    # §I-9 — 그런 지명 최소
RHO_MIN = 0.30     # §I-9 — 방향만 맞는 것과 값을 대신 쓰는 것은 다르다


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def median(v):
    return float(np.median(v))


def main():
    argparse.ArgumentParser().parse_args()
    con = sqlite3.connect(DB_PATH)

    # --- 텍스트: 지명별 1인당 지출 중앙값
    per = defaultdict(list)
    for place, v in con.execute(
            "SELECT place, per_person FROM price_label "
            "WHERE per_person IS NOT NULL"):
        per[place].append(v)
    txt = {p: median(v) for p, v in per.items() if len(v) >= MIN_MENTION}
    print(f"텍스트 지명 {len(txt)} (금액 {MIN_MENTION}건 이상)")

    # --- 정형: 지명별 객단가 중앙값 (상권 안 격자만, NULL 은 제외하고 0 으로 안 채운다)
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place"))
    acc = defaultdict(list)
    for gid, amt, cnt in con.execute(
            "SELECT grid_id, sales_amt, sales_cnt FROM grid_feature "
            "WHERE sales_amt IS NOT NULL AND sales_cnt IS NOT NULL AND sales_cnt > 0"):
        p = g2p.get(gid)
        if p:
            acc[p].append(amt / cnt)
    fl = {p: median(v) for p, v in acc.items() if v}
    print(f"정형 지명 {len(fl)} (상권 안 격자 있음)\n")
    con.close()

    common = sorted(set(txt) & set(fl))
    print(f"교집합 {len(common)} 지명"
          f"{'  → §I-9 최소 30 미달, 판정 보류' if len(common) < MIN_PLACES else ''}")
    if len(common) < MIN_PLACES:
        return 1

    x = np.array([txt[p] for p in common])
    y = np.array([fl[p] for p in common])
    print(f"텍스트 중앙값 {np.median(x):,.0f}원 · 정형 객단가 중앙값 {np.median(y):,.0f}원")

    r = spearman(x, y)
    rng = np.random.default_rng(SEED)
    boot = np.array([spearman(x[k], y[k]) for k in
                     (rng.integers(0, len(common), len(common)) for _ in range(NBOOT))])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"\nSpearman rho {r:+.3f}   95% CI [{lo:+.3f}, {hi:+.3f}]   n={len(common)}")

    ci_ok = lo > 0
    rho_ok = r >= RHO_MIN
    print("\n" + "=" * 60)
    print(f"CI 가 0 을 배제: {'예' if ci_ok else '아니오'}")
    print(f"rho >= {RHO_MIN}: {'예' if rho_ok else '아니오'}  (실측 {r:+.3f})")
    ok = ci_ok and rho_ok
    print(f"I-9 판정: {'통과' if ok else '기각'}")
    if ok:
        print("=> §I-9 대로 score_meta 에 price_by_place 를 추가한다.")
        print("   상권 밖 격자의 응답에만 붙인다. 매출 추정이라 부르지 않는다.")
    else:
        print("=> §I-9 대로 키를 만들지 않는다.")
        print("   가격대는 비정형으로 메꿀 수 없다고 기록한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
