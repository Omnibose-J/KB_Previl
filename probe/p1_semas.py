"""Probe: SEMAS store (commercial district) info API.

Goal: confirm endpoint, auth, response fields, and the finest spatial unit
(per-store coordinates?) for Seoul restaurant categories.
"""
import json
import sys

import requests

from common import ENV, brief, key, keystat, save

BASE = "http://apis.data.go.kr/B553077/api/open/sdsc2"
SVC = key("SEMAS_SERVICE_KEY", "DATA_GO_KR_SERVICE_KEY", "DATA_GO_KR_API_KEY")

# Gangnam station area (WGS84) - dense restaurant zone, good stress test
CX, CY = 127.0276, 37.4979

OPS = [
    ("storeListInRadius", {"radius": 300, "cx": CX, "cy": CY, "indsLclsCd": "I2"}),
    ("storeListInDong", {"divId": "adongCd", "key": "1168064000"}),
    ("storeListInUpjong", {"divId": "indsLclsCd", "key": "I2"}),
    ("storeZoneInRadius", {"radius": 500, "cx": CX, "cy": CY}),
    ("largeUpjongList", {}),
    ("middleUpjongList", {}),
]

out = {"keystat": keystat("SEMAS_SERVICE_KEY", "DATA_GO_KR_SERVICE_KEY", "DATA_GO_KR_API_KEY"),
       "base": BASE, "ops": {}}

if not SVC:
    print(json.dumps(out, ensure_ascii=False, indent=2))
    sys.exit(1)

for op, extra in OPS:
    params = {"serviceKey": SVC, "type": "json", "pageNo": 1, "numOfRows": 5}
    params.update(extra)
    rec = {"params": {k: v for k, v in params.items() if k != "serviceKey"}}
    try:
        r = requests.get(f"{BASE}/{op}", params=params, timeout=30)
        rec["http"] = r.status_code
        txt = r.text
        rec["ctype"] = r.headers.get("Content-Type", "")
        try:
            j = r.json()
            body = (j.get("body") or {})
            items = body.get("items") or []
            rec["totalCount"] = body.get("totalCount")
            rec["returned"] = len(items)
            rec["header"] = j.get("header")
            if items:
                f, n = brief(items[0])
                rec["field_count"] = n
                rec["fields"] = f
                rec["sample"] = {k: items[0].get(k) for k in
                                 ("bizesNm", "indsLclsNm", "indsMclsNm", "indsSclsNm",
                                  "lnoAdr", "rdnmAdr", "lon", "lat", "adongCd", "adongNm",
                                  "trarNo", "trarNm", "ctprvnNm", "signguNm") if k in items[0]}
        except Exception:
            rec["raw_head"] = txt[:400]
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
    out["ops"][op] = rec

save("p1_semas", out)
print(json.dumps(out, ensure_ascii=False, indent=2)[:6000])
