"""Probe: Tier-2 structured + all unstructured sources, in one pass.

For each source the question is the same: does the key work, what comes back,
and what is the finest spatial unit it can address.
"""
import json

import requests

from common import key, keystat, save

out = {}
# Euljiro / Jongno test point (WGS84) - dense restaurant area
LON, LAT = 126.9910, 37.5665
ADDR = "서울특별시 중구 을지로 66"

# ---------------------------------------------------------------- VWORLD
vk = key("VWORLD_API_KEY")
out["vworld"] = {"keystat": keystat("VWORLD_API_KEY"), "calls": {}}
if vk:
    tests = {
        "geocode": ("https://api.vworld.kr/req/address", {
            "service": "address", "request": "getcoord", "version": "2.0",
            "crs": "epsg:4326", "address": ADDR, "type": "road", "key": vk, "format": "json"}),
        "parcel_LP_PA_CBND": ("https://api.vworld.kr/req/data", {
            "service": "data", "request": "GetFeature", "data": "LP_PA_CBND_BUBUN",
            "key": vk, "format": "json", "size": 3, "geomFilter": f"POINT({LON} {LAT})",
            "geometry": "true", "crs": "EPSG:4326"}),
        "zoning_LT_C_UQ111": ("https://api.vworld.kr/req/data", {
            "service": "data", "request": "GetFeature", "data": "LT_C_UQ111",
            "key": vk, "format": "json", "size": 3, "geomFilter": f"POINT({LON} {LAT})",
            "geometry": "false", "crs": "EPSG:4326"}),
        "building_LT_C_SPBD": ("https://api.vworld.kr/req/data", {
            "service": "data", "request": "GetFeature", "data": "LT_C_SPBD",
            "key": vk, "format": "json", "size": 3, "geomFilter": f"POINT({LON} {LAT})",
            "geometry": "false", "crs": "EPSG:4326"}),
    }
    for name, (u, p) in tests.items():
        rec = {}
        try:
            r = requests.get(u, params=p, timeout=30)
            rec["http"] = r.status_code
            j = r.json()
            resp = j.get("response") or j
            rec["status"] = resp.get("status")
            rec["error"] = (resp.get("error") or {}).get("text") if resp.get("error") else None
            feats = (((resp.get("result") or {}).get("featureCollection") or {}).get("features")) or []
            if feats:
                rec["n"] = len(feats)
                rec["props"] = list(feats[0].get("properties", {}).keys())
                rec["sample"] = {k: v for k, v in list(feats[0].get("properties", {}).items())[:12]}
            elif resp.get("result"):
                rec["result_head"] = json.dumps(resp["result"], ensure_ascii=False)[:300]
        except Exception as e:
            rec["exc"] = f"{type(e).__name__}: {str(e)[:120]}"
        out["vworld"]["calls"][name] = rec

# ---------------------------------------------------------------- KAKAO
kk = key("KAKAO_REST_API_KEY")
out["kakao"] = {"keystat": keystat("KAKAO_REST_API_KEY")}
if kk:
    try:
        r = requests.get("https://dapi.kakao.com/v2/local/search/category.json",
                         headers={"Authorization": f"KakaoAK {kk}"},
                         params={"category_group_code": "FD6", "x": LON, "y": LAT,
                                 "radius": 300, "size": 5, "sort": "distance"}, timeout=30)
        out["kakao"]["http"] = r.status_code
        j = r.json()
        out["kakao"]["total"] = (j.get("meta") or {}).get("total_count")
        out["kakao"]["pageable"] = (j.get("meta") or {}).get("pageable_count")
        docs = j.get("documents") or []
        if docs:
            out["kakao"]["fields"] = list(docs[0].keys())
            out["kakao"]["sample"] = docs[0]
    except Exception as e:
        out["kakao"]["exc"] = f"{type(e).__name__}: {str(e)[:120]}"

# ---------------------------------------------------------------- NAVER
nid, nsec = key("NAVER_CLIENT_ID"), key("NAVER_CLIENT_SECRET")
out["naver"] = {"keystat": keystat("NAVER_CLIENT_ID"), "calls": {}}
if nid and nsec:
    h = {"X-Naver-Client-Id": nid, "X-Naver-Client-Secret": nsec}
    for name, (u, p) in {
        "local": ("https://openapi.naver.com/v1/search/local.json",
                  {"query": "을지로 맛집", "display": 5}),
        "blog": ("https://openapi.naver.com/v1/search/blog.json",
                 {"query": "을지로 맛집", "display": 5, "sort": "date"}),
        "news": ("https://openapi.naver.com/v1/search/news.json",
                 {"query": "을지로 상권", "display": 5}),
        "datalab_check": ("https://openapi.naver.com/v1/search/blog.json",
                          {"query": "성수동 카페", "display": 1}),
    }.items():
        rec = {}
        try:
            r = requests.get(u, headers=h, params=p, timeout=30)
            rec["http"] = r.status_code
            j = r.json()
            rec["total"] = j.get("total")
            rec["returned"] = len(j.get("items") or [])
            items = j.get("items") or []
            if items:
                rec["fields"] = list(items[0].keys())
                rec["sample"] = items[0]
        except Exception as e:
            rec["exc"] = f"{type(e).__name__}: {str(e)[:120]}"
        out["naver"]["calls"][name] = rec

# ---------------------------------------------------------- GOOGLE PLACES
gk = key("GOOGLE_MAPS_API_KEY")
out["google_places"] = {"keystat": keystat("GOOGLE_MAPS_API_KEY"), "calls": {}}
if gk:
    # Places API (New) - searchNearby
    try:
        r = requests.post(
            "https://places.googleapis.com/v1/places:searchNearby",
            headers={"Content-Type": "application/json", "X-Goog-Api-Key": gk,
                     "X-Goog-FieldMask": "places.id,places.displayName,places.rating,"
                                         "places.userRatingCount,places.primaryType,"
                                         "places.location,places.priceLevel"},
            json={"includedTypes": ["restaurant"], "maxResultCount": 5,
                  "locationRestriction": {"circle": {
                      "center": {"latitude": LAT, "longitude": LON}, "radius": 300.0}},
                  "languageCode": "ko"}, timeout=30)
        rec = {"http": r.status_code}
        j = r.json()
        if "places" in j:
            rec["n"] = len(j["places"])
            rec["sample"] = j["places"][0]
        else:
            rec["body_head"] = json.dumps(j, ensure_ascii=False)[:400]
        out["google_places"]["calls"]["searchNearby_new"] = rec
    except Exception as e:
        out["google_places"]["calls"]["searchNearby_new"] = {"exc": f"{type(e).__name__}: {str(e)[:120]}"}
    # legacy nearbysearch
    try:
        r = requests.get("https://maps.googleapis.com/maps/api/place/nearbysearch/json",
                         params={"location": f"{LAT},{LON}", "radius": 300,
                                 "type": "restaurant", "language": "ko", "key": gk}, timeout=30)
        j = r.json()
        out["google_places"]["calls"]["nearbysearch_legacy"] = {
            "http": r.status_code, "status": j.get("status"),
            "n": len(j.get("results") or []),
            "error_message": j.get("error_message"),
            "sample_fields": list((j.get("results") or [{}])[0].keys()) if j.get("results") else None}
    except Exception as e:
        out["google_places"]["calls"]["nearbysearch_legacy"] = {"exc": f"{type(e).__name__}: {str(e)[:120]}"}

# ---------------------------------------------------------------- YOUTUBE
yk = key("YOUTUBE_API_KEY")
out["youtube"] = {"keystat": keystat("YOUTUBE_API_KEY")}
if yk:
    try:
        r = requests.get("https://www.googleapis.com/youtube/v3/search",
                         params={"part": "snippet", "q": "성수동 맛집", "type": "video",
                                 "maxResults": 5, "order": "date", "key": yk}, timeout=30)
        j = r.json()
        out["youtube"]["http"] = r.status_code
        out["youtube"]["total"] = (j.get("pageInfo") or {}).get("totalResults")
        out["youtube"]["n"] = len(j.get("items") or [])
        out["youtube"]["error"] = (j.get("error") or {}).get("message")
    except Exception as e:
        out["youtube"]["exc"] = f"{type(e).__name__}: {str(e)[:120]}"

# ------------------------------------------------- REB commercial rent (data.go.kr)
dk = key("DATA_GO_KR_SERVICE_KEY", "DATA_GO_KR_API_KEY")
out["reb_rent"] = {"keystat": keystat("DATA_GO_KR_SERVICE_KEY"), "calls": {}}
for name, u in {
    "reb_stat_1": "http://apis.data.go.kr/1611000/nsdi/BuildingUseService/attr/getBuildingUse",
    "reb_commercial": "http://apis.data.go.kr/B552081/rebOpenApi/rentLevel",
    "odcloud_15002275": "https://api.odcloud.kr/api/15002275/v1/uddi:",
}.items():
    rec = {}
    try:
        r = requests.get(u, params={"serviceKey": dk, "type": "json", "page": 1,
                                    "perPage": 3, "numOfRows": 3, "pageNo": 1}, timeout=30)
        rec["http"] = r.status_code
        rec["head"] = r.text[:250].replace("\n", " ")
    except Exception as e:
        rec["exc"] = f"{type(e).__name__}: {str(e)[:120]}"
    out["reb_rent"]["calls"][name] = rec

save("p6_others", out)
print(json.dumps(out, ensure_ascii=False, indent=2)[:9000])
