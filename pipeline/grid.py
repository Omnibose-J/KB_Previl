"""100m grid over Seoul, in EPSG:5179 (UTM-K) metres.

Why a projected metric CRS and not lon/lat degrees: a degree of longitude is
~88km at Seoul's latitude and a degree of latitude is ~111km, so degree-based
cells are rectangles that change shape with latitude. UTM-K cells are square
and comparable, which is what "within 100m" has to mean for a recommendation.

grid_id is derived purely from floor-divided metre coordinates, so it is
deterministic and reversible - no counter, no database sequence.
"""
import argparse
import random

from pyproj import Transformer

from .config import CRS_GRID, CRS_LICENCE, CRS_TRDAR, CRS_WGS84, GRID_SIZE_M, SEOUL_BBOX

_to_grid = Transformer.from_crs(CRS_WGS84, CRS_GRID, always_xy=True)
_from_grid = Transformer.from_crs(CRS_GRID, CRS_WGS84, always_xy=True)
_licence_to_wgs = Transformer.from_crs(CRS_LICENCE, CRS_WGS84, always_xy=True)
_trdar_to_wgs = Transformer.from_crs(CRS_TRDAR, CRS_WGS84, always_xy=True)


def licence_to_wgs84(x, y):
    """LOCALDATA X/Y (EPSG:2097) -> (lon, lat). None if outside Seoul."""
    try:
        lon, lat = _licence_to_wgs.transform(float(x), float(y))
    except (TypeError, ValueError):
        return None
    return (lon, lat) if in_seoul(lon, lat) else None


def trdar_to_wgs84(x, y):
    """Commercial-area centroid (EPSG:5181) -> (lon, lat). None if outside Seoul."""
    try:
        lon, lat = _trdar_to_wgs.transform(float(x), float(y))
    except (TypeError, ValueError):
        return None
    return (lon, lat) if in_seoul(lon, lat) else None


def in_seoul(lon, lat):
    lo_min, la_min, lo_max, la_max = SEOUL_BBOX
    return lo_min < lon < lo_max and la_min < lat < la_max


def to_grid_id(lon, lat):
    """(lon, lat) -> 'gx_gy'. Deterministic; same input always same id."""
    x, y = _to_grid.transform(lon, lat)
    return f"{int(x // GRID_SIZE_M)}_{int(y // GRID_SIZE_M)}"


def grid_center(grid_id):
    """'gx_gy' -> (lon, lat) of the cell centre."""
    gx, gy = (int(v) for v in grid_id.split("_"))
    x = gx * GRID_SIZE_M + GRID_SIZE_M / 2
    y = gy * GRID_SIZE_M + GRID_SIZE_M / 2
    return _from_grid.transform(x, y)


def neighbors(grid_id, ring=1):
    """Cell ids within `ring` cells (Chebyshev), including the centre."""
    gx, gy = (int(v) for v in grid_id.split("_"))
    return [f"{gx + dx}_{gy + dy}"
            for dx in range(-ring, ring + 1)
            for dy in range(-ring, ring + 1)]


def selftest(n=1000, seed=42):
    """Prove determinism and round-trip stability over random Seoul points."""
    rng = random.Random(seed)
    lo_min, la_min, lo_max, la_max = SEOUL_BBOX
    pts = [(rng.uniform(lo_min, lo_max), rng.uniform(la_min, la_max)) for _ in range(n)]

    first = [to_grid_id(*p) for p in pts]
    second = [to_grid_id(*p) for p in pts]
    if first != second:
        raise AssertionError("grid_id is not deterministic")

    # centre of a cell must map back into the same cell
    bad = [g for g in set(first) if to_grid_id(*grid_center(g)) != g]
    if bad:
        raise AssertionError(f"round-trip failed for {len(bad)} cells, e.g. {bad[:3]}")

    # cell edge length must be GRID_SIZE_M within float tolerance
    g0 = first[0]
    gx, gy = (int(v) for v in g0.split("_"))
    p1 = _from_grid.transform(gx * GRID_SIZE_M, gy * GRID_SIZE_M)
    p2 = _from_grid.transform((gx + 1) * GRID_SIZE_M, gy * GRID_SIZE_M)
    span = _to_grid.transform(*p2)[0] - _to_grid.transform(*p1)[0]
    if abs(span - GRID_SIZE_M) > 0.01:
        raise AssertionError(f"cell width {span}m != {GRID_SIZE_M}m")

    lo_g = to_grid_id(lo_min, la_min)
    hi_g = to_grid_id(lo_max, la_max)
    w = int(hi_g.split("_")[0]) - int(lo_g.split("_")[0])
    h = int(hi_g.split("_")[1]) - int(lo_g.split("_")[1])

    print(f"points tested        : {n}")
    print(f"determinism          : PASS (2 runs identical)")
    print(f"round-trip           : PASS ({len(set(first))} distinct cells)")
    print(f"cell width           : {span:.4f} m")
    print(f"seoul bbox grid      : {w} x {h} = {w * h:,} cells")
    return True


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        selftest()
