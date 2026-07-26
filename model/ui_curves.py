"""③ 등급별 horizon 곡선 · ④ 등급 x 면적 조건부 표 — UI가 바로 쓰는 실측값.

③ ρ가 0.8 미만이라는 사실을 어떻게 다룰 것인가
   E3에서 1년 등급과 3년 등급의 Spearman ρ가 0.701로 나왔다. 이건 "1년 기준으로 다시
   순위를 매기면 순서가 꽤 달라진다"는 뜻이다. 그런데 제품이 필요한 것은 1년 *등급*이
   아니라 **"이 등급의 자리들이 1년에 실제로 얼마나 살아남았나"**이다. 후자는 순위
   일치와 무관한 순수 측정이다 — 3년 등급으로 묶고 1년 결과를 세면 끝난다.

   그래서 별도 1년 등급을 만들지 않는다. 등급은 하나(3년 모델)이고, horizon별로는
   그 등급 집단의 실측 곡선을 붙인다. 이렇게 하면 ρ 논쟁이 UI 결정에 영향을 주지
   않으면서도, "1년 순위는 다르다"는 사실을 숨기지도 않는다(§8-D에 남아 있다).

   구현 주의: 등급 경계는 3년 홀드아웃에서 얻고, 1년·5년 코호트는 **같은 적합 모델로
   점수만 매겨 같은 경계에 태운다.** 행을 매칭하지 않는다 — (격자, 개업월) 키가 유일하지
   않아 매칭이 조용히 다른 점포를 집는다(§8-F가 겪은 문제).

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
from .train import CONFIRMED_TRAIN_YEARS, DEPLOY, WINNER, Encoder, fit_predict

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
    tr3, te3 = cached_split(con, CONFIRMED_TRAIN_YEARS, TEST_YEARS, 3)
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
    for h in (1, 3, 5):
        if h == 3:
            y, g = te3[1], g3
        else:
            _, teh = cached_split(con, CONFIRMED_TRAIN_YEARS, WINDOWS[h], h)
            ph = m3.predict_proba(enc.transform(teh[0], scale=WINNER in ("logit", "mlp")))[:, 1]
            y, g = teh[1], grade_of(ph, edges)
        row = []
        for label, sel in GRADE_BANDS:
            mask = np.array([sel(x) for x in g])
            k, tot = int(y[mask].sum()), int(mask.sum())
            lo, hi = wilson(k, tot)
            row.append((label, k / tot, lo, hi, tot))
        curves[h] = {"rows": row, "overall": float(y.mean()), "n": len(y),
                     "window": WINDOWS[h]}
        print(f"\n  horizon {h}년  (test {WINDOWS[h][0]}-{WINDOWS[h][-1]}, n={len(y):,}, "
              f"전체 {y.mean()*100:.1f}%)")
        for label, v, lo, hi, tot in row:
            print(f"    {label:<14} {v*100:>5.1f}%  [{lo*100:.1f}, {hi*100:.1f}]  n={tot:,}")

    print(f"\n  같은 등급의 자리가 시간이 갈수록 어떻게 되는가 (상위10% / 중간 / 하위10%)")
    for label, _ in GRADE_BANDS:
        vals = [next(v for l, v, *_ in curves[h]["rows"] if l == label) for h in (1, 3, 5)]
        print(f"    {label:<14} 1년 {vals[0]*100:.1f}% → 3년 {vals[1]*100:.1f}% "
              f"→ 5년 {vals[2]*100:.1f}%")
    print(f"\n  주의: 1년·5년은 test 창이 다르다(1년 2019–2024 / 5년 2019–2021). "
          f"관측 가능 분모 원칙 때문이며,")
    print(f"  같은 창으로 강제하면 5년 판정이 안 난 점포를 생존으로 세게 된다.")

    # ---------------------------------------------------------------- ④
    print("\n" + "=" * 78)
    print("④ 등급 × 점포 면적 — 자리를 고른 뒤의 질문에 실측으로 답한다")
    print("=" * 78)
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
        for h in (1, 3, 5):
            c = curves[h]
            rows.append((f"observed_by_gradeband_{h}y",
                         ",".join(f"{v:.4f}:{lo:.4f}:{hi:.4f}:{t}" for _, v, lo, hi, t in c["rows"])))
            rows.append((f"overall_survival_{h}y", f"{c['overall']:.4f}"))
            rows.append((f"test_window_{h}y", f"{c['window'][0]}-{c['window'][-1]}"))
        rows.append(("gradeband_labels", ",".join(l for l, _ in GRADE_BANDS)))
        rows.append(("area_bands", ",".join(BAND_LABEL)))
        rows.append(("observed_by_grade_area",
                     ";".join("|".join("" if c is None else f"{c['v']:.4f}:{c['lo']:.4f}:{c['hi']:.4f}:{c['n']}"
                                       for c in g["cells"]) for g in grid)))
        con.executemany("INSERT OR REPLACE INTO score_meta VALUES(?,?)", rows)
        con.commit()
        print(f"\n  score_meta에 {len(rows)}개 키 기록 (레인 B 통보 대상)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
