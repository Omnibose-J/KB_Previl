"""R12 — hyperparameter search over LightGBM, CatBoost and a torch MLP.

Contract: docs/model-findings.md R12. What E-M (tournament.py) actually covered
was six *families* at 3-4 configurations each - 22 fits, on the legacy bench.
It never searched hyperparameters broadly, never saw CatBoost (installed but
absent from its GRID, which documents only the XGBoost exclusion), and gave the
MLP four shapes topping out at two layers. Those are the three gaps this file
closes.

The rule that shapes the file is the same one tournament.py states: selection and
confirmation must not share a dataset. With ~95 configurations against a holdout
standard error near 0.003, reporting the best-of-95 on the holdout would make it
a validation set. So every configuration is scored on the last two confirmed
training years, and the holdout sees exactly two fits - the winner and the
incumbent.

Selection ranks on the **top decile**, not AUC. Round 2 of E-M picked rf on AUC
(+0.0043) and moved the served number by -0.1%p; round 3 re-registered the
criterion as the decile for that reason. Ranking on AUC here would repeat the
mistake with 95 chances instead of 22.

Search is random, not grid: at this budget a random draw covers each dimension's
range better than a factorial slice of it, and the seed is fixed so the draw is
reproducible.
"""
import argparse
import sys
import time

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .ablation import paired_bootstrap_ci
from .cache import cached_split
from .train import (CONFIRMED_TEST_YEARS, CONFIRMED_TRAIN_YEARS, DEPLOY, Encoder,
                    fit_predict)
from .tournament import DECILE_MIN_GAIN, deciles, paired_bootstrap_decile, top_decile

SEED = 20260730
INNER_TEST = CONFIRMED_TRAIN_YEARS[-2:]
INNER_TRAIN = CONFIRMED_TRAIN_YEARS[:-2]

# Search budget per family. Kept explicit so a run that trims it says so.
BUDGET = {"gbm": 50, "cat": 20, "torch": 25}


# ----------------------------------------------------------------- samplers
def sample_gbm(rng):
    # Ranges re-centred 2026-07-30 after the regularisation scan
    # (learning_curve.py --axis regular) put the optimum OUTSIDE the first ones:
    # num_leaves 7 beat 31 by +0.89%p on internal validation while the old range
    # started at 15, and min_child_samples 1600 beat 100 by +0.61%p while the old
    # range stopped at 400. A search whose range excludes the optimum cannot find
    # it, so the first gbm sweep is discarded rather than reported.
    return {"n_estimators": int(rng.choice([200, 400, 800, 1200, 2000])),
            "learning_rate": float(rng.choice([0.01, 0.02, 0.03, 0.05, 0.1])),
            "num_leaves": int(rng.choice([3, 7, 15, 31, 63])),
            "min_child_samples": int(rng.choice([100, 400, 800, 1600, 3200])),
            # subsample needs subsample_freq >= 1 or LightGBM ignores it; freq 0
            # is kept in the draw so "no bagging" stays a reachable option.
            "subsample": float(rng.choice([0.6, 0.8, 1.0])),
            "subsample_freq": int(rng.choice([0, 1, 5])),
            "colsample_bytree": float(rng.choice([0.4, 0.6, 0.8, 1.0])),
            "reg_lambda": float(rng.choice([0.0, 10.0, 100.0, 1000.0]))}


def sample_cat(rng):
    # Same re-centring as gbm: the scan says this data wants small trees and big
    # leaves, so depth reaches down to 3 and min_data_in_leaf up to 1600.
    return {"iterations": int(rng.choice([300, 600, 1000, 2000])),
            "learning_rate": float(rng.choice([0.02, 0.03, 0.05, 0.1])),
            "depth": int(rng.choice([3, 4, 6, 8])),
            "l2_leaf_reg": float(rng.choice([1.0, 3.0, 10.0, 30.0])),
            "min_data_in_leaf": int(rng.choice([20, 100, 400, 1600]))}


def sample_torch(rng):
    depth = int(rng.choice([2, 3, 4]))
    width = int(rng.choice([32, 64, 128, 256]))
    return {"hidden": [width // (2 ** i) if rng.random() < 0.5 else width
                       for i in range(depth)],
            "dropout": float(rng.choice([0.0, 0.1, 0.2, 0.3])),
            "batchnorm": bool(rng.random() < 0.5),
            "lr": float(rng.choice([3e-4, 1e-3, 3e-3])),
            "weight_decay": float(rng.choice([0.0, 1e-5, 1e-4, 1e-3])),
            "batch_size": int(rng.choice([256, 512, 1024])),
            "epochs": int(rng.choice([20, 40, 60]))}


# ----------------------------------------------------------------- fitters
def fit_cat(params, Xtr, ytr, Xte, enc):
    """CatBoost on the same encoded matrix the other families see.

    Native categorical handling is the reason CatBoost is worth a look, but it
    cannot be used here: Encoder already one-hots 업태 and every downstream
    comparison (ablation, robustness, precompute) consumes that matrix. Feeding
    CatBoost a different design would measure the encoding change, not the model.
    A native-categorical variant is a separate experiment, recorded as untested.
    """
    from catboost import CatBoostClassifier
    m = CatBoostClassifier(random_seed=0, verbose=0, allow_writing_files=False,
                           **params)
    m.fit(enc.transform(Xtr, scale=False), ytr)
    return m.predict_proba(enc.transform(Xte, scale=False))[:, 1]


def fit_torch(params, Xtr, ytr, Xte, enc):
    """Plain MLP in torch. Scaled inputs, BCE loss, no early stopping.

    No early stopping on purpose: a stopping set carved out of the training years
    would be a second validation set, and stopping on the selection set would
    leak it into every configuration's score.
    """
    import torch
    from torch import nn

    torch.manual_seed(0)
    Xa = np.asarray(enc.transform(Xtr, scale=True), dtype=np.float32)
    Xb = np.asarray(enc.transform(Xte, scale=True), dtype=np.float32)
    ya = np.asarray(ytr, dtype=np.float32)

    layers, prev = [], Xa.shape[1]
    for h in params["hidden"]:
        layers.append(nn.Linear(prev, h))
        if params["batchnorm"]:
            layers.append(nn.BatchNorm1d(h))
        layers.append(nn.ReLU())
        if params["dropout"]:
            layers.append(nn.Dropout(params["dropout"]))
        prev = h
    layers.append(nn.Linear(prev, 1))
    net = nn.Sequential(*layers)

    opt = torch.optim.AdamW(net.parameters(), lr=params["lr"],
                            weight_decay=params["weight_decay"])
    lossf = nn.BCEWithLogitsLoss()
    ds = torch.utils.data.TensorDataset(torch.from_numpy(Xa),
                                        torch.from_numpy(ya).unsqueeze(1))
    dl = torch.utils.data.DataLoader(ds, batch_size=params["batch_size"],
                                     shuffle=True, drop_last=True)
    net.train()
    for _ in range(params["epochs"]):
        for xb, yb in dl:
            opt.zero_grad()
            lossf(net(xb), yb).backward()
            opt.step()
    net.eval()
    with torch.no_grad():
        return torch.sigmoid(net(torch.from_numpy(Xb))).numpy().ravel()


FAMILIES = {
    "gbm": (sample_gbm, None),          # None -> go through train.fit_predict
    "cat": (sample_cat, fit_cat),
    "torch": (sample_torch, fit_torch),
}


def score_config(family, params, train, test, cols, enc):
    Xtr, ytr, _ = train
    Xte, yte, _ = test
    sampler, fitter = FAMILIES[family]
    if fitter is None:
        p, _ = fit_predict(family, train, test, num=cols, seed=0, params=params, enc=enc)
    else:
        p = fitter(params, Xtr, ytr, Xte, enc)
    return {"top": top_decile(yte, p), "auc": roc_auc_score(yte, p),
            "gap": (lambda d: d[0] - d[-1])(deciles(yte, p)), "p": p}


def main():
    ap = argparse.ArgumentParser(description="R12 하이퍼파라미터 탐색 (확정 벤치)")
    ap.add_argument("--families", default="gbm,cat,torch")
    ap.add_argument("--budget", type=int, default=0,
                    help="가족별 시도 수 상한 (0 = BUDGET 기본값)")
    a = ap.parse_args()
    fams = [f for f in a.families.split(",") if f in FAMILIES]
    t0 = time.time()
    con = init()
    cols = list(DEPLOY)

    print("=" * 96)
    print(f"R12 하이퍼파라미터 탐색 — 선별은 내부 검증에서만 · 홀드아웃은 승자+현행 1회")
    print(f"사전 등록: 선별 1순위 = 내부검증 상위10% 실측 · 채택 = 짝지은 부트 Δ(상위10%) "
          f"CI 하한 > 0 그리고 점추정 >= +{DECILE_MIN_GAIN*100:.1f}%p 그리고 십분위 단조")
    print("=" * 96)

    tr, va = cached_split(con, INNER_TRAIN, INNER_TEST, 3)
    enc = Encoder(cols).fit(tr[0])
    print(f"\n[선별] train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} / val "
          f"{INNER_TEST[0]}-{INNER_TEST[-1]} (n={len(va[1]):,}) · 세트 DEPLOY({len(cols)})")

    base = score_config("gbm", {}, tr, va, cols, enc)
    print(f"  현행 gbm 기본구성   상위10% {base['top']*100:.2f}%  "
          f"AUC {base['auc']:.4f}  격차 {base['gap']*100:.1f}%p\n")

    rng = np.random.default_rng(SEED)
    results = []
    for fam in fams:
        budget = a.budget or BUDGET[fam]
        sampler, _ = FAMILIES[fam]
        print(f"  --- {fam} · {budget}회 ---", flush=True)
        for i in range(budget):
            params = sampler(rng)
            t1 = time.time()
            try:
                r = score_config(fam, params, tr, va, cols, enc)
            except Exception as e:      # a bad draw must not kill the sweep
                print(f"    {fam}[{i:02d}] FAILED {type(e).__name__}: {e}", flush=True)
                continue
            r.update(family=fam, params=params, secs=time.time() - t1)
            results.append(r)
            mark = " *" if r["top"] > base["top"] else ""
            print(f"    {fam}[{i:02d}] 상위10% {r['top']*100:5.2f}%  AUC {r['auc']:.4f}  "
                  f"격차 {r['gap']*100:4.1f}%p  ({r['secs']:.0f}s){mark}", flush=True)

    if not results:
        print("\n시도가 전부 실패했다 — 홀드아웃을 열지 않는다.")
        return 1

    # selection: top decile, then gap, then AUC (tournament.py decile criterion)
    results.sort(key=lambda r: (-r["top"], -r["gap"], -r["auc"]))
    win = results[0]
    print(f"\n  내부검증 상위 5:")
    for r in results[:5]:
        print(f"    {r['family']:<6} 상위10% {r['top']*100:5.2f}%  AUC {r['auc']:.4f}  "
              f"격차 {r['gap']*100:4.1f}%p  {r['params']}")
    print(f"\n  선별 승자: {win['family']} · 내부검증 상위10% {win['top']*100:.2f}% "
          f"(현행 {base['top']*100:.2f}%, Δ {(win['top']-base['top'])*100:+.2f}%p)")
    print(f"  파라미터: {win['params']}")

    if win["top"] <= base["top"]:
        print(f"\n홀드아웃 확인 생략 — 내부검증에서 현행을 넘지 못했다. R12 기각으로 기록한다.")
        print(f"\n({time.time()-t0:.0f}초 · 시도 {len(results)}건)")
        return 0

    # ---------------------------------------------------------------- holdout
    print(f"\n[확인] 홀드아웃 {CONFIRMED_TEST_YEARS[0]} — 승자와 현행 두 번만")
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS, 3)
    henc = Encoder(cols).fit(train[0])
    y = test[1]
    hb = score_config("gbm", {}, train, test, cols, henc)
    hw = score_config(win["family"], win["params"], train, test, cols, henc)
    # The registered criterion is an interval on the *decile*, not on AUC.
    # tournament.py already owns that estimator; AUC is printed as context only.
    point, lo, hi = paired_bootstrap_decile(y, hw["p"], hb["p"])
    aucd, alo, ahi = paired_bootstrap_ci(y, hw["p"], hb["p"])
    dw = deciles(y, hw["p"])
    mono = all(dw[i] >= dw[i + 1] - 0.02 for i in range(9))

    print(f"  현행 gbm      상위10% {hb['top']*100:.2f}%  AUC {hb['auc']:.4f}")
    print(f"  승자 {win['family']:<9} 상위10% {hw['top']*100:.2f}%  AUC {hw['auc']:.4f}")
    print(f"  짝지은 부트 Δ상위10% {point*100:+.2f}%p  95% CI "
          f"[{lo*100:+.2f}, {hi*100:+.2f}]%p")
    print(f"  (참고) ΔAUC {aucd:+.4f}  95% CI [{alo:+.4f}, {ahi:+.4f}]")
    checks = [("CI 하한 > 0", lo > 0),
              (f"점추정 >= +{DECILE_MIN_GAIN*100:.1f}%p", point >= DECILE_MIN_GAIN),
              ("십분위 단조", mono)]
    for nm, ok in checks:
        print(f"    {nm:<28} {'O' if ok else 'X'}")
    adopt = all(ok for _, ok in checks)
    print(f"  -> R12 {'채택 후보 — DEPLOY/precompute 교체는 별도 승인' if adopt else '기각 (현행 유지)'}")
    print(f"\n({time.time()-t0:.0f}초 · 시도 {len(results)}건)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
