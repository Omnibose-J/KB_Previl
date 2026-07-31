"""Raw cache -> normalized tables.

Two failure modes get explicit guards here because both fail *silently*:

1. Dates arrive as '2026-07-23              ' (hyphens + 24-char padding).
   A YYYYMMDD parser returns nothing for every row and the cohort table comes
   out empty rather than wrong - which is how it was actually caught.
2. Coordinates are EPSG:2097 in licensing and EPSG:5181 in commercial areas.
   Feeding either straight into a WGS84 consumer yields points off the coast
   of Africa, or - worse - plausibly shifted points inside Korea.
"""
import argparse
import json
import re
from collections import defaultdict

from .config import CACHE_DIR, FOOD_INDUTY
from .db import init
from .grid import in_seoul, licence_to_wgs84, to_grid_id, trdar_to_wgs84

SUCCESSION_WINDOW_DAYS = 90


def load(name):
    p = CACHE_DIR / f"{name}.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"{p} - run pipeline.collect first")
    return [json.loads(row) for row in open(p, encoding="utf-8")]


def stream(name):
    """Line-by-line iterator. licence.jsonl is 545MB; materializing it as a
    list of dicts costs several GB of Python objects for no benefit."""
    p = CACHE_DIR / f"{name}.jsonl"
    if not p.exists():
        raise FileNotFoundError(f"{p} - run pipeline.collect first")
    with open(p, encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def parse_ymd(v):
    """'2026-07-23              ' | '20260723' | '' -> (y, m, d) or None."""
    digits = "".join(ch for ch in str(v or "") if ch.isdigit())
    if len(digits) < 8:
        return None
    y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
    if not (1900 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return y, m, d


def days_since_epoch(ymd):
    """Cheap ordinal for interval comparison; exact calendar math not needed."""
    y, m, d = ymd
    return y * 372 + m * 31 + d


_PAREN = re.compile(r"\(.*?\)")
_WS = re.compile(r"\s+")


def addr_key(a):
    """Normalize a 지번 address for same-premises matching."""
    a = _PAREN.sub(" ", str(a or ""))
    return _WS.sub(" ", a).strip()


def norm_licence(con, batch=20000):
    """Raw JSON stays in pipeline/cache/licence.jsonl - it is the archive.
    Duplicating 545MB into SQLite would triple the db for no query anyone runs.
    """
    con.execute("DELETE FROM licence")

    recs = []
    stat = defaultdict(int)
    total = 0

    def flush():
        nonlocal recs
        if recs:
            con.executemany(
                "INSERT OR REPLACE INTO licence(mgtno,bplcnm,uptae,addr,open_y,open_m,"
                "close_y,close_m,state,is_closed,site_area,lon,lat,grid_id,"
                "succession_suspect) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", recs)
        con.commit()
        recs = []

    for r in stream("licence"):
        mgtno = str(r.get("MGTNO") or "").strip()
        if not mgtno:
            stat["no_mgtno"] += 1
            continue
        op = parse_ymd(r.get("APVPERMYMD"))
        cl = parse_ymd(r.get("DCBYMD"))
        stat["open_parsed"] += 1 if op else 0
        stat["close_parsed"] += 1 if cl else 0

        lon = lat = gid = None
        x, y = str(r.get("X") or "").strip(), str(r.get("Y") or "").strip()
        if x and y:
            stat["has_xy"] += 1
            p = licence_to_wgs84(x, y)
            if p:
                lon, lat = p
                gid = to_grid_id(lon, lat)
                stat["gridded"] += 1
            else:
                stat["xy_out_of_seoul"] += 1

        state = (r.get("TRDSTATENM") or "").strip()
        try:
            area = float(str(r.get("SITEAREA") or "").strip() or 0) or None
        except ValueError:
            area = None

        recs.append((
            mgtno, (r.get("BPLCNM") or "").strip(), (r.get("UPTAENM") or "").strip(),
            addr_key(r.get("SITEWHLADDR")),
            op[0] if op else None, op[1] if op else None,
            cl[0] if cl else None, cl[1] if cl else None,
            state, 1 if "폐업" in state else 0, area, lon, lat, gid, 0))
        total += 1
        if len(recs) >= batch:
            flush()
            print(f"    {total:,} rows", flush=True)
    flush()

    n = total
    print(f"licence: {n:,} rows")
    print(f"  open date parsed : {stat['open_parsed']:,} ({stat['open_parsed']/n*100:.1f}%)")
    print(f"  close date parsed: {stat['close_parsed']:,} ({stat['close_parsed']/n*100:.1f}%)")
    print(f"  has X/Y          : {stat['has_xy']:,} ({stat['has_xy']/n*100:.1f}%)")
    print(f"  gridded          : {stat['gridded']:,} ({stat['gridded']/n*100:.1f}%)")
    if stat["xy_out_of_seoul"]:
        print(f"  XY outside Seoul : {stat['xy_out_of_seoul']:,}  <- check CRS if large")
    return stat


def flag_succession(con):
    """Mark closures that look like an ownership handover, not a real failure.

    Same premises + same 업태 + a new permit within 90 days of the closure.
    Flagged rows stay in the table; the cohort step reports both with and
    without them, because excluding them is a judgement call, not a fact.
    """
    con.execute("UPDATE licence SET succession_suspect=0")
    rows = con.execute(
        "SELECT mgtno, addr, uptae, open_y, open_m, close_y, close_m, is_closed "
        "FROM licence WHERE addr<>'' AND open_y IS NOT NULL").fetchall()

    by_place = defaultdict(list)
    for r in rows:
        by_place[(r["addr"], r["uptae"])].append(r)

    flagged = []
    for key, group in by_place.items():
        if len(group) < 2:
            continue
        opens = sorted((days_since_epoch((g["open_y"], g["open_m"], 1)), g["mgtno"])
                       for g in group)
        for g in group:
            if not g["is_closed"] or g["close_y"] is None:
                continue
            c = days_since_epoch((g["close_y"], g["close_m"], 1))
            # a successor permit starting within the window after this closure
            if any(0 <= o - c <= SUCCESSION_WINDOW_DAYS and m != g["mgtno"] for o, m in opens):
                flagged.append((g["mgtno"],))

    con.executemany("UPDATE licence SET succession_suspect=1 WHERE mgtno=?", flagged)
    con.commit()
    total_closed = con.execute("SELECT count(*) FROM licence WHERE is_closed=1").fetchone()[0]
    print(f"succession_suspect: {len(flagged):,} of {total_closed:,} closures "
          f"({len(flagged)/max(1,total_closed)*100:.1f}%)")
    return len(flagged)


def norm_trdar(con, quarter=None):
    """Quarter-filtered caches carry the quarter in their filename
    (trdar_sales_20261.jsonl), matching how collect.py names them."""
    import math
    from .config import DEFAULT_QUARTER
    q = quarter or DEFAULT_QUARTER
    areas = load("trdar_area")
    con.execute("DELETE FROM trdar_area")
    recs, dropped = [], 0
    for a in areas:
        p = trdar_to_wgs84(a.get("XCNTS_VALUE"), a.get("YDNTS_VALUE"))
        if not p:
            dropped += 1
            continue
        ar = float(a.get("RELM_AR") or 0)
        recs.append((a["TRDAR_CD"], a.get("TRDAR_CD_NM"), a.get("TRDAR_SE_CD"),
                     a.get("TRDAR_SE_CD_NM"), a.get("SIGNGU_CD"), a.get("ADSTRD_CD"),
                     ar, math.sqrt(ar / math.pi) if ar else None, p[0], p[1]))
    con.executemany(
        "INSERT OR REPLACE INTO trdar_area(trdar_cd,trdar_nm,trdar_se_cd,trdar_se_nm,"
        "signgu_cd,adstrd_cd,area_m2,equiv_radius_m,center_lon,center_lat)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)", recs)
    print(f"trdar_area: {len(recs):,} rows" + (f" ({dropped} dropped, outside Seoul)" if dropped else ""))

    def f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    sales = [r for r in load(f"trdar_sales_{q}") if r.get("SVC_INDUTY_CD") in FOOD_INDUTY]
    con.execute("DELETE FROM trdar_sales")
    con.executemany(
        "INSERT OR REPLACE INTO trdar_sales VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(r["STDR_YYQU_CD"], r["TRDAR_CD"], r["SVC_INDUTY_CD"],
          f(r.get("THSMON_SELNG_AMT")), f(r.get("THSMON_SELNG_CO")),
          f(r.get("MDWK_SELNG_AMT")), f(r.get("WKEND_SELNG_AMT")),
          f(r.get("TMZON_00_06_SELNG_AMT")), f(r.get("TMZON_06_11_SELNG_AMT")),
          f(r.get("TMZON_11_14_SELNG_AMT")), f(r.get("TMZON_14_17_SELNG_AMT")),
          f(r.get("TMZON_17_21_SELNG_AMT")), f(r.get("TMZON_21_24_SELNG_AMT")))
         for r in sales])
    print(f"trdar_sales: {len(sales):,} rows (요식업 {len(FOOD_INDUTY)}개 업종만)")

    stores = [r for r in load(f"trdar_store_{q}") if r.get("SVC_INDUTY_CD") in FOOD_INDUTY]
    con.execute("DELETE FROM trdar_store")
    con.executemany(
        "INSERT OR REPLACE INTO trdar_store VALUES(?,?,?,?,?,?,?,?)",
        [(r["STDR_YYQU_CD"], r["TRDAR_CD"], r["SVC_INDUTY_CD"],
          f(r.get("STOR_CO")), f(r.get("SIMILR_INDUTY_STOR_CO")), f(r.get("FRC_STOR_CO")),
          f(r.get("OPBIZ_RT")), f(r.get("CLSBIZ_RT"))) for r in stores])
    print(f"trdar_store: {len(stores):,} rows")

    fl = load(f"trdar_flpop_{q}")
    con.execute("DELETE FROM trdar_flpop")
    con.executemany(
        "INSERT OR REPLACE INTO trdar_flpop VALUES(?,?,?,?,?,?,?,?,?)",
        [(r["STDR_YYQU_CD"], r["TRDAR_CD"], f(r.get("TOT_FLPOP_CO")),
          f(r.get("TMZON_00_06_FLPOP_CO")), f(r.get("TMZON_06_11_FLPOP_CO")),
          f(r.get("TMZON_11_14_FLPOP_CO")), f(r.get("TMZON_14_17_FLPOP_CO")),
          f(r.get("TMZON_17_21_FLPOP_CO")), f(r.get("TMZON_21_24_FLPOP_CO")))
         for r in fl])
    print(f"trdar_flpop: {len(fl):,} rows")
    con.commit()


def norm_lvpop(con):
    rows = load("lvpop")
    agg = defaultdict(lambda: [0.0, 0])
    for r in rows:
        dong, tz = r.get("ADSTRD_CODE_SE"), r.get("TMZON_PD_SE")
        try:
            v = float(r.get("TOT_LVPOP_CO"))
        except (TypeError, ValueError):
            continue
        a = agg[(dong, tz)]
        a[0] += v
        a[1] += 1
    con.execute("DELETE FROM lvpop_profile")
    con.executemany("INSERT OR REPLACE INTO lvpop_profile VALUES(?,?,?,?)",
                    [(d, t, s / n, n) for (d, t), (s, n) in agg.items()])
    con.commit()
    days = len({r.get("STDR_DE_ID") for r in rows})
    print(f"lvpop_profile: {len(agg):,} rows ({len({d for d,_ in agg}):,} 행정동 x "
          f"{len({t for _,t in agg})} 시간대, {days} days averaged)")


def norm_store(con):
    p = CACHE_DIR / "semas_seoul.jsonl"
    if not p.exists():
        print("store: skipped (semas_seoul.jsonl absent)")
        return
    rows = [json.loads(row) for row in open(p, encoding="utf-8")]
    con.execute("DELETE FROM store")
    recs = []
    for r in rows:
        try:
            lon, lat = float(r["lon"]), float(r["lat"])
        except (TypeError, ValueError, KeyError):
            continue
        if not in_seoul(lon, lat):
            continue
        recs.append((r.get("bizesId"), r.get("bizesNm"), r.get("indsLclsNm"),
                     r.get("indsMclsNm"), r.get("indsSclsNm"), r.get("adongCd"),
                     r.get("pnu"), r.get("bldNm"), r.get("flrNo"),
                     lon, lat, to_grid_id(lon, lat)))
    con.executemany("INSERT OR REPLACE INTO store VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", recs)
    con.commit()
    print(f"store: {len(recs):,} rows")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["licence", "trdar", "lvpop", "store"])
    a = ap.parse_args()
    con = init()
    if a.only in (None, "licence"):
        norm_licence(con)
        flag_succession(con)
    if a.only in (None, "trdar"):
        norm_trdar(con)
    if a.only in (None, "lvpop"):
        norm_lvpop(con)
    if a.only in (None, "store"):
        norm_store(con)
