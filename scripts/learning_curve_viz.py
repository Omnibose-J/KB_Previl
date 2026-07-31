"""Learning-curve / regularisation figures for the technical deck.

Reads the measurements written by `model.learning_curve --json` and draws them.
It does not fit anything: the numbers in the deck and the numbers in
docs/model-findings.md §26 must come from one measurement, and a figure script
that re-fits would eventually disagree with the text by a decimal.

Three panels, because they answer three different questions and a reader who
sees only one of them draws the wrong conclusion:

  A  cohort axis   "would more history help?"      -> flat, so no
  B  row axis      "would more rows help?"         -> saturates near 120k
  C  regularisation "is overfitting the binding constraint?" -> yes on internal
                    validation, and that gain did not survive the holdout (§26-D)

Panel C carries the caveat in its subtitle rather than in a caption someone can
crop away.

Usage:  python scripts/learning_curve_viz.py [--json docs/figures/learning-curve.json]
"""
import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Same palette as scripts/roc_viz.py so the deck reads as one set.
SURFACE, INK, INK2 = "#FBF9F6", "#1A1613", "#4A423B"
MUTED, GRID, AXIS = "#8A7F74", "#E5DED5", "#C9BFB3"
VAL, TRAIN, MARK = "#1F6F5C", "#B8860B", "#B23A3A"


def setup_style():
    for family in ("Malgun Gothic", "NanumGothic", "AppleGothic"):
        if any(family == f.name for f in matplotlib.font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = family
            break
    plt.rcParams.update({
        "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK2,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "grid.color": GRID, "grid.linewidth": 0.8,
        "axes.grid": True, "axes.axisbelow": True,
        "axes.unicode_minus": False, "savefig.facecolor": SURFACE,
    })


def axis_rows(rows, axis):
    return [r for r in rows if r["axis"] == axis]


def draw_curve(ax, rows, xlabel, title, note):
    xs = list(range(len(rows)))
    ax.plot(xs, [r["val_top"] * 100 for r in rows], "-o", color=VAL, lw=2,
            ms=5, label="검증 상위10% 실측")
    ax.plot(xs, [r["tr_auc"] * 100 for r in rows], "--s", color=TRAIN, lw=1.5,
            ms=4, alpha=0.85, label="학습 AUC ×100")
    ax.plot(xs, [r["val_auc"] * 100 for r in rows], ":^", color=INK2, lw=1.5,
            ms=4, alpha=0.7, label="검증 AUC ×100")
    ax.set_xticks(xs)
    ax.set_xticklabels([r["label"].replace(" rows", "") for r in rows],
                       rotation=30, ha="right", fontsize=8.5)
    ax.set_xlabel(xlabel, fontsize=9.5)
    # pad must clear the note line below it, or the title overprints it.
    ax.set_title(title, color=INK, fontsize=12, fontweight="bold", loc="left", pad=24)
    ax.text(0, 1.015, note, transform=ax.transAxes, color=MUTED, fontsize=8.5,
            va="bottom")
    ax.tick_params(labelsize=8.5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default="docs/figures/learning-curve.json")
    ap.add_argument("--out", default="docs/figures/fig7-learning-curve.png")
    a = ap.parse_args()

    src = Path(a.json)
    if not src.exists():
        print(f"{src} 없음 — 먼저 `python -m model.learning_curve --json {src}` 를 돌린다",
              file=sys.stderr)
        return 1
    payload = json.loads(src.read_text(encoding="utf-8"))
    rows = payload["rows"]

    cohorts = axis_rows(rows, "cohorts")
    rowsax = axis_rows(rows, "rows")
    # One regularisation knob per panel would need five panels; the strongest one
    # is drawn and the rest live in the §26-C table.
    reg = axis_rows(rows, "regular:reg_lambda")
    if not (cohorts and rowsax and reg):
        print("세 축이 모두 필요하다 — `--axis cohorts,rows,regular` 로 다시 측정할 것",
              file=sys.stderr)
        return 1

    setup_style()
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 5.0))

    draw_curve(axes[0], cohorts, "학습 시작연도 (검증 2021–22 고정)",
               "A. 더 오래된 이력을 넣으면?",
               "2.7배로 늘려도 평평하다 — 최고점이 중간(2007)이다")
    draw_curve(axes[1], rowsax, "같은 창의 무작위 부분표본",
               "B. 행을 더 넣으면?",
               "약 12만 행에서 포화 · 현행 학습셋은 그 1.6배")
    # ASCII hyphen, not U+2212: Malgun Gothic has no MINUS SIGN glyph and renders
    # it as a box in the exported PNG.
    draw_curve(axes[2], reg, "reg_lambda (L2)",
               "C. 과적합을 조이면?",
               "내부검증에선 오른다 — 그러나 홀드아웃에서 -0.25%p (§26-D)")

    axes[0].legend(loc="lower right", frameon=True, facecolor=SURFACE,
                   edgecolor=GRID, fontsize=8.5, labelcolor=INK)
    axes[0].set_ylabel("퍼센트", fontsize=9.5)

    fig.suptitle("AUC 0.6369 는 측정된 상한이다 — 학습곡선·정규화 진단",
                 color=INK, fontsize=14, fontweight="bold", x=0.008, ha="left", y=0.985)
    fig.text(0.008, 0.925,
             f"모델 {payload['model']} · 세트 {payload['features']}"
             f"({payload['n_features']}) · 검증 {payload['val_years'][0]}–"
             f"{payload['val_years'][-1]} n={payload['val_n']:,} · 홀드아웃 미개방",
             color=MUTED, fontsize=9.5, ha="left")
    fig.tight_layout(rect=[0, 0, 1, 0.90])

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170)
    print(f"{out}  ({out.stat().st_size/1000:.0f} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
