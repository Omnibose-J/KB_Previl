"""Which CRS are LOCALDATA X/Y actually in?

The candidates all share the Korean central-belt origin and differ mainly in
datum shift, so they produce points 100-200m apart - close enough that every
internal check passes regardless, and only an external witness can decide.

Method: transform the same rows under each candidate, reverse-geocode with
Kakao, and score against the 구 in the row's own address. The correct CRS
should score near 100%; the rest should lose exactly the boundary-adjacent rows.
"""
import io
import json
import random
import sys

import requests
from pyproj import Transformer

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
from pipeline.config import ENV_PATH, ROOT  # noqa: E402
from pipeline.db import init  # noqa: E402

CANDIDATES = ["EPSG:2097", "EPSG:5174", "EPSG:5181", "EPSG:5186", "EPSG:5178"]
N = 120

env = {}
for line in ENV_PATH.open(encoding="utf-8-sig"):
    s = line.strip()
    if s and not s.startswith("#") and "=" in s:
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()
KK = env["KAKAO_REST_API_KEY"]

con = init()
rows = con.execute(
    "SELECT l.addr, r.x, r.y FROM licence l JOIN ("
    "  SELECT mgtno, NULL x, NULL y FROM licence WHERE 0) r ON 1=0").fetchall()

# raw X/Y are not stored in the db (only the transformed lon/lat), so read the
# cache to test alternative transforms against the original values
raw = []
with io.open(ROOT / "pipeline" / "cache" / "licence.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        x, y = str(d.get("X") or "").strip(), str(d.get("Y") or "").strip()
        a = str(d.get("SITEWHLADDR") or "")
        if x and y and a.startswith("서울"):
            gu = next((p for p in a.split() if p.endswith("구")), None)
            if gu:
                raw.append((float(x), float(y), gu, a))

random.seed(5)
sample = random.sample(raw, N)
print(f"표본 {len(sample)}건 (서울 주소 + 좌표 보유 {len(raw):,}건 중)\n")


def gu_at(lon, lat):
    try:
        r = requests.get("https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
                         headers={"Authorization": f"KakaoAK {KK}"},
                         params={"x": lon, "y": lat}, timeout=15).json()
        docs = r.get("documents") or []
        return (docs[0].get("region_2depth_name") or "").strip() if docs else None
    except Exception:
        return None


results = {}
for crs in CANDIDATES:
    try:
        tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    except Exception as e:
        print(f"{crs}: transformer 생성 실패 {e}")
        continue
    ok = miss = err = 0
    examples = []
    for x, y, gu, addr in sample:
        lon, lat = tr.transform(x, y)
        if not (126.7 < lon < 127.3 and 37.4 < lat < 37.75):
            err += 1
            continue
        got = gu_at(lon, lat)
        if got is None:
            err += 1
        elif got == gu:
            ok += 1
        else:
            miss += 1
            if len(examples) < 3:
                examples.append((addr[:30], gu, got))
    tested = ok + miss
    pct = ok / tested * 100 if tested else 0
    results[crs] = pct
    print(f"{crs}: 일치 {ok}/{tested} = {pct:.1f}%   (범위밖/실패 {err})")
    for a, want, got in examples:
        print(f"    '{a}' 주소={want} 역지오={got}")

print("\n" + "=" * 46)
best = max(results, key=results.get) if results else None
for c, p in sorted(results.items(), key=lambda kv: -kv[1]):
    print(f"  {c}: {p:.1f}%" + ("   <-- BEST" if c == best else ""))
