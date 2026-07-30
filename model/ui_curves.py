"""③ 등급별 horizon 곡선 · ④ 등급 x 면적 조건부 표 — UI가 바로 쓰는 실측값.

③ ρ가 0.8 미만이라는 사실을 어떻게 다룰 것인가
   E3에서 1년 등급과 3년 등급의 Spearman ρ가 0.701로 나왔다. 이건 "1년 기준으로 다시
   순위를 매기면 순서가 꽤 달라진다"는 뜻이다. 그런데 제품이 필요한 것은 1년 *등급*이
   아니라 **"이 등급의 자리들이 1년에 실제로 얼마나 살아남았나"**이다. 후자는 순위
   일치와 무관한 순수 측정이다 — 3년 등급으로 묶고 1년 결과를 세면 끝난다.

   그래서 별도 1년 등급을 만들지 않는다. 등급은 하나(3년 모델)이고, horizon별로는
   그 등급 집단의 실측 곡선을 붙인다. 이렇게 하면 ρ 논쟁이 UI 결정에 영향을 주지
   않으면서도, "1년 순위는 다르다"는 사실을 숨기지도 않는다(§8-D에 남아 있다).

   구현 주의: 등급 경계는 3년 홀드아웃에서 얻고, 1년·2년·5년 코호트는 **같은 적합
   모델로 점수만 매겨 같은 경계에 태운다.** 행을 매칭하지 않는다 — (격자, 개업월) 키가
   유일하지 않아 매칭이 조용히 다른 점포를 집는다(§8-F가 겪은 문제).

④ 면적을 순위에서 뺐지만 사용자에게는 줘야 한다
   절제표에서 면적군(G6)은 ΔAUC +0.0477 · 단독 0.6325로 순위 모델 전체보다 크다.
   순위에서 빼는 이유는 성능이 아니라 **사용자가 면적을 정하므로 모든 후보 격자에 같은
   값이 들어가 순위를 못 바꾸기 때문**이다. 그러나 "이 자리에 25㎡면 / 90㎡면"은 자리가
   정해진 뒤의 질문이고, 그건 실측으로 답할 수 있다. 등급 x 면적 교차표가 그 답이다.
"""
import argparse
import sys

import numpy as np

from pipeline.db import init

from .cache import cached_split
from .evaluate import TEST_YEARS
from .horizon import WINDOWS
from .train import (CONFIRMED_TEST_YEARS, CONFIRMED_TRAIN_YEARS, DEPLOY, LEGACY_TRAIN_YEARS,
                    WINNER, Encoder, fit_predict)

# horizon별 (학습창, 검증창). 5년만 구 벤치인 이유: 배포 학습창이 2022까지 가므로 5년
# 판정이 가능한 개업(<=2021-07)이 전부 학습에 들어간다 — 같은 벤치에서 5년을 재면
# in-sample이 된다. 그래서 5년만 구 벤치의 별도 적합이고, 표에 그렇게 표기한다.
BENCH = {1: (CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS),
         2: (CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS),
         3: (CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS),
         5: (LEGACY_TRAIN_YEARS, [2019, 2020, 2021])}

# 2년이 여기 있는 이유: 상가 임대차는 1~2년 계약이 흔해 «계약기간 안에 버티는가»가
# 실제 질문인데, 2년만 비어 있었다. in-sample 문제도 없다 — 2년 판정이 가능한 개업은
# <=2024-07 이고 학습창은 2022 까지라 검증 코호트가 학습에 들어가지 않는다.
# 표본은 오히려 3년보다 크다: 2023 코호트가 2년은 전량 판정되고 3년은 상반기만 된다.
HORIZONS = (1, 2, 3, 5)
CONTINUOUS = (1, 2, 3)      # 같은 코호트(2023)라 곡선으로 이어 읽을 수 있는 구간

BANDS = [(0, 25), (25, 37), (37, 56), (56, 90), (90, 10 ** 6)]
BAND_LABEL = ["~25㎡", "25~37㎡", "37~56㎡", "56~90㎡", "90㎡~"]
GRADE_BANDS = [("상위 10%", lambda g: g == 1), ("중간 (2~9분위)", lambda g: 2 <= g <= 9),
               ("하위 10%", lambda g: g == 10)]


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 1.0)
    p, d = k / n, 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - r) / d, (c + r) / d)


def grade_of(scores, edges):
    out = np.empty(len(scores), dtype=int)
    for i, s in enumerate(scores):
        out[i] = next((j + 1 for j, e in enumerate(edges) if s >= e), 10)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="score_meta에 기록")
    a = ap.parse_args()
    con = init()
    cols = list(DEPLOY)

    # 3년 홀드아웃에서 등급 경계를 잡는다 — precompute와 같은 계산이다
    tr3, te3 = cached_split(con, *BENCH[3], 3)
    enc = Encoder(cols).fit(tr3[0])
    p3, (m3, _) = fit_predict(WINNER, tr3, te3, num=cols, enc=enc)
    order = np.argsort(-p3)
    n = len(p3)
    edges = [float(p3[order[int(n * i / 10):int(n * (i + 1) / 10)]].min()) for i in range(10)]
    g3 = grade_of(p3, edges)

    print(f"모델 {WINNER} · 세트 DEPLOY({len(cols)}) · 등급 경계는 3년 홀드아웃 "
          f"(n={n:,})에서 산출\n")

    # ---------------------------------------------------------------- ③
    print("=" * 78)
    print("③ 등급별 horizon 실측 곡선 — 등급은 하나(3년 모델), 곡선만 horizon별")
    print("=" * 78)
    curves = {}
    for h in HORIZONS:
        if h == 3:
            y, g = te3[1], g3
        elif h in (1, 2):
            _, teh = cached_split(con, *BENCH[h], h)
            ph = m3.predict_proba(enc.transform(teh[0], scale=WINNER in ("logit", "mlp")))[:, 1]
            y, g = teh[1], grade_of(ph, edges)
        else:
            # 5년은 구 벤치의 독립 적합 — 배포 모델로는 in-sample이 된다
            ltr, lte = cached_split(con, *BENCH[5], 5)
            lenc = Encoder(cols).fit(ltr[0])
            pl, (lm, _) = fit_predict(WINNER, ltr, lte, num=cols, enc=lenc)
            lo_ = np.argsort(-pl)
            ln = len(pl)
            ledges = [float(pl[lo_[int(ln * i / 10):int(ln * (i + 1) / 10)]].min())
                      for i in range(10)]
            y, g = lte[1], grade_of(pl, ledges)
        row = []
        for label, sel in GRADE_BANDS:
            mask = np.array([sel(x) for x in g])
            k, tot = int(y[mask].sum()), int(mask.sum())
            lo, hi = wilson(k, tot)
            row.append((label, k / tot, lo, hi, tot))
        trw, tew = BENCH[h]
        curves[h] = {"rows": row, "overall": float(y.mean()), "n": len(y), "window": tew,
                     "train": [trw[0], trw[-1]],
                     "bench": "legacy" if h == 5 else "deploy"}
        print(f"\n  horizon {h}년  (train {trw[0]}-{trw[-1]} / test {tew[0]}-{tew[-1]}, "
              f"n={len(y):,}, 전체 {y.mean()*100:.1f}%"
              f"{'  ← 구 벤치·별도 적합' if h == 5 else ''})")
        for label, v, lo, hi, tot in row:
            print(f"    {label:<14} {v*100:>5.1f}%  [{lo*100:.1f}, {hi*100:.1f}]  n={tot:,}")

    print(f"\n  곡선 — 1·2·3년은 같은 코호트(2023)라 이어 읽을 수 있다")
    for label, _ in GRADE_BANDS:
        vals = {h: next(v for l, v, *_ in curves[h]["rows"] if l == label) for h in HORIZONS}
        chain = " → ".join(f"{h}년 {vals[h]*100:.1f}%" for h in CONTINUOUS)
        print(f"    {label:<14} {chain}      (참고·구 벤치 5년 {vals[5]*100:.1f}%)")

    print(f"\n  ** 5년을 곡선에 잇지 말 것 **")
    print(f"  배포 학습창이 2022까지 가므로 5년 판정이 가능한 개업(<=2021-07)이 전부 학습에")
    print(f"  들어간다 — 같은 벤치에서 5년을 재면 in-sample이다. 그래서 5년만 구 벤치")
    print(f"  (train 2005-2018 / test 2019-2021)의 독립 적합이고, 그 코호트는 코로나기다.")
    print(f"  실제로 하위10%가 3년 {curves[3]['rows'][2][1]*100:.1f}% → 5년 "
          f"{curves[5]['rows'][2][1]*100:.1f}%로 역전되는데, 이건 시간이 지나 생존율이")
    print(f"  올라간 게 아니라 두 값이 다른 코호트·다른 시기라서다.")
    print(f"  2023 코호트의 5년 판정은 2028년에야 나온다. 그때까지 5년은 참고값이다.")

    # ---------------------------------------------------------------- ④
    print("\n" + "=" * 78)
    print("④ 등급 × 점포 면적 — 자리를 고른 뒤의 질문에 실측으로 답한다")
    print("=" * 78)
    # 이 표만 구 벤치(n=48,889)를 쓴다. 3x5=15칸을 나누려면 배포 벤치의 7,915행으로는
    # 60%가 n<100이 되어 표가 구멍난다. 성능 주장이 아니라 조건부 기술표이므로 표본이
    # 큰 쪽이 옳다 — 대신 코로나기 코호트라는 것을 표에 명기한다.
    ltr3, lte3 = cached_split(con, LEGACY_TRAIN_YEARS, TEST_YEARS, 3)
    lenc3 = Encoder(cols).fit(ltr3[0])
    pl3, _ = fit_predict(WINNER, ltr3, lte3, num=cols, enc=lenc3)
    lo3 = np.argsort(-pl3)
    n3 = len(pl3)
    ledges3 = [float(pl3[lo3[int(n3 * i / 10):int(n3 * (i + 1) / 10)]].min()) for i in range(10)]
    g3 = grade_of(pl3, ledges3)
    te3 = lte3
    print(f"\n  벤치: train {LEGACY_TRAIN_YEARS[0]}-{LEGACY_TRAIN_YEARS[-1]} / "
          f"test {TEST_YEARS[0]}-{TEST_YEARS[-1]} (n={n3:,}) — 칸을 채우기 위해 구 벤치 사용")
    areas = np.array([f["site_area"] or 0 for f in te3[0]], dtype=float)
    y = te3[1]
    print(f"\n  {'등급':<14} " + " ".join(f"{b:>12}" for b in BAND_LABEL))
    grid = []
    for label, sel in GRADE_BANDS:
        gm = np.array([sel(x) for x in g3])
        cells, txt = [], []
        for lo_a, hi_a in BANDS:
            m = gm & (areas >= lo_a) & (areas < hi_a)
            tot = int(m.sum())
            if tot < 100:
                cells.append(None)
                txt.append(f"{'n<100':>12}")
                continue
            v = float(y[m].mean())
            lo, hi = wilson(int(y[m].sum()), tot)
            cells.append({"v": v, "lo": lo, "hi": hi, "n": tot})
            txt.append(f"{v*100:>7.1f}% ({tot//1000}k)" if tot >= 1000
                       else f"{v*100:>8.1f}% ({tot})")
        grid.append({"grade": label, "cells": cells})
        print(f"  {label:<14} " + " ".join(txt))

    top = grid[0]["cells"]
    bot = grid[-1]["cells"]
    print(f"\n  읽는 법 — 두 축은 서로를 대체하지 못한다")
    for i, b in enumerate(BAND_LABEL):
        if top[i] and bot[i]:
            print(f"    {b:<10} 상위10% {top[i]['v']*100:.1f}%  vs  하위10% "
                  f"{bot[i]['v']*100:.1f}%   격차 {(top[i]['v']-bot[i]['v'])*100:.1f}%p")
    ok = [c for c in top if c]
    if len(ok) >= 2:
        print(f"    같은 상위10% 안에서도 면적으로 "
              f"{(ok[-1]['v']-ok[0]['v'])*100:.1f}%p 벌어진다 "
              f"({BAND_LABEL[0]} {ok[0]['v']*100:.1f}% ↔ {BAND_LABEL[-1]} {ok[-1]['v']*100:.1f}%)")

    if a.write:
        rows = []
        for h in HORIZONS:
            c = curves[h]
            rows.append((f"observed_by_gradeband_{h}y",
                         ",".join(f"{v:.4f}:{lo:.4f}:{hi:.4f}:{t}" for _, v, lo, hi, t in c["rows"])))
            rows.append((f"overall_survival_{h}y", f"{c['overall']:.4f}"))
            rows.append((f"test_window_{h}y", f"{c['window'][0]}-{c['window'][-1]}"))
            rows.append((f"bench_{h}y", c["bench"]))
        rows.append(("gradeband_labels", ",".join(l for l, _ in GRADE_BANDS)))
        rows.append(("area_bands", ",".join(BAND_LABEL)))
        rows.append(("grade_area_bench", f"legacy train {LEGACY_TRAIN_YEARS[0]}-{LEGACY_TRAIN_YEARS[-1]} / test {TEST_YEARS[0]}-{TEST_YEARS[-1]}"))
        rows.append(("observed_by_grade_area",
                     ";".join("|".join("" if c is None else f"{c['v']:.4f}:{c['lo']:.4f}:{c['hi']:.4f}:{c['n']}"
                                       for c in g["cells"]) for g in grid)))
        con.executemany("INSERT OR REPLACE INTO score_meta VALUES(?,?)", rows)
        con.commit()
        print(f"\n  score_meta에 {len(rows)}개 키 기록 (레인 B 통보 대상)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
