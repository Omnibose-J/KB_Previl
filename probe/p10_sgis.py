"""Map the SGIS API surface we need: 집계구 boundaries + statistics.

Goal is to replace 행정동-level demand (424 units for Seoul) with 집계구
(~19k units), which actually matches a 100m grid. Need to establish: which
endpoint returns 집계구 geometry, which returns its statistics, and what the
smallest addressable unit really is.
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

BASE = "https://sgisapi.kostat.go.kr/OpenAPI3"
tok = requests.get(f"{BASE}/auth/authentication.json",
                   params={"consumer_key": env["SGIS_CONSUMER_KEY"],
                           "consumer_secret": env["SGIS_CONSUMER_SECRET"]},
                   timeout=30).json()["result"]["accessToken"]
print(f"accessToken len={len(tok)}\n")


def call(path, **params):
    params["accessToken"] = tok
    try:
        r = requests.get(f"{BASE}/{path}", params=params, timeout=60)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"_raw": r.text[:200]}
    except Exception as e:
        return None, {"_err": f"{type(e).__name__}: {e}"}


def show(label, path, **p):
    sc, j = call(path, **p)
    err = j.get("errCd") if isinstance(j, dict) else None
    msg = j.get("errMsg") if isinstance(j, dict) else None
    if "features" in (j or {}):
        feats = j["features"]
        print(f"{label:<34} {sc} features={len(feats)}")
        if feats:
            print(f"    props: {list(feats[0]['properties'].keys())}")
            print(f"    sample: {json.dumps(feats[0]['properties'], ensure_ascii=False)[:160]}")
    elif isinstance(j, dict) and "result" in j:
        res = j["result"]
        n = len(res) if isinstance(res, list) else 1
        print(f"{label:<34} {sc} errCd={err} rows={n}")
        if isinstance(res, list) and res:
            print(f"    keys: {list(res[0].keys())[:14]}")
            print(f"    sample: {json.dumps(res[0], ensure_ascii=False)[:200]}")
    else:
        print(f"{label:<34} {sc} errCd={err} msg={msg} {str(j)[:120]}")


print("=" * 70)
print("1) 경계 API — 집계구 지오메트리를 주는 엔드포인트 찾기")
show("hadmarea (행정동, low=2)", "boundary/hadmarea.geojson",
     year="2022", adm_cd="11110", low_search="1")
show("hrstatsarea (집계구?)", "boundary/hrstatsarea.geojson",
     year="2022", adm_cd="11110", low_search="1")
show("hrstatsarea no low", "boundary/hrstatsarea.geojson",
     year="2022", adm_cd="11110")
show("stats boundary", "boundary/stats.geojson", year="2022", adm_cd="11110")

print()
print("=" * 70)
print("2) 통계 API — 집계구 단위 인구/가구/사업체")
show("population low=0 (11110)", "stats/population.json", year="2022", adm_cd="11110")
show("population low=1", "stats/population.json", year="2022", adm_cd="11110", low_search="1")
show("population low=2", "stats/population.json", year="2022", adm_cd="11110", low_search="2")
show("household low=1", "stats/household.json", year="2022", adm_cd="11110", low_search="1")
show("company low=1", "stats/company.json", year="2022", adm_cd="11110", low_search="1")

print()
print("=" * 70)
print("3) 사업체 통계 — 음식점 업종 필터 가능한지")
show("company (theme)", "stats/company.json", year="2022", adm_cd="11110",
     low_search="1", theme_cd="A")

print()
print("=" * 70)
print("4) 주소/단계 조회")
show("addr stage", "addr/stage.json", pg_yn="0")
