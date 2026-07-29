"""Tier 2 — 휴게음식점 (LOCALDATA_072405) as a second licensing source.

The existing feature set counts 일반음식점 only, which means Starbucks, most
cafes and most fast food are invisible to every competition and agglomeration
feature. That is a named blind spot, not a rounding error: a cell surrounded by
cafes currently looks empty.

Same source family as the main licence table, so the as-of reconstruction is
identical - open date, close date, X/Y in EPSG:5174. Normalisation deliberately
reuses pipeline.normalize / pipeline.grid rather than reimplementing date and
CRS handling: a second parser that disagrees by one convention would place these
shops in different cells than the shops they are supposed to compete with.
"""
import argparse
import sys
import time

from pipeline.db import init
from pipeline.grid import licence_to_wgs84, to_grid_id
from pipeline.normalize import parse_ymd, stream

SCHEMA = """
CREATE TABLE IF NOT EXISTS licence_rest (
  mgtno    TEXT PRIMARY KEY,
  bplcnm   TEXT,
  uptae    TEXT,
  open_y   INTEGER, open_m INTEGER,
  close_y  INTEGER, close_m INTEGER,
  is_closed INTEGER,
  grid_id  TEXT
);
CREATE INDEX IF NOT EXISTS ix_rest_grid ON licence_rest(grid_id);
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default="licence_rest")
    a = ap.parse_args()

    t0 = time.time()
    con = init()
    con.executescript(SCHEMA)
    con.execute("DELETE FROM licence_rest")

    recs, stat, total = [], {"open": 0, "xy": 0, "grid": 0, "closed": 0}, 0
    for r in stream(a.cache):
        mgtno = str(r.get("MGTNO") or "").strip()
        if not mgtno:
            continue
        op, cl = parse_ymd(r.get("APVPERMYMD")), parse_ymd(r.get("DCBYMD"))
        stat["open"] += 1 if op else 0
        gid = None
        x, y = str(r.get("X") or "").strip(), str(r.get("Y") or "").strip()
        if x and y:
            stat["xy"] += 1
            p = licence_to_wgs84(x, y)
            if p:
                gid = to_grid_id(*p)
                stat["grid"] += 1
        state = (r.get("TRDSTATENM") or "").strip()
        closed = 1 if "폐업" in state else 0
        stat["closed"] += closed
        recs.append((mgtno, (r.get("BPLCNM") or "").strip(),
                     (r.get("UPTAENM") or "").strip(),
                     op[0] if op else None, op[1] if op else None,
                     cl[0] if cl else None, cl[1] if cl else None, closed, gid))
        total += 1
        if len(recs) >= 20000:
            con.executemany("INSERT OR REPLACE INTO licence_rest VALUES(?,?,?,?,?,?,?,?,?)", recs)
            con.commit()
            recs = []
    if recs:
        con.executemany("INSERT OR REPLACE INTO licence_rest VALUES(?,?,?,?,?,?,?,?,?)", recs)
    con.commit()

    print(f"licence_rest: {total:,} rows · {time.time()-t0:.0f}초")
    print(f"  개업일 파싱 {stat['open']:,} ({stat['open']/total*100:.1f}%)")
    print(f"  X/Y 보유    {stat['xy']:,} ({stat['xy']/total*100:.1f}%)")
    print(f"  격자 배정   {stat['grid']:,} ({stat['grid']/total*100:.1f}%)")
    print(f"  폐업        {stat['closed']:,} ({stat['closed']/total*100:.1f}%)")
    top = con.execute("SELECT uptae, count(*) c FROM licence_rest GROUP BY 1 "
                      "ORDER BY c DESC LIMIT 8").fetchall()
    print("  업태 상위: " + " · ".join(f"{r[0]} {r[1]:,}" for r in top))
    cov = con.execute("SELECT count(DISTINCT grid_id) FROM licence_rest "
                      "WHERE grid_id IS NOT NULL").fetchone()[0]
    # 전체 격자 수를 상수로 박아두면 재구축 때마다 조용히 낡는다(실제로 21,544
    # 에서 23,572 로 늘었는데 이 줄만 남아 있었다). 그때그때 센다.
    total = con.execute("SELECT count(*) FROM grid").fetchone()[0]
    print(f"  커버 격자 {cov:,} / 전체 {total:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
