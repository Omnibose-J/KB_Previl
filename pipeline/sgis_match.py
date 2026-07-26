"""Match grid cells to SGIS 행정동 by polygon containment.

Necessary because SGIS uses 통계청 administrative codes while our cells carry
행정안전부 codes from Kakao reverse geocoding - they look alike (both 8 digits)
but do not correspond: SGIS 11110 is 노원구 where MOIS 11110 is 종로구. Joining
on the code string matched 32 of 440 dongs, which would have silently attached
the wrong district's population to almost every cell.

Name matching would be ambiguous (신사동 exists in both 강남구 and 은평구), so
this uses geometry instead. SGIS serves 행정동 polygons in EPSG:5179 - the same
CRS our grid is defined in - so containment is exact with no reprojection.

집계구 polygons are NOT available (low_search=2 returns errCd -100), so this
stops at 행정동. See the spatial-resolution decision: we do not fabricate a
finer join by allocating dong values across cells.
"""
import argparse
import io
import json

import requests
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

from .config import CACHE_DIR, ENV_PATH, GRID_SIZE_M, ROOT
from .db import init

BASE = "https://sgisapi.kostat.go.kr/OpenAPI3"
YEAR = "2022"


def token():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    j = requests.get(f"{BASE}/auth/authentication.json",
                     params={"consumer_key": env["SGIS_CONSUMER_KEY"],
                             "consumer_secret": env["SGIS_CONSUMER_SECRET"]},
                     timeout=30).json()
    return j["result"]["accessToken"]


def fetch_dong_polygons():
    """426 Seoul 행정동 polygons, EPSG:5179."""
    cache = CACHE_DIR / "sgis_dong_geom.geojson"
    if cache.exists():
        d = json.load(io.open(cache, encoding="utf-8"))
        print(f"  [cache] 행정동 폴리곤 {len(d['features']):,}개")
        return d

    tok = token()
    sggs = [r["cd"] for r in requests.get(
        f"{BASE}/addr/stage.json", params={"accessToken": tok, "cd": "11"},
        timeout=30).json()["result"]]

    feats = []
    for i, sgg in enumerate(sggs):
        j = requests.get(f"{BASE}/boundary/hadmarea.geojson",
                         params={"accessToken": tok, "year": YEAR,
                                 "adm_cd": sgg, "low_search": "1"}, timeout=120).json()
        feats.extend(j.get("features") or [])
        if (i + 1) % 5 == 0:
            print(f"    {i+1}/{len(sggs)} 구, {len(feats)} 행정동", flush=True)
    fc = {"type": "FeatureCollection", "features": feats}
    json.dump(fc, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  [fetched] 행정동 폴리곤 {len(feats):,}개")
    return fc


def match(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS grid_sgis (
          grid_id     TEXT PRIMARY KEY,
          sgis_adm_cd TEXT,
          sgis_adm_nm TEXT
        );
        CREATE INDEX IF NOT EXISTS ix_grid_sgis_cd ON grid_sgis(sgis_adm_cd);
    """)

    fc = fetch_dong_polygons()
    polys, meta = [], []
    for f in fc["features"]:
        try:
            polys.append(shape(f["geometry"]))
            meta.append((f["properties"]["adm_cd"], f["properties"]["adm_nm"]))
        except Exception:
            pass
    tree = STRtree(polys)
    print(f"  폴리곤 인덱스 {len(polys):,}개")

    # grid_id encodes EPSG:5179 metres directly - reconstruct the centre there
    cells = con.execute("SELECT grid_id FROM grid").fetchall()
    rows, unmatched = [], 0
    for c in cells:
        gx, gy = (int(v) for v in c["grid_id"].split("_"))
        p = Point(gx * GRID_SIZE_M + GRID_SIZE_M / 2, gy * GRID_SIZE_M + GRID_SIZE_M / 2)
        hit = None
        for idx in tree.query(p):
            if polys[idx].contains(p):
                hit = meta[idx]
                break
        if hit:
            rows.append((c["grid_id"], hit[0], hit[1]))
        else:
            unmatched += 1

    con.execute("DELETE FROM grid_sgis")
    con.executemany("INSERT OR REPLACE INTO grid_sgis VALUES(?,?,?)", rows)
    con.commit()

    n = len(cells)
    joined = con.execute(
        "SELECT count(*) FROM grid_sgis gs JOIN sgis_dong s ON gs.sgis_adm_cd=s.adm_cd"
    ).fetchone()[0]
    dongs = con.execute("SELECT count(DISTINCT sgis_adm_cd) FROM grid_sgis").fetchone()[0]
    print(f"grid_sgis: {len(rows):,}/{n:,} 격자 매칭 ({len(rows)/n*100:.1f}%) · "
          f"미매칭 {unmatched:,}")
    print(f"  SGIS 통계 조인 가능 격자: {joined:,} · 고유 행정동 {dongs}")
    return unmatched


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    a = ap.parse_args()
    match(init())
