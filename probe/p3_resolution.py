"""Probe: how fine can we actually get, spatially?

Pulls all 1,650 Seoul commercial areas and measures their real footprint,
then cross-checks against per-store coordinates from SEMAS. The output is the
evidence for choosing the recommendation unit.
"""
import json
import math
import statistics as st

import requests

from common import key, save

SEOUL = key("SEOUL_OPEN_API_KEY")
BASE = "http://openapi.seoul.go.kr:8088"


def fetch_all(svc, total=None, step=1000, extra=""):
    rows, start = [], 1
    while True:
        end = start + step - 1
        r = requests.get(f"{BASE}/{SEOUL}/json/{svc}/{start}/{end}/{extra}", timeout=60)
        j = r.json()
        root = j.get(svc) or {}
        got = root.get("row") or []
        rows.extend(got)
        cnt = root.get("list_total_count") or 0
        if len(got) < step or len(rows) >= (total or cnt):
            break
        start = end + 1
    return rows


out = {}

# ---- 1. commercial area footprints -------------------------------------
areas = fetch_all("TbgisTrdarRelm")
ar = [float(a["RELM_AR"]) for a in areas if a.get("RELM_AR")]
by_type = {}
for a in areas:
    t = a.get("TRDAR_SE_CD_NM") or "?"
    by_type.setdefault(t, []).append(float(a.get("RELM_AR") or 0))


def radius(m2):
    return round(math.sqrt(m2 / math.pi))


out["trdar"] = {
    "count": len(areas),
    "area_m2": {
        "min": int(min(ar)), "p25": int(st.quantiles(ar, n=4)[0]),
        "median": int(st.median(ar)), "p75": int(st.quantiles(ar, n=4)[2]),
        "p95": int(st.quantiles(ar, n=20)[18]), "max": int(max(ar)),
    },
    "equiv_radius_m": {
        "p25": radius(st.quantiles(ar, n=4)[0]), "median": radius(st.median(ar)),
        "p75": radius(st.quantiles(ar, n=4)[2]), "p95": radius(st.quantiles(ar, n=20)[18]),
    },
    "by_type": {t: {"n": len(v), "median_m2": int(st.median(v)),
                    "median_radius_m": radius(st.median(v))}
                for t, v in sorted(by_type.items(), key=lambda x: -len(x[1]))},
    "distinct_adstrd": len({a.get("ADSTRD_CD") for a in areas}),
    "distinct_signgu": len({a.get("SIGNGU_CD") for a in areas}),
    "coord_system": "EPSG:5181 (XCNTS_VALUE/YDNTS_VALUE)",
}

# ---- 2. industry codes: which ones are food service? -------------------
sample = fetch_all("VwsmTrdarStorQq", total=3000, step=1000)
induty = {}
for r in sample:
    induty[r["SVC_INDUTY_CD"]] = r["SVC_INDUTY_CD_NM"]
out["induty_sample"] = {"n_rows": len(sample), "n_codes": len(induty),
                        "codes": dict(sorted(induty.items()))}

# ---- 3. available quarters --------------------------------------------
q_stor = sorted({r["STDR_YYQU_CD"] for r in sample})
out["quarters_seen_in_sample"] = q_stor

save("p3_resolution", out)
print(json.dumps(out["trdar"], ensure_ascii=False, indent=2))
print("\nINDUSTRY CODES (%d):" % len(induty))
for k, v in sorted(induty.items()):
    print(" ", k, v)
print("\nQUARTERS in sample:", q_stor)
