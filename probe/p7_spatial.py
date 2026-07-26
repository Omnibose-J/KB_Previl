"""Probe: how fine a spatial unit can we actually support?

Three sources, three coordinate systems, three different units. This measures
what survives when they are forced onto one grid:
  - LOCALDATA restaurants: point, EPSG:2097
  - Seoul commercial areas: centroid + area, EPSG:5181
  - SEMAS stores: point, WGS84 (+ PNU parcel id)
Output decides the recommendation unit.
"""
import io
import json
import math
from collections import Counter, defaultdict

import requests
from pyproj import Transformer

from common import RESULTS, key, save

S = key("SEOUL_OPEN_API_KEY")

to_wgs_2097 = Transformer.from_crs("EPSG:2097", "EPSG:4326", always_xy=True)
to_wgs_5181 = Transformer.from_crs("EPSG:5181", "EPSG:4326", always_xy=True)

out = {}

# ---- 1. restaurants -> WGS84 ------------------------------------------
rows = [json.loads(l) for l in io.open(RESULTS / "localdata_sample.jsonl", encoding="utf-8")]
pts = []
for r in rows:
    x, y = str(r.get("X") or "").strip(), str(r.get("Y") or "").strip()
    if not x or not y:
        continue
    try:
        lon, lat = to_wgs_2097.transform(float(x), float(y))
    except Exception:
        continue
    if 126.7 < lon < 127.3 and 37.4 < lat < 37.75:
        pts.append((lon, lat, r))

out["restaurants"] = {
    "sampled": len(rows),
    "with_xy": sum(1 for r in rows if str(r.get("X") or "").strip()),
    "in_seoul_bbox_after_transform": len(pts),
    "transform_sanity_pct": round(len(pts) / max(1, sum(1 for r in rows if str(r.get("X") or "").strip())) * 100, 1),
    "sample_converted": {
        "addr": pts[0][2].get("SITEWHLADDR", "").strip(),
        "lon": round(pts[0][0], 6), "lat": round(pts[0][1], 6)} if pts else None,
}

# ---- 2. commercial areas -> WGS84 -------------------------------------
areas, start = [], 1
while True:
    j = requests.get(f"http://openapi.seoul.go.kr:8088/{S}/json/TbgisTrdarRelm/{start}/{start+999}/",
                     timeout=60).json()["TbgisTrdarRelm"]
    g = j.get("row") or []
    areas.extend(g)
    if len(g) < 1000:
        break
    start += 1000

acirc = []
for a in areas:
    try:
        lon, lat = to_wgs_5181.transform(float(a["XCNTS_VALUE"]), float(a["YDNTS_VALUE"]))
        rad = math.sqrt(float(a["RELM_AR"]) / math.pi)
        acirc.append((lon, lat, rad, a))
    except Exception:
        pass

out["areas"] = {"n": len(acirc),
                "sample": {"name": acirc[0][3]["TRDAR_CD_NM"],
                           "lon": round(acirc[0][0], 6), "lat": round(acirc[0][1], 6),
                           "equiv_radius_m": round(acirc[0][2])} if acirc else None}

# ---- 3. how many restaurants fall inside a commercial area? -----------
M_PER_DEG_LAT = 111_320.0


def m_per_deg_lon(lat):
    return 111_320.0 * math.cos(math.radians(lat))


# bucket areas by coarse cell for a cheap spatial index
GRID = 0.01  # ~1.1km
idx = defaultdict(list)
for lon, lat, rad, a in acirc:
    idx[(int(lon / GRID), int(lat / GRID))].append((lon, lat, rad, a))

inside = 0
matched_type = Counter()
for lon, lat, r in pts:
    gx, gy = int(lon / GRID), int(lat / GRID)
    hit = None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for alon, alat, arad, a in idx.get((gx + dx, gy + dy), ()):
                d = math.hypot((lon - alon) * m_per_deg_lon(lat), (lat - alat) * M_PER_DEG_LAT)
                if d <= arad:
                    hit = a
                    break
            if hit:
                break
        if hit:
            break
    if hit:
        inside += 1
        matched_type[hit.get("TRDAR_SE_CD_NM")] += 1

out["coverage"] = {
    "restaurants_tested": len(pts),
    "inside_a_commercial_area": inside,
    "pct": round(inside / len(pts) * 100, 1) if pts else None,
    "by_area_type": dict(matched_type.most_common()),
    "method": "circle approximation of TRDAR (centroid + equivalent radius from RELM_AR); "
              "true polygons would shift this figure - direction unknown",
}

# ---- 4. grid density: is a 100m cell usable? --------------------------
for size in (50, 100, 200):
    cells = Counter()
    for lon, lat, r in pts:
        cx = int(lon * m_per_deg_lon(lat) / size)
        cy = int(lat * M_PER_DEG_LAT / size)
        cells[(cx, cy)] += 1
    vals = sorted(cells.values())
    out.setdefault("grid", {})[f"{size}m"] = {
        "nonempty_cells": len(cells),
        "restaurants_per_cell_median": vals[len(vals) // 2],
        "p90": vals[int(len(vals) * .9)],
        "max": vals[-1],
        "pct_cells_with_1_only": round(sum(1 for v in vals if v == 1) / len(vals) * 100, 1),
    }

save("p7_spatial", out)
print(json.dumps(out, ensure_ascii=False, indent=2))
