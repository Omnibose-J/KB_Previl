"""ROC / AUC figures for the technical deck.

Read-only. Every fit reuses the disk-cached splits under model/.cache. The
script reads the licence summary needed to select the matching data-fingerprinted
cache path through a read-only database connection. If a split is missing the
script fails loudly rather than silently rebuilding it.

Two benches, deliberately kept apart:

  SELECTION bench   train 2005-2018 / test 2019-2022  -- where the six-family
                    tournament actually ran. Exposure-spent, so comparing six
                    candidates on it costs nothing that was not already spent.
  HEADLINE bench    train 2005-2022 / test 2023       -- the fresh holdout the
                    deployed model is measured on. Only the incumbent and the
                    no-learning baseline are drawn here; putting six candidates
                    on this axis would turn the holdout into a validation set.

Usage:  python scripts/roc_viz.py [--out docs/figures]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import PercentFormatter
from sklearn.metrics import roc_auc_score, roc_curve

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from model.cache import cached_split, fingerprint, split_cache_path   # noqa: E402
from model.evaluate import baseline_prior_surv                        # noqa: E402
from model.train import (CONFIRMED_TEST_YEARS, CONFIRMED_TRAIN_YEARS,  # noqa: E402
                         DEPLOY, LEGACY_TRAIN_YEARS, Encoder, fit_predict)
from pipeline.db import connect_ro                                    # noqa: E402
from pipeline.grade_bands import GRADE_COUNT                           # noqa: E402

SELECT_TEST_YEARS = [2019, 2020, 2021, 2022]

# --- palette (dataviz reference instance, light mode; validated 6 slots) ------
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300"]
# Secondary encoding: three slots sit below 3:1 on this surface, so identity
# never rests on hue alone (dataviz relief rule). None = solid.
DASHES = [None, (6, 2), (2, 2), (8, 2, 2, 2), (4, 1, 1, 1), (1, 1.6)]

MODELS = [
    ("gbm", "LightGBM (현행)"),
    ("rf", "RandomForest"),
    ("et", "ExtraTrees"),
    ("hgb", "HistGradientBoosting"),
    ("logit", "로지스틱 회귀"),
    ("mlp", "MLP (신경망)"),
]

GROUP_KO = {
    "G1_competition": "G1 경쟁·집적",
    "G2_dynamics": "G2 동학 (교체·급증·폐업가속)",
    "G3_prior_survival": "G3 과거 생존",
    "G5_grid_physical": "G5 격자 물리 (이웃 면적)",
    "G6_store_attrs": "G6 면적 — 점포 속성, 순위 제외",
    "G8_tier1_rederived": "G8 인허가 재파생 — 편입 기각",
    "G9_tier2_rest": "G9 휴게음식점 — 편입 기각",
    "G4_access": "G4 지하철 접근성 — 부표",
    "G7_trend": "G7 검색 트렌드 — 부표",
    "G10_tier3_ridership": "G10 지하철 승하차 — 부표",
}
# Groups measured on a sub-bench or excluded from ranking by policy; drawn in a
# recessive tone so they are never read as deploy-set contributors.
OFF_SET = {"G6", "G8", "G9", "G4", "G7", "G10"}
# A positive CI is not the last word: the trend group cleared the ablation and
# was then killed by the placebo control (§8-G). Reading the verdict off `lo`
# alone would put a rejected source on stage as a contributor.
OVERRIDE_VERDICT = {"G7_trend": "위약 대조에서 기각"}


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


def require_split(train_years, test_years, horizon=3):
    con = connect_ro()
    try:
        path = split_cache_path(con, train_years, test_years, horizon)
        if not path.exists():
            raise SystemExit(
                f"필요한 스플릿 캐시가 없다: {path.name}\n"
                "  이 스크립트는 캐시만 읽는다. 먼저 해당 벤치를 한 번 만들어야 한다."
            )
        return cached_split(con, train_years, test_years, horizon)
    finally:
        con.close()


def fit_all(train, test, cols):
    """One seed=0 fit per family at its default settings -- the same construction
    service/precompute.py deploys. Hyperparameter search is NOT repeated here;
    §7-A of model-findings.md holds that table."""
    enc = Encoder(cols).fit(train[0])
    out = []
    for kind, label in MODELS:
        p, _ = fit_predict(kind, train, test, num=cols, seed=0, enc=enc)
        out.append((kind, label, p, roc_auc_score(test[1], p)))
        print(f"  {kind:<6} AUC {out[-1][3]:.4f}", flush=True)
    return out


def fig_roc_six(results, y, n_test, out):
    fig, (axL, axR) = plt.subplots(
        1, 2, figsize=(13, 5.6), gridspec_kw={"width_ratios": [1.35, 1]})

    axL.plot([0, 1], [0, 1], color=AXIS, lw=1.2, ls=(0, (3, 3)), zorder=1)
    axL.text(0.62, 0.55, "무작위 (AUC 0.500)", color=MUTED, fontsize=9, rotation=34)

    # Colour follows the model, never its rank: re-sorting the legend must not
    # repaint a curve.
    order = sorted(range(len(results)), key=lambda i: -results[i][3])
    for i in order:
        kind, label, p, auc = results[i]
        fpr, tpr, _ = roc_curve(y, p)
        incumbent = kind == "gbm"
        style = {"dashes": DASHES[i]} if DASHES[i] else {}
        axL.plot(fpr, tpr, color=SERIES[i], lw=2.8 if incumbent else 1.9,
                 label=f"{label}  ·  AUC {auc:.4f}", **style,
                 zorder=5 if incumbent else 3, alpha=1.0 if incumbent else 0.88)

    axL.set_xlim(0, 1)
    axL.set_ylim(0, 1)
    axL.set_xlabel("거짓 양성률 (실제 폐업을 생존으로 본 비율)")
    axL.set_ylabel("참 양성률 (실제 생존을 맞힌 비율)")
    axL.set_title("후보 6종 ROC — 선발 무대", color=INK, fontsize=13,
                  fontweight="bold", loc="left", pad=12)
    axL.legend(loc="lower right", frameon=True, facecolor=SURFACE,
               edgecolor=GRID, fontsize=9.5, labelcolor=INK2)

    aucs = [results[i][3] for i in order]
    labels = [results[i][1] for i in order]
    ypos = np.arange(len(order))[::-1]
    axR.barh(ypos, aucs, height=0.62, color=[SERIES[i] for i in order], zorder=3)
    axR.axvline(0.5, color=AXIS, lw=1.2, ls=(0, (3, 3)), zorder=2)
    for yy, a in zip(ypos, aucs):
        axR.text(a + 0.004, yy, f"{a:.4f}", va="center", fontsize=10,
                 color=INK, fontweight="bold")
    axR.set_yticks(ypos)
    axR.set_yticklabels(labels, fontsize=10, color=INK2)
    axR.set_xlim(0.5, max(aucs) + 0.035)
    axR.set_xlabel("홀드아웃 AUC")
    axR.set_title("같은 조건, 같은 스플릿", color=INK, fontsize=13,
                  fontweight="bold", loc="left", pad=12)
    axR.grid(axis="y", visible=False)

    fig.suptitle(
        f"모델을 바꿔서 얻은 것은 없다 — 후보 6종 비교  (학습 2005–2018 / 검증 2019–2022, n={n_test:,})",
        color=INK, fontsize=15, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.015,
             "각 후보의 기본 설정 · seed=0 · 동일 인코더 · 피처 LOC2 20개. "
             "하이퍼파라미터 탐색 결과는 model-findings.md §7-A 참조.",
             color=MUTED, fontsize=9)
    fig.tight_layout(rect=[0, 0.035, 1, 0.945])
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_roc_deploy(p_model, p_base, y, n_test, out):
    fig, ax = plt.subplots(figsize=(7.6, 6.4))
    auc_m = roc_auc_score(y, p_model)
    auc_b = roc_auc_score(y, p_base)

    fpr, tpr, _ = roc_curve(y, p_model)
    fpr_b, tpr_b, _ = roc_curve(y, p_base)

    ax.plot([0, 1], [0, 1], color=AXIS, lw=1.2, ls=(0, (3, 3)), zorder=1)
    # Shade the gap the headline actually quotes: model minus baseline, not
    # model minus the diagonal.
    grid = np.linspace(0, 1, 500)
    t_model = np.interp(grid, fpr, tpr)
    t_base = np.interp(grid, fpr_b, tpr_b)
    ax.fill_between(grid, t_base, t_model, where=t_model >= t_base,
                    color=SERIES[0], alpha=0.14, zorder=2)
    ax.plot(fpr_b, tpr_b, color=SERIES[1], lw=2.0, dashes=(6, 2), zorder=3,
            label=f"베이스라인 · 그 칸의 과거 생존율  ·  AUC {auc_b:.4f}")
    ax.plot(fpr, tpr, color=SERIES[0], lw=2.8, zorder=4,
            label=f"배포 모델 · LightGBM  ·  AUC {auc_m:.4f}")

    ax.text(0.63, 0.34, f"학습으로 얻은 몫\nΔAUC +{auc_m - auc_b:.4f}",
            color=INK2, fontsize=10.5, ha="center")
    ax.annotate("", xy=(0.50, 0.585), xytext=(0.61, 0.40),
                arrowprops=dict(arrowstyle="->", color=MUTED, lw=1.2))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("거짓 양성률")
    ax.set_ylabel("참 양성률", labelpad=10)
    ax.set_title("배포 모델 ROC — 신선 홀드아웃",
                 color=INK, fontsize=15, fontweight="bold", loc="left", pad=14)
    ax.legend(loc="lower right", frameon=True, facecolor=SURFACE,
              edgecolor=GRID, fontsize=10, labelcolor=INK2)
    fig.text(0.012, 0.015,
             f"학습 2005–2022 / 검증 2023 (n={n_test:,}) · 피처 LOC2 20개 · seed=0. "
             "2023 코호트는 어떤 라운드에서도 조회된 적이 없다.",
             color=MUTED, fontsize=9)
    fig.tight_layout(rect=[0, 0.035, 1, 1])
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_ablation(path_json, out):
    data = json.loads(Path(path_json).read_text(encoding="utf-8"))
    rows = sorted(data["groups"], key=lambda g: g["delta"])
    fig, ax = plt.subplots(figsize=(12.6, 7.0))

    ypos = np.arange(len(rows))
    for i, g in enumerate(rows):
        tag = g["group"].split("_")[0]
        contributes = g["lo"] > 0
        off = tag in OFF_SET
        color = MUTED if off else (SERIES[0] if contributes else AXIS)
        ax.barh(i, g["delta"], height=0.6, color=color, zorder=3,
                alpha=0.55 if off else 1.0)
        ax.plot([g["lo"], g["hi"]], [i, i], color=INK2, lw=1.6, zorder=4)
        ax.plot([g["lo"], g["lo"]], [i - .12, i + .12], color=INK2, lw=1.6, zorder=4)
        ax.plot([g["hi"], g["hi"]], [i - .12, i + .12], color=INK2, lw=1.6, zorder=4)
        verdict = OVERRIDE_VERDICT.get(
            g["group"], "기여" if contributes else "판별 불가")
        ax.text(g["hi"] + 0.0012, i, f"{g['delta']:+.4f}  {verdict}",
                va="center", fontsize=9.5, color=INK if not off else MUTED)

    ax.axvline(0, color=AXIS, lw=1.4, zorder=2)
    ax.set_yticks(ypos)
    ax.set_yticklabels([GROUP_KO.get(g["group"], g["group"]) for g in rows],
                       fontsize=10, color=INK2)
    ax.set_xlabel("절제 ΔAUC — 이 피처군을 빼면 잃는 정확도 (95% CI)")
    ax.set_xlim(-0.004, max(g["hi"] for g in rows) + 0.016)
    ax.grid(axis="y", visible=False)
    ax.set_title("어떤 정보가 실제로 기여하는가 — 피처군 절제표",
                 color=INK, fontsize=15, fontweight="bold", loc="left", pad=14)
    fig.text(0.010, 0.032,
             "회색 = 순위 모델에 넣지 않는 군 — 점포 속성이거나, 편입이 기각됐거나, "
             "학습 표본이 달라 부표에서만 잰 군이다 (부표 값은 위 행들과 직접 비교 불가).",
             color=MUTED, fontsize=9)
    fig.text(0.010, 0.010,
             "CI가 0을 포함하면 «기여 0»이 아니라 «판별 불가»로 읽는다.  "
             "gbm · 시드 5개 평균 · 짝지은 부트스트랩 200회 · 벤치 2019–2022.",
             color=MUTED, fontsize=9)
    fig.tight_layout(rect=[0, 0.055, 1, 1])
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_decile(db, out):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = dict(con.execute("SELECT k, v FROM score_meta").fetchall())
    con.close()
    obs = [float(x) for x in meta["observed_by_grade"].split(",")]
    lo = [float(x) for x in meta["observed_by_grade_ci_low"].split(",")]
    hi = [float(x) for x in meta["observed_by_grade_ci_high"].split(",")]
    n = [int(x) for x in meta["observed_by_grade_n"].split(",")]
    overall = float(meta["overall_survival"])

    fig, ax = plt.subplots(figsize=(11, 6.2))
    x = np.arange(1, GRADE_COUNT + 1)
    tails = (0, GRADE_COUNT - 1)
    colors = [SERIES[0] if i in tails else "#9ec5f4" for i in range(GRADE_COUNT)]
    ax.bar(x, obs, width=0.66, color=colors, zorder=3)
    ax.errorbar(x, obs, yerr=[np.array(obs) - lo, np.array(hi) - np.array(obs)],
                fmt="none", ecolor=INK2, elinewidth=1.6, capsize=5, zorder=4)
    ax.axhline(overall, color=SERIES[1], lw=1.8, dashes=(6, 2), zorder=2)
    ax.text(GRADE_COUNT + 0.52, overall + 0.014,
            f"전체 평균 {overall*100:.1f}%", color=SERIES[1],
            fontsize=10.5, ha="right", va="bottom", fontweight="bold")

    for i in tails:
        ax.text(x[i], hi[i] + 0.022, f"{obs[i]*100:.1f}%", ha="center",
                fontsize=14, fontweight="bold", color=INK)
    # The gap is stated, not drawn across the bars: an arrow spanning all bars
    # collides with every one of them.
    label_x = (GRADE_COUNT + 1) / 2 + 1
    ax.text(label_x, 0.90, f"등급 격차 {(obs[0]-obs[-1])*100:.1f}%p",
            ha="center", fontsize=15, fontweight="bold", color=INK)
    ax.text(label_x, 0.845,
            f"1등급과 {GRADE_COUNT}등급의 실측 생존율 차이", ha="center",
            fontsize=10, color=MUTED)

    ax.set_xticks(x)
    ax.set_xticklabels([f"{i}등급" for i in x], fontsize=10, color=INK2)
    ax.set_xlim(0.4, GRADE_COUNT + 0.6)
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.set_ylabel("실측 3년 생존율", labelpad=10)
    ax.grid(axis="x", visible=False)
    ax.set_title("등급은 실제로 생존을 가른다 — 홀드아웃 실측",
                 color=INK, fontsize=15, fontweight="bold", loc="left", pad=14)
    fig.text(0.010, 0.015,
             f"2023년 개업 코호트 · 등급당 n = {min(n):,}~{max(n):,} · 오차막대 = 95% 신뢰구간. "
             "등급은 홀드아웃의 내신형 9등급 절대 경계이며, 막대는 예측이 아니라 그 등급 자리에서 "
             "실제로 관측된 생존율이다.",
             color=MUTED, fontsize=9)
    fig.tight_layout(rect=[0, 0.04, 1, 1])
    fig.savefig(out, dpi=200)
    plt.close(fig)


def fig_area_tradeoff(tr, te, out):
    """The one lever that provably raises AUC -- and the reason it stays unused.

    Shop area is the single strongest predictor available, but the product ranks
    *locations* for a user who supplies the area, so it takes the same value on
    every candidate. Ranking on it would predict capital, not place.
    """
    from model.train import NUM2

    y = te[1]
    bars = []
    for cols, tag, usable in ((None, "베이스라인\n그 칸의 과거 생존율", True),
                              (DEPLOY, "배포 모델\n입지 20개", True),
                              (["site_area"], "면적 단독\n피처 1개", False),
                              (NUM2, "배포 + 면적\n21개", False)):
        if cols is None:
            p = baseline_prior_surv(tr[0], tr[1], te[0])
        else:
            enc = Encoder(cols).fit(tr[0])
            p, _ = fit_predict("gbm", tr, te, num=cols, seed=0, enc=enc)
        o = np.argsort(-p)
        ys = np.asarray(y)[o]
        n = len(ys)
        d = [float(ys[int(n * i / 10):int(n * (i + 1) / 10)].mean()) for i in range(10)]
        bars.append((tag, roc_auc_score(y, p), (d[0] - d[-1]) * 100, usable))
        print(f"  {tag.splitlines()[0]:<12} AUC {bars[-1][1]:.4f}  격차 {bars[-1][2]:.1f}%p",
              flush=True)

    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 6.0))
    xs = np.arange(len(bars))
    labels = [b[0] for b in bars]
    # Excluded bars get a darker neutral so the white "사용 불가" stamp holds
    # contrast against them.
    colors = [SERIES[0] if b[3] else "#6f6e69" for b in bars]
    colors[0] = SERIES[1]

    for ax, vals, ylab, fmt, title in (
            (a1, [b[1] for b in bars], "홀드아웃 AUC", "{:.4f}", "정확도 (AUC)"),
            (a2, [b[2] for b in bars], "십분위 격차 (%p)", "{:.1f}%p", "제품 지표 (십분위 격차)")):
        ax.bar(xs, vals, width=0.62, color=colors, zorder=3)
        for xx, v in zip(xs, vals):
            ax.text(xx, v + (max(vals) * 0.015), fmt.format(v), ha="center",
                    fontsize=11.5, fontweight="bold", color=INK)
        ax.set_xticks(xs)
        ax.set_xticklabels(labels, fontsize=9.5, color=INK2)
        ax.set_ylabel(ylab)
        ax.set_ylim(0, max(vals) * 1.20)
        ax.set_title(title, color=INK, fontsize=12.5, fontweight="bold",
                     loc="left", pad=10)
        ax.grid(axis="x", visible=False)
        for xx, v, b in zip(xs, vals, bars):
            if not b[3]:
                ax.text(xx, v * 0.5, "순위에\n사용 불가", ha="center", va="center",
                        fontsize=10, color="#ffffff", fontweight="bold",
                        linespacing=1.5, zorder=5)

    fig.suptitle("AUC는 더 올릴 수 있다 — 올리지 않는 이유",
                 color=INK, fontsize=15, fontweight="bold", x=0.012, ha="left", y=0.985)
    fig.text(0.012, 0.055,
             "면적은 단일 최강 예측자다. 면적 하나만으로 AUC "
             f"{bars[2][1]:.4f}로, 입지 피처 20개를 쓴 배포 모델({bars[1][1]:.4f})보다 높다.",
             color=INK2, fontsize=10)
    fig.text(0.012, 0.020,
             "그런데도 순위에서 뺀다 — 추천은 «어느 자리가 좋은가»를 가리는 일이고, "
             "면적은 사용자가 정하므로 모든 후보에 같은 값이 들어가 순위를 가르지 못한다. "
             "넣으면 입지 예측기가 아니라 자본력 예측기가 된다.",
             color=MUTED, fontsize=9.5)
    fig.tight_layout(rect=[0, 0.085, 1, 0.945])
    fig.savefig(out, dpi=200)
    plt.close(fig)


SPLIT_SQL = """
SELECT a.trdar_nm, s.grade, COUNT(*) AS n, MAX(f.sales_amt) AS sales
FROM grid_score s
JOIN grid_feature f ON f.grid_id = s.grid_id
JOIN trdar_area a ON a.trdar_cd = f.trdar_cd
WHERE s.uptae = ? AND f.has_sales_data = 1
GROUP BY f.trdar_cd, s.grade
"""


def fig_area_split(db, out, uptae="한식", top=10):
    """Same trade area, same sales figure, across all served grades.

    This is the one comparison with no leakage exposure: the trade-area metrics
    are not model inputs, and the contrast is resolution against resolution
    rather than prediction against outcome. A trade area carries ONE sales
    number, so every cell in the row below is tied on it.
    """
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(SPLIT_SQL, (uptae,)).fetchall()
    con.close()

    areas = {}
    for name, grade, n, sales in rows:
        a = areas.setdefault(name, {"g": {}, "sales": sales or 0})
        a["g"][grade] = n
    # Keep only areas that actually straddle the scale, then take the largest.
    split = {k: v for k, v in areas.items()
             if 1 in v["g"] and GRADE_COUNT in v["g"]}
    picked = sorted(split.items(), key=lambda kv: -sum(kv[1]["g"].values()))[:top]
    picked.reverse()
    print(
        f"  대상 상권 {len(areas):,}개 중 "
        f"1등급·{GRADE_COUNT}등급 공존 {len(split)}개"
    )

    fig, ax = plt.subplots(figsize=(12.4, 6.8))
    maxn = max(n for _, v in picked for n in v["g"].values())
    for i, (name, v) in enumerate(picked):
        gs = sorted(v["g"])
        ax.plot([min(gs), max(gs)], [i, i], color=GRID, lw=6, solid_capstyle="round",
                zorder=2)
        for g, n in v["g"].items():
            edge = g in (1, GRADE_COUNT)
            ax.scatter(g, i, s=90 + 900 * (n / maxn), zorder=4,
                       color=SERIES[0] if edge else "#9ec5f4",
                       edgecolors=SURFACE, linewidths=1.5)
            if n >= 6:
                ax.text(g, i, str(n), ha="center", va="center", zorder=5,
                        fontsize=8.5, color="#ffffff", fontweight="bold")
        ax.text(GRADE_COUNT + 0.75, i, f"{v['sales']/1e8:,.0f}억",
                va="center", ha="right",
                fontsize=9.5, color=INK2)

    ax.set_yticks(range(len(picked)))
    ax.set_yticklabels([n[:18] for n, _ in picked], fontsize=10, color=INK2)
    ax.set_xticks(range(1, GRADE_COUNT + 1))
    ax.set_xticklabels(
        [f"{g}" for g in range(1, GRADE_COUNT + 1)],
        fontsize=10,
        color=INK2,
    )
    ax.set_xlim(0.3, GRADE_COUNT + 0.9)
    ax.set_ylim(-0.7, len(picked) - 0.3)
    ax.set_xlabel(
        f"입지 등급  (1 = 최상위 · {GRADE_COUNT} = 최하위)"
        " — 원 크기 = 그 등급의 격자 수"
    )
    ax.grid(axis="y", visible=False)
    ax.text(GRADE_COUNT + 0.75, len(picked) - 0.45, "상권 월매출",
            ha="right", fontsize=9,
            color=MUTED, fontweight="bold")
    ax.set_title(
        f"같은 상권, 같은 매출 — 그런데 자리는 "
        f"1등급부터 {GRADE_COUNT}등급까지 ({uptae})",
                 color=INK, fontsize=15, fontweight="bold", loc="left", pad=14)
    fig.text(0.010, 0.032,
             "상권 하나에는 매출·유동인구 값이 하나뿐이라, 한 줄에 놓인 격자들은 그 지표에서 전부 동점이다. "
             "상권 단위 분석으로는 이 줄 안의 차이를 원리적으로 볼 수 없다.",
             color=INK2, fontsize=9.5)
    fig.text(0.010, 0.010,
             f"«{uptae}» 기준 · 매출 데이터가 있는 상권만 · 등급은 서울 전역 홀드아웃의 내신형 9등급 절대 기준이다.",
             color=MUTED, fontsize=9)
    fig.tight_layout(rect=[0, 0.055, 1, 1])
    fig.savefig(out, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "figures"))
    a = ap.parse_args()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    setup_style()

    print(f"피처 코드 지문 {fingerprint()}")

    print("\n[1/5] 선발 무대 — 후보 6종 (학습 2005–2018 / 검증 2019–2022)")
    tr, te = require_split(LEGACY_TRAIN_YEARS, SELECT_TEST_YEARS)
    res = fit_all(tr, te, DEPLOY)
    fig_roc_six(res, te[1], len(te[1]), outdir / "fig1-roc-6models.png")

    print("\n[2/4] 헤드라인 무대 — 배포 모델 (학습 2005–2022 / 검증 2023)")
    tr2, te2 = require_split(CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS)
    enc = Encoder(DEPLOY).fit(tr2[0])
    p, _ = fit_predict("gbm", tr2, te2, num=DEPLOY, seed=0, enc=enc)
    base = baseline_prior_surv(tr2[0], tr2[1], te2[0])
    print(f"  gbm AUC {roc_auc_score(te2[1], p):.4f}  "
          f"baseline {roc_auc_score(te2[1], base):.4f}")
    fig_roc_deploy(p, base, te2[1], len(te2[1]), outdir / "fig2-roc-deploy.png")

    print("\n[3/5] 피처군 절제표")
    fig_ablation(ROOT / "model" / ".cache" / "ablation.json",
                 outdir / "fig3-ablation.png")

    print("\n[4/5] 등급별 실측 생존율")
    fig_decile(ROOT / "kb.db", outdir / "fig4-decile.png")

    print("\n[5/6] 면적 트레이드오프")
    fig_area_tradeoff(tr2, te2, outdir / "fig5-area-tradeoff.png")

    print("\n[6/6] 같은 상권, 갈리는 등급")
    fig_area_split(ROOT / "kb.db", outdir / "fig6-same-area-split.png")

    print(f"\n완료 — {outdir}")
    for p in sorted(outdir.glob("*.png")):
        print(f"  {p.name}  {p.stat().st_size/1024:.0f}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
