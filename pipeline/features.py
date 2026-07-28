"""Build grid + grid_feature.

The one invariant that matters here: a cell with no source for a feature gets
NULL, not 0. Sales outside a commercial area are unknown, not zero - and a
0 would rank that cell as the worst possible location instead of an unscored
one. Every NULL-vs-0 decision in this file is deliberate.
"""
import argparse
import json
import math
import sqlite3
from collections import Counter, defaultdict

from .config import DEFAULT_QUARTER
from .db import init
from .grid import grid_center, neighbors, to_grid_id

MIN_SURVIVAL_SAMPLE = 20      # below this a local survival rate is noise -> NULL
M_PER_DEG_LAT = 111_320.0


def _m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


def build_grid(con):
    """Cells that any source actually touches, plus commercial-area assignment."""
    con.execute("DELETE FROM grid")

    cells = {}
    for tbl in ("licence", "store"):
        try:
            rows = con.execute(
                f"SELECT DISTINCT grid_id FROM {tbl} WHERE grid_id IS NOT NULL").fetchall()
        except sqlite3.OperationalError:
            # 테이블이 아직 없는 경우만 넘긴다. Exception 을 통째로 삼키면 SQL
            # 오타·DB 손상까지 "데이터 없음" 으로 위장돼 피처가 조용히 빈다.
            continue
        for r in rows:
            cells.setdefault(r["grid_id"], None)
    print(f"grid: {len(cells):,} cells touched by data")

    areas = con.execute(
        "SELECT trdar_cd, trdar_se_nm, adstrd_cd, equiv_radius_m, center_lon, center_lat "
        "FROM trdar_area WHERE center_lon IS NOT NULL").fetchall()
    # coarse spatial index (~1.1km buckets)
    idx = defaultdict(list)
    for a in areas:
        idx[(int(a["center_lon"] / 0.01), int(a["center_lat"] / 0.01))].append(a)

    recs = []
    for gid in cells:
        lon, lat = grid_center(gid)
        gx, gy = int(lon / 0.01), int(lat / 0.01)
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for a in idx.get((gx + dx, gy + dy), ()):
                    d = math.hypot((lon - a["center_lon"]) * _m_per_deg_lon(lat),
                                   (lat - a["center_lat"]) * M_PER_DEG_LAT)
                    if a["equiv_radius_m"] and d <= a["equiv_radius_m"]:
                        # smallest containing area wins - the most specific one
                        if best is None or a["equiv_radius_m"] < best["equiv_radius_m"]:
                            best = a
        # adstrd_cd is deliberately left NULL here - pipeline.geocode fills it by
        # reverse geocoding. Seeding it from the containing commercial area was
        # only 75.5% accurate and, worse, survived as a stale value wherever a
        # later geocode call failed.
        recs.append((gid, lon, lat, None,
                     best["trdar_cd"] if best else None,
                     best["trdar_se_nm"] if best else None,
                     1 if best else 0))

    con.executemany(
        "INSERT OR REPLACE INTO grid(grid_id,center_lon,center_lat,adstrd_cd,"
        "trdar_cd,trdar_se_nm,has_sales_data) VALUES(?,?,?,?,?,?,?)", recs)
    con.commit()

    inside = sum(1 for r in recs if r[6])
    print(f"  in a commercial area: {inside:,} cells ({inside/len(recs)*100:.1f}%)")
    return len(recs)


def fill_dong(con):
    """Cells outside any commercial area still need a 행정동 for demand data.

    Falls back to the nearest area's dong; cells with neither stay NULL and
    lose the demand feature rather than borrowing a wrong one.
    """
    rows = con.execute("SELECT grid_id, center_lon, center_lat FROM grid "
                       "WHERE adstrd_cd IS NULL").fetchall()
    if not rows:
        return 0
    areas = con.execute("SELECT adstrd_cd, center_lon, center_lat FROM trdar_area "
                        "WHERE center_lon IS NOT NULL AND adstrd_cd IS NOT NULL").fetchall()
    idx = defaultdict(list)
    for a in areas:
        idx[(int(a["center_lon"] / 0.02), int(a["center_lat"] / 0.02))].append(a)

    upd = []
    for r in rows:
        lon, lat = r["center_lon"], r["center_lat"]
        gx, gy = int(lon / 0.02), int(lat / 0.02)
        best, bd = None, 1e18
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                for a in idx.get((gx + dx, gy + dy), ()):
                    d = ((lon - a["center_lon"]) * _m_per_deg_lon(lat)) ** 2 + \
                        ((lat - a["center_lat"]) * M_PER_DEG_LAT) ** 2
                    if d < bd:
                        best, bd = a, d
        # 1.5km cap - beyond that the nearest dong is not a defensible proxy
        if best and math.sqrt(bd) <= 1500:
            upd.append((best["adstrd_cd"], r["grid_id"]))
    con.executemany("UPDATE grid SET adstrd_cd=? WHERE grid_id=?", upd)
    con.commit()
    left = con.execute("SELECT count(*) FROM grid WHERE adstrd_cd IS NULL").fetchone()[0]
    print(f"  dong backfilled: {len(upd):,}   still NULL: {left:,}")
    return len(upd)


def build_features(con, quarter=DEFAULT_QUARTER):
    con.execute("DELETE FROM grid_feature")

    grid = {r["grid_id"]: r for r in con.execute("SELECT * FROM grid")}

    # --- competition + local history, from licensing ---------------------
    open_by_cell = Counter()
    uptae_by_cell = defaultdict(Counter)
    hist_open, hist_close = Counter(), Counter()
    surv_obs, surv_closed = Counter(), Counter()

    cut = con.execute("SELECT MAX(open_y*12+open_m) FROM licence").fetchone()[0]
    for r in con.execute("SELECT grid_id,uptae,is_closed,open_y,open_m,close_y,close_m "
                         "FROM licence WHERE grid_id IS NOT NULL"):
        g = r["grid_id"]
        hist_open[g] += 1
        if r["is_closed"]:
            hist_close[g] += 1
        else:
            open_by_cell[g] += 1
            uptae_by_cell[g][r["uptae"] or "기타"] += 1
        if r["open_y"]:
            om = r["open_y"] * 12 + (r["open_m"] or 1)
            if om + 36 <= cut:
                surv_obs[g] += 1
                if r["is_closed"] and r["close_y"]:
                    cm = r["close_y"] * 12 + (r["close_m"] or 1)
                    if cm - om <= 36:
                        surv_closed[g] += 1

    # --- franchise + sales, from commercial-area tables -------------------
    frc, sales, flpop = {}, {}, {}
    for r in con.execute("SELECT trdar_cd, SUM(frc_stor_co) f FROM trdar_store "
                         "WHERE quarter=? GROUP BY trdar_cd", (quarter,)):
        frc[r["trdar_cd"]] = r["f"]
    for r in con.execute("SELECT trdar_cd, SUM(sales_amt) a, SUM(sales_cnt) c "
                         "FROM trdar_sales WHERE quarter=? GROUP BY trdar_cd", (quarter,)):
        sales[r["trdar_cd"]] = (r["a"], r["c"])
    for r in con.execute("SELECT trdar_cd, tot_flpop FROM trdar_flpop WHERE quarter=?",
                         (quarter,)):
        flpop[r["trdar_cd"]] = r["tot_flpop"]

    # --- census demand, joined via SGIS polygon match ---------------------
    # Cells inside the same 행정동 tie on these. That is deliberate: allocating
    # a dong total across its cells would invent numbers we cannot defend.
    sgis = {}
    try:
        for r in con.execute(
                "SELECT gs.grid_id, s.adm_cd, s.ppltn_dnsty, s.avg_age, "
                "  s.avg_fmember_cnt, s.corp_cnt, s.tot_worker, s.tot_ppltn "
                "FROM grid_sgis gs JOIN sgis_dong s ON gs.sgis_adm_cd=s.adm_cd"):
            sgis[r["grid_id"]] = r
    except Exception:
        pass

    # --- demand, from living population ----------------------------------
    day, night = {}, {}
    for r in con.execute(
            "SELECT adstrd_cd, "
            "AVG(CASE WHEN CAST(tmzon AS INTEGER) BETWEEN 11 AND 17 THEN avg_lvpop END) d,"
            "AVG(CASE WHEN CAST(tmzon AS INTEGER) BETWEEN 18 AND 23 THEN avg_lvpop END) n "
            "FROM lvpop_profile GROUP BY adstrd_cd"):
        day[r["adstrd_cd"]] = r["d"]
        night[r["adstrd_cd"]] = r["n"]

    recs = []
    for gid, g in grid.items():
        ring = neighbors(gid, 1)
        cnt_r1 = sum(open_by_cell.get(n, 0) for n in ring)
        obs = sum(surv_obs.get(n, 0) for n in ring)
        cls = sum(surv_closed.get(n, 0) for n in ring)
        t = g["trdar_cd"]
        s = sales.get(t) if t else None

        sg = sgis.get(gid)
        wpr = None
        if sg and sg["tot_worker"] and sg["tot_ppltn"]:
            wpr = round(sg["tot_worker"] / sg["tot_ppltn"], 3)

        recs.append((
            gid, g["center_lon"], g["center_lat"], g["adstrd_cd"], t, g["has_sales_data"],
            open_by_cell.get(gid, 0),
            cnt_r1,
            json.dumps(dict(uptae_by_cell.get(gid, {})), ensure_ascii=False),
            frc.get(t) if t else None,
            hist_open.get(gid, 0),
            hist_close.get(gid, 0),
            # local 3y survival: NULL unless the ring holds a usable sample
            round((1 - cls / obs) * 100, 1) if obs >= MIN_SURVIVAL_SAMPLE else None,
            obs,
            day.get(g["adstrd_cd"]),
            night.get(g["adstrd_cd"]),
            sg["adm_cd"] if sg else None,
            sg["ppltn_dnsty"] if sg else None,
            sg["avg_age"] if sg else None,
            sg["avg_fmember_cnt"] if sg else None,
            sg["corp_cnt"] if sg else None,
            sg["tot_worker"] if sg else None,
            wpr,
            # sales/flpop stay NULL outside a commercial area - never 0
            s[0] if s else None,
            s[1] if s else None,
            flpop.get(t) if t else None,
            "full" if g["has_sales_data"] else "partial",
        ))

    con.executemany(
        "INSERT OR REPLACE INTO grid_feature VALUES(" + ",".join("?" * 27) + ")", recs)
    con.commit()

    # index by name, not position - adding a column silently broke this once
    n = len(recs)
    full = con.execute(
        "SELECT count(*) FROM grid_feature WHERE confidence='full'").fetchone()[0]
    withsurv = con.execute(
        "SELECT count(*) FROM grid_feature WHERE survive_3y_local IS NOT NULL").fetchone()[0]
    withsgis = con.execute(
        "SELECT count(*) FROM grid_feature WHERE corp_cnt IS NOT NULL").fetchone()[0]
    print(f"grid_feature: {n:,} rows")
    print(f"  confidence=full   : {full:,} ({full/n*100:.1f}%)")
    print(f"  local 3y survival : {withsurv:,} ({withsurv/n*100:.1f}%) "
          f"(n>={MIN_SURVIVAL_SAMPLE} in 3x3 ring)")
    print(f"  SGIS 센서스        : {withsgis:,} ({withsgis/n*100:.1f}%) 행정동 단위")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quarter", default=DEFAULT_QUARTER)
    a = ap.parse_args()
    con = init()
    build_grid(con)
    fill_dong(con)
    build_features(con, a.quarter)
