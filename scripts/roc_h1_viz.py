"""ROC + threshold-metrics figure for the 1-year (contract-term) bench.

Six candidate families on train 2005-2024 / test 2025 / horizon 1 / NUM2
(store conditions included). Model *selection* stays where it happened - the
2019-2022 selection bench (model-findings.md 7-A); this figure re-confirms the
incumbent on the contract-term task the deck now leads with.

Thresholded metrics follow model/clf_metrics.py discipline: every cut point is
derived from that model's TRAIN predictions only (survive-F1 at train f1max,
closure precision at fixed 0.5), never from the holdout.

Read-only: reuses the disk-cached split; fails loudly if it is missing.

Usage:  python scripts/roc_h1_viz.py [--out docs/figures]
"""
import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import f1_score, precision_score, roc_auc_score, roc_curve

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from roc_viz import (AXIS, DASHES, GRID, INK, INK2, MODELS, MUTED, SERIES,  # noqa: E402
                     SURFACE, require_split, setup_style)
from model.clf_metrics import best_f1_threshold                             # noqa: E402
from model.train import NUM2, Encoder, fit_predict                          # noqa: E402

TRAIN_YEARS = list(range(2005, 2025))
TEST_YEARS = [2025]
HORIZON = 1


def metrics_row(kind, train, test, enc):
    p_te, _ = fit_predict(kind, train, test, num=NUM2, seed=0, enc=enc)
    p_tr, _ = fit_predict(kind, train, train, num=NUM2, seed=0, enc=enc)
    y_te, y_tr = np.asarray(test[1]), np.asarray(train[1])

    t_f1 = best_f1_threshold(y_tr, p_tr)
    yhat = (p_te >= t_f1).astype(int)
    row = {
        "auc": roc_auc_score(y_te, p_te),
        "f1_surv": f1_score(y_te, yhat),
        "macro": (f1_score(y_te, yhat)
                  + f1_score(y_te, yhat, pos_label=0, zero_division=0)) / 2,
        "prec_close": precision_score(y_te, (p_te >= 0.5).astype(int),
                                      pos_label=0, zero_division=0),
        "p": p_te,
    }
    print(f"  {kind:<6} AUC {row['auc']:.4f}  생존F1 {row['f1_surv']:.4f}  "
          f"폐업P {row['prec_close']:.4f}  macro {row['macro']:.4f}", flush=True)
    return row


def fig_roc_h1(rows, y, n_test, out):
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(13, 5.6), gridspec_kw={"width_ratios": [1.2, 1]})

    axL.plot([0, 1], [0, 1], color=AXIS, lw=1.2, ls=(0, (3, 3)), zorder=1)
    axL.text(0.62, 0.55, "무작위 (AUC 0.500)", color=MUTED, fontsize=9, rotation=38)

    # Colour follows the model, never its rank (same slots as fig1).
    order = sorted(range(len(MODELS)), key=lambda i: -rows[i]["auc"])
    for i in order:
        kind, label = MODELS[i]
        r = rows[i]
        fpr, tpr, _ = roc_curve(y, r["p"])
        incumbent = kind == "gbm"
        style = {"dashes": DASHES[i]} if DASHES[i] else {}
        axL.plot(fpr, tpr, color=SERIES[i], lw=2.8 if incumbent else 1.9,
                 label=f"{label}  ·  AUC {r['auc']:.4f}", **style,
                 zorder=5 if incumbent else 3, alpha=1.0 if incumbent else 0.88)

    axL.set_xlim(0, 1)
    axL.set_ylim(0, 1)
    axL.set_xlabel("거짓 양성률 (실제 폐업을 생존으로 본 비율)")
    axL.set_ylabel("참 양성률 (실제 생존을 맞힌 비율)")
    axL.set_title("후보 6종 ROC — 1년 생존 예측", color=INK, fontsize=13,
                  fontweight="bold", loc="left", pad=12)
    axL.legend(loc="lower right", frameon=True, facecolor=SURFACE,
               edgecolor=GRID, fontsize=9.5, labelcolor=INK2)

    # Right panel: the comparison table. Text wears ink, never series color;
    # a swatch square beside each row carries identity instead.
    axR.set_axis_off()
    cols = [("AUC", "auc"), ("생존 F1", "f1_surv"),
            ("폐업 정밀도", "prec_close"), ("macro-F1", "macro")]
    x_model, x_vals = 0.02, [0.44, 0.62, 0.815, 0.99]
    y_top, dy = 0.86, 0.115

    axR.text(x_model, y_top + dy * 0.9, "모델", fontsize=10, color=MUTED,
             fontweight="bold")
    for (name, _), xv in zip(cols, x_vals):
        axR.text(xv, y_top + dy * 0.9, name, fontsize=10, color=MUTED,
                 fontweight="bold", ha="right")
    axR.axhline(y_top + dy * 0.45, xmin=0.01, xmax=0.99, color=GRID, lw=1.2)

    for pos, i in enumerate(order):
        kind, label = MODELS[i]
        r = rows[i]
        yy = y_top - pos * dy
        best = pos == 0
        axR.add_patch(plt.Rectangle((x_model, yy - 0.018), 0.035, 0.055,
                                    color=SERIES[i], transform=axR.transAxes,
                                    clip_on=False))
        axR.text(x_model + 0.055, yy, label, fontsize=10,
                 color=INK if best else INK2,
                 fontweight="bold" if best else "normal")
        for (_, key), xv in zip(cols, x_vals):
            axR.text(xv, yy, f"{r[key]:.3f}", fontsize=10, ha="right",
                     color=INK if best else INK2,
                     fontweight="bold" if best else "normal")

    axR.set_title("같은 스플릿 · 같은 인코더 · 임계값은 train에서만",
                  color=INK, fontsize=13, fontweight="bold", loc="left", pad=12)

    fig.suptitle(
        f"왜 LightGBM인가 — 후보 6종, 계약기간(1년) 생존 예측  "
        f"(학습 2005–2024 / 검증 2025, n={n_test:,})",
        color=INK, fontsize=15, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.015,
             "피처 NUM2 21개(점포조건 포함) · 각 후보 기본 설정 · seed=0. "
             "생존 F1·macro-F1은 각 모델의 train F1 최대 임계, 폐업 정밀도는 t=0.5. "
             "모델 선정 자체는 2019–2022 선발 무대에서 확정(§7-A); 이 그림은 1년 과제 재확인이다.",
             color=MUTED, fontsize=9)
    fig.tight_layout(rect=[0, 0.035, 1, 0.945])
    fig.savefig(out, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    a = ap.parse_args()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    setup_style()

    print(f"1년 벤치 — 학습 {TRAIN_YEARS[0]}–{TRAIN_YEARS[-1]} / 검증 {TEST_YEARS[0]} / NUM2")
    train, test = require_split(TRAIN_YEARS, TEST_YEARS, HORIZON)
    enc = Encoder(NUM2).fit(train[0])
    rows = [metrics_row(kind, train, test, enc) for kind, _ in MODELS]

    out = outdir / "fig8-roc-h1-6models.png"
    fig_roc_h1(rows, test[1], len(test[1]), out)
    print(f"완료 — {out}  {out.stat().st_size/1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
