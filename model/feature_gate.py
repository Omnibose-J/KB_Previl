"""Admission gate for a candidate feature family, on the confirmed bench.

Contract: docs/experiment-plan.md "확장 피처의 편입 기준". extend.py runs the same
procedure on the legacy bench and is left untouched so the T1/T2/T3 rejections stay
reproducible; the plan says screening happens on "확정 train의 마지막 2년", which is
2021-2022 today.

Why a gate: with a handful of candidates and a holdout standard error near 0.003,
reading the holdout once per candidate would let a +0.002 threshold pass on noise.
Candidates are screened on internal validation; the holdout is opened once, for
the bundle.

One module handles every family so the thresholds cannot drift into a friendlier
form per experiment - they are imported from extend.py, not restated.

Families (R10-B ran as `--family osm` under the earlier name osm_gate.py):
  osm  road geometry (model/osm.py)              -> rejected, ΔAUC -0.0009
  cbd  distance to Seoul's three city centres    -> rejected (§25, sign flipped)
"""
import argparse
import sys
import time

from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .ablation import deciles, paired_bootstrap_ci, seed_avg_predict
from .cache import cached_split
from .extend import BUNDLE_MIN_GAIN, SCREEN_SEEDS, TOP_DECILE_FLOOR, district_pass
from .train import CBD, CONFIRMED_TEST_YEARS, CONFIRMED_TRAIN_YEARS, DEPLOY, OSM, WINNER

# family -> (candidate columns, the dataset.build flag that materialises them)
FAMILIES = {"osm": (list(OSM), {"with_osm": True}),
            "cbd": (list(CBD), {"with_cbd": True})}

INNER_TEST = CONFIRMED_TRAIN_YEARS[-2:]
INNER_TRAIN = CONFIRMED_TRAIN_YEARS[:-2]


def main():
    ap = argparse.ArgumentParser(description="확장 피처군 편입 심사 (확정 벤치)")
    ap.add_argument("--family", required=True, choices=sorted(FAMILIES))
    ap.add_argument("--model", default=WINNER)
    ap.add_argument("--horizon", type=int, default=3,
                    help="3 = 사전등록 판정. 다른 값은 사후 탐색이며 채택 근거로 못 쓴다")
    a = ap.parse_args()
    cand, flag = FAMILIES[a.family]
    t0 = time.time()
    con = init()
    base = list(DEPLOY)

    print("=" * 92)
    print(f"편입 심사 — 피처군 {a.family}({len(cand)}) · 모델 {a.model} "
          f"· horizon {a.horizon}년 · 선별은 내부 검증에서만 · 홀드아웃 1회")
    if a.horizon != 3:
        # The registered criterion is the 3-year label. A different horizon is a
        # different task on a non-independent cohort, so it can establish that a
        # signal exists but never that the family is admitted.
        print(f"** 사후 탐색 ** horizon {a.horizon}년은 사전등록 판정(3년)이 아니다. "
              f"같은 2023 코호트라 3년 검정과 독립이 아니므로 채택 근거로 쓰지 않는다.")
    print("=" * 92)

    # ------------------------------------------------------------- screening
    tr, va = cached_split(con, INNER_TRAIN, INNER_TEST, a.horizon, **flag)
    print(f"\n[선별] 내부 검증 train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} "
          f"/ val {INNER_TEST[0]}-{INNER_TEST[-1]} (n={len(va[1]):,}) · 시드 {len(SCREEN_SEEDS)}개")
    base_auc = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, base, SCREEN_SEEDS))
    print(f"  기준 DEPLOY({len(base)}) AUC {base_auc:.4f}")

    picked = []
    print(f"  {'후보':<22} {'add-one ΔAUC':>13}  {'결측률':>7}")
    for c in cand:
        auc = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, base + [c], SCREEN_SEEDS))
        miss = sum(1 for f in tr[0] if f.get(c) is None) / len(tr[0])
        d = auc - base_auc
        if d > 0:
            picked.append(c)
        print(f"  {c:<22} {d:>+13.4f}  {miss*100:>6.1f}%", flush=True)

    auc_all = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, base + cand, SCREEN_SEEDS))
    print(f"  {'(참고) ' + a.family + ' 전체':<22} {auc_all - base_auc:>+13.4f}")

    # Standalone signal: separates "this source knows nothing" from "this source
    # knows something the incumbent features already encode". Explanatory only -
    # it is not part of the admission rule.
    auc_solo = roc_auc_score(va[1], seed_avg_predict(a.model, tr, va, cand, SCREEN_SEEDS))
    print(f"  {'(참고) ' + a.family + ' 단독':<22} {auc_solo:>13.4f}  "
          f"(무작위 0.5000 · 기준 {base_auc:.4f})")

    print(f"\n  편입 후보군 ({len(picked)}개, 규칙: 내부검증 add-one ΔAUC > 0): "
          + (", ".join(picked) or "없음"))

    if not picked:
        print(f"\n홀드아웃 확인 생략 — 편입 후보 없음. {a.family} 기각으로 기록한다.")
        print(f"\n({time.time() - t0:.0f}초)")
        return 0

    # ---------------------------------------------------------------- bundle
    print(f"\n[확인] 홀드아웃 {CONFIRMED_TEST_YEARS[0]} — 번들 1회만")
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS,
                               a.horizon, **flag)
    y = test[1]
    p_base = seed_avg_predict(a.model, train, test, base)
    p_bund = seed_avg_predict(a.model, train, test, base + picked)
    point, lo, hi = paired_bootstrap_ci(y, p_bund, p_base)
    d_base, d_bund = deciles(y, p_base), deciles(y, p_bund)
    top_delta = d_bund[0] - d_base[0]
    g_base = district_pass(con, test[2], y, p_base)
    g_bund = district_pass(con, test[2], y, p_bund)
    mono = all(d_bund[i] >= d_bund[i + 1] - 0.02 for i in range(9))

    print(f"  기준  DEPLOY({len(base)})              AUC {roc_auc_score(y, p_base):.4f}  "
          f"상위10% {d_base[0]*100:.1f}%  자치구 {g_base[0]}/{g_base[1]}")
    print(f"  번들  DEPLOY+{len(picked)}({len(base)+len(picked)})            "
          f"AUC {roc_auc_score(y, p_bund):.4f}  상위10% {d_bund[0]*100:.1f}%  "
          f"자치구 {g_bund[0]}/{g_bund[1]}")
    print(f"\n  짝지은 부트스트랩 ΔAUC {point:+.4f}  95% CI [{lo:+.4f}, {hi:+.4f}]")
    checks = [("CI 하한 > 0", lo > 0),
              (f"점추정 >= +{BUNDLE_MIN_GAIN}", point >= BUNDLE_MIN_GAIN),
              (f"상위10% 하락 {TOP_DECILE_FLOOR*100:.1f}%p 이내", top_delta >= TOP_DECILE_FLOOR),
              (f"자치구 기준선 {g_base[0]}/{g_base[1]} 유지", g_bund[0] >= g_base[0]),
              ("십분위 단조", mono)]
    for nm, ok in checks:
        print(f"    {nm:<30} {'O' if ok else 'X'}")
    adopt = all(ok for _, ok in checks)
    print(f"  상위10% 변화 {top_delta*100:+.2f}%p")
    print(f"  -> {a.family} {'채택 — DEPLOY 교체는 별도 승인 사항' if adopt else '기각 (DEPLOY 유지)'}")
    print(f"\n({time.time() - t0:.0f}초)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
