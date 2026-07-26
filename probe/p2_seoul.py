"""Probe: Seoul Open Data Plaza APIs.

The dataset pages are JS-rendered so service names can't be scraped; brute-force
a candidate list instead. Seoul's API returns INFO-000 on success and
ERROR-336 / INFO-200 style codes otherwise, so a wrong name is cheap to detect.

Goal: which commercial-analysis + living-population services are actually live,
what their spatial unit is, and which quarters are available.
"""
import io
import json

import requests

from common import key, keystat, save

KEY = key("SEOUL_OPEN_API_KEY")
BASE = "http://openapi.seoul.go.kr:8088"

CANDIDATES = [
    # commercial analysis - post-2024 "표준단위구역" era
    "VwsmTrdarSelngQq",      # 추정매출-상권
    "VwsmTrdarFlpopQq",      # 길단위인구-상권
    "VwsmTrdarStorQq",       # 점포-상권
    "VwsmTrdarIndutyQq",
    "VwsmTrdhlSelngQq",      # 상권배후지 추정매출
    "VwsmTrdhlFlpopQq",
    "TbgisTrdarRelm",        # 영역-상권
    "VwsmAdstrdSelngQq",     # 행정동 추정매출
    "VwsmSignguSelngQq",
    "VwsmMegaSelngQq",
    # legacy 우리마을가게 naming
    "TbgisTrdarRelm2",
    "VwsmTrdarSelngW",
    "trdarSelngQq",
    # living population
    "SPOP_LOCAL_RESD_DONG",   # 행정동 단위 생활인구
    "SPOP_LOCAL_RESD_JACHI",  # 자치구 단위
    "SPOP_LOCAL_RESD_TIME",
    "SPOP_DAILYSUM_JACHI",
    # transit
    "CardSubwayStatsNew",     # 지하철 승하차
    "CardSubwayTime",
    "busStopLocationXY",
]

out = {"keystat": keystat("SEOUL_OPEN_API_KEY"), "base": BASE, "services": {}}

for svc in CANDIDATES:
    url = f"{BASE}/{KEY}/json/{svc}/1/3/"
    rec = {}
    try:
        r = requests.get(url, timeout=30)
        rec["http"] = r.status_code
        try:
            j = r.json()
        except Exception:
            rec["raw_head"] = r.text[:200]
            out["services"][svc] = rec
            continue
        # error envelope
        if "RESULT" in j:
            rec["code"] = j["RESULT"].get("CODE")
            rec["msg"] = j["RESULT"].get("MESSAGE")
        else:
            root = j.get(svc) or next(iter(j.values()))
            rec["code"] = (root.get("RESULT") or {}).get("CODE")
            rec["total"] = root.get("list_total_count")
            rows = root.get("row") or []
            rec["returned"] = len(rows)
            if rows:
                rec["field_count"] = len(rows[0])
                rec["fields"] = list(rows[0].keys())
                rec["sample"] = rows[0]
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    out["services"][svc] = rec

save("p2_seoul", out)

for svc, r in out["services"].items():
    ok = r.get("total") is not None
    print(f"{'OK ' if ok else '-- '} {svc:26s} code={r.get('code')} total={r.get('total')} "
          f"nfield={r.get('field_count')} msg={(r.get('msg') or '')[:40]}")
