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
                     CACHE_DIR, load_env)
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
        if not rows:
            # 이제는 빈 캐시를 새로 만들지 않지만, 그 버그가 이미 남긴 0바이트
            # 파일은 그대로 있다. 받아들이면 «받아 봤더니 없더라»가 되어 다음
            # 단계가 조용히 빈 손으로 진행된다.
            raise RuntimeError(
                f"{cache} 가 비어 있다 — 예전 수집이 실패하고 남긴 껍데기다. "
                "지우고 다시 실행하면 원천에서 다시 받는다")
        print(f"  [cache] semas_seoul: {len(rows):,} rows")
        return rows

    env = load_env()
    svc_key = env.get("DATA_GO_KR_SERVICE_KEY") or env.get("DATA_GO_KR_API_KEY")
    if not svc_key:
        raise RuntimeError(
            "DATA_GO_KR_SERVICE_KEY 가 .env 에 없다 — SEMAS 는 이 키로만 받는다")

    def page(pageno, rows_per_page, timeout):
        """한 페이지. 응답이 기대한 모양이 아니면 «0건» 이 아니라 실패다.

        data.go.kr 은 키가 막혀도 200 과 함께 오류 payload 를 준다. 그것을
        «items 없음» 으로 읽으면 빈 캐시가 만들어지고, 캐시가 있으니 다음
        실행부터는 API 를 아예 부르지 않는다 — 한 번의 인증 오류가 영구
        결손이 된다.
        """
        r = requests.get(
            f"{SEMAS_BASE}/storeListInUpjong",
            params={"serviceKey": svc_key, "type": "json", "pageNo": pageno,
                    "numOfRows": rows_per_page, "divId": "indsLclsCd",
                    "key": SEMAS_FOOD_LCLS}, timeout=timeout)
        r.raise_for_status()
        body = (r.json() or {}).get("body")
        if not isinstance(body, dict) or "totalCount" not in body:
            raise RuntimeError(
                f"SEMAS 응답이 기대한 모양이 아니다 (page {pageno}): "
                f"{r.text[:200]}")
        return body

    if dry_run:
        tot = page(1, 1, 30)["totalCount"]
        print(f"  [dry-run] SEMAS nationwide food: {tot:,} -> ~{-(-tot // 1000)} calls "
              f"(data.go.kr quota, separate from Seoul)")
        return []

    rows, pageno = [], 1
    while True:
        body = page(pageno, 1000, 60)
        items = body.get("items") or []
        if not items:
            break
        rows.extend([x for x in items if (x.get("ctprvnNm") or "").startswith("서울")])
        if pageno % 100 == 0:
            print(f"    page {pageno}, seoul rows {len(rows):,}", flush=True)
        if pageno * 1000 >= (body.get("totalCount") or 0):
            break
        pageno += 1

    if not rows:
        # 서울에 음식점이 0곳일 수는 없다. 빈 캐시를 남기면 재시도가 막힌다.
        raise RuntimeError(
            f"SEMAS 가 서울 행을 하나도 주지 않았다 ({pageno} 페이지). "
            "캐시를 만들지 않았으므로 원인을 고친 뒤 그대로 다시 실행하면 된다")

    tmp = cache.with_suffix(cache.suffix + ".part")
    with open(tmp, "w", encoding="utf-8") as f:
        for x in rows:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    tmp.replace(cache)          # 완주한 것만 캐시가 된다
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
