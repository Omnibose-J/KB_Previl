"""Transit accessibility per grid cell.

Why this and not more licensing-derived features: adding seven more ring
statistics moved AUC by 0.0001 - the licensing history is saturated, every new
aggregate restates information already present. Station distance is genuinely
outside that table, so it can carry information the model has never seen.

Time validity: station positions are effectively constant over the study period.
A handful of lines opened during 2013-2022 (신림선 2022, 김포골드 2019 ...), and
the API does not expose opening dates, so those cells get a distance slightly
too optimistic for early years. Recorded as a known limitation rather than
silently ignored - the affected share is small and the direction is knowable.
"""
import argparse
import math

import requests

from .config import GRID_SIZE_M, SEOUL_BASE
from .db import init
from .seoul_api import api_key

SVC = "subwayStationMaster"
M_PER_DEG_LAT = 111_320.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS station (
  bldn_id  TEXT PRIMARY KEY,
  name     TEXT,
  route    TEXT,
  lat      REAL,
  lon      REAL
);
CREATE TABLE IF NOT EXISTS grid_access (
  grid_id        TEXT PRIMARY KEY,
  station_dist_m REAL,
  station_name   TEXT,
  stations_500m  INTEGER,
  stations_1km   INTEGER,
  transfer_dist_m REAL      -- nearest station served by 2+ routes
);
"""


def fetch_stations(con):
    rows, start = [], 1
    while True:
        r = requests.get(f"{SEOUL_BASE}/{api_key()}/json/{SVC}/{start}/{start+999}/",
                         timeout=60).json().get(SVC) or {}
        got = r.get("row") or []
        rows.extend(got)
        if len(got) < 1000:
            break
        start += 1000

    recs, seen = [], {}
    for s in rows:
        try:
            lat, lon = float(s["LAT"]), float(s["LOT"])
        except (TypeError, ValueError, KeyError):
            continue
        recs.append((s.get("BLDN_ID"), s.get("BLDN_NM"), s.get("ROUTE"), lat, lon))
        seen.setdefault(s.get("BLDN_NM"), set()).add(s.get("ROUTE"))
    con.executescript(SCHEMA)
    con.execute("DELETE FROM station")
    con.executemany("INSERT OR REPLACE INTO station VALUES(?,?,?,?,?)", recs)
    con.commit()
    multi = {n for n, r in seen.items() if len(r) >= 2}
    print(f"station: {len(recs):,}개 (환승역 {len(multi):,}개)")
    return recs, multi


def build(con):
    recs, multi = fetch_stations(con)
    lats = [r[3] for r in recs]
    lons = [r[4] for r in recs]
    names = [r[1] for r in recs]
    is_tr = [1 if r[1] in multi else 0 for r in recs]

    cells = con.execute("SELECT grid_id, center_lon, center_lat FROM grid").fetchall()
    out = []
    for c in cells:
        lon, lat = c["center_lon"], c["center_lat"]
        mlon = M_PER_DEG_LAT * math.cos(math.radians(lat))
        best = bestn = None
        bestd = 1e18
        tr_d = 1e18
        n500 = n1k = 0
        for i in range(len(recs)):
            dx = (lon - lons[i]) * mlon
            dy = (lat - lats[i]) * M_PER_DEG_LAT
            d2 = dx * dx + dy * dy
            if d2 < bestd:
                bestd, bestn = d2, names[i]
            if is_tr[i] and d2 < tr_d:
                tr_d = d2
            if d2 <= 500 ** 2:
                n500 += 1
            if d2 <= 1000 ** 2:
                n1k += 1
        out.append((c["grid_id"], round(math.sqrt(bestd), 1), bestn, n500, n1k,
                    round(math.sqrt(tr_d), 1) if tr_d < 1e18 else None))

    con.execute("DELETE FROM grid_access")
    con.executemany("INSERT OR REPLACE INTO grid_access VALUES(?,?,?,?,?,?)", out)
    con.commit()

    r = con.execute(
        "SELECT count(*) n, AVG(station_dist_m) a, MIN(station_dist_m) mn, "
        "MAX(station_dist_m) mx, SUM(station_dist_m<=500) near "
        "FROM grid_access").fetchone()
    print(f"grid_access: {r[0]:,}격자 · 역까지 평균 {r[1]:.0f}m "
          f"(최소 {r[2]:.0f} / 최대 {r[3]:.0f}) · 500m 이내 {r[4]:,}격자")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    a = ap.parse_args()
    build(init())
