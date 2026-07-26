"""Read-only query layer for the UI. Everything returns plain JSON-safe dicts.

All scoring happens in `service.precompute`; nothing here trains or fits, so a
call is a few indexed SQLite lookups. That keeps the UI contract stable even if
the model behind `grid_score` is retrained or replaced.

Numbers carry their provenance. `survival_pct` is the rate OBSERVED for that
grade on held-out data, not the model's probability, and every area-level field
is labelled with the unit it came from so the UI can show it honestly.
"""
import json
from functools import lru_cache

from pipeline.db import connect
from pipeline.grid import grid_center, to_grid_id

# What resolution each field actually comes from - the UI should surface this.
RESOLUTION = {
    "food_store_cnt": "격자 100m",
    "food_store_cnt_r1": "격자 3x3 (300m)",
    "survive_3y_local": "격자 3x3 (300m)",
    "hist_open_cnt": "격자 100m",
    "hist_close_cnt": "격자 100m",
    "lvpop_day": "행정동",
    "lvpop_night": "행정동",
    "corp_cnt": "행정동",
    "tot_worker": "행정동",
    "ppltn_dnsty": "행정동",
    "sales_amt": "상권 (중앙값 반경 151m)",
    "flpop": "상권 (중앙값 반경 151m)",
    "station_dist_m": "지점 실측",
}


@lru_cache(maxsize=1)
def meta():
    con = connect()
    m = {r["k"]: r["v"] for r in con.execute("SELECT k, v FROM score_meta")}
    uptae = [r[0] for r in con.execute(
        "SELECT DISTINCT uptae FROM grid_score ORDER BY 1")]
    gu = [r[0] for r in con.execute(
        "SELECT DISTINCT substr(sgis_adm_nm, 7, 4) FROM grid_sgis "
        "WHERE sgis_adm_nm IS NOT NULL ORDER BY 1") if r[0] and r[0].endswith("구")]
    obs = [float(x) for x in (m.get("observed_by_grade") or "").split(",") if x]
    con.close()
    return {
        "as_of": m.get("as_of"),
        "uptae": uptae,
        "districts": gu,
        "grades": [{"grade": i + 1, "survival_pct": round(v * 100, 1)}
                   for i, v in enumerate(obs)],
        "overall_survival_pct": round(float(m.get("overall_survival", 0)) * 100, 1),
        "model": {
            "auc_holdout": 0.5909,
            "note": "순위는 입지 피처만 사용(점포 면적·층 제외). "
                    "상위 10% 실측 생존율 74.3% vs 전체 61.7%.",
            "caveat": "상위 10% 자리에서도 약 27%는 3년 내 폐업한다.",
        },
        "resolution": RESOLUTION,
    }


def _row(r, nm=None):
    f = dict(r)
    try:
        mix = json.loads(f.get("competitor_same_uptae") or "{}")
    except Exception:
        mix = {}
    return {
        "grid_id": f["grid_id"],
        "lat": round(f["center_lat"], 6),
        "lon": round(f["center_lon"], 6),
        "area_name": nm,
        "grade": f.get("grade"),
        "survival_pct": round((f.get("observed") or 0) * 100, 1) if f.get("observed") else None,
        "confidence": f.get("confidence"),
        "competition": {
            "cell": f.get("food_store_cnt"),
            "ring": f.get("food_store_cnt_r1"),
            "by_uptae": dict(sorted(mix.items(), key=lambda kv: -kv[1])[:6]),
            "franchise_in_trdar": f.get("franchise_cnt"),
        },
        "history": {
            "opened": f.get("hist_open_cnt"),
            "closed": f.get("hist_close_cnt"),
            "survive_3y_local_pct": f.get("survive_3y_local"),
            "sample": f.get("survive_3y_n"),
        },
        "demand": {
            "lvpop_day": f.get("lvpop_day"),
            "lvpop_night": f.get("lvpop_night"),
            "businesses": f.get("corp_cnt"),
            "workers": f.get("tot_worker"),
            "worker_per_resident": f.get("worker_per_resident"),
            "population_density": f.get("ppltn_dnsty"),
        },
        # NULL means unobserved, never zero - see README
        "sales": {
            "quarterly_amt": f.get("sales_amt"),
            "quarterly_cnt": f.get("sales_cnt"),
            "flpop": f.get("flpop"),
            "available": f.get("sales_amt") is not None,
        },
        "access": {
            "station_dist_m": f.get("station_dist_m"),
            "station_name": f.get("station_name"),
            "stations_500m": f.get("stations_500m"),
        },
    }


SELECT = """
SELECT f.*, s.grade, s.observed, s.score, gs.sgis_adm_nm nm,
       a.station_dist_m, a.station_name, a.stations_500m
FROM grid_feature f
JOIN grid_score s ON s.grid_id=f.grid_id AND s.uptae=?
LEFT JOIN grid_sgis gs ON gs.grid_id=f.grid_id
LEFT JOIN grid_access a ON a.grid_id=f.grid_id
"""


def recommend(uptae, district=None, top=20, require_sales=False, min_grade=None):
    con = connect()
    sql = SELECT
    args = [uptae]
    where = []
    if district:
        where.append("gs.sgis_adm_nm LIKE ?")
        args.append(f"%{district}%")
    if require_sales:
        where.append("f.sales_amt IS NOT NULL")
    if min_grade:
        where.append("s.grade <= ?")
        args.append(min_grade)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY s.score DESC LIMIT ?"
    args.append(top)
    rows = con.execute(sql, args).fetchall()
    out = [_row(r, r["nm"]) for r in rows]
    con.close()
    return {"uptae": uptae, "district": district, "count": len(out), "items": out}


def grid_detail(grid_id, uptae):
    con = connect()
    r = con.execute(SELECT + " WHERE f.grid_id=?", (uptae, grid_id)).fetchone()
    con.close()
    return _row(r, r["nm"]) if r else None


def at_point(lon, lat, uptae):
    return grid_detail(to_grid_id(lon, lat), uptae)


def district_summary(uptae):
    """Grade distribution per 자치구 - useful for a first-pass map."""
    con = connect()
    rows = con.execute(
        "SELECT substr(gs.sgis_adm_nm, 7, 4) gu, count(*) n, "
        "  SUM(s.grade<=2) top20, AVG(s.observed) avg_surv "
        "FROM grid_score s JOIN grid_sgis gs ON gs.grid_id=s.grid_id "
        "WHERE s.uptae=? AND gs.sgis_adm_nm IS NOT NULL GROUP BY 1 "
        "ORDER BY top20*1.0/n DESC", (uptae,)).fetchall()
    con.close()
    return [{"district": r["gu"], "cells": r["n"], "top20pct_cells": r["top20"],
             "top20_share": round(r["top20"] / r["n"] * 100, 1),
             "avg_survival_pct": round((r["avg_surv"] or 0) * 100, 1)}
            for r in rows if r["gu"] and r["gu"].endswith("구")]


if __name__ == "__main__":
    import sys
    print(json.dumps(meta(), ensure_ascii=False, indent=2)[:900])
    u = sys.argv[1] if len(sys.argv) > 1 else "한식"
    r = recommend(u, top=2)
    print("\n" + json.dumps(r, ensure_ascii=False, indent=2)[:1400])
