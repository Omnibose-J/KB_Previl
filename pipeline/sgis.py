"""SGIS (통계청 통계지리정보) — census demand features.

What this adds that we did not have: 사업체 수 / 종사자 수 per dong, which is
the closest public proxy for daytime working population, plus household size and
age structure. Living population tells us how many bodies are present; this tells
us what kind of place it is.

Spatial resolution note: 집계구 (14-digit, ~19k for Seoul) statistics ARE
returned, but SGIS does not serve 집계구 boundary geometry through the open API
(`boundary/statsarea.geojson` -> errCd -200) and its reverse geocoder resolves
only to 행정동. Without polygons there is no way to say which 집계구 a grid cell
falls in, so cell-level joins stay at 행정동. The 집계구 rows are collected
anyway - they are the payload waiting for a boundary file, and their spread
within a dong is itself informative.
"""
import argparse
import io
import json

import requests

from .config import CACHE_DIR, ENV_PATH
from .db import init

BASE = "https://sgisapi.kostat.go.kr/OpenAPI3"
YEAR = "2022"
SEOUL_SGG = [f"111{i:02d}" for i in range(10, 26)]   # placeholder, replaced below


def _keys():
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    ck, cs = env.get("SGIS_CONSUMER_KEY"), env.get("SGIS_CONSUMER_SECRET")
    if not ck or not cs:
        raise RuntimeError("SGIS_CONSUMER_KEY/SECRET missing from .env")
    return ck, cs


def token():
    ck, cs = _keys()
    j = requests.get(f"{BASE}/auth/authentication.json",
                     params={"consumer_key": ck, "consumer_secret": cs}, timeout=30).json()
    if j.get("errCd") != 0:
        raise RuntimeError(f"SGIS auth failed: {j.get('errMsg')}")
    return j["result"]["accessToken"]


def sgg_list(tok):
    """Seoul's 시군구 codes, from SGIS itself rather than hardcoded."""
    j = requests.get(f"{BASE}/addr/stage.json",
                     params={"accessToken": tok, "cd": "11"}, timeout=30).json()
    return [r["cd"] for r in (j.get("result") or [])]


def fetch(tok, api, adm_cd, low):
    j = requests.get(f"{BASE}/stats/{api}.json",
                     params={"accessToken": tok, "year": YEAR,
                             "adm_cd": adm_cd, "low_search": low}, timeout=60).json()
    if j.get("errCd") != 0:
        return []
    return j.get("result") or []


def collect(low="1"):
    """low='1' -> 행정동, low='2' -> 집계구."""
    cache = CACHE_DIR / f"sgis_{'dong' if low == '1' else 'jipgyegu'}.json"
    if cache.exists():
        d = json.load(io.open(cache, encoding="utf-8"))
        print(f"  [cache] sgis low={low}: {len(d):,} rows")
        return d

    tok = token()
    sggs = sgg_list(tok)
    print(f"  서울 시군구 {len(sggs)}개")

    merged = {}
    for i, sgg in enumerate(sggs):
        for api, fields in (
                ("population", ["tot_ppltn", "ppltn_dnsty", "avg_age",
                                "tot_family", "avg_fmember_cnt"]),
                ("household", ["household_cnt", "avg_family_member_cnt"]),
                ("company", ["corp_cnt", "tot_worker"])):
            for r in fetch(tok, api, sgg, low):
                cd = r.get("adm_cd")
                if not cd:
                    continue
                m = merged.setdefault(cd, {"adm_cd": cd, "adm_nm": r.get("adm_nm")})
                for f in fields:
                    v = r.get(f)
                    if v not in (None, "N/A", ""):
                        try:
                            m[f] = float(v)
                        except ValueError:
                            pass
        if (i + 1) % 5 == 0:
            print(f"    {i+1}/{len(sggs)} 구, {len(merged):,} rows", flush=True)

    out = list(merged.values())
    json.dump(out, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  [fetched] sgis low={low}: {len(out):,} rows")
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS sgis_dong (
  adm_cd        TEXT PRIMARY KEY,
  adm_nm        TEXT,
  tot_ppltn     REAL,
  ppltn_dnsty   REAL,
  avg_age       REAL,
  tot_family    REAL,
  avg_fmember_cnt REAL,
  household_cnt REAL,
  corp_cnt      REAL,
  tot_worker    REAL
);
CREATE TABLE IF NOT EXISTS sgis_jipgyegu (
  adm_cd        TEXT PRIMARY KEY,
  dong_cd       TEXT,
  adm_nm        TEXT,
  tot_ppltn     REAL,
  ppltn_dnsty   REAL,
  avg_age       REAL,
  household_cnt REAL,
  corp_cnt      REAL,
  tot_worker    REAL
);
CREATE INDEX IF NOT EXISTS ix_jgg_dong ON sgis_jipgyegu(dong_cd);
"""


def load(con, low="1"):
    con.executescript(SCHEMA)
    rows = collect(low)
    if low == "1":
        con.execute("DELETE FROM sgis_dong")
        con.executemany(
            "INSERT OR REPLACE INTO sgis_dong VALUES(?,?,?,?,?,?,?,?,?,?)",
            [(r["adm_cd"], r.get("adm_nm"), r.get("tot_ppltn"), r.get("ppltn_dnsty"),
              r.get("avg_age"), r.get("tot_family"), r.get("avg_fmember_cnt"),
              r.get("household_cnt"), r.get("corp_cnt"), r.get("tot_worker"))
             for r in rows])
        n = con.execute("SELECT count(*) FROM sgis_dong").fetchone()[0]
        w = con.execute("SELECT count(*) FROM sgis_dong WHERE corp_cnt IS NOT NULL").fetchone()[0]
        print(f"sgis_dong: {n:,} rows (사업체수 보유 {w:,})")
    else:
        con.execute("DELETE FROM sgis_jipgyegu")
        con.executemany(
            "INSERT OR REPLACE INTO sgis_jipgyegu VALUES(?,?,?,?,?,?,?,?,?)",
            [(r["adm_cd"], r["adm_cd"][:8], r.get("adm_nm"), r.get("tot_ppltn"),
              r.get("ppltn_dnsty"), r.get("avg_age"), r.get("household_cnt"),
              r.get("corp_cnt"), r.get("tot_worker")) for r in rows])
        n = con.execute("SELECT count(*) FROM sgis_jipgyegu").fetchone()[0]
        d = con.execute("SELECT count(DISTINCT dong_cd) FROM sgis_jipgyegu").fetchone()[0]
        print(f"sgis_jipgyegu: {n:,} rows ({d:,} 행정동)")
    con.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--low", default="1", choices=["1", "2"])
    ap.add_argument("--both", action="store_true")
    a = ap.parse_args()
    con = init()
    if a.both:
        load(con, "1")
        load(con, "2")
    else:
        load(con, a.low)
