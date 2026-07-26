"""Build (features at opening, survived N years) rows for a cohort year.

Two rules that keep this honest:

1. Features are taken at `open_ym - 1` - the month *before* the shop opened.
   The shop being placed must not appear in its own neighbourhood count, and
   taking the state one month earlier is the natural way to say "what was here
   before I arrived".

2. Right-censored shops are dropped, not counted as survivors. A shop that
   opened 18 months ago has no 3-year verdict yet; keeping it would label it
   "survived" and inflate every downstream number.

The survival definition is imported behaviour from pipeline/cohort.py - same
horizon arithmetic, same censoring test - so the two can be cross-checked.
"""
import argparse
from functools import lru_cache

from pipeline.db import init

from .asof import AccessIndex, AsOf, MentionIndex, TrendIndex, load_shops, ym


def observation_cut(con):
    r = con.execute(
        "SELECT MAX(open_y*12+COALESCE(open_m,1)) FROM licence WHERE open_y IS NOT NULL"
    ).fetchone()[0]
    return r


def build(con, year, horizon=3, verbose=False, with_trend=False,
          with_mention=False, gu=None):
    shops = load_shops(con)
    ao = AsOf(shops)
    ti = TrendIndex(con) if with_trend else None
    mi = MentionIndex(con) if with_mention else None
    ai = AccessIndex(con)
    cut = observation_cut(con)
    hm = horizon * 12

    if gu:
        rows = con.execute(
            "SELECT l.grid_id, l.uptae, l.open_y, l.open_m, l.close_y, l.close_m, "
            "  l.is_closed, l.site_area FROM licence l "
            "JOIN grid_sgis gs ON l.grid_id=gs.grid_id "
            "WHERE l.grid_id IS NOT NULL AND l.open_y=? AND gs.sgis_adm_nm LIKE ?",
            (year, f"%{gu}%")).fetchall()
    else:
        rows = con.execute(
            "SELECT grid_id, uptae, open_y, open_m, close_y, close_m, is_closed, site_area "
            "FROM licence WHERE grid_id IS NOT NULL AND open_y=?", (year,)).fetchall()

    # memoize cell state per (cell, month) - a cohort year has <=12 distinct months
    @lru_cache(maxsize=None)
    def cell_ring(cell, t, uptae):
        f = ao.cell_state(cell, t, uptae)
        f.update(ao.ring_state(cell, t, uptae))
        return f

    X, y, censored, meta = [], [], 0, []
    for r in rows:
        o = ym(r["open_y"], r["open_m"])
        if o + hm > cut:
            censored += 1
            continue                      # horizon not elapsed -> no verdict
        ut = r["uptae"] or "기타"
        f = dict(cell_ring(r["grid_id"], o - 1, ut))
        f["site_area"] = r["site_area"]
        f["open_month"] = r["open_m"] or 1
        f["uptae"] = ut
        if ai.available:
            f.update(ai.features(r["grid_id"]))
        if ti is not None:
            f.update(ti.features(r["grid_id"], o))
        if mi is not None:
            f.update(mi.features(r["grid_id"], o))

        closed_within = False
        if r["is_closed"] and r["close_y"]:
            c = ym(r["close_y"], r["close_m"])
            closed_within = (c - o) <= hm
        X.append(f)
        y.append(0 if closed_within else 1)   # 1 = survived
        meta.append({"grid_id": r["grid_id"], "uptae": ut, "open_ym": o})

    if verbose:
        sr = sum(y) / len(y) * 100 if y else 0
        print(f"{year}년 코호트 · horizon {horizon}년")
        print(f"  사용 {len(y):,}건 · 우편절단 제외 {censored:,}건")
        print(f"  라벨 생존율 {sr:.1f}%")
    return X, y, meta, censored


def check(con, year, horizon=3):
    """Label mean must agree with pipeline's cohort table."""
    X, y, meta, censored = build(con, year, horizon, verbose=True)
    ref = con.execute(
        f"SELECT survive_{horizon}y, observable_{horizon}y FROM cohort_survival "
        "WHERE scope='seoul' AND succession_excluded=0 AND open_year=?", (year,)).fetchone()
    if not ref or ref[0] is None:
        print("  cohort_survival에 비교 대상 없음")
        return False
    mine = sum(y) / len(y) * 100
    d = abs(mine - ref[0])
    print(f"  cohort_survival 값 {ref[0]:.1f}% (n={ref[1]:,})")
    print(f"  편차 {d:.2f}%p (허용 0.5%p) -> {'PASS' if d <= 0.5 else 'FAIL'}")
    print(f"  * 표본 차이: 모델은 좌표 보유 격자만, cohort는 전량")
    return d <= 0.5


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    con = init()
    if a.check:
        raise SystemExit(0 if check(con, a.year, a.horizon) else 1)
    build(con, a.year, a.horizon, verbose=True)
