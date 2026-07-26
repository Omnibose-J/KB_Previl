"""Naver DataLab search trend per neighbourhood — the one unstructured signal
that can be reconstructed as-of a past date.

Everything else unstructured (Google ratings, YouTube counts, blog top-N) is a
snapshot of today and cannot be replayed to 2019, so it cannot enter a model
that must be validated on the past. DataLab serves monthly series back to 2016,
so it can.

Normalisation problem and fix: DataLab's `ratio` is scaled to the maximum WITHIN
each request - the same keyword returned 24.97 in one request and 15.28 in
another (measured). Values from different requests are therefore not comparable.
Every request here includes a fixed anchor keyword, and each neighbourhood's
series is divided by the anchor's series. The result reads as "interest in this
neighbourhood relative to Seoul overall", which is both comparable across
requests and more meaningful than a raw index.
"""
import argparse
import io
import json
import re
import time

import requests

from .config import CACHE_DIR, ENV_PATH, ROOT
from .db import init

API = "https://openapi.naver.com/v1/datalab/search"
ANCHOR = "서울 맛집"
START = "2016-01-01"
END = "2026-06-30"
GROUP_MAX = 5          # measured: 6 -> 400 "should NOT have more than 5 items"


def _headers():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    return {"X-Naver-Client-Id": env["NAVER_CLIENT_ID"],
            "X-Naver-Client-Secret": env["NAVER_CLIENT_SECRET"],
            "Content-Type": "application/json"}


_NUM = re.compile(r"\d+")


def place_name(adm_nm):
    """'월계1동' -> '월계동'. Numbered sub-dongs are administrative; people
    search the base neighbourhood name."""
    if not adm_nm:
        return None
    nm = adm_nm.strip().split()[-1]
    nm = _NUM.sub("", nm)
    return nm if nm.endswith("동") and len(nm) >= 3 else (nm or None)


def targets(con):
    """Distinct searchable neighbourhood names present in the grid."""
    rows = con.execute(
        "SELECT DISTINCT sgis_adm_nm FROM grid_sgis WHERE sgis_adm_nm IS NOT NULL").fetchall()
    names = {}
    for r in rows:
        p = place_name(r[0])
        if p:
            names.setdefault(p, []).append(r[0])
    return names


def fetch_chunk(headers, names):
    """One request: anchor + up to 4 neighbourhoods. Returns anchor-relative series."""
    groups = [{"groupName": "__anchor__", "keywords": [ANCHOR]}]
    for n in names:
        groups.append({"groupName": n, "keywords": [f"{n} 맛집"]})
    body = {"startDate": START, "endDate": END, "timeUnit": "month",
            "keywordGroups": groups}
    r = requests.post(API, headers=headers, json=body, timeout=40)
    if r.status_code != 200:
        return None, r.text[:160]
    res = {g["title"]: {d["period"]: d["ratio"] for d in g["data"]}
           for g in r.json().get("results", [])}
    anchor = res.get("__anchor__") or {}
    if not anchor:
        return None, "anchor missing"
    out = {}
    for n in names:
        s = res.get(n) or {}
        out[n] = {p: (v / anchor[p]) for p, v in s.items()
                  if anchor.get(p)}          # anchor 0 -> drop that month
    return out, None


def collect(con):
    cache = CACHE_DIR / "naver_trend.json"
    if cache.exists():
        d = json.load(io.open(cache, encoding="utf-8"))
        print(f"  [cache] trend: {len(d):,} 지역")
        return d

    h = _headers()
    names = sorted(targets(con))
    print(f"  대상 지역명 {len(names)}개 · 요청 {-(-len(names)//(GROUP_MAX-1))}회")

    out, fails = {}, []
    step = GROUP_MAX - 1
    for i in range(0, len(names), step):
        chunk = names[i:i + step]
        got, err = fetch_chunk(h, chunk)
        if got is None:
            fails.append((chunk, err))
        else:
            out.update(got)
        if (i // step + 1) % 20 == 0:
            print(f"    {i+len(chunk)}/{len(names)} 지역, 실패 {len(fails)}", flush=True)
        time.sleep(0.1)

    json.dump(out, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  [fetched] trend: {len(out):,} 지역 · 실패 {len(fails)}")
    for c, e in fails[:3]:
        print(f"    실패 예: {c} -> {e}")
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS trend (
  place    TEXT,
  period   TEXT,          -- YYYY-MM-01
  rel      REAL,          -- anchor-relative interest
  PRIMARY KEY (place, period)
);
CREATE INDEX IF NOT EXISTS ix_trend_place ON trend(place);
CREATE TABLE IF NOT EXISTS grid_place (
  grid_id  TEXT PRIMARY KEY,
  place    TEXT
);
CREATE INDEX IF NOT EXISTS ix_grid_place ON grid_place(place);
"""


def load(con):
    con.executescript(SCHEMA)
    data = collect(con)
    con.execute("DELETE FROM trend")
    rows = [(p, per, v) for p, series in data.items() for per, v in series.items()]
    con.executemany("INSERT OR REPLACE INTO trend VALUES(?,?,?)", rows)

    con.execute("DELETE FROM grid_place")
    gp = []
    for r in con.execute("SELECT grid_id, sgis_adm_nm FROM grid_sgis "
                         "WHERE sgis_adm_nm IS NOT NULL"):
        p = place_name(r[1])
        if p:
            gp.append((r[0], p))
    con.executemany("INSERT OR REPLACE INTO grid_place VALUES(?,?)", gp)
    con.commit()

    n = con.execute("SELECT count(*) FROM trend").fetchone()[0]
    pl = con.execute("SELECT count(DISTINCT place) FROM trend").fetchone()[0]
    months = con.execute("SELECT min(period), max(period) FROM trend").fetchone()
    cov = con.execute(
        "SELECT count(*) FROM grid_place gp WHERE EXISTS "
        "(SELECT 1 FROM trend t WHERE t.place=gp.place)").fetchone()[0]
    tot = con.execute("SELECT count(*) FROM grid").fetchone()[0]
    print(f"trend: {n:,}행 · {pl}개 지역 · {months[0]}~{months[1]}")
    print(f"grid_place: 트렌드 보유 격자 {cov:,}/{tot:,} ({cov/tot*100:.1f}%)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    a = ap.parse_args()
    load(init())
