"""Turn the survival model into a ranked recommendation.

Consistency rule: the model learned from features computed as-of a shop's
opening month, so scoring must do the same thing at today's month. The exact
same code path (`AsOf.features`) produces both, which is what makes the trained
weights applicable at all - a separate "current state" query written by hand
would drift from the training definition and quietly invalidate the model.

Eligibility: a cell is only scored if its 3x3 ring holds enough history to make
the local features meaningful. An empty cell scores well simply by having no
observed failures, which is not evidence of a good location - it is absence of
evidence, and ranking on it would be the most misleading thing this tool could do.
"""
import argparse
import json
import sys

import numpy as np

from pipeline.db import init

from .asof import AsOf, load_shops, ym
from .evaluate import TEST_YEARS, TRAIN_YEARS, load_split
from .train import NUM, fit_predict

MIN_RING_HISTORY = 20      # shops ever opened in the 3x3 ring
NOW = None                 # resolved from data, not the wall clock


def current_month(con):
    r = con.execute(
        "SELECT MAX(open_y*12+COALESCE(open_m,1)) FROM licence WHERE open_y IS NOT NULL"
    ).fetchone()[0]
    return r


def score_all(con, uptae, site_area=None, verbose=True):
    """Score every eligible cell for a given 업태, as of the latest data month."""
    t = current_month(con)
    if verbose:
        print(f"기준 시점 {t//12}-{t%12 or 12:02d} · 업태 '{uptae}'")

    shops = load_shops(con)
    ao = AsOf(shops)

    if site_area is None:
        site_area = con.execute(
            "SELECT site_area FROM licence WHERE uptae=? AND site_area>0 "
            "ORDER BY site_area LIMIT 1 OFFSET "
            "(SELECT count(*)/2 FROM licence WHERE uptae=? AND site_area>0)",
            (uptae, uptae)).fetchone()
        site_area = site_area[0] if site_area else 40.0
        if verbose:
            print(f"점포 면적 미지정 → 해당 업태 중앙값 {site_area:.1f}㎡ 사용")

    cells = [r["grid_id"] for r in con.execute("SELECT grid_id FROM grid")]
    X, keep = [], []
    for gid in cells:
        f = ao.features(gid, t, uptae, site_area, (t % 12) or 12)
        if f["prior_surv_n"] < MIN_RING_HISTORY:
            continue           # not enough history to say anything
        X.append(f)
        keep.append(gid)

    if verbose:
        print(f"평가 대상 격자 {len(keep):,} / 전체 {len(cells):,} "
              f"(이웃 이력 {MIN_RING_HISTORY}건 미만 제외)")

    # Two fits with different jobs:
    #  - calib: trained on the past only, scored on the held-out later years.
    #    Its predictions give the score distribution and, crucially, the
    #    OBSERVED survival rate per decile. Raw model probabilities run
    #    2.7-6.7%p optimistic (see backtest) because the training era was
    #    kinder than the validation era, so we report measured rates instead.
    #  - final: refit on everything to score today.
    # site_area is excluded from ranking on purpose. It is the strongest single
    # predictor (AUC 0.6227 alone; 25㎡ shops survive 44.8% vs 74.4% at 90㎡+),
    # but it describes the SHOP, not the LOCATION - and in a recommendation the
    # user fixes it, so it is identical across every candidate cell. Leaving it
    # in would inflate the reported grade without changing the order.
    rank_cols = [c for c in NUM if c != "site_area"]

    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, 3, verbose=False)
    p_hold, _ = fit_predict("gbm", train, test, num=rank_cols)
    yte = test[1]

    order = np.argsort(-p_hold)
    n = len(p_hold)
    edges, observed = [], []
    for i in range(10):
        seg = order[int(n * i / 10):int(n * (i + 1) / 10)]
        edges.append(p_hold[seg].min())
        observed.append(float(yte[seg].mean()))

    Xtr = train[0] + test[0]
    ytr = np.concatenate([train[1], test[1]])
    p, _ = fit_predict("gbm", (Xtr, ytr, None), (X, None, None), num=rank_cols)

    def to_decile(score):
        for i, e in enumerate(edges):
            if score >= e:
                return i + 1, observed[i]
        return 10, observed[-1]

    if verbose:
        print(f"보정 기준: {TEST_YEARS[0]}~{TEST_YEARS[-1]} 홀드아웃 실측 "
              f"(상위10% {observed[0]*100:.1f}% / 하위10% {observed[-1]*100:.1f}%)")
    return keep, X, p, to_decile


def enrich(con, gids):
    q = ",".join("?" * len(gids))
    rows = {r["grid_id"]: dict(r) for r in con.execute(
        f"SELECT * FROM grid_feature WHERE grid_id IN ({q})", gids)}
    nm = {r["grid_id"]: r["sgis_adm_nm"] for r in con.execute(
        f"SELECT grid_id, sgis_adm_nm FROM grid_sgis WHERE grid_id IN ({q})", gids)}
    return rows, nm


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uptae", required=True, help="예: 한식 / 까페 / 분식 / 호프-간이주점")
    ap.add_argument("--area", help="자치구명 필터 (예: 마포구)")
    ap.add_argument("--site-area", type=float, help="점포 면적 ㎡")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--require-sales", action="store_true",
                    help="매출 데이터가 있는 상권 내 격자만")
    a = ap.parse_args()

    con = init()
    gids, X, p, to_decile = score_all(con, a.uptae, a.site_area)
    if not gids:
        print("평가 가능한 격자가 없습니다.")
        return 1

    feat, nm = enrich(con, gids)

    cand = []
    for gid, f, prob in zip(gids, X, p):
        g = feat.get(gid) or {}
        area = nm.get(gid) or ""
        if a.area and a.area not in area:
            continue
        if a.require_sales and not g.get("has_sales_data"):
            continue
        cand.append((prob, gid, f, g, area))
    cand.sort(key=lambda x: -x[0])

    print(f"\n총 후보 {len(cand):,}곳 중 상위 {min(a.top, len(cand))}곳"
          + (f" · 지역 필터 '{a.area}'" if a.area else ""))
    print("=" * 78)

    for rank, (prob, gid, f, g, area) in enumerate(cand[:a.top], 1):
        dec, obs = to_decile(prob)
        print(f"\n[{rank}] {area}  ({g.get('center_lat', 0):.5f}, {g.get('center_lon', 0):.5f})")
        print(f"    입지등급 상위 {dec*10}% 이내 · 같은 등급 자리의 실측 3년 생존율 "
              f"{obs*100:.1f}%   (전체 평균 61.7%)")
        print(f"    grid={gid}   신뢰도={g.get('confidence', '?')}")
        print(f"    경쟁  이 자리 {f['open_cnt']}곳 · 3x3 이웃 {f['open_cnt_r1']}곳"
              f" · 동일업태 이웃 {f['same_uptae_r1']}곳")
        ps = f.get("prior_surv_3y")
        print(f"    이력  최근3년 개업 {f['openings_36m']} / 폐업 {f['closures_36m']}"
              f" · 자리교체율 {f['churn_36m']*100:.0f}%"
              + (f" · 이 일대 과거 3년생존율 {ps*100:.0f}% (n={f['prior_surv_n']})"
                 if ps is not None else ""))
        d, w = g.get("lvpop_day"), g.get("tot_worker")
        if d:
            print(f"    수요  주간 생활인구 {d:,.0f} · 야간 {g.get('lvpop_night') or 0:,.0f}"
                  + (f" · 종사자 {w:,.0f}명(행정동)" if w else ""))
        if g.get("sales_amt"):
            print(f"    매출  상권 분기 추정 {g['sales_amt']/1e8:.0f}억")
        else:
            print(f"    매출  — (상권 영역 밖, 미관측)")

    print("\n" + "=" * 78)
    print("주의")
    print(" · 순위는 입지 피처만으로 매긴다(점포 면적 제외). 홀드아웃 성능 AUC 0.588,")
    print("   상위 10% 실측 생존율 73.1% vs 전체 61.7% — 무작위보다 나은 수준이다.")
    print(" · 상위 10% 자리에서도 약 27%는 3년 내 폐업한다. 입지는 일부일 뿐이다.")
    print(" · 점포 면적은 순위에서 뺐지만 생존과 강하게 연관된다(25㎡ 44.8% ↔ 90㎡+ 74.4%).")
    print("   자리를 고른 뒤 '얼마나 큰 가게를 낼 수 있는가'가 별개로 중요하다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
