"""검색 트렌드 재검정 (라운드 3) — §7-B에서 CI가 0을 벗어난 유일한 신호.

왜 다시 재는가: §6은 트렌드를 기각했는데(+0.0014, 임계 +0.005), §7-B의 절제 측정은
같은 부표에서 +0.0042 [+0.0021, +0.0065]로 0을 벗어났다. 두 결과의 차이는 피처셋
(NUM -> DEPLOY)과 추정량(단일 적합 -> 시드 5개 평균 + 짝지은 부트스트랩)에서 온다.
어느 쪽이 맞는지는 더 강한 검정으로만 갈린다.

핵심 설계 — 플라시보 귀무분포. 짝지은 부트스트랩 CI는 "적합된 두 모델이 주어졌을 때"의
불확실성만 재고, **컬럼을 2개 더한다는 행위 자체가 트리 모델에 주는 이득**은 재지 않는다.
그래서 트렌드 두 컬럼을 행 방향으로 섞은(정보는 파괴하고 주변분포·결측패턴·상호상관은
보존한) 위약 피처로 같은 절제를 반복해 귀무분포를 만든다. 관측값이 그 분포 안에 있으면
"트렌드가 안다"가 아니라 "컬럼이 2개 늘었다"를 잰 것이다.

사전 등록 판정 기준 (실행 전 고정, 2026-07-27):
  (a) 짝지은 부트스트랩 ΔAUC 95% CI 하한 > 0
  (b) 점추정 >= +0.005  — §6의 임계를 그대로 쓴다. 바꾸지 않는다
  (c) 플라시보 귀무분포 대비 경험적 p < 0.05
  (d) 모델 3종(gbm·rf·logit) 중 2종 이상에서 (a) 성립
  네 조건이 전부 참일 때만 채택. 하나라도 미달이면 §6·§6-B 기각을 유지하고
  "세 번째 확인"으로 기록한다.

검정력도 같이 보고한다. 부트스트랩 표준오차에서 최소검출효과(MDE)를 역산해, 이 설계가
임계 +0.005를 애초에 잡을 수 있는지 밝힌다 — 못 잡는 설계에서 나온 음성은 증거가 아니다.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .ablation import paired_bootstrap_ci, seed_avg_predict
from .cache import cached_split
from .evaluate import TEST_YEARS
from .train import DEPLOY, TREND

SUB_TRAIN = [2017, 2018]          # 트렌드 커버리지가 2016-01부터라 이 창이 최대다
MIN_GAIN = 0.005                  # §6 사전 등록 임계 — 불변
ALPHA = 0.05
MODELS = ("gbm", "rf", "logit")
N_PLACEBO = 30


def top_decile(y, p):
    o = np.argsort(-np.asarray(p))
    k = max(1, len(y) // 10)
    return float(np.asarray(y)[o[:k]].mean())


def paired_bootstrap_decile(y, pa, pb, n_resamples=400, seed=0):
    y = np.asarray(y)
    point = top_decile(y, pa) - top_decile(y, pb)
    rng = np.random.default_rng(seed)
    d = [top_decile(y[i], pa[i]) - top_decile(y[i], pb[i])
         for i in (rng.integers(0, len(y), len(y)) for _ in range(n_resamples))]
    return point, float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def shuffled(X, cols, rng):
    """트렌드 두 컬럼을 같은 순열로 행 방향 섞기.

    같은 순열을 쓰는 이유: 두 컬럼의 상호상관과 결측 동반 패턴까지 보존해야 위약이
    실제 피처 블록과 '정보만 빼고' 같아진다. 따로 섞으면 위약이 실제보다 더 무의미해져
    귀무분포가 좁아지고, 그러면 없는 유의성이 생긴다.
    """
    perm = rng.permutation(len(X))
    out = []
    for i, f in enumerate(X):
        g = dict(f)
        src = X[perm[i]]
        for c in cols:
            g[c] = src.get(c)
        out.append(g)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=N_PLACEBO)
    a = ap.parse_args()

    con = init()
    tr, te = cached_split(con, SUB_TRAIN, TEST_YEARS, 3, with_trend=True)
    y = te[1]
    base, full = list(DEPLOY), list(DEPLOY) + TREND

    print("=" * 84)
    print(f"검색 트렌드 재검정 — train {SUB_TRAIN[0]}-{SUB_TRAIN[-1]} (n={len(tr[1]):,}) "
          f"/ test {TEST_YEARS[0]}-{TEST_YEARS[-1]} (n={len(y):,})")
    print("=" * 84)

    cov_tr = np.mean([f.get("trend_12m") is not None for f in tr[0]])
    cov_te = np.mean([f.get("trend_12m") is not None for f in te[0]])
    print(f"\n커버리지  학습 {cov_tr*100:.1f}% · 검증 {cov_te*100:.1f}% "
          f"(결측은 학습 중앙값으로 대치된다)")

    # ------------------------------------------------------------- 관측값
    print("\n[1] 관측 효과 — 모델 3종 (시드 5개 평균 · 짝지은 부트스트랩 400회)")
    print(f"  {'모델':<8} {'ΔAUC':>10} {'95% CI':>22} {'Δ상위10%':>10} {'95% CI':>20}")
    obs = {}
    for m in MODELS:
        pb = seed_avg_predict(m, tr, te, base)
        pf = seed_avg_predict(m, tr, te, full)
        pt, lo, hi = paired_bootstrap_ci(y, pf, pb, n_resamples=400)
        dt, dlo, dhi = paired_bootstrap_decile(y, pf, pb)
        obs[m] = {"pt": pt, "lo": lo, "hi": hi, "auc_base": roc_auc_score(y, pb),
                  "auc_full": roc_auc_score(y, pf), "dt": dt}
        print(f"  {m:<8} {pt:>+10.4f} {f'[{lo:+.4f}, {hi:+.4f}]':>22} "
              f"{dt*100:>+9.2f}%p {f'[{dlo*100:+.2f}, {dhi*100:+.2f}]':>20}")

    g = obs["gbm"]
    se = (g["hi"] - g["lo"]) / (2 * 1.96)
    mde = 2.49 * se          # 80% power, one-sided alpha=0.05
    print(f"\n  검정력: 부트스트랩 SE {se:.4f} -> 최소검출효과(80% power, 단측 α=.05) "
          f"{mde:+.4f}")
    print(f"  -> 이 설계는 임계 +{MIN_GAIN}를 검출할 수 "
          f"{'있다 (MDE < 임계)' if mde < MIN_GAIN else '없다 (MDE >= 임계) — 음성이 증거가 못 된다'}")

    # ------------------------------------------------------- 플라시보 귀무
    print(f"\n[2] 플라시보 귀무분포 — 트렌드 2컬럼을 행 방향으로 섞어 {a.placebo}회 반복")
    print("    (정보만 파괴하고 주변분포·결측패턴·상호상관은 보존)")
    rng = np.random.default_rng(0)
    p_base = seed_avg_predict("gbm", tr, te, base)
    null = []
    for k in range(a.placebo):
        trs = (shuffled(tr[0], TREND, rng), tr[1], tr[2])
        tes = (shuffled(te[0], TREND, rng), te[1], te[2])
        pf = seed_avg_predict("gbm", trs, tes, full)
        null.append(roc_auc_score(y, pf) - roc_auc_score(y, p_base))
        if (k + 1) % 10 == 0:
            print(f"    {k+1}/{a.placebo}", flush=True)
    null = np.array(null)
    p_emp = float((null >= g["pt"]).sum() + 1) / (len(null) + 1)
    print(f"\n  위약 ΔAUC 평균 {null.mean():+.4f} · sd {null.std():.4f} · "
          f"범위 [{null.min():+.4f}, {null.max():+.4f}]")
    print(f"  95 백분위 {np.percentile(null, 95):+.4f}")
    print(f"  관측 {g['pt']:+.4f} · 경험적 p = {p_emp:.3f}")

    # ------------------------------------------------------------- 판정
    c = [("(a) 짝지은 CI 하한 > 0", g["lo"] > 0, f"{g['lo']:+.4f}"),
         (f"(b) 점추정 >= +{MIN_GAIN}", g["pt"] >= MIN_GAIN, f"{g['pt']:+.4f}"),
         (f"(c) 위약 대비 p < {ALPHA}", p_emp < ALPHA, f"{p_emp:.3f}"),
         ("(d) 3종 중 2종 이상 CI 하한 > 0",
          sum(1 for m in MODELS if obs[m]["lo"] > 0) >= 2,
          f"{sum(1 for m in MODELS if obs[m]['lo'] > 0)}/3")]
    print("\n[3] 사전 등록 판정")
    for nm, ok, v in c:
        print(f"    {nm:<28} {v:>8}  {'PASS' if ok else 'FAIL'}")
    ok = all(x[1] for x in c)
    print(f"\n  -> 검색 트렌드 {'채택' if ok else '기각 유지 (§6·§6-B에 이은 세 번째 확인)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
