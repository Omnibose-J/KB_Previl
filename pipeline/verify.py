"""Predicate checks from docs/tracking/criteria-pipeline-v1.md.

Each check prints its evidence and returns pass/fail. Exit code is non-zero if
any requested check fails, so this is usable as a gate. The checks encode the
measured baselines from probe/ - if reality drifts outside tolerance the build
fails rather than silently shipping different numbers.
"""
import argparse
import sys

from .config import (COVERAGE_CEIL, COVERAGE_FLOOR, EXPECT_COORD_PCT,
                     EXPECT_COORD_TOL, FOOD_INDUTY)
from .db import init

CHECKS = {}


def check(name):
    def deco(fn):
        CHECKS[name] = fn
        return fn
    return deco


def _pct(a, b):
    return (a / b * 100) if b else 0.0


@check("coords")
def c_coords(con):
    n = con.execute("SELECT count(*) FROM licence").fetchone()[0]
    xy = con.execute("SELECT count(*) FROM licence WHERE lon IS NOT NULL").fetchone()[0]
    gr = con.execute("SELECT count(*) FROM licence WHERE grid_id IS NOT NULL").fetchone()[0]
    p = _pct(gr, n)
    lo, hi = EXPECT_COORD_PCT - EXPECT_COORD_TOL, EXPECT_COORD_PCT + EXPECT_COORD_TOL
    ok = lo <= p <= hi
    print(f"  rows={n:,} with_coords={xy:,} gridded={gr:,} ({p:.1f}%)")
    print(f"  expected {EXPECT_COORD_PCT}%±{EXPECT_COORD_TOL}%p -> [{lo:.1f}, {hi:.1f}]")
    return ok


@check("dates")
def c_dates(con):
    n = con.execute("SELECT count(*) FROM licence").fetchone()[0]
    op = con.execute("SELECT count(*) FROM licence WHERE open_y IS NOT NULL").fetchone()[0]
    lo, hi = con.execute("SELECT MIN(open_y), MAX(open_y) FROM licence").fetchone()
    cl_closed = con.execute(
        "SELECT count(*) FROM licence WHERE is_closed=1 AND close_y IS NOT NULL").fetchone()[0]
    closed = con.execute("SELECT count(*) FROM licence WHERE is_closed=1").fetchone()[0]
    print(f"  open parsed={op:,}/{n:,} ({_pct(op,n):.1f}%)  year range={lo}..{hi}")
    print(f"  close parsed={cl_closed:,}/{closed:,} closed ({_pct(cl_closed,closed):.1f}%)")
    # a padded-date parse failure shows up as a near-zero parse rate
    ok = _pct(op, n) > 95 and lo and 1900 <= lo <= 2000 and hi and hi >= 2020
    return ok


@check("counts")
def c_counts(con):
    from .seoul_api import total_count
    from .config import SVC_LICENCE
    db_n = con.execute("SELECT count(*) FROM licence").fetchone()[0]
    api_n = total_count(SVC_LICENCE)
    ok = db_n == api_n
    print(f"  licence={db_n:,}  api list_total_count={api_n:,}  {'MATCH' if ok else 'MISMATCH'}")
    return ok


@check("induty")
def c_induty(con):
    got = [r[0] for r in con.execute(
        "SELECT DISTINCT induty_cd FROM trdar_sales ORDER BY 1")]
    ok = set(got) <= set(FOOD_INDUTY) and len(got) > 0
    print(f"  distinct induty in trdar_sales: {len(got)} -> {got}")
    print(f"  all within the {len(FOOD_INDUTY)} food codes: {ok}")
    return ok


@check("coverage")
def c_coverage(con):
    tot = con.execute(
        "SELECT count(*) FROM licence WHERE grid_id IS NOT NULL").fetchone()[0]
    inside = con.execute(
        "SELECT count(*) FROM licence l JOIN grid g ON l.grid_id=g.grid_id "
        "WHERE g.has_sales_data=1").fetchone()[0]
    p = _pct(inside, tot)
    ok = COVERAGE_FLOOR <= p <= COVERAGE_CEIL
    print(f"  restaurants in a commercial-area cell: {inside:,}/{tot:,} ({p:.1f}%)")
    print(f"  probe measured 57.6%; accepted band [{COVERAGE_FLOOR}, {COVERAGE_CEIL}]")
    return ok


@check("nullzero")
def c_nullzero(con):
    """The invariant: no source -> NULL, never 0."""
    bad = con.execute(
        "SELECT count(*) FROM grid_feature WHERE has_sales_data=0 "
        "AND (sales_amt IS NOT NULL OR sales_cnt IS NOT NULL OR flpop IS NOT NULL)"
    ).fetchone()[0]
    zeros = con.execute(
        "SELECT count(*) FROM grid_feature WHERE has_sales_data=0 "
        "AND (sales_amt=0 OR flpop=0)").fetchone()[0]
    print(f"  has_sales_data=0 cells carrying a sales value : {bad}  (must be 0)")
    print(f"  ... of which literal zeros                    : {zeros}  (must be 0)")
    return bad == 0 and zeros == 0


@check("gridone")
def c_gridone(con):
    n, d = con.execute(
        "SELECT count(*), count(DISTINCT grid_id) FROM grid_feature").fetchone()
    orphan = con.execute(
        "SELECT count(*) FROM grid_feature f LEFT JOIN grid g ON f.grid_id=g.grid_id "
        "WHERE g.grid_id IS NULL").fetchone()[0]
    print(f"  grid_feature rows={n:,} distinct grid_id={d:,}  orphans={orphan}")
    return n == d and orphan == 0


@check("dong")
def c_dong(con):
    """Originally required 0 unassigned cells. Reverse geocoding leaves a small
    residue - river surface, park interiors, restricted land - where no 행정동
    is returned at all. Those cells keep NULL demand features rather than
    borrowing a neighbour's, which is the correct outcome, so the predicate is
    a bound plus the NULL invariant rather than an absolute zero.
    """
    n = con.execute("SELECT count(*) FROM grid WHERE adstrd_cd IS NULL").fetchone()[0]
    tot = con.execute("SELECT count(*) FROM grid").fetchone()[0]
    leaked = con.execute(
        "SELECT count(*) FROM grid_feature WHERE adstrd_cd IS NULL "
        "AND (lvpop_day IS NOT NULL OR lvpop_night IS NOT NULL)").fetchone()[0]
    print(f"  grid cells without 행정동: {n:,}/{tot:,} ({n/tot*100:.2f}%, 허용 0.5%)")
    print(f"  ... 중 수요값이 채워진 격자: {leaked}  (must be 0)")
    return n / tot < 0.005 and leaked == 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checks", nargs="*", default=None,
                    help=f"one of: {', '.join(CHECKS)} (default: all)")
    a = ap.parse_args()
    names = a.checks or list(CHECKS)
    con = init()
    results = {}
    for nm in names:
        if nm not in CHECKS:
            print(f"unknown check: {nm}")
            return 2
        print(f"\n[{nm}]")
        try:
            results[nm] = bool(CHECKS[nm](con))
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")
            results[nm] = False
        print(f"  -> {'PASS' if results[nm] else 'FAIL'}")
    bad = [k for k, v in results.items() if not v]
    print("\n" + "=" * 52)
    print(f"{len(results)-len(bad)}/{len(results)} PASS" + (f"   FAILED: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
