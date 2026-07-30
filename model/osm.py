"""OSM physical geography - road adjacency, junction density, road class.

Why this source exists: every feature in LOC2 is derived from licence history,
and §8-C found that family saturated. Road geometry is a different mechanism
entirely - it measures the *street* a site sits on, which practitioners rank
first and the model currently cannot see at all.

Three properties make it admissible under the project's spatial rules:

1. Point grain. Road centrelines are finer than the 100m cell, so cells are
   separated on their own evidence - no coarse value is distributed onto the
   grid (CLAUDE.md rule 3).
2. No API quota. Overpass is public; this does not touch the Seoul open-data
   900-call budget.
3. Time-invariant, so `<=T` truncation is vacuous - the as-of self-test passes
   by construction.

The honest limit of (3): OSM is a *current* snapshot. A road built in 2015 is
credited to a 2010 opening. Seoul's arterial network is stable over the study
window, but residential geometry is not, so this is recorded as a known
anachronism rather than a clean as-of source.
"""
import argparse
import json
import math
import time

import numpy as np
import requests
from scipy.spatial import cKDTree

from pipeline.config import CACHE_DIR
from pipeline.db import connect, connect_ro

TILE_DIR = CACHE_DIR / "osm_tiles"

# The free Overpass instances rate-limit hard (429) and occasionally time out
# (504). Tiles are therefore cached one file at a time and the fetch resumes
# where it stopped - a run that dies on tile 9 keeps tiles 1-8.
ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.kumi.systems/api/interpreter"]
UA = {"User-Agent": "kb-previl-research/0.1 (storefront location study)"}

RETRY_WAIT_S = 60      # 429 means "come back later"; short retries just burn the quota
TILE_WAIT_S = 5

# Seoul bounding box, split into tiles so no single query times out.
BBOX = (37.41, 126.75, 37.71, 127.20)
TILES = 4

HIGHWAY = "^(motorway|trunk|primary|secondary|tertiary|residential)$"

# Ordinal road class. Higher = larger road. Used as a single ordinal feature
# rather than one-hot: the classes are genuinely ordered by capacity.
CLASS_RANK = {"residential": 1, "tertiary": 2, "secondary": 3,
              "primary": 4, "trunk": 5, "motorway": 6}
MAJOR = {"secondary", "primary", "trunk", "motorway"}

# Metres per degree at Seoul's latitude. The city spans 0.3 degrees of
# latitude, over which the longitude scale moves 0.4% - 0.4m at a 100m radius,
# below the resolution of anything downstream.
LAT_M = 111_320.0
LON_M = 111_320.0 * math.cos(math.radians(37.55))

RESAMPLE_M = 25.0   # spacing when densifying segments; bounds nearest-point error to 12.5m
RADIUS_M = 100.0    # cell-centred radius for density features; covers the whole 100m cell

FEATURES = {
    "osm_road_dist_m": "distance from cell centre to the nearest road of any class",
    "osm_major_dist_m": "distance to the nearest arterial (secondary and above)",
    "osm_junction_dist_m": "distance to the nearest junction (node shared by 2+ ways)",
    "osm_road_len_m": f"road length within {RADIUS_M:.0f}m of the cell centre",
    "osm_major_len_m": f"arterial length within {RADIUS_M:.0f}m",
    "osm_junctions": f"junction count within {RADIUS_M:.0f}m",
    "osm_road_class": "ordinal class of the nearest road (1 residential .. 6 motorway)",
}

COLUMNS = list(FEATURES)


def _query(south, west, north, east):
    return (f'[out:json][timeout:180];\n'
            f'way["highway"~"{HIGHWAY}"]({south},{west},{north},{east});\n'
            f'out geom;')


def _tile_path(i, j):
    return TILE_DIR / f"tile_{i}_{j}.jsonl"


def _fetch_tile(q, label, verbose):
    """One tile, rotating endpoints and backing off on rate limits.

    Fails loud after exhausting both endpoints twice - a silently short tile
    would leave a hole in the grid that no downstream check could see.
    """
    for attempt in range(2 * len(ENDPOINTS)):
        url = ENDPOINTS[attempt % len(ENDPOINTS)]
        try:
            r = requests.post(url, data={"data": q}, timeout=300, headers=UA)
        except requests.RequestException as e:
            if verbose:
                print(f"  {label} {type(e).__name__} on {url.split('/')[2]}")
            time.sleep(RETRY_WAIT_S)
            continue
        if r.status_code == 200:
            return r.json().get("elements", [])
        if verbose:
            print(f"  {label} HTTP {r.status_code} on {url.split('/')[2]} "
                  f"- wait {RETRY_WAIT_S}s (attempt {attempt + 1})")
        time.sleep(RETRY_WAIT_S)
    raise RuntimeError(f"{label} failed on every endpoint")


def fetch(force=False, verbose=True):
    """Pull Seoul road geometry tile by tile. Resumable: cached tiles are skipped."""
    TILE_DIR.mkdir(parents=True, exist_ok=True)
    s0, w0, n0, e0 = BBOX
    dlat, dlon = (n0 - s0) / TILES, (e0 - w0) / TILES

    for i in range(TILES):
        for j in range(TILES):
            path = _tile_path(i, j)
            if path.exists() and not force:
                if verbose:
                    print(f"  tile {i},{j}: cached")
                continue
            s, w = s0 + i * dlat, w0 + j * dlon
            els = _fetch_tile(_query(s, w, s + dlat, w + dlon), f"tile {i},{j}", verbose)

            # write to a temp name and rename, so an interrupted write never
            # leaves a half tile that a later run would trust
            tmp = path.with_suffix(".part")
            kept = 0
            with tmp.open("w", encoding="utf-8") as f:
                for w_ in els:
                    geom = w_.get("geometry")
                    if not geom:
                        continue
                    f.write(json.dumps(
                        {"id": w_["id"],
                         "highway": (w_.get("tags") or {}).get("highway"),
                         "geometry": [[g["lat"], g["lon"]] for g in geom]},
                        ensure_ascii=False) + "\n")
                    kept += 1
            tmp.replace(path)
            if verbose:
                print(f"  tile {i},{j}: {len(els):,} ways, {kept:,} with geometry")
            time.sleep(TILE_WAIT_S)

    n = len(load_roads())
    if verbose:
        print(f"cached {n:,} distinct ways across {TILES * TILES} tiles -> {TILE_DIR}")
    return n


def load_roads():
    """All cached tiles, de-duplicated by way id (tiles overlap at their edges)."""
    files = sorted(TILE_DIR.glob("tile_*.jsonl")) if TILE_DIR.exists() else []
    if not files:
        raise FileNotFoundError(
            f"no tiles in {TILE_DIR} - run `python -m model.osm --fetch` first")
    missing = [f"{i},{j}" for i in range(TILES) for j in range(TILES)
               if not _tile_path(i, j).exists()]
    if missing:
        raise RuntimeError(
            f"incomplete tile set - missing {len(missing)}: {', '.join(missing)}. "
            "Re-run --fetch; it resumes from the cached tiles.")
    ways = {}
    for path in files:
        with path.open(encoding="utf-8") as f:
            for line in f:
                w = json.loads(line)
                ways[w["id"]] = w
    return list(ways.values())


def _to_xy(lat, lon):
    return lon * LON_M, lat * LAT_M


def _densify(ways):
    """Return (points, is_major, class_rank) arrays for every road, resampled.

    Nearest-point distance on a densified polyline approximates true segment
    distance to within half the spacing, which is what makes a KD-tree usable
    here instead of exact point-to-segment geometry.
    """
    pts, major, rank = [], [], []
    for w in ways:
        cls = CLASS_RANK.get(w["highway"], 1)
        is_major = w["highway"] in MAJOR
        g = w["geometry"]
        for k in range(len(g) - 1):
            x1, y1 = _to_xy(*g[k])
            x2, y2 = _to_xy(*g[k + 1])
            d = math.hypot(x2 - x1, y2 - y1)
            steps = max(1, int(d // RESAMPLE_M))
            for s in range(steps):
                t = s / steps
                pts.append((x1 + (x2 - x1) * t, y1 + (y2 - y1) * t))
                major.append(is_major)
                rank.append(cls)
        x, y = _to_xy(*g[-1])
        pts.append((x, y))
        major.append(is_major)
        rank.append(cls)
    return np.array(pts), np.array(major, dtype=bool), np.array(rank, dtype=np.int8)


def _junctions(ways):
    """Nodes shared by two or more distinct ways, as projected points.

    OSM guarantees that crossing ways share a node object, so an exact
    coordinate match is the definition of a junction, not a tolerance test.
    """
    count = {}
    for w in ways:
        for lat, lon in {(a, b) for a, b in w["geometry"]}:
            key = (lat, lon)
            count[key] = count.get(key, 0) + 1
    return np.array([_to_xy(lat, lon) for (lat, lon), c in count.items() if c >= 2])


def compute(verbose=True):
    """Compute per-cell features. Returns {grid_id: {feature: value}}."""
    ways = load_roads()
    if verbose:
        print(f"roads: {len(ways):,} ways")
    pts, major, rank = _densify(ways)
    jpts = _junctions(ways)
    if verbose:
        print(f"resampled points: {len(pts):,} · junctions: {len(jpts):,}")

    tree = cKDTree(pts)
    mtree = cKDTree(pts[major])
    jtree = cKDTree(jpts)

    con = connect_ro()
    cells = con.execute(
        "SELECT grid_id, center_lon, center_lat FROM grid ORDER BY grid_id").fetchall()
    con.close()
    xy = np.array([_to_xy(c["center_lat"], c["center_lon"]) for c in cells])

    d_road, i_road = tree.query(xy, k=1)
    d_major, _ = mtree.query(xy, k=1)
    d_junc, _ = jtree.query(xy, k=1)
    near_road = tree.query_ball_point(xy, RADIUS_M)
    near_junc = jtree.query_ball_point(xy, RADIUS_M)

    out = {}
    for n, c in enumerate(cells):
        idx = near_road[n]
        n_major = int(major[idx].sum()) if idx else 0
        out[c["grid_id"]] = {
            "osm_road_dist_m": float(d_road[n]),
            "osm_major_dist_m": float(d_major[n]),
            "osm_junction_dist_m": float(d_junc[n]),
            "osm_road_len_m": len(idx) * RESAMPLE_M,
            "osm_major_len_m": n_major * RESAMPLE_M,
            "osm_junctions": len(near_junc[n]),
            "osm_road_class": int(rank[i_road[n]]),
        }
    return out


def build(verbose=True):
    feats = compute(verbose=verbose)
    con = connect()
    cols = ", ".join(f"{c} REAL" for c in COLUMNS)
    con.execute("DROP TABLE IF EXISTS grid_osm")
    con.execute(f"CREATE TABLE grid_osm (grid_id TEXT PRIMARY KEY, {cols})")
    con.executemany(
        f"INSERT INTO grid_osm (grid_id, {', '.join(COLUMNS)}) "
        f"VALUES (?, {', '.join('?' * len(COLUMNS))})",
        [(g, *[v[c] for c in COLUMNS]) for g, v in feats.items()])
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM grid_osm").fetchone()[0]
    con.close()
    if verbose:
        print(f"grid_osm: {n:,} rows")
    return n


def selftest():
    """Sanity predicates that would catch a projection or units error."""
    con = connect_ro()
    n = con.execute("SELECT COUNT(*) FROM grid_osm").fetchone()[0]
    grid_n = con.execute("SELECT COUNT(*) FROM grid").fetchone()[0]
    stats = con.execute(
        "SELECT AVG(osm_road_dist_m), MAX(osm_road_dist_m), "
        "       AVG(osm_major_dist_m), AVG(osm_junctions), AVG(osm_road_len_m) "
        "FROM grid_osm").fetchone()
    far = con.execute("SELECT COUNT(*) FROM grid_osm WHERE osm_road_dist_m > 500").fetchone()[0]
    con.close()

    checks = [
        ("coverage", n == grid_n, f"{n:,} / {grid_n:,} cells"),
        ("road_dist mean < 100m", stats[0] < 100, f"mean {stats[0]:.1f}m"),
        ("road_dist max plausible", stats[1] < 5000, f"max {stats[1]:.0f}m"),
        ("major >= any", stats[2] >= stats[0], f"major mean {stats[2]:.1f}m"),
        ("junction density > 0", stats[3] > 0, f"mean {stats[3]:.2f} per cell"),
        ("road length > 0", stats[4] > 0, f"mean {stats[4]:.0f}m"),
    ]
    ok = True
    for name, passed, detail in checks:
        print(f"[{name:26}] {'PASS' if passed else 'FAIL'}  {detail}")
        ok &= passed
    print(f"cells farther than 500m from any road: {far:,}")
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="OSM road features for the 100m grid")
    ap.add_argument("--fetch", action="store_true", help="pull road geometry into the cache")
    ap.add_argument("--force", action="store_true", help="refetch even if cached")
    ap.add_argument("--build", action="store_true", help="compute features and write grid_osm")
    ap.add_argument("--selftest", action="store_true", help="check the built table")
    a = ap.parse_args()
    if a.fetch or a.force:
        fetch(force=a.force)
    if a.build:
        build()
    if a.selftest:
        return selftest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
