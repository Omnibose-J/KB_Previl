"""Collect raw source data into pipeline/cache/*.jsonl.

Ordered by irreplaceability: licensing history first (it is the failure label
and the largest fetch), then commercial-area context, then living population.
Everything is cached, so a re-run costs no API calls.
"""
import argparse
import json

import requests

from .config import (DEFAULT_QUARTER, SEMAS_BASE, SEMAS_FOOD_LCLS, SVC_LICENCE,
                     SVC_LICENCE_REST, SVC_LVPOP_DONG, SVC_TRDAR_AREA,
                     SVC_TRDAR_FLPOP, SVC_TRDAR_SALES, SVC_TRDAR_STORE,
                     CACHE_DIR)
from .seoul_api import fetch_all, remaining
from .db import init


def collect_seoul(quarter=DEFAULT_QUARTER, lvpop_days=7, dry_run=False,
                  force=False):
    plan = [
        ("licence",     SVC_LICENCE,     "",            None),
        # 휴게음식점. 카페·베이커리·패스트푸드가 여기 있고, 서울 영업 중
        # 음식업의 16.9% 다. 빠지면 model.tier2 가 만들 것이 없고 service.api
        # 의 까페 집계와 model.concept_mix 가 «no such table: licence_rest» 로
        # 죽는다 — 예전에 손으로 한 번 받아 캐시에만 있던 것을 체인에 넣는다.
        ("licence_rest", SVC_LICENCE_REST, "",          None),
        ("trdar_area",  SVC_TRDAR_AREA,  "",            None),
        ("trdar_sales", SVC_TRDAR_SALES, f"{quarter}/", None),
        ("trdar_store", SVC_TRDAR_STORE, f"{quarter}/", None),
        ("trdar_flpop", SVC_TRDAR_FLPOP, f"{quarter}/", None),
        # rows arrive newest-first, so a prefix is the most recent N days
        ("lvpop",       SVC_LVPOP_DONG,  "",            424 * 24 * lvpop_days),
    ]
    out = {}
    for name, svc, args, limit in plan:
        out[name] = fetch_all(
            svc,
            args=args,
            cache_name=name,
            limit=limit,
            dry_run=dry_run,
            force=force,
        )
    return out


def collect_semas(dry_run=False):
    """SEMAS store snapshot for Seoul food service, via 시군구 radius sweep.

    storeListInUpjong returns nationwide rows with no region filter, so we page
    it and keep Seoul. 827k nationwide at 1000/page is 828 calls against a
    separate quota (data.go.kr), which is independent of the Seoul budget.
    """
    cache = CACHE_DIR / "semas_seoul.jsonl"
    if cache.exists():
        rows = [json.loads(line) for line in open(cache, encoding="utf-8")]
        print(f"  [cache] semas_seoul: {len(rows):,} rows")
        return rows

    import io as _io
    env = {}
    for line in _io.open(CACHE_DIR.parent.parent / ".env", encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    svc_key = env.get("DATA_GO_KR_SERVICE_KEY") or env.get("DATA_GO_KR_API_KEY")

    if dry_run:
        r = requests.get(f"{SEMAS_BASE}/storeListInUpjong",
                         params={"serviceKey": svc_key, "type": "json", "pageNo": 1,
                                 "numOfRows": 1, "divId": "indsLclsCd",
                                 "key": SEMAS_FOOD_LCLS}, timeout=30)
        tot = (r.json().get("body") or {}).get("totalCount")
        print(f"  [dry-run] SEMAS nationwide food: {tot:,} -> ~{-(-tot // 1000)} calls "
              f"(data.go.kr quota, separate from Seoul)")
        return []

    rows, pageno = [], 1
    while True:
        r = requests.get(f"{SEMAS_BASE}/storeListInUpjong",
                         params={"serviceKey": svc_key, "type": "json", "pageNo": pageno,
                                 "numOfRows": 1000, "divId": "indsLclsCd",
                                 "key": SEMAS_FOOD_LCLS}, timeout=60)
        body = r.json().get("body") or {}
        items = body.get("items") or []
        if not items:
            break
        rows.extend([x for x in items if (x.get("ctprvnNm") or "").startswith("서울")])
        if pageno % 100 == 0:
            print(f"    page {pageno}, seoul rows {len(rows):,}", flush=True)
        if pageno * 1000 >= (body.get("totalCount") or 0):
            break
        pageno += 1

    with open(cache, "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(f"  [fetched] semas_seoul: {len(rows):,} rows ({pageno} calls)")
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quarter", default=DEFAULT_QUARTER)
    ap.add_argument("--lvpop-days", type=int, default=7)
    ap.add_argument("--semas", action="store_true", help="also collect SEMAS snapshot")
    a = ap.parse_args()

    init()
    print(f"Seoul API budget remaining: {remaining()}")
    collect_seoul(a.quarter, a.lvpop_days, a.dry_run)
    if a.semas:
        collect_semas(a.dry_run)
