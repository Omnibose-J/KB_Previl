"""Tier 3 — 지하철 역별 월간 승하차 (CardSubwayTime).

Coverage starts 2015-01, which is the whole story for how this feature can be
used. The confirmed training period reaches back to 2005, so on the main bench
most rows would be imputed and the measurement would return a structural zero
that reads like a rejection. It is therefore measured on the same 2017-2018
sub-bench the search-trend feature uses, with the constraint printed beside the
number - not folded into the headline set.

Values are station-level and joined to a cell through its nearest station
(grid_access.station_name), so they are labelled a station-unit value: cells
sharing a nearest station tie on it, exactly like every other coarse feature.
That is the honest alternative to smearing the value across a grid.
"""
import argparse
import sys
import time

from pipeline.db import init
from pipeline.seoul_api import fetch_all, remaining

SCHEMA = """
CREATE TABLE IF NOT EXISTS station_ride (
  station TEXT,
  ym      INTEGER,          -- year*12 + month
  riders  REAL,             -- monthly boarding + alighting
  PRIMARY KEY (station, ym)
);
"""
START, END = (2015, 1), (2022, 12)


def months(a, b):
    y, m = a
    while (y, m) <= b:
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    con = init()
    con.executescript(SCHEMA)
    want = list(months(START, END))
    print(f"수집 대상 {len(want)}개월 ({START[0]}-{START[1]:02d} ~ {END[0]}-{END[1]:02d}) · "
          f"남은 호출 {remaining()}")
    if a.dry_run:
        return 0

    rows, seen = [], 0
    for y, m in want:
        mm = f"{y}{m:02d}"
        got = fetch_all("CardSubwayTime", args=f"{mm}/", cache_name=f"subway_{mm}")
        for r in got:
            tot = sum(float(v or 0) for k, v in r.items() if k.startswith("HR_"))
            rows.append(((r.get("STTN") or "").strip(), y * 12 + m, tot))
        seen += len(got)
        if len(rows) >= 5000:
            con.executemany("INSERT OR REPLACE INTO station_ride VALUES(?,?,?)", rows)
            con.commit()
            rows = []
    if rows:
        con.executemany("INSERT OR REPLACE INTO station_ride VALUES(?,?,?)", rows)
    con.commit()

    n = con.execute("SELECT count(*) FROM station_ride").fetchone()[0]
    ns = con.execute("SELECT count(DISTINCT station) FROM station_ride").fetchone()[0]
    match = con.execute(
        "SELECT count(DISTINCT ga.station_name) FROM grid_access ga "
        "WHERE ga.station_name IN (SELECT station FROM station_ride)").fetchone()[0]
    total = con.execute("SELECT count(DISTINCT station_name) FROM grid_access").fetchone()[0]
    print(f"station_ride: {n:,}행 · 역 {ns} · {time.time()-t0:.0f}초")
    print(f"  grid_access 최근접역 이름 매칭 {match}/{total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
