"""Is "add more data" still a lever, or has it saturated?

Both adopted improvements in this project were training-data expansions (E1
2013→2005, R4 →2022); every new feature family and every model swap failed. That
makes the shape of the learning curve the most decision-relevant thing we can
measure: if validation performance is still climbing at the current window, the
next round should widen the window, and if it has flattened, widening is wasted
effort and the remaining levers are features and labels.

Two axes, because they answer different questions:

  cohorts  training window start year, validation fixed. This is the lever E1/R4
           actually pulled - adding *older cohorts*, which brings both more rows
           and a different era.
  rows     random subsample of a fixed window. Isolates sample size from era, so
           a gain on the cohort axis that does not appear here is an era effect
           rather than a volume effect.

Train-set scores are reported alongside validation so an overfitting gap is
visible rather than inferred. Everything is scored on the top decile first,
because that is what the product serves and what E-M round 3 registered - a
curve drawn on AUC could keep rising while the served number does not move.

No holdout is opened here. The curve is a planning instrument, and its readings
are internal-validation only.
"""
import argparse
import sys
import time

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .cache import cached_split
from .train import CONFIRMED_TRAIN_YEARS, DEPLOY, SCALED, Encoder, fit_predict
from .tournament import deciles, top_decile

# The widest window the cohort-health check cleared. 1990-1994 is excluded on
# evidence, not taste: 1990 openings show 87.9% three-year survival against
# 62-70% everywhere else (closures under-recorded that early) and 62.9%
# prior_surv missingness. 2000 is indistinguishable from 2005 on both.
WIDE_START = 2000
VAL_YEARS = CONFIRMED_TRAIN_YEARS[-2:]          # 2021-2022, same as every gate
COHORT_STARTS = [2013, 2010, 2007, 2005, 2002, 2000]
ROW_FRACTIONS = [0.15, 0.3, 0.5, 0.75, 1.0]
SEED = 20260730

# One-dimensional scans of capacity/regularisation, each spanning the current
# default in BOTH directions. The random search in tune.py moves these jointly,
# which is right for finding a winner and wrong for reading a single knob's
# effect - a joint draw cannot tell "more regularisation helps" from "this
# particular combination helps". Defaults (train.build_model): num_leaves 31,
# min_child_samples 100, reg_lambda 0, subsample 0.9, colsample_bytree 0.9.
#
# The direction of interest is not obvious a priori. The row axis shows train AUC
# at 0.6586 against val 0.6190 - a gap of 0.04, which is small. If the binding
# constraint is information rather than variance, tightening these knobs should
# move val down, not up, and loosening them should not help either.
REGULAR_SCANS = [
    ("num_leaves", [7, 15, 31, 63, 127, 255]),          # capacity
    ("min_child_samples", [10, 20, 100, 400, 1600]),    # leaf-size floor
    ("reg_lambda", [0.0, 1.0, 10.0, 100.0, 1000.0]),    # L2
    ("subsample", [0.5, 0.7, 0.9, 1.0]),                # row bagging
    ("colsample_bytree", [0.4, 0.6, 0.9, 1.0]),         # feature bagging
]


def _subset(split, keep):
    """Filter a built split by a boolean mask over its rows."""
    X, y, meta = split
    idx = [i for i, k in enumerate(keep) if k]
    return ([X[i] for i in idx], np.asarray([y[i] for i in idx]),
            [meta[i] for i in idx])


def evaluate(train, val, cols, model, label, axis, params=None):
    enc = Encoder(cols).fit(train[0])
    p_val, (m, _) = fit_predict(model, train, val, num=cols, seed=0, params=params, enc=enc)
    # Scaling must match what fit_predict used, or the train-set score is read
    # off a different design than the model was fitted on.
    p_tr = m.predict_proba(enc.transform(train[0], scale=model in SCALED))[:, 1]
    d = deciles(val[1], p_val)
    row = {"label": label, "axis": axis, "n": len(train[1]),
           "val_top": top_decile(val[1], p_val), "val_auc": roc_auc_score(val[1], p_val),
           "val_gap": d[0] - d[-1],
           "tr_top": top_decile(train[1], p_tr), "tr_auc": roc_auc_score(train[1], p_tr)}
    print(f"  {label:<16} n={row['n']:>7,}  val 상위10% {row['val_top']*100:5.2f}%  "
          f"AUC {row['val_auc']:.4f}  격차 {row['val_gap']*100:4.1f}%p   "
          f"| train AUC {row['tr_auc']:.4f}  (과적합 {row['tr_auc']-row['val_auc']:+.4f})",
          flush=True)
    return row


def main():
    ap = argparse.ArgumentParser(description="학습곡선 — 데이터를 더 넣는 레버가 남았나")
    ap.add_argument("--model", default="gbm")
    ap.add_argument("--axis", default="cohorts,rows")
    ap.add_argument("--json", help="측정값 저장 경로 — 그림 스크립트가 이걸 읽는다")
    a = ap.parse_args()
    t0 = time.time()
    con = init()
    cols = list(DEPLOY)
    axes = [s.strip() for s in a.axis.split(",")]

    print("=" * 100)
    print(f"학습곡선 — 모델 {a.model} · 세트 DEPLOY({len(cols)}) · 검증 고정 "
          f"{VAL_YEARS[0]}-{VAL_YEARS[-1]} · 홀드아웃 미개방")
    print("=" * 100)

    # One build covers every cohort start: the widest window contains them all,
    # and narrower windows are row filters on it.
    wide_years = list(range(WIDE_START, VAL_YEARS[0]))
    print(f"\n스플릿 빌드 train {wide_years[0]}-{wide_years[-1]} / val "
          f"{VAL_YEARS[0]}-{VAL_YEARS[-1]} ...", flush=True)
    train, val = cached_split(con, wide_years, list(VAL_YEARS), 3)
    years = np.array([m["open_ym"] // 12 for m in train[2]])
    print(f"  train {len(train[1]):,}행 · val {len(val[1]):,}행")

    rows = []
    if "cohorts" in axes:
        print(f"\n[코호트 축] 학습 시작연도를 뒤로 밀면 검증 성능이 계속 오르나")
        for start in COHORT_STARTS:
            rows.append(evaluate(_subset(train, years >= start), val, cols,
                                 a.model, f"{start}-{wide_years[-1]}", "cohorts"))

    if "rows" in axes:
        print(f"\n[행 축] 같은 창({WIDE_START}-{wide_years[-1]})에서 행만 줄이면")
        rng = np.random.default_rng(SEED)
        n = len(train[1])
        order = rng.permutation(n)
        for frac in ROW_FRACTIONS:
            keep = np.zeros(n, dtype=bool)
            keep[order[:int(n * frac)]] = True
            rows.append(evaluate(_subset(train, keep), val, cols, a.model,
                                 f"{int(frac*100)}% rows", "rows"))

    if "regular" in axes:
        print(f"\n[정규화·용량 축] 전체 창에서 손잡이를 하나씩만 돌린다 (기본값 양쪽으로)")
        for name, values in REGULAR_SCANS:
            print(f"  -- {name} --")
            for v in values:
                rows.append(evaluate(train, val, cols, a.model,
                                     f"{name}={v}", f"regular:{name}", {name: v}))

    # Reading: compare the last two points on each axis. A flat tail means the
    # lever is spent; a rising tail means the next round should widen the window.
    print(f"\n  읽는 법")
    for axis in ("cohorts", "rows"):
        seg = [r for r in rows if r["axis"] == axis]
        if len(seg) < 2:
            continue
        d_top = (seg[-1]["val_top"] - seg[-2]["val_top"]) * 100
        d_auc = seg[-1]["val_auc"] - seg[-2]["val_auc"]
        verdict = ("아직 오른다 — 창을 더 넓히는 것이 다음 라운드"
                   if d_top > 0.5 else
                   "포화 — 데이터 확대는 소진됐고 남은 레버는 피처·라벨")
        print(f"    {axis:<8} 마지막 두 점 Δ상위10% {d_top:+.2f}%p · ΔAUC {d_auc:+.4f} → {verdict}")

    # For each knob: does any setting beat the default, and which direction?
    # A knob whose best is its default is spent; a knob that improves when
    # LOOSENED says the constraint was capacity, not variance.
    reg = [r for r in rows if r["axis"].startswith("regular:")]
    if reg:
        print(f"\n  정규화·용량 손잡이별 최적 (기준 = 현행 기본값)")
        for name, values in REGULAR_SCANS:
            seg = [r for r in reg if r["axis"] == f"regular:{name}"]
            if not seg:
                continue
            best = max(seg, key=lambda r: r["val_top"])
            base = next((r for r in seg if r["label"].endswith(
                f"={dict(num_leaves=31, min_child_samples=100, reg_lambda=0.0, subsample=0.9, colsample_bytree=0.9)[name]}")), None)
            tag = "" if base is None else f" (기본 {base['val_top']*100:.2f}%)"
            print(f"    {name:<20} 최적 {best['label']:<28} "
                  f"val 상위10% {best['val_top']*100:5.2f}%{tag}  "
                  f"과적합 {best['tr_auc']-best['val_auc']:+.4f}")

    if a.json:
        import json
        from pathlib import Path
        payload = {"model": a.model, "features": "DEPLOY", "n_features": len(cols),
                   "val_years": list(VAL_YEARS), "wide_start": WIDE_START,
                   "val_n": len(val[1]), "rows": rows}
        p = Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  측정값 -> {p}")
    print(f"\n({time.time()-t0:.0f}초)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
