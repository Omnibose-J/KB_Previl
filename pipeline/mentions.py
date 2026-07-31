"""Per-shop blog mentions, aggregated up to the grid — pilot on 마포구.

The point of doing it per shop rather than per neighbourhood: aggregation
upward from points is legitimate, disaggregation downward from an area is not.
Querying "성수동 맛집" returns a 행정동-level number that cannot distinguish
cells; querying each shop's name returns a point-level number that can.

As-of validity: a shop's OWN mentions only exist after it opens, so its own
count can never be a feature for its own opening. What is reconstructable is
the mention volume of the shops already around it, restricted to posts dated
before the opening month. `postdate` on every blog result makes that possible.

Coverage caveat: the Naver API returns at most 100 results per request here, so
shops with more mentions than that are truncated and flagged rather than counted
exactly. Shop names are also not unique ("김밥천국"), so counts for generic names
carry other branches' posts — recorded as a known limitation, not corrected for.
"""
import argparse
import io
import json
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import requests

from .config import CACHE_DIR, ENV_PATH
from .db import init

API = "https://openapi.naver.com/v1/search/blog.json"
WORKERS = 5
PER_REQ = 100

_local = threading.local()


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        env = {}
        for line in ENV_PATH.open(encoding="utf-8-sig"):
            t = line.strip()
            if t and not t.startswith("#") and "=" in t:
                k, v = t.split("=", 1)
                env[k.strip()] = v.strip()
        s = requests.Session()
        s.headers.update({"X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
                          "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"]})
        _local.s = s
    return s


def lookup(item, tries=3):
    """-> (mgtno, total, [YYYYMM...]) ; None total means the call never answered.

    Query is "<동명> <상호명>", not the shop name alone. Bare names pulled in
    every same-named shop nationwide - 82% of a 300-shop trial hit the result
    ceiling, which makes the count meaningless as a location signal.
    """
    mgtno, name = item
    for attempt in range(tries):
        try:
            r = _session().get(API, params={"query": name, "display": PER_REQ,
                                            "sort": "date"}, timeout=20)
            if r.status_code != 200:
                time.sleep(0.4 * (attempt + 1))
                continue
            j = r.json()
            months = [(it.get("postdate") or "")[:6] for it in (j.get("items") or [])]
            return mgtno, j.get("total", 0), [m for m in months if len(m) == 6]
        except Exception:
            time.sleep(0.3 * (attempt + 1))
    return mgtno, None, []


def targets(con, gu, min_name=2, limit=None, since=2010):
    """Shops that were around during the validation window. `since` keeps the
    request count inside Naver's daily quota (25k) - 마포구 has 27.9k in total."""
    from .trend import place_name
    rows = con.execute(
        "SELECT l.mgtno, l.bplcnm, gs.sgis_adm_nm FROM licence l "
        "JOIN grid_sgis gs ON l.grid_id=gs.grid_id "
        "WHERE gs.sgis_adm_nm LIKE ? AND l.grid_id IS NOT NULL "
        "AND length(trim(l.bplcnm)) >= ? "
        "AND (l.open_y >= ? OR l.is_closed=0)", (f"%{gu}%", min_name, since)).fetchall()
    out = []
    for r in rows:
        if not r[1]:
            continue
        dong = place_name(r[2]) or gu
        out.append((r[0], f"{dong} {r[1].strip()}"))
    return out[:limit] if limit else out


def collect(con, gu="마포구", limit=None):
    cache = CACHE_DIR / f"mentions_{gu}.json"
    done = json.load(io.open(cache, encoding="utf-8")) if cache.exists() else {}
    todo = [t for t in targets(con, gu, limit=limit) if t[0] not in done]
    print(f"  {gu}: 대상 {len(todo):,} (캐시 {len(done):,})")
    if not todo:
        return done

    failed = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (mgtno, total, months) in enumerate(ex.map(lookup, todo), 1):
            if total is None:
                failed += 1
            else:
                done[mgtno] = {"total": total, "months": months}
            if i % 2000 == 0:
                print(f"    {i:,}/{len(todo):,} (실패 {failed})", flush=True)
                json.dump(done, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(done, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  수집 {len(done):,} · 실패 {failed:,}")
    return done


SCHEMA = """
CREATE TABLE IF NOT EXISTS mention (
  mgtno     TEXT,
  period    INTEGER,        -- year*12+month
  cnt       INTEGER,
  PRIMARY KEY (mgtno, period)
);
CREATE INDEX IF NOT EXISTS ix_mention_mgtno ON mention(mgtno);
CREATE TABLE IF NOT EXISTS mention_shop (
  mgtno     TEXT PRIMARY KEY,
  total     INTEGER,
  truncated INTEGER          -- 1 when total exceeded what one request returns
);
"""


def load(con, gu="마포구", limit=None):
    con.executescript(SCHEMA)
    data = collect(con, gu, limit)

    shop_rows, mon_rows = [], []
    for mgtno, d in data.items():
        shop_rows.append((mgtno, d["total"], 1 if d["total"] > PER_REQ else 0))
        c = defaultdict(int)
        for m in d["months"]:
            c[int(m[:4]) * 12 + int(m[4:6])] += 1
        mon_rows.extend((mgtno, p, n) for p, n in c.items())

    con.executemany("INSERT OR REPLACE INTO mention_shop VALUES(?,?,?)", shop_rows)
    con.executemany("INSERT OR REPLACE INTO mention VALUES(?,?,?)", mon_rows)
    con.commit()

    n = con.execute("SELECT count(*) FROM mention_shop").fetchone()[0]
    tr = con.execute("SELECT count(*) FROM mention_shop WHERE truncated=1").fetchone()[0]
    z = con.execute("SELECT count(*) FROM mention_shop WHERE total=0").fetchone()[0]
    md = con.execute("SELECT count(*) FROM mention").fetchone()[0]
    print(f"mention_shop: {n:,}개 점포 · 언급 0건 {z:,} ({z/max(1,n)*100:.0f}%) · "
          f"100건 초과(절단) {tr:,}")
    print(f"mention: {md:,}행 (점포×월)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gu", default="마포구")
    ap.add_argument("--limit", type=int)
    a = ap.parse_args()
    load(init(), a.gu, a.limit)
