"""Probe: Seoul restaurant licensing records (LOCALDATA mirrored by Seoul).

This is the failure-label source, so it gets the hardest look:
coordinate completeness, coordinate system, business-state distribution,
permit-date range, and whether open/close dates actually support survival labels.
"""
import json
import random
from collections import Counter

import requests

from common import key, save

S = key("SEOUL_OPEN_API_KEY")
BASE = "http://openapi.seoul.go.kr:8088"
SVC = "LOCALDATA_072404"   # 일반음식점

STEP = 1000
SAMPLE_PAGES = 40          # 40k records, spread across the table


def page(start):
    r = requests.get(f"{BASE}/{S}/json/{SVC}/{start}/{start + STEP - 1}/", timeout=60)
    j = r.json().get(SVC) or {}
    return j.get("list_total_count"), (j.get("row") or [])


total, first = page(1)
rows = list(first)

random.seed(7)
maxpage = (total // STEP) + 1
picks = sorted(random.sample(range(2, maxpage), min(SAMPLE_PAGES - 1, maxpage - 2)))
for p in picks:
    _, r = page((p - 1) * STEP + 1)
    rows.extend(r)

n = len(rows)


def nonempty(f):
    return sum(1 for r in rows if str(r.get(f) or "").strip())


state = Counter(r.get("TRDSTATENM") for r in rows)
uptae = Counter(r.get("UPTAENM") for r in rows)
permit_years = Counter((r.get("APVPERMYMD") or "")[:4] for r in rows if r.get("APVPERMYMD"))
close_years = Counter((r.get("DCBYMD") or "")[:4] for r in rows if str(r.get("DCBYMD") or "").strip())

xs = [float(r["X"]) for r in rows if str(r.get("X") or "").strip()]
ys = [float(r["Y"]) for r in rows if str(r.get("Y") or "").strip()]

# survival label feasibility: closed rows that have BOTH permit and close date
closed = [r for r in rows if r.get("TRDSTATENM") and "폐업" in r["TRDSTATENM"]]
closed_dated = [r for r in closed
                if str(r.get("APVPERMYMD") or "").strip() and str(r.get("DCBYMD") or "").strip()]
lifespans = []
for r in closed_dated:
    try:
        a, b = r["APVPERMYMD"][:8], r["DCBYMD"][:8]
        if len(a) == 8 and len(b) == 8 and b > a:
            y = (int(b[:4]) - int(a[:4])) + (int(b[4:6]) - int(a[4:6])) / 12
            if 0 < y < 60:
                lifespans.append(y)
    except Exception:
        pass
lifespans.sort()

out = {
    "service": SVC,
    "total_records": total,
    "sampled": n,
    "field_completeness_pct": {
        f: round(nonempty(f) / n * 100, 1)
        for f in ["X", "Y", "SITEWHLADDR", "RDNWHLADDR", "APVPERMYMD", "DCBYMD",
                  "UPTAENM", "SITEAREA", "BPLCNM", "MANEIPCNT"]
    },
    "business_state": dict(state.most_common()),
    "coord_range": {
        "x_min": round(min(xs)), "x_max": round(max(xs)),
        "y_min": round(min(ys)), "y_max": round(max(ys)),
        "n_with_coords": len(xs),
        "guess": "EPSG:2097 (TM 중부원점) if x~190k-220k / y~440k-470k",
    },
    "permit_year_range": {
        "min": min(permit_years), "max": max(permit_years),
        "recent": {y: permit_years[y] for y in sorted(permit_years)[-6:]},
        "oldest": {y: permit_years[y] for y in sorted(permit_years)[:3]},
    },
    "close_year_recent": {y: close_years[y] for y in sorted(close_years)[-6:]},
    "uptae_top20": dict(uptae.most_common(20)),
    "survival_label": {
        "closed_rows": len(closed),
        "closed_with_both_dates": len(closed_dated),
        "usable_lifespans": len(lifespans),
        "lifespan_years": {
            "p10": round(lifespans[int(len(lifespans) * .10)], 1),
            "p25": round(lifespans[int(len(lifespans) * .25)], 1),
            "median": round(lifespans[int(len(lifespans) * .50)], 1),
            "p75": round(lifespans[int(len(lifespans) * .75)], 1),
            "p90": round(lifespans[int(len(lifespans) * .90)], 1),
        } if lifespans else None,
        "pct_closed_under_3y": round(
            sum(1 for x in lifespans if x < 3) / len(lifespans) * 100, 1) if lifespans else None,
    },
}

save("p4_localdata", out)
print(json.dumps(out, ensure_ascii=False, indent=2))
