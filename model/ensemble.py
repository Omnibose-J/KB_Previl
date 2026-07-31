"""E-ENS — 앙상블이 현행 단일 gbm 을 이기는가. 실행 전 사전 등록.

왜 묻는가
   E-M 은 후보 6종을 **하나씩** 겨뤄 현행 유지로 끝났다(§7-A). 그때 남은 질문이
   «그럼 섞으면 어떤가» 인데, 한 번도 재지 않았다. 앙상블은 분산을 줄이는 것이
   본업이라, 단일 승자가 없다는 결과와 «섞어도 안 된다» 는 결과는 별개다.

무엇을 섞는가 — 가중치를 학습하지 않는다
   스태킹(메타 학습기)을 쓰지 않는 이유는 검정력이다. 메타 가중치를 어디서
   고르든 그 데이터는 더 이상 확인용이 아니고, 신선 홀드아웃은 n=7,915 라
   가중치 하나 더 쓸 여유가 없다. 그래서 후보는 전부 **무가중** 결합이다:
   확률 평균과 순위 평균, 그리고 그 둘의 상위 3종 판.
   순위 평균을 함께 두는 이유는 확률 눈금이 모델마다 다르기 때문이다 — mlp 의
   0.7 과 rf 의 0.7 은 같은 뜻이 아니라, 확률 평균은 눈금이 넓은 모델에 끌린다.

사전 등록 판정 (실행 전 고정, 2026-08-01)
  선발    fresh-inner (train 2005–2020 / val 2021–2022)
          기준 = 상위10% 실측 생존율, 동률 시 십분위 격차 -> Brier
          앙상블 후보 중 1위 하나만 홀드아웃으로 올린다
  확인 A  (검정력 있음, 노출됨)  train 2005–2018 / test 2019–2022
          짝지은 부트스트랩 Δ상위10% CI 하한 > 0 · 점추정 >= +0.5%p · 십분위 단조
  확인 B  (깨끗함, 검정력 약함)   train 2005–2022 / test 2023
          점추정 부호가 A 와 같을 것 (임계 없음 — 검정력 부족을 인정한다)
  채택    A 와 B 가 둘 다 참일 때만. 아니면 현행 gbm 유지.

  임계 +0.5%p 는 §8-C 확장 게이트가 쓰던 값 그대로다. 라운드 4 가 신선 홀드아웃
  에서 크기를 못 재는 이유(상위10% n=791, 표준오차 약 1.5%p)도 그대로 적용된다.

등록의 구멍 (실행 후 발견, 2026-08-01)
   십분위 단조를 확인 A 에서만 걸었다. B 에서도 걸었어야 했다 — 배포되는 계보가
   B 이기 때문이다. 결과를 보고 게이트를 고치지는 않는다(그건 사후 조정이다).
   대신 B 의 단조 여부를 «등록 밖 관측»으로 함께 찍어, 판정을 읽는 사람이 그
   사실을 놓치지 않게 한다.

실행
    python -m model.ensemble                  # 선발 + 확인 A + 확인 B
    python -m model.ensemble --no-holdout     # 선발만
"""
import argparse
import sys
import time

import numpy as np
from scipy.stats import rankdata
from sklearn.metrics import brier_score_loss, roc_auc_score

from pipeline.db import init

from .cache import cached_split
from .evaluate import TEST_YEARS, baseline_prior_surv
from .tournament import (GRID, SIMPLICITY, decile_ci, deciles,
                         paired_bootstrap_decile)
from .train import (FRESH_TEST_YEARS, FRESH_TRAIN_YEARS, LEGACY_TRAIN_YEARS,
                    Encoder, fit_predict)

INCUMBENT = "gbm"
DECILE_MIN_GAIN = 0.005
INNER_TRAIN = FRESH_TRAIN_YEARS[:-2]      # 2005–2020
INNER_TEST = FRESH_TRAIN_YEARS[-2:]       # 2021–2022

# 무가중 결합만. members=None 은 «내부 검증 상위 k 종» 을 뜻하고, 그 선택은
# 선발 단계에서만 일어난다.
RECIPES = [
    ("avg6", "확률 평균 · 6종", "prob", None),
    ("rank6", "순위 평균 · 6종", "rank", None),
    ("avg3", "확률 평균 · 상위 3종", "prob", 3),
    ("rank3", "순위 평균 · 상위 3종", "rank", 3),
    ("boost2", "확률 평균 · gbm+hgb", "prob", ("gbm", "hgb")),
]


def blend(preds, how):
    """preds: [(kind, p)] -> 결합 점수. 순위는 [0,1] 로 정규화해 모델 간 눈금을
    없앤다. 확률 평균은 눈금을 그대로 두므로 둘을 나란히 잰다."""
    if how == "rank":
        n = len(preds[0][1])
        return np.mean([rankdata(p) / n for _, p in preds], axis=0)
    return np.mean([p for _, p in preds], axis=0)


def members_of(recipe, ranked_kinds):
    """레시피가 쓸 후보 이름들. 상위 k 종은 선발 단계의 순위에서만 온다."""
    _, _, _, spec = recipe
    if spec is None:
        return list(ranked_kinds)
    if isinstance(spec, tuple):
        return [k for k in spec]
    return list(ranked_kinds[:spec])


def _key(r):
    """낮을수록 좋다. 동률이 float 먼지가 아니라 진짜 동률이 되게 먼저 반올림."""
    return (-round(r["top"], 4), -round(r["gap"], 4), round(r["brier"], 4),
            r.get("order", 99))


def score(y, p, kind, order=99):
    d = deciles(y, p)
    return {"kind": kind, "p": p, "auc": roc_auc_score(y, p),
            "brier": brier_score_loss(y, np.clip(p, 0, 1)),
            "top": d[0], "gap": d[0] - d[-1], "dec": d, "order": order}


def fit_families(train, test, cols, enc, best_params, kinds):
    """필요한 계열만 그 계열의 최적 설정으로 한 번씩 적합. seed=0 은 배포와 같다."""
    out = []
    for kind in [k for k in SIMPLICITY if k in kinds]:
        t0 = time.time()
        p, _ = fit_predict(kind, train, test, num=cols, seed=0,
                           params=best_params[kind], enc=enc)
        out.append((kind, p))
        print(f"    {kind:<6} {time.time() - t0:>6.1f}초", flush=True)
    return out


def select(con, cols):
    """내부 검증만 본다. -> (승자 레시피, 계열별 최적 설정)"""
    train, val = cached_split(con, INNER_TRAIN, INNER_TEST, 3)
    enc = Encoder(cols).fit(train[0])
    yv = val[1]
    print(f"선발 · 내부 검증  train {INNER_TRAIN[0]}-{INNER_TRAIN[-1]} "
          f"(n={len(train[1]):,}) / val {INNER_TEST[0]}-{INNER_TEST[-1]} "
          f"(n={len(yv):,}) · 피처 {len(cols)}개")
    print("  기준: 상위10% 실측 생존율 (동률 시 십분위 격차 -> Brier)\n")

    # 1) 계열별 최적 설정 — 토너먼트와 같은 격자, 같은 기준
    print(f"  {'후보':<7} {'설정':<44} {'상위10%':>8} {'십분위격차':>10} {'AUC':>8} {'Brier':>8}")
    singles, best_params = {}, {}
    for kind in SIMPLICITY:
        rows = []
        for params in GRID[kind]:
            p, _ = fit_predict(kind, train, val, num=cols, seed=0, params=params, enc=enc)
            r = score(yv, p, kind, SIMPLICITY.index(kind))
            r["params"] = params
            rows.append(r)
            print(f"  {kind:<7} {str(params):<44} {r['top']*100:>7.1f}% "
                  f"{r['gap']*100:>9.1f}%p {r['auc']:>8.4f} {r['brier']:>8.4f}", flush=True)
        best = min(rows, key=_key)
        singles[kind] = best
        best_params[kind] = best["params"]

    ranked_kinds = [r["kind"] for r in sorted(singles.values(), key=_key)]
    print(f"\n  계열 순위: {' > '.join(ranked_kinds)}")

    # 2) 같은 예측을 재사용해 앙상블을 만든다 (추가 적합 없음)
    preds = {k: singles[k]["p"] for k in SIMPLICITY}
    print(f"\n  {'앙상블':<8} {'구성':<34} {'상위10%':>8} {'십분위격차':>10} {'AUC':>8} {'Brier':>8}")
    ens = []
    for recipe in RECIPES:
        name, label, how, _ = recipe
        ms = members_of(recipe, ranked_kinds)
        p = blend([(k, preds[k]) for k in ms], how)
        r = score(yv, p, name)
        r["members"], r["how"], r["label"] = ms, how, label
        ens.append(r)
        print(f"  {name:<8} {'+'.join(ms):<34} {r['top']*100:>7.1f}% "
              f"{r['gap']*100:>9.1f}%p {r['auc']:>8.4f} {r['brier']:>8.4f}", flush=True)

    inc = singles[INCUMBENT]
    print(f"\n  (현행) {INCUMBENT} {best_params[INCUMBENT]} "
          f"상위10% {inc['top']*100:.1f}%  격차 {inc['gap']*100:.1f}%p  AUC {inc['auc']:.4f}")

    winner = min(ens, key=_key)
    lo, hi = decile_ci(yv, winner["p"])
    ilo, ihi = decile_ci(yv, inc["p"])
    print(f"\n  -> 앙상블 승자 {winner['kind']} ({winner['label']}) "
          f"상위10% {winner['top']*100:.1f}% [{lo*100:.1f}, {hi*100:.1f}]")
    print(f"     현행 gbm 밴드 [{ilo*100:.1f}, {ihi*100:.1f}]")
    if hi >= ilo and lo <= ihi:
        print("  [검정력 주의] 두 밴드가 겹친다 — 내부 검증의 순위는 재현되지 않을 수 있다.")
    return winner, best_params


def run_holdout(con, cols, tag, train_years, test_years, winner, best_params):
    """홀드아웃 한 번. 앙상블 하나 대 현행 하나.

    구성원과 설정은 선발 단계에서 이미 고정됐다 — 여기서 다시 고르지 않는다.
    """
    train, test = cached_split(con, train_years, test_years, 3)
    enc = Encoder(cols).fit(train[0])
    yte = test[1]
    print(f"\n{tag}  train {train_years[0]}-{train_years[-1]} / "
          f"test {test_years[0]}-{test_years[-1]} (n={len(yte):,})")

    members = winner["members"]
    print(f"  구성원 적합 ({'+'.join(members)})")
    fitted = dict(fit_families(train, test, cols, enc, best_params,
                               set(members) | {INCUMBENT}))
    p_ens = blend([(k, fitted[k]) for k in members], winner["how"])

    r_ens = score(yte, p_ens, winner["kind"])
    r_inc = score(yte, fitted[INCUMBENT], INCUMBENT)
    for label, r in (("앙상블", r_ens), ("현행", r_inc)):
        mono = all(r["dec"][i] >= r["dec"][i + 1] - 0.02 for i in range(9))
        r["mono"] = mono
        print(f"  {label:<5} {r['kind']:<7} AUC {r['auc']:.4f}  Brier {r['brier']:.4f}  "
              f"상위10% {r['dec'][0]*100:.1f}%  하위10% {r['dec'][-1]*100:.1f}%  "
              f"단조 {'O' if mono else 'X'}")

    prior = roc_auc_score(yte, baseline_prior_surv(train[0], train[1], test[0]))
    print(f"  베이스라인 prior_surv AUC {prior:.4f}  "
          f"(마진 앙상블 {r_ens['auc']-prior:+.4f} / 현행 {r_inc['auc']-prior:+.4f})")

    point, lo, hi = paired_bootstrap_decile(yte, p_ens, fitted[INCUMBENT])
    print(f"  짝지은 부트스트랩 Δ상위10% {point*100:+.2f}%p  "
          f"95% CI [{lo*100:+.2f}, {hi*100:+.2f}]%p")
    return {"point": point, "lo": lo, "hi": hi, "ens": r_ens, "inc": r_inc}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", default="DEPLOY")
    ap.add_argument("--no-holdout", action="store_true", help="선발만 하고 홀드아웃은 안 연다")
    a = ap.parse_args()
    from .robustness import FEATURE_SETS
    cols = FEATURE_SETS.get(a.features) or [c for c in a.features.split(",") if c]

    con = init()
    print("=" * 78)
    print(f"E-ENS 앙상블 검정 — 무가중 결합 5종 대 현행 단일 {INCUMBENT} · 세트 {a.features}")
    print("=" * 78)
    winner, best_params = select(con, cols)
    if a.no_holdout:
        print("\n홀드아웃 조회 생략 (--no-holdout)")
        return 0

    A = run_holdout(con, cols, "확인 A (검정력 있음, 노출됨)",
                    LEGACY_TRAIN_YEARS, TEST_YEARS, winner, best_params)
    B = run_holdout(con, cols, "확인 B (깨끗함, 검정력 약함)",
                    FRESH_TRAIN_YEARS, FRESH_TEST_YEARS, winner, best_params)

    print("\n" + "=" * 78)
    a_ok = A["lo"] > 0 and A["point"] >= DECILE_MIN_GAIN and A["ens"]["mono"]
    b_ok = (B["point"] > 0) == (A["point"] > 0)
    print(f"확인 A  CI 하한 > 0 ({'O' if A['lo'] > 0 else 'X'}) · "
          f"점추정 >= +{DECILE_MIN_GAIN*100:.1f}%p ({'O' if A['point'] >= DECILE_MIN_GAIN else 'X'}) · "
          f"십분위 단조 ({'O' if A['ens']['mono'] else 'X'})  -> {'통과' if a_ok else '미달'}")
    print(f"확인 B  부호 일치 ({'O' if b_ok else 'X'})  "
          f"A {A['point']*100:+.2f}%p / B {B['point']*100:+.2f}%p")
    print(f"등록 판정 -> {'채택' if (a_ok and b_ok) else f'기각: 현행 단일 {INCUMBENT} 유지'}")

    # 등록 밖 관측. 게이트에 넣지 않는다(사후 조정) — 다만 배포되는 계보가 B 라,
    # 여기서 십분위가 깨지면 등록 판정을 그대로 읽으면 안 된다. 재현한 사람이
    # 기록(§30)과 반대되는 결론을 화면에서 먼저 읽지 않도록 함께 찍는다.
    print(f"[등록 밖] 확인 B 십분위 단조  앙상블 "
          f"{'O' if B['ens']['mono'] else 'X'} / 현행 {'O' if B['inc']['mono'] else 'X'}")
    print(f"[등록 밖] 확인 B 는 배포 계보다. 여기 CI 는 "
          f"[{B['lo']*100:+.2f}, {B['hi']*100:+.2f}]%p 로 0 을 품는다.")
    print("\n기록된 판정 -> 기각(현행 단일 gbm 유지). 등록 게이트는 통과했으나 "
          "배포 계보에서 크기가 0 이고 단조가 깨진다 — docs/model-findings.md §30.")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
