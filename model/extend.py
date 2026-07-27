"""Extension screening + bundle confirmation. Contract: docs/experiment-plan.md
E-A "확장 피처의 편입 기준".

The rule this file exists to enforce: with ~13 candidates and a holdout standard
error near 0.003, checking each candidate against the holdout would let a +0.002
threshold pass on noise alone. So every candidate is screened on the internal
validation, and the holdout is opened exactly once, for the bundle.

Screening rule, declared before the run: a candidate enters the bundle if its
add-one delta-AUC on the internal validation is positive. The plan fixes where
the screening happens but not a cut value; anything stricter would be a
threshold invented after seeing the numbers.

Tier 3 (station ridership) is deliberately not screenable here. Its source
starts 2015-01 while the confirmed training period starts 2005, so on this bench
most rows are imputed and the measurement would report a coverage artefact. It
is measured on the 2017-2018 sub-bench instead and cannot be adopted.
"""
import argparse
import sys
import time
from collections import defaultdict

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .ablation import deciles, paired_bootstrap_ci, seed_avg_predict
from .cache import cached_split
from .evaluate import TEST_YEARS
from .train import LEGACY_TRAIN_YEARS, DEPLOY, TIER1, TIER2, TIER3, WINNER

BUNDLE_MIN_GAIN = 0.002        # pre-registered, holdout, bundle only
TOP_DECILE_FLOOR = -0.005      # top-decile observed survival may not fall 0.5%p
INNER_TEST = LEGACY_TRAIN_YEARS[-2:]
INNER_TRAIN = LEGACY_TRAIN_YEARS[:-2]
SUB_TRAIN = [2017, 2018]
SCREEN_SEEDS = (0, 1, 2)


def district_pass(con, meta, y, p):
    """Districts where the top decile beats the district's own average."""
    gu = {}
    for r in con.execute("SELECT grid_id, sgis_adm_nm FROM grid_sgis"):
        parts = (r[1] or "").split()
        if len(parts) >= 2:
            gu[r[0]] = parts[1]
    by = defaultdict(list)
    for i, m in enumerate(meta):
        g = gu.get(m["grid_id"])
        if g:
            by[g].append(i)
    good = tot = 0
    for g, idxs in by.items():
        idx = np.array(idxs)
        if len(idx) < 50:
            continue
        k = max(1, int(len(idx) * 0.1))
        top = y[idx][np.argsort(-p[idx])[:k]].mean()
        tot += 1
        good += 1 if top / y[idx].mean() > 1.0 else 0
    return good, tot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=WINNER)
    a = ap.parse_args()
    t0 = time.time()
    con = init()
    base = list(DEPLOY)

    print("=" * 92)
    print(f"확장 피처 편입 심사 — 모델 {a.model} · 선별은 내부 검증에서만")
    print("=" * 92)

    tr, va = cached_split(con, INNER_TRAIN, INNER_TEST, 3)
    print(f"\n[선별] 내부 검증 train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} "
          f"/ val {INNER_TEST[0]}-{INNER_TEST[-1]} (n={len(va[1]):,}) · 시드 {len(SCREEN_SEEDS)}개")
    base_auc = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, base, SCREEN_SEEDS))
    print(f"  기준 DEPLOY({len(base)}) AUC {base_auc:.4f}")

    cand = [(c, "Tier1") for c in TIER1] + [(c, "Tier2") for c in TIER2]
    picked, screen = [], []
    print(f"  {'후보':<20} {'군':<6} {'add-one ΔAUC':>13}  {'결측률':>7}")
    for c, tier in cand:
        auc = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, base + [c], SCREEN_SEEDS))
        miss = sum(1 for f in tr[0] if f.get(c) is None) / len(tr[0])
        d = auc - base_auc
        screen.append({"feature": c, "tier": tier, "delta": d, "missing": miss})
        if d > 0:
            picked.append(c)
        print(f"  {c:<20} {tier:<6} {d:>+13.4f}  {miss*100:>6.1f}%", flush=True)

    for tier, cols in (("Tier1 전체", TIER1), ("Tier2 전체", TIER2)):
        auc = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, base + cols, SCREEN_SEEDS))
        print(f"  {'(참고) ' + tier:<27} {auc - base_auc:>+13.4f}")

    print(f"\n  편입 후보군 ({len(picked)}개, 규칙: 내부검증 add-one ΔAUC > 0): "
          + (", ".join(picked) or "없음"))

    if not picked:
        print("\n홀드아웃 확인 생략 — 편입 후보 없음. 확장 피처 전부 기각으로 기록.")
        return 0

    # ---------------------------------------------------------------- bundle
    print(f"\n[확인] 홀드아웃 {TEST_YEARS[0]}-{TEST_YEARS[-1]} — 번들 1회만")
    train, test = cached_split(con, LEGACY_TRAIN_YEARS, TEST_YEARS, 3)
    y = test[1]
    p_base = seed_avg_predict(a.model, train, test, base)
    p_bund = seed_avg_predict(a.model, train, test, base + picked)
    point, lo, hi = paired_bootstrap_ci(y, p_bund, p_base)
    d_base, d_bund = deciles(y, p_base), deciles(y, p_bund)
    top_delta = d_bund[0] - d_base[0]
    g_base = district_pass(con, test[2], y, p_base)
    g_bund = district_pass(con, test[2], y, p_bund)
    mono = all(d_bund[i] >= d_bund[i + 1] - 0.02 for i in range(9))

    print(f"  기준  DEPLOY({len(base)})            AUC {roc_auc_score(y, p_base):.4f}  "
          f"상위10% {d_base[0]*100:.1f}%  자치구 {g_base[0]}/{g_base[1]}")
    print(f"  번들  DEPLOY+{len(picked)}({len(base)+len(picked)})          "
          f"AUC {roc_auc_score(y, p_bund):.4f}  상위10% {d_bund[0]*100:.1f}%  "
          f"자치구 {g_bund[0]}/{g_bund[1]}")
    print(f"\n  짝지은 부트스트랩 ΔAUC {point:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
    checks = [("CI 하한 > 0", lo > 0),
              (f"점추정 >= +{BUNDLE_MIN_GAIN}", point >= BUNDLE_MIN_GAIN),
              (f"상위10% 하락 {TOP_DECILE_FLOOR*100:.1f}%p 이내", top_delta >= TOP_DECILE_FLOOR),
              (f"자치구 기준선 {g_base[0]}/{g_base[1]} 유지", g_bund[0] >= g_base[0]),
              ("십분위 단조", mono)]
    for nm, ok in checks:
        print(f"    {nm:<28} {'O' if ok else 'X'}")
    adopt = all(ok for _, ok in checks)
    print(f"  상위10% 변화 {top_delta*100:+.2f}%p")
    print(f"  -> 번들 {'채택' if adopt else '기각 (DEPLOY 유지)'}")

    # ------------------------------------------------------------- Tier 3 sub
    print(f"\n[Tier 3 부표] train {SUB_TRAIN[0]}-{SUB_TRAIN[-1]} "
          f"— 승하차 커버리지가 2015-01부터라 확정 벤치엔 실을 수 없다")
    str_, ste = cached_split(con, SUB_TRAIN, TEST_YEARS, 3)
    miss = sum(1 for f in str_[0] if f.get("ride_12m") is None) / len(str_[0])
    p_s = seed_avg_predict(a.model, str_, ste, base)
    p_r = seed_avg_predict(a.model, str_, ste, base + TIER3)
    pt, l2, h2 = paired_bootstrap_ci(ste[1], p_r, p_s)
    print(f"  기준 AUC {roc_auc_score(ste[1], p_s):.4f} · +승하차 "
          f"{roc_auc_score(ste[1], p_r):.4f} · ΔAUC {pt:+.4f} [{l2:+.4f}, {h2:+.4f}] "
          f"· 학습행 결측 {miss*100:.1f}%")
    print(f"  판정: {'기여' if l2 > 0 else '판별 불가'} — 편입 불가(커버리지), 측정값으로만 기록")

    print(f"\n{time.time()-t0:.0f}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
