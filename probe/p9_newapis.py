"""Probe newly-applied-for APIs: SGIS, FTC franchise, REB rents, VWORLD.

data.go.kr returns `500 Unexpected errors` both for an unapproved key and for a
wrong endpoint path, so a failure here is ambiguous by itself. Each block prints
enough of the raw body to tell the two apart.
"""
import io
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.config import ENV_PATH, ROOT  # noqa: E402

env = {}
for line in ENV_PATH.open(encoding="utf-8-sig"):
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()

DK = env.get("DATA_GO_KR_SERVICE_KEY")
out = {}

# ------------------------------------------------------------------ SGIS
print("=" * 60)
print("SGIS 통계지리정보")
ck, cs = env.get("SGIS_CONSUMER_KEY"), env.get("SGIS_CONSUMER_SECRET")
if not ck or not cs:
    print("  키 없음")
else:
    try:
        r = requests.get("https://sgisapi.kostat.go.kr/OpenAPI3/auth/authentication.json",
                         params={"consumer_key": ck, "consumer_secret": cs}, timeout=30)
        j = r.json()
        print(f"  인증: errCd={j.get('errCd')} errMsg={j.get('errMsg')}")
        tok = (j.get("result") or {}).get("accessToken")
        if tok:
            print(f"  accessToken 획득 (len={len(tok)})")
            # 행정구역 경계 - 서울 시도 단위
            b = requests.get("https://sgisapi.kostat.go.kr/OpenAPI3/boundary/hadmarea.geojson",
                             params={"accessToken": tok, "year": "2022", "adm_cd": "11",
                                     "low_search": "1"}, timeout=60)
            try:
                g = b.json()
                feats = g.get("features") or []
                print(f"  경계 API: {b.status_code} features={len(feats)}")
                if feats:
                    print(f"    props: {list(feats[0].get('properties', {}).keys())}")
            except Exception:
                print(f"  경계 API: {b.status_code} {b.text[:150]}")
            # 집계구 통계 (인구)
            s2 = requests.get("https://sgisapi.kostat.go.kr/OpenAPI3/stats/population.json",
                              params={"accessToken": tok, "year": "2022", "adm_cd": "11",
                                      "low_search": "2"}, timeout=60)
            try:
                sj = s2.json()
                res = sj.get("result") or []
                print(f"  인구통계: errCd={sj.get('errCd')} rows={len(res)}")
                if res:
                    print(f"    sample keys: {list(res[0].keys())[:10]}")
            except Exception:
                print(f"  인구통계: {s2.status_code} {s2.text[:150]}")
            out["sgis"] = "OK"
    except Exception as e:
        print(f"  ERR {type(e).__name__}: {str(e)[:120]}")

# -------------------------------------------------------------- FTC 가맹정보
print("=" * 60)
print("공정위 가맹정보 (창업비용)")
FTC = [
    ("브랜드별 창업금액", "http://apis.data.go.kr/1130000/FftcBrandFrcsCurSttus2_Service/getBrandFrcsCurSttus"),
    ("브랜드별 창업금액b", "http://apis.data.go.kr/1130000/FftcBrandOpbizCost2_Service/getBrandOpbizCost"),
    ("브랜드별 창업금액c", "http://apis.data.go.kr/1130000/FftcBrandRlsInfo2_Service/getBrandOpbizCost"),
    ("브랜드 목록", "http://apis.data.go.kr/1130000/FftcBrandRlsInfo2_Service/getBrandList"),
    ("업종별 창업비용", "http://apis.data.go.kr/1130000/FftcIndutyOpbizCost2_Service/getIndutyOpbizCost"),
]
for nm, url in FTC:
    try:
        r = requests.get(url, params={"serviceKey": DK, "pageNo": 1, "numOfRows": 3,
                                      "resultType": "json", "yr": "2024"}, timeout=30)
        body = r.text[:200].replace("\n", " ")
        print(f"  {nm:<18} {r.status_code} {body}")
    except Exception as e:
        print(f"  {nm:<18} ERR {type(e).__name__}")

# ------------------------------------------------------------------- REB
print("=" * 60)
print("부동산원 임대동향")
REB = [
    ("통계조회", "http://apis.data.go.kr/1611000/RealEstateTradingSvc/getRealEstateTrading"),
    ("임대동향", "http://apis.data.go.kr/1613000/RealEstateRentSvc/getRent"),
]
for nm, url in REB:
    try:
        r = requests.get(url, params={"serviceKey": DK, "pageNo": 1, "numOfRows": 3,
                                      "type": "json"}, timeout=30)
        print(f"  {nm:<12} {r.status_code} {r.text[:160]}")
    except Exception as e:
        print(f"  {nm:<12} ERR {type(e).__name__}")

# ---------------------------------------------------------------- VWORLD
print("=" * 60)
print("VWORLD 데이터API")
vk = env.get("VWORLD_API_KEY")
for nm, data in [("연속지적도", "LP_PA_CBND_BUBUN"), ("용도지역", "LT_C_UQ111")]:
    try:
        r = requests.get("https://api.vworld.kr/req/data",
                         params={"service": "data", "request": "GetFeature", "data": data,
                                 "key": vk, "format": "json", "size": 2,
                                 "geomFilter": "POINT(126.9910 37.5665)",
                                 "geometry": "false", "crs": "EPSG:4326"}, timeout=30)
        j = r.json().get("response", {})
        print(f"  {nm:<10} status={j.get('status')} err={(j.get('error') or {}).get('text')}")
    except Exception as e:
        print(f"  {nm:<10} ERR {type(e).__name__}")

print("=" * 60)
