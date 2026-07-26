"""Seoul Open Data API client with a hard call budget.

The daily quota is not reported in responses, so exceeding it shows up as
sudden failures mid-load. This client counts every call, persists the count
per day, and refuses to start a fetch it cannot finish within the remaining
budget - a partial load that looks complete is worse than a refused one.
"""
import io
import json
import sys
from datetime import date

import requests

from .config import CACHE_DIR, SEOUL_BASE, SEOUL_DAILY_BUDGET, SEOUL_PAGE
from .db import connect, init


def _key():
    env = {}
    p = CACHE_DIR.parent.parent / ".env"
    for line in io.open(p, encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    k = env.get("SEOUL_OPEN_API_KEY")
    if not k:
        raise RuntimeError("SEOUL_OPEN_API_KEY missing from .env")
    return k


KEY = _key()
TODAY = date.today().isoformat()


def calls_today(con=None):
    own = con is None
    con = con or init()
    r = con.execute("SELECT COALESCE(SUM(calls),0) FROM api_log WHERE day=?", (TODAY,)).fetchone()
    if own:
        con.close()
    return r[0]


def _record(service, n, con):
    con.execute(
        "INSERT INTO api_log(day,service,calls) VALUES(?,?,?) "
        "ON CONFLICT(day,service) DO UPDATE SET calls=calls+excluded.calls",
        (TODAY, service, n))
    con.commit()


def remaining():
    return max(0, SEOUL_DAILY_BUDGET - calls_today())


def _get(service, start, end, args=""):
    url = f"{SEOUL_BASE}/{KEY}/json/{service}/{start}/{end}/{args}"
    r = requests.get(url, timeout=60)
    j = r.json()
    if "RESULT" in j:
        code = j["RESULT"].get("CODE")
        if code == "INFO-200":
            return None, []
        raise RuntimeError(f"{service}: {code} {j['RESULT'].get('MESSAGE')}")
    root = j.get(service) or {}
    res = root.get("RESULT") or {}
    if res.get("CODE") not in (None, "INFO-000"):
        raise RuntimeError(f"{service}: {res.get('CODE')} {res.get('MESSAGE')}")
    return root.get("list_total_count"), (root.get("row") or [])


def total_count(service, args=""):
    """One call: how many rows does this filter select?"""
    con = init()
    total, _ = _get(service, 1, 1, args)
    _record(service, 1, con)
    con.close()
    return total or 0


def fetch_all(service, args="", cache_name=None, limit=None, dry_run=False):
    """Page through a service, caching to jsonl. Returns list of dicts.

    Re-running is free: a complete cache short-circuits before any HTTP call.
    """
    cache = CACHE_DIR / f"{cache_name or service}{'_' + args.strip('/').replace('/', '_') if args else ''}.jsonl"
    if cache.exists():
        rows = [json.loads(l) for l in io.open(cache, encoding="utf-8")]
        print(f"  [cache] {service}{' ' + args if args else ''}: {len(rows):,} rows")
        return rows

    con = init()
    total, first = _get(service, 1, SEOUL_PAGE, args)
    _record(service, 1, con)
    total = total or 0
    target = min(total, limit) if limit else total
    need = max(0, -(-target // SEOUL_PAGE) - 1)      # pages after the first

    if dry_run:
        con.close()
        print(f"  [dry-run] {service}{' ' + args if args else ''}: total={total:,} "
              f"-> {need + 1} calls (remaining budget {remaining()})")
        return []

    if need > remaining():
        con.close()
        raise RuntimeError(
            f"{service} needs {need + 1} calls but only {remaining()} remain in today's "
            f"budget ({SEOUL_DAILY_BUDGET}). Refusing a partial load. "
            f"Run again tomorrow or raise SEOUL_DAILY_BUDGET if the real quota is higher.")

    # Append pages to a .partial as they land so an interrupted 500-call fetch
    # resumes instead of restarting. Only a completed fetch gets the real name.
    partial = cache.with_suffix(".partial")
    rows = []
    if partial.exists():
        rows = [json.loads(l) for l in io.open(partial, encoding="utf-8")]
        done_pages = len(rows) // SEOUL_PAGE
        print(f"  [resume] {service}: {len(rows):,} rows already cached, "
              f"continuing from page {done_pages + 1}")
    else:
        rows = list(first)
        with io.open(partial, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        done_pages = 1

    short_pages = []
    for i in range(done_pages, need + 1):
        s = i * SEOUL_PAGE + 1
        _, got = _get(service, s, s + SEOUL_PAGE - 1, args)
        _record(service, 1, con)
        if not got:
            # An empty page mid-range means the server dropped rows, not that
            # data ended. Record it and keep going rather than truncating.
            short_pages.append(s)
            continue
        if len(got) < SEOUL_PAGE and s + SEOUL_PAGE - 1 <= target:
            short_pages.append(s)
        rows.extend(got)
        with io.open(partial, "a", encoding="utf-8") as f:
            for r in got:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if i % 50 == 0:
            print(f"    {len(rows):,}/{target:,}", flush=True)
    con.close()

    if limit:
        rows = rows[:limit]
    elif len(rows) < total:
        # Keep the .partial so a re-run resumes, and fail loudly. A cache file
        # that looks complete but is short would poison every downstream count.
        raise RuntimeError(
            f"{service}: collected {len(rows):,} of {total:,} rows "
            f"({len(short_pages)} short/empty pages, first at offset {short_pages[0] if short_pages else '?'}). "
            f"Partial cache kept at {partial.name} - re-run to resume.")

    with io.open(cache, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    partial.unlink(missing_ok=True)
    if short_pages:
        print(f"  [warn] {len(short_pages)} pages returned short but total matched")
    print(f"  [fetched] {service}{' ' + args if args else ''}: {len(rows):,} rows "
          f"({need + 1} calls, {remaining()} left)")
    return rows


if __name__ == "__main__":
    print(f"day={TODAY} used={calls_today()} remaining={remaining()}/{SEOUL_DAILY_BUDGET}")
    if len(sys.argv) > 1 and sys.argv[1] == "--reset":
        con = init()
        con.execute("DELETE FROM api_log WHERE day=?", (TODAY,))
        con.commit()
        print("api_log reset for today")
