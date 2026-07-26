"""E-A runner — the feature-weight table. Contract: docs/experiment-plan.md E-A.

Three benches, because one bench cannot honestly hold all of them:

  rank    the confirmed deploy set (train.DEPLOY on CONFIRMED_TRAIN_YEARS) with
          the E-M winner. Every delta here is on the same footing as the headline.
  measure rank + G6 (site_area). Shop attributes are measured and never ranked
          on - the number exists to justify the exclusion, not to reverse it.
  sub     benches a group the rank bench structurally cannot carry, each with the
          constraint printed next to it:
            G4 accessibility - asof.py has no line opening dates, so the wide
              2005 period would show a 2005 shop stations built later. Measured
              on LOC3 / train 2013-2018.
            G7 trend - coverage starts 2016-01, so a 2005-2018 bench would impute
              most training rows and return a structural zero that reads like a
              third rejection. Measured on train 2017-2018, as in section 6.

Every split this run needs is loaded before the first fit, so editing a feature
module while it runs cannot swap the data underneath it mid-table.
"""
import argparse
import json
import sys
import time

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .ablation import (GROUPS, deciles, leave_one_group_out, only_one_group_in,
                       paired_bootstrap_ci, permutation_importance_auc, seed_avg_predict)
from .cache import cached_split
from .evaluate import TEST_YEARS
from .train import CONFIRMED_TRAIN_YEARS, DEPLOY, LOC3, TREND, WINNER, Encoder, weights

TREND_TRAIN = [2017, 2018]
LOC3_TRAIN = list(range(2013, 2019))


def measure(name, split, cols_full, group, model, note="", p_full=None):
    """One row of the table: leave-one-out delta with CI, plus standalone AUC.

    `p_full` is passed in because the full-bench prediction is identical for
    every group on that bench; refitting it per group is the single most
    expensive redundancy in this programme.
    """
    train, test = split
    y = test[1]
    without = leave_one_group_out(cols_full, group)
    only = only_one_group_in(cols_full, group)
    if len(without) == len(cols_full):
        return None                       # group absent from this bench

    if p_full is None:
        p_full = seed_avg_predict(model, train, test, cols_full)
    p_wo = seed_avg_predict(model, train, test, without)
    point, lo, hi = paired_bootstrap_ci(y, p_full, p_wo)
    solo = roc_auc_score(y, seed_avg_predict(model, train, test, only)) if only else float("nan")
    d_full, d_wo = deciles(y, p_full), deciles(y, p_wo)
    verdict = "기여" if lo > 0 else ("음(-)" if hi < 0 else "판별 불가")
    row = {"group": name, "n_feat": len(GROUPS[group]), "delta": point, "lo": lo, "hi": hi,
           "solo": solo, "top_full": d_full[0], "top_wo": d_wo[0],
           "verdict": verdict, "note": note}
    print(f"  {name:<20} ΔAUC {point:+.4f} [{lo:+.4f}, {hi:+.4f}]  단독 {solo:.4f}  "
          f"상위10% {d_full[0]*100:.1f}%->{d_wo[0]*100:.1f}%  {verdict}  {note}")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=WINNER)
    ap.add_argument("--out", default="model/.cache/ablation.json")
    a = ap.parse_args()

    t0 = time.time()
    con = init()
    print("=" * 96)
    print(f"E-A 피처군 절제 프로그램 — 모델 {a.model} · 시드 5개 · 짝지은 부트스트랩 200회")
    print("=" * 96)

    print("\n스플릿 적재...", flush=True)
    rank = cached_split(con, CONFIRMED_TRAIN_YEARS, TEST_YEARS, 3)
    loc3 = cached_split(con, LOC3_TRAIN, TEST_YEARS, 3)
    trend = cached_split(con, TREND_TRAIN, TEST_YEARS, 3, with_trend=True)
    rank_cols = list(DEPLOY)
    meas_cols = rank_cols + ["site_area"]
    print(f"  순위 벤치 n_tr={len(rank[0][1]):,} · 측정 벤치 +site_area · "
          f"G4 부표 n_tr={len(loc3[0][1]):,} · G7 부표 n_tr={len(trend[0][1]):,}")

    rows = []
    print(f"\n[순위 벤치] DEPLOY({len(rank_cols)}) · train {CONFIRMED_TRAIN_YEARS[0]}-"
          f"{CONFIRMED_TRAIN_YEARS[-1]} · 이 벤치의 ΔAUC가 헤드라인과 같은 기준", flush=True)
    p_rank = seed_avg_predict(a.model, rank[0], rank[1], rank_cols)
    for g in ("G1_competition", "G2_dynamics", "G3_prior_survival", "G5_grid_physical"):
        r = measure(g, rank, rank_cols, g, a.model, p_full=p_rank)
        if r:
            rows.append(r)

    # Pre-registered fallback: all three licensing groups indistinguishable means
    # the groups overlap, not that licensing history contributes nothing. Ablate
    # the whole source at once to get a number that is not swallowed by overlap.
    lic = [r for r in rows if r["group"].startswith(("G1", "G2", "G3"))]
    if lic and all(r["verdict"] == "판별 불가" for r in lic):
        print("\n  [폴백 발동] G1·G2·G3 전부 CI∋0 -> 인허가군 통째 절제 (원천 수준 기여)")
        allc = set(GROUPS["G1_competition"] + GROUPS["G2_dynamics"] + GROUPS["G3_prior_survival"])
        without = [c for c in rank_cols if c not in allc]
        p_wo = seed_avg_predict(a.model, rank[0], rank[1], without)
        point, lo, hi = paired_bootstrap_ci(rank[1][1], p_rank, p_wo)
        print(f"  {'G1+G2+G3 (인허가 전체)':<20} ΔAUC {point:+.4f} [{lo:+.4f}, {hi:+.4f}]")
        rows.append({"group": "G1+G2+G3_licensing_all", "n_feat": len(allc), "delta": point,
                     "lo": lo, "hi": hi, "solo": float("nan"), "verdict":
                     "기여" if lo > 0 else "판별 불가", "note": "폴백"})

    print(f"\n[측정 벤치] DEPLOY + site_area — 순위 모델에는 넣지 않는다")
    r = measure("G6_store_attrs", (rank[0], rank[1]), meas_cols, "G6_store_attrs", a.model,
                note="측정 전용")
    if r:
        rows.append(r)

    print(f"\n[G4 부표] LOC3 · train {LOC3_TRAIN[0]}-{LOC3_TRAIN[-1]} "
          f"— 확대 기간엔 노선 개통일이 없어 실을 수 없다")
    r = measure("G4_access", loc3, list(LOC3), "G4_access", a.model,
                note="표본 제약: train 2013-2018")
    if r:
        rows.append(r)

    print(f"\n[G7 부표] train {TREND_TRAIN[0]}-{TREND_TRAIN[-1]} "
          f"— 트렌드 커버리지가 2016-01부터라 확대 벤치에선 구조적 0이 된다")
    r = measure("G7_trend", trend, list(DEPLOY) + TREND, "G7_trend", a.model,
                note="표본 제약: train 2017-2018")
    if r:
        rows.append(r)

    # ---- per-feature: permutation importance on the winner, logit sign -------
    print(f"\n[피처 단위] 순열 중요도({a.model}, 홀드아웃 AUC 하락) + 로짓 표준화 계수(방향)")
    enc = Encoder(rank_cols).fit(rank[0][0])
    from .train import fit_predict
    _, (m, _) = fit_predict(a.model, rank[0], rank[1], num=rank_cols, enc=enc)
    Xte = enc.transform(rank[1][0], scale=False)
    blocks = {c: [i] for i, c in enumerate(rank_cols)}
    blocks["uptae(범주형)"] = list(range(len(rank_cols), Xte.shape[1]))
    base, imp = permutation_importance_auc(m, Xte, rank[1][1], blocks)
    coef = dict(weights(rank[0], top=999, num=rank_cols)[0])
    print(f"  기준 AUC {base:.4f}")
    print(f"  {'피처':<20} {'순열 ΔAUC':>11} {'±sd':>8} {'로짓계수':>10} {'방향':>6}")
    per_feat = []
    for name, (mu, sd) in sorted(imp.items(), key=lambda kv: -kv[1][0]):
        c = coef.get(name)
        arrow = "" if c is None else ("생존↑" if c > 0 else "생존↓")
        print(f"  {name:<20} {mu:>+11.4f} {sd:>8.4f} "
              f"{('%+.4f' % c) if c is not None else '—':>10} {arrow:>6}")
        per_feat.append({"feature": name, "perm": mu, "perm_sd": sd, "logit": c})

    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"model": a.model, "bench_cols": rank_cols, "groups": rows,
                   "features": per_feat, "base_auc": base}, f, ensure_ascii=False, indent=1)
    print(f"\n{a.out} 기록 · {time.time()-t0:.0f}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
