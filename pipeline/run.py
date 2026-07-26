"""End-to-end: collect -> normalize -> cohort -> features -> verify.

Re-running is cheap and idempotent: collection is cached to jsonl, every
normalize step truncates its own table before inserting, and grid_feature is
rebuilt from scratch. Two consecutive runs must produce identical row counts.
"""
import argparse
import sys
import time

from .config import DEFAULT_QUARTER
from .db import init


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--quarter", default=DEFAULT_QUARTER)
    ap.add_argument("--skip-collect", action="store_true")
    ap.add_argument("--semas", action="store_true")
    a = ap.parse_args()

    t0 = time.time()
    con = init()

    if not a.skip_collect:
        print("=" * 60)
        print("1/5 COLLECT")
        from .collect import collect_seoul, collect_semas
        collect_seoul(a.quarter)
        if a.semas:
            collect_semas()

    print("=" * 60)
    print("2/5 NORMALIZE")
    from .normalize import flag_succession, norm_licence, norm_lvpop, norm_store, norm_trdar
    norm_licence(con)
    flag_succession(con)
    norm_trdar(con)
    norm_lvpop(con)
    norm_store(con)

    print("=" * 60)
    print("3/5 COHORT")
    from .cohort import compare_probe, compute, show
    rows, cut = compute(con)
    show(rows, cut, "연도별 개업 코호트 생존율 — 서울 일반음식점 (전량)")
    cohort_ok = compare_probe(rows)
    compute(con, exclude_succession=True)

    print("=" * 60)
    print("4/6 GRID")
    from .features import build_features, build_grid
    build_grid(con)

    print("=" * 60)
    print("5/6 GEOCODE 행정동")
    # Deriving dong from the containing commercial area measured only 75.5%
    # accurate; reverse geocoding the cell centre is exact. Cached on disk.
    from .geocode import run as geocode_run
    geocode_run()

    print("=" * 60)
    print("6/6 FEATURES + VERIFY")
    build_features(con, a.quarter)
    from .verify import main as verify_main
    rc = verify_main()

    print(f"\nelapsed {time.time()-t0:.0f}s")
    return 0 if (rc == 0 and cohort_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
