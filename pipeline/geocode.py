"""Assign 행정동 to grid cells by reverse geocoding the cell centre.

Why not derive it from the commercial area a cell sits in: measured 75.5%
accurate (151/200) - roughly one cell in four lands in a neighbouring dong.
Living-population demand is keyed by 행정동, so that error rate propagates
straight into the demand feature. Reverse geocoding the centre point is exact
by construction.

Results are cached to disk keyed by grid_id, so this costs its API calls once.
"""
import argparse
import io
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .config import CACHE_DIR, ENV_PATH, ROOT
from .db import init

CACHE = CACHE_DIR / "grid_dong.json"
# Kakao throttles per-second; 12 workers tripped it often enough that failures
# outnumbered successes once non-200s were counted honestly.
WORKERS = 6


def _key():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    k = env.get("KAKAO_REST_API_KEY")
    if not k:
        raise RuntimeError("KAKAO_REST_API_KEY missing from .env")
    return k


KK = _key()

# One Session per worker thread. requests.Session is NOT thread-safe: sharing
# one across the pool let responses cross between requests, which showed up as
# cells being assigned a neighbouring - sometimes different-district - dong.
_local = threading.local()


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers.update({"Authorization": f"KakaoAK {KK}"})
        _local.s = s
    return s


def lookup(item, tries=4):
    """-> (grid_id, adstrd_cd or None). region_type 'H' is the 행정동 entry.

    Retries with backoff: a transient failure that returns None would leave the
    cell holding whatever value was there before, which is exactly how a stale
    proximity-derived dong survived a supposedly authoritative pass.
    """
    gid, lon, lat = item
    for attempt in range(tries):
        try:
            r = _session().get(
                "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
                params={"x": lon, "y": lat}, timeout=20)
            # Any non-200 is a failed call, not an answer. Treating it as
            # "no 행정동 here" silently blanked 43% of cells on the last run.
            if r.status_code != 200:
                time.sleep(0.5 * (attempt + 1))
                continue
            docs = r.json().get("documents") or []
        except Exception:
            time.sleep(0.3 * (attempt + 1))
            continue
        for d in docs:
            if d.get("region_type") == "H":
                code = (d.get("code") or "")[:8]
                return gid, (code or None)
        return gid, None          # answered, genuinely no 행정동 there
    return gid, "__FAILED__"      # never answered - must not be confused with "none"


def run(limit=None, only_missing=False):
    con = init()
    cache = json.load(io.open(CACHE, encoding="utf-8")) if CACHE.exists() else {}

    sql = "SELECT grid_id, center_lon, center_lat FROM grid"
    if only_missing:
        sql += " WHERE adstrd_cd IS NULL"
    todo = [(r["grid_id"], r["center_lon"], r["center_lat"])
            for r in con.execute(sql) if r["grid_id"] not in cache]
    if limit:
        todo = todo[:limit]

    print(f"cached {len(cache):,} · to look up {len(todo):,}")
    done = failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for gid, code in ex.map(lookup, todo):
            if code == "__FAILED__":
                failed += 1
            else:
                cache[gid] = code          # may be None: answered, no dong here
            done += 1
            if done % 2000 == 0:
                print(f"  {done:,}/{len(todo):,} (failed {failed})", flush=True)
                json.dump(cache, io.open(CACHE, "w", encoding="utf-8"))
    json.dump(cache, io.open(CACHE, "w", encoding="utf-8"))

    # Every cell gets its geocoded value, including an explicit NULL. Cells the
    # API never answered for are cleared too - keeping a stale value would be a
    # silent downgrade to the 75.5%-accurate heuristic this replaced.
    con.execute("UPDATE grid SET adstrd_cd=NULL")
    con.executemany("UPDATE grid SET adstrd_cd=? WHERE grid_id=?",
                    [(v, k) for k, v in cache.items() if v])
    con.commit()
    if failed:
        print(f"  [warn] {failed:,} cells never answered - left NULL, re-run to retry")

    tot = con.execute("SELECT count(*) FROM grid").fetchone()[0]
    null = con.execute("SELECT count(*) FROM grid WHERE adstrd_cd IS NULL").fetchone()[0]
    dongs = con.execute(
        "SELECT count(DISTINCT adstrd_cd) FROM grid WHERE adstrd_cd IS NOT NULL").fetchone()[0]
    print(f"grid dong: {tot-null:,}/{tot:,} assigned · {dongs} distinct 행정동 · NULL {null:,}")
    return null


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only-missing", action="store_true")
    a = ap.parse_args()
    sys.exit(0 if run(a.limit, a.only_missing) == 0 else 1)
