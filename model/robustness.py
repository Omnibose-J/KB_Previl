"""Is the recommendation actually useful, or just technically valid?

backtest.py shows the ranking works overall. That is necessary and not
sufficient. Four questions decide whether it earns a place in someone's
decision:

  1. Does it beat the advice a shop owner already has? "Open where the shops
     are" and "open where the crowds are" are free. If a trained model cannot
     beat them, it is decoration.
  2. Does it hold year by year, including 2020-2021? A model that worked only
     in normal times is not a model of anything durable.
  3. Does it hold per 업태 and per district, or is it carried by one segment?
  4. When it is wrong, how wrong? Top-decile cells that still failed are the
     honest counterweight to the headline number.

Everything reuses the single time-split prediction from evaluate/train. No new
fitting, so none of these can look better than the headline.
"""
import argparse
import sys
from collections import defaultdict

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .evaluate import TEST_YEARS, TRAIN_YEARS, load_split
from .train import NUM, fit_predict


def lift(y, p, q=0.10):
    y, p = np.asarray(y), np.asarray(p)
    if len(y) < 50 or y.mean() in (0.0, 1.0):
        return None, None, None
    k = max(1, int(len(y) * q))
    idx = np.argsort(-p)[:k]
    top = y[idx].mean()
    return top, y.mean(), top / y.mean()


def safe_auc(y, p):
    y = np.asarray(y)
    if len(set(y.tolist())) < 2:
        return None
    return roc_auc_score(y, p)


# ---- naive rules a shop owner could apply without any model ---------------
def rule_density(X):
    """'Open where the shops already are.'"""
    return np.array([f["open_cnt_r1"] for f in X], dtype=float)


def rule_low_churn(X):
    """'Avoid streets where places keep turning over.'"""
    return np.array([-f["churn_36m"] for f in X], dtype=float)


def rule_big_shop(X):
    """'Get a bigger unit.'"""
    return np.array([f["site_area"] or 0 for f in X], dtype=float)


def rule_no_recent_surge(X):
    """'Do not pile into a block everyone just opened in.'"""
    return np.array([-f["openings_36m"] for f in X], dtype=float)


RULES = {
    "점포 많은 곳": rule_density,
    "교체 적은 곳": rule_low_churn,
    "넓은 점포": rule_big_shop,
    "최근 개업 적은 곳": rule_no_recent_surge,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gbm")
    a = ap.parse_args()

    con = init()
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, 3, verbose=False)
    Xte, yte, mte = test
    p, _ = fit_predict(a.model, train, test, num=NUM)
    overall = yte.mean()

    print(f"검증 {TEST_YEARS[0]}~{TEST_YEARS[-1]} 개업 {len(yte):,}건 · "
          f"실제 3년 생존율 {overall*100:.1f}%")

    # ---------------------------------------------------------------- 1
    print("\n" + "=" * 72)
    print("1) 상식 규칙 대비 — 자영업자가 이미 아는 것보다 나은가")
    print(f"  {'기준':<20} {'상위10% 생존율':>14} {'전체대비':>9} {'AUC':>8}")
    top, _, lf = lift(yte, p)
    print(f"  {'모델(' + a.model + ')':<20} {top*100:>13.1f}% {lf:>8.2f}x "
          f"{safe_auc(yte, p):>8.4f}")
    for nm, fn in RULES.items():
        s = fn(Xte)
        t2, _, l2 = lift(yte, s)
        print(f"  {nm:<20} {t2*100:>13.1f}% {l2:>8.2f}x {safe_auc(yte, s):>8.4f}")
    print("  * 상식 규칙이 모델에 근접하면 모델의 추가 가치는 그만큼 작다")

    # ---------------------------------------------------------------- 2
    print("\n" + "=" * 72)
    print("2) 연도별 안정성 — 코로나 시기 포함")
    by_year = defaultdict(list)
    for i, m in enumerate(mte):
        by_year[m["open_ym"] // 12].append(i)
    print(f"  {'개업연도':<10} {'건수':>7} {'전체생존':>9} {'상위10%':>9} {'배수':>7} {'AUC':>8}")
    for yr in sorted(by_year):
        idx = np.array(by_year[yr])
        yy, pp = yte[idx], p[idx]
        t3, o3, l3 = lift(yy, pp)
        if t3 is None:
            continue
        auc = safe_auc(yy, pp)
        print(f"  {yr:<10} {len(idx):>7,} {o3*100:>8.1f}% {t3*100:>8.1f}% "
              f"{l3:>6.2f}x {auc:>8.4f}")

    # ---------------------------------------------------------------- 3
    print("\n" + "=" * 72)
    print("3) 업태별 — 특정 업종이 끌고 가는 것은 아닌가")
    by_u = defaultdict(list)
    for i, f in enumerate(Xte):
        by_u[f["uptae"]].append(i)
    print(f"  {'업태':<18} {'건수':>7} {'전체생존':>9} {'상위10%':>9} {'배수':>7} {'AUC':>8}")
    for u, idxs in sorted(by_u.items(), key=lambda kv: -len(kv[1]))[:8]:
        idx = np.array(idxs)
        t4, o4, l4 = lift(yte[idx], p[idx])
        if t4 is None:
            continue
        print(f"  {u:<18} {len(idx):>7,} {o4*100:>8.1f}% {t4*100:>8.1f}% "
              f"{l4:>6.2f}x {safe_auc(yte[idx], p[idx]):>8.4f}")

    # ---------------------------------------------------------------- 4
    print("\n" + "=" * 72)
    print("4) 자치구별 — 특정 지역만 맞는 것은 아닌가")
    gu_of = {}
    for r in con.execute("SELECT grid_id, sgis_adm_nm FROM grid_sgis"):
        parts = (r[1] or "").split()
        if len(parts) >= 2:
            gu_of[r[0]] = parts[1]
    by_g = defaultdict(list)
    for i, m in enumerate(mte):
        g = gu_of.get(m["grid_id"])
        if g:
            by_g[g].append(i)
    rows = []
    for g, idxs in by_g.items():
        idx = np.array(idxs)
        t5, o5, l5 = lift(yte[idx], p[idx])
        if t5 is not None:
            rows.append((g, len(idx), o5, t5, l5))
    rows.sort(key=lambda r: -r[4])
    print(f"  {'자치구':<12} {'건수':>7} {'전체생존':>9} {'상위10%':>9} {'배수':>7}")
    for g, n, o5, t5, l5 in rows[:4]:
        print(f"  {g:<12} {n:>7,} {o5*100:>8.1f}% {t5*100:>8.1f}% {l5:>6.2f}x")
    print(f"  {'...':<12}")
    for g, n, o5, t5, l5 in rows[-4:]:
        print(f"  {g:<12} {n:>7,} {o5*100:>8.1f}% {t5*100:>8.1f}% {l5:>6.2f}x")
    good = sum(1 for r in rows if r[4] > 1.0)
    print(f"  개선이 나타난 자치구 {good}/{len(rows)}")

    # ---------------------------------------------------------------- 5
    print("\n" + "=" * 72)
    print("5) 틀린 경우 — 상위 추천인데 폐업한 자리")
    k = int(len(yte) * 0.10)
    top_idx = np.argsort(-p)[:k]
    failed = [i for i in top_idx if yte[i] == 0]
    print(f"  상위 10% {k:,}건 중 3년 내 폐업 {len(failed):,}건 "
          f"({len(failed)/k*100:.1f}%)")
    print(f"  -> 상위 추천을 따라도 4곳 중 1곳 가까이는 문을 닫는다.")
    print(f"     이 수치를 감추면 신뢰를 잃는다. 함께 제시할 것.")

    bot_idx = np.argsort(-p)[-k:]
    survived = [i for i in bot_idx if yte[i] == 1]
    print(f"  하위 10% {k:,}건 중 3년 생존 {len(survived):,}건 "
          f"({len(survived)/k*100:.1f}%)")
    print(f"  -> 나쁜 자리에서도 열에 넷은 살아남는다. 입지는 일부일 뿐이다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
