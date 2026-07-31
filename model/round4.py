"""라운드 4 — ① 신선 홀드아웃 · ② 동학 시간해상도(G2X). 실행 전 사전 등록.

① 왜 홀드아웃을 바꾸는가
   2019–2022는 라운드 2~3에서 여러 번 열렸다(E1·E2·E-M·확장 번들·절제표·트렌드 재검정).
   개별 비교는 전부 사전 등록됐지만 누적 노출은 되돌릴 수 없다. 2023년 개업은 2026년에
   3년 판정이 나고 한 번도 채점된 적이 없으므로 유일하게 깨끗한 행이다.

   대가를 먼저 적는다: n=7,915 (2023-01~07 개업. 08월부터는 2026-07 관측 상한에서
   아직 우측중도절단). 구 홀드아웃 48,889의 1/6이다. 상위10%가 n=791이 되므로
   십분위 지표의 표준오차가 약 0.6%p -> 1.5%p로 벌어진다.

   **그래서 신선 홀드아웃은 +0.5%p급 효과를 확인할 검정력이 없다.** 이 사실을 무시하고
   여기서 "판별 불가"가 나왔다고 기각을 선언하면 그것은 증거가 아니라 표본 부족이다.
   따라서 확인을 둘로 나눈다:
     확인 A (검정력 있음, 노출됨)  train 2005–2018 / test 2019–2022
     확인 B (검정력 약함, 깨끗함)  train 2005–2022 / test 2023
   A는 크기를 재고, B는 **부호가 재현되는가**만 묻는다. 각자 할 수 있는 것만 시킨다.

② G2X — 측정이 가리킨 유일한 방향
   절제표에서 동학군(G2)이 ΔAUC +0.0216으로 모든 원천을 앞섰는데, 배포 세트는 그걸
   36개월 창 하나로만 표현한다. 올해 회전 중인 블록과 3년 전에 회전했던 블록이 같은
   값을 갖는다. 새 외부 원천 5종이 전부 기각된 뒤 남은 유일한 근거 있는 방향이다.

사전 등록 판정 (실행 전 고정, 2026-07-27):
  선발    fresh-inner(train 2005–2020 / val 2021–2022) add-one ΔAUC > 0
  확인 A  짝지은 부트스트랩 Δ상위10% CI 하한 > 0 그리고 점추정 >= +0.5%p
          그리고 위약 대조 경험적 p < 0.05
  확인 B  점추정 부호가 A와 같을 것 (임계 없음 — 검정력 부족을 인정한다)
  모델    3종(gbm·rf·logit) 중 2종 이상에서 확인 A 성립
  넷이 전부 참일 때만 채택. 임계는 §8-C 확장 게이트가 쓰던 +0.5%p 그대로다.
"""
import argparse
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

from pipeline.db import init

from .ablation import paired_bootstrap_ci, seed_avg_predict
from .cache import cached_split
from .evaluate import TEST_YEARS, baseline_prior_surv
from .experiment_trend2 import paired_bootstrap_decile, shuffled, top_decile
from .train import (LEGACY_TRAIN_YEARS, DEPLOY, FRESH_TEST_YEARS, FRESH_TRAIN_YEARS,
                    G2X, WINNER, fit_predict)

MIN_DECILE_GAIN = 0.005
ALPHA = 0.05
MODELS = ("gbm", "rf", "logit")
N_PLACEBO = 30
INNER_TEST = FRESH_TRAIN_YEARS[-2:]
INNER_TRAIN = FRESH_TRAIN_YEARS[:-2]


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p, d = k / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - r) / d, (c + r) / d)


def deciles(y, p, k=10):
    o = np.argsort(-np.asarray(p))
    y = np.asarray(y)[o]
    n = len(y)
    return [(float(y[int(n * i / k):int(n * (i + 1) / k)].mean()),
             len(y[int(n * i / k):int(n * (i + 1) / k)])) for i in range(k)]


def baseline_report(con, cols, model):
    """① 신선 홀드아웃 기준선 + 검정력."""
    out = {}
    for tag, tr_y, te_y in (("구 홀드아웃 2019–2022", LEGACY_TRAIN_YEARS, TEST_YEARS),
                            ("신선 홀드아웃 2023", FRESH_TRAIN_YEARS, FRESH_TEST_YEARS)):
        tr, te = cached_split(con, tr_y, te_y, 3)
        y = te[1]
        p, _ = fit_predict(model, tr, te, num=cols)
        d = deciles(y, p)
        lo1, hi1 = wilson(int(round(d[0][0] * d[0][1])), d[0][1])
        lo10, hi10 = wilson(int(round(d[-1][0] * d[-1][1])), d[-1][1])
        prior = roc_auc_score(y, baseline_prior_surv(tr[0], tr[1], te[0]))
        mono = all(d[i][0] >= d[i + 1][0] - 0.02 for i in range(9))
        out[tag] = {"auc": roc_auc_score(y, p), "prior": prior, "n": len(y),
                    "top": d[0][0], "bot": d[-1][0], "mono": mono, "p": p, "y": y,
                    "ci_top": (lo1, hi1), "ci_bot": (lo10, hi10),
                    "overall": float(y.mean()), "train_n": len(tr[1])}
        r = out[tag]
        print(f"  {tag:<22} n_tr={r['train_n']:>7,} n_te={r['n']:>6,} "
              f"전체생존 {r['overall']*100:.1f}%  AUC {r['auc']:.4f} (prior {r['prior']:.4f})")
        print(f"  {'':<22} 상위10% {r['top']*100:.1f}% [{lo1*100:.1f}, {hi1*100:.1f}]  "
              f"하위10% {r['bot']*100:.1f}% [{lo10*100:.1f}, {hi10*100:.1f}]  "
              f"단조 {'O' if mono else 'X'}")
    return out


def mde_report(y, p_a, p_b, label):
    """짝지은 부트스트랩 표준오차에서 최소검출효과를 역산."""
    _, alo, ahi = paired_bootstrap_ci(y, p_a, p_b, n_resamples=400)
    _, dlo, dhi = paired_bootstrap_decile(y, p_a, p_b)
    se_auc = (ahi - alo) / (2 * 1.96)
    se_dec = (dhi - dlo) / (2 * 1.96)
    print(f"  {label:<22} ΔAUC SE {se_auc:.4f} -> MDE {2.49*se_auc:+.4f}   "
          f"Δ상위10% SE {se_dec*100:.2f}%p -> MDE {2.49*se_dec*100:+.2f}%p")
    return 2.49 * se_auc, 2.49 * se_dec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--placebo", type=int, default=N_PLACEBO)
    ap.add_argument("--only", default="", help="1 | 2")
    a = ap.parse_args()
    con = init()
    base, full = list(DEPLOY), list(DEPLOY) + G2X
    want = a.only or "1,2"

    if "1" in want:
        print("=" * 92)
        print("① 신선 홀드아웃 — 2023 코호트 (한 번도 채점되지 않은 유일한 행)")
        print("=" * 92)
        b = baseline_report(con, base, WINNER)
        print("\n  검정력 (같은 벤치에서 G2X 유무를 비교했을 때의 최소검출효과)")
        for tag, tr_y, te_y in (("구 홀드아웃", LEGACY_TRAIN_YEARS, TEST_YEARS),
                                ("신선 홀드아웃", FRESH_TRAIN_YEARS, FRESH_TEST_YEARS)):
            tr, te = cached_split(con, tr_y, te_y, 3)
            pb = seed_avg_predict(WINNER, tr, te, base)
            pf = seed_avg_predict(WINNER, tr, te, full)
            mde_report(te[1], pf, pb, tag)
        print("\n  읽는 법: 신선 홀드아웃은 표본이 1/6이라 MDE가 그만큼 커진다.")
        print("  크기를 재는 일은 구 홀드아웃이, 부호가 재현되는지는 신선 홀드아웃이 맡는다.")

    if "2" in want:
        print("\n" + "=" * 92)
        print(f"② G2X 동학 시간해상도 — 후보 {len(G2X)}개")
        print("=" * 92)

        tr, va = cached_split(con, INNER_TRAIN, INNER_TEST, 3)
        b_auc = roc_auc_score(va[1], seed_avg_predict(WINNER, tr, va, base, (0, 1, 2)))
        print(f"\n[선발] 내부 검증 train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} / "
              f"val {INNER_TEST[0]}-{INNER_TEST[-1]} (n={len(va[1]):,}) · 기준 {b_auc:.4f}")
        picked = []
        for c in G2X:
            auc = roc_auc_score(va[1], seed_avg_predict(WINNER, tr, va, base + [c], (0, 1, 2)))
            if auc - b_auc > 0:
                picked.append(c)
            print(f"  {c:<16} add-one ΔAUC {auc - b_auc:>+8.4f}", flush=True)
        blk = roc_auc_score(va[1], seed_avg_predict(WINNER, tr, va, full, (0, 1, 2)))
        print(f"  {'(블록 전체)':<16} ΔAUC {blk - b_auc:>+8.4f}")
        print(f"  편입 후보군 {len(picked)}개: {', '.join(picked) or '없음'}")
        if not picked:
            print("\n  -> 선발 통과 없음. G2X 기각.")
            return 0
        sel = base + picked

        res = {}
        for tag, tr_y, te_y in (("A", LEGACY_TRAIN_YEARS, TEST_YEARS),
                                ("B", FRESH_TRAIN_YEARS, FRESH_TEST_YEARS)):
            trn, te = cached_split(con, tr_y, te_y, 3)
            y = te[1]
            print(f"\n[확인 {tag}] train {tr_y[0]}-{tr_y[-1]} / test {te_y[0]}-{te_y[-1]} "
                  f"(n={len(y):,}) — 모델 3종")
            res[tag] = {}
            for m in MODELS:
                pb = seed_avg_predict(m, trn, te, base)
                pf = seed_avg_predict(m, trn, te, sel)
                dt, dlo, dhi = paired_bootstrap_decile(y, pf, pb)
                at, alo, ahi = paired_bootstrap_ci(y, pf, pb, n_resamples=400)
                res[tag][m] = {"dt": dt, "dlo": dlo, "at": at, "alo": alo,
                               "pb": pb, "pf": pf}
                print(f"  {m:<6} ΔAUC {at:>+8.4f} [{alo:+.4f}, {ahi:+.4f}]   "
                      f"Δ상위10% {dt*100:>+6.2f}%p [{dlo*100:+.2f}, {dhi*100:+.2f}]")

        # 위약 대조 — 확인 A에서만 (검정력이 있는 벤치)
        print(f"\n[위약 대조] 확인 A · 선택된 {len(picked)}컬럼을 같은 순열로 섞어 "
              f"{a.placebo}회")
        trn, te = cached_split(con, LEGACY_TRAIN_YEARS, TEST_YEARS, 3)
        y = te[1]
        pb = res["A"][WINNER]["pb"]
        rng = np.random.default_rng(0)
        null = []
        for k in range(a.placebo):
            trs = (shuffled(trn[0], picked, rng), trn[1], trn[2])
            tes = (shuffled(te[0], picked, rng), te[1], te[2])
            pf = seed_avg_predict(WINNER, trs, tes, sel)
            null.append(top_decile(y, pf) - top_decile(y, pb))
            if (k + 1) % 10 == 0:
                print(f"    {k+1}/{a.placebo}", flush=True)
        null = np.array(null)
        obs = res["A"][WINNER]["dt"]
        p_emp = float((null >= obs).sum() + 1) / (len(null) + 1)
        print(f"  위약 Δ상위10% 평균 {null.mean()*100:+.2f}%p · sd {null.std()*100:.2f}%p "
              f"· 95백분위 {np.percentile(null, 95)*100:+.2f}%p")
        print(f"  관측 {obs*100:+.2f}%p · 경험적 p = {p_emp:.3f}")

        A = res["A"][WINNER]
        checks = [
            ("(1) 확인A CI 하한 > 0", A["dlo"] > 0, f"{A['dlo']*100:+.2f}%p"),
            (f"(2) 확인A 점추정 >= +{MIN_DECILE_GAIN*100:.1f}%p",
             A["dt"] >= MIN_DECILE_GAIN, f"{A['dt']*100:+.2f}%p"),
            (f"(3) 위약 대비 p < {ALPHA}", p_emp < ALPHA, f"{p_emp:.3f}"),
            ("(4) 확인B 부호 일치", res["B"][WINNER]["dt"] > 0,
             f"{res['B'][WINNER]['dt']*100:+.2f}%p"),
            ("(5) 3종 중 2종 이상 (1)",
             sum(1 for m in MODELS if res["A"][m]["dlo"] > 0) >= 2,
             f"{sum(1 for m in MODELS if res['A'][m]['dlo'] > 0)}/3")]
        print("\n[판정] 사전 등록")
        for nm, ok, v in checks:
            print(f"  {nm:<28} {v:>9}  {'PASS' if ok else 'FAIL'}")
        print(f"\n  -> G2X {'채택' if all(c[1] for c in checks) else '기각'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
