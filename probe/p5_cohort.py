"""Probe: can we actually build a survival label?

The headline claim of the service ("this spot is risky") is only defensible if
we can compute, for restaurants that opened in year Y, what share were still
open N years later. That is a cohort calculation, not a ratio over closed rows -
those two get confused constantly and the second one is meaningless.

Also caches the raw sample so later probes don't re-spend API quota.
"""
import io
import json
import random
from collections import Counter, defaultdict

import requests

from common import RESULTS, key, save

S = key("SEOUL_OPEN_API_KEY")
BASE = "http://openapi.seoul.go.kr:8088"
SVC = "LOCALDATA_072404"
STEP = 1000
PAGES = 100          # ~100k rows
TODAY_Y, TODAY_M = 2026, 7

cache = RESULTS / "localdata_sample.jsonl"
rows = []
if cache.exists():
    for line in io.open(cache, encoding="utf-8"):
        rows.append(json.loads(line))
    print(f"loaded {len(rows)} cached rows")
else:
    r = requests.get(f"{BASE}/{S}/json/{SVC}/1/{STEP}/", timeout=60).json()[SVC]
    total = r["list_total_count"]
    rows.extend(r["row"])
    maxpage = total // STEP + 1
    random.seed(11)
    picks = sorted(random.sample(range(2, maxpage), min(PAGES - 1, maxpage - 2)))
    for i, p in enumerate(picks):
        st = (p - 1) * STEP + 1
        try:
            j = requests.get(f"{BASE}/{S}/json/{SVC}/{st}/{st + STEP - 1}/", timeout=60).json()
            rows.extend((j.get(SVC) or {}).get("row") or [])
        except Exception as e:
            print("page fail", p, type(e).__name__)
            break
        if i % 20 == 0:
            print(f"  {i}/{len(picks)} pages, {len(rows)} rows")
    with io.open(cache, "w", encoding="utf-8") as f:
        for r_ in rows:
            f.write(json.dumps(r_, ensure_ascii=False) + "\n")
    print(f"cached {len(rows)} rows")


def ym(s):
    """Dates arrive as '2001-05-23              ' - strip separators and padding."""
    s = "".join(ch for ch in str(s or "") if ch.isdigit())
    if len(s) < 6:
        return None
    return int(s[:4]), int(s[4:6])


def months_between(a, b):
    return (b[0] - a[0]) * 12 + (b[1] - a[1])


# ---- cohort survival ---------------------------------------------------
cohorts = defaultdict(lambda: {"n": 0, "closed_by": Counter()})
HORIZONS = [1, 2, 3, 5]

for r in rows:
    op = ym(r.get("APVPERMYMD"))
    if not op or op[0] < 2005:
        continue
    y = op[0]
    cohorts[y]["n"] += 1
    st = r.get("TRDSTATENM") or ""
    if "폐업" in st:
        cl = ym(r.get("DCBYMD"))
        if cl:
            m = months_between(op, cl)
            for h in HORIZONS:
                if 0 <= m <= h * 12:
                    cohorts[y]["closed_by"][h] += 1

table = {}
for y in sorted(cohorts):
    c = cohorts[y]
    row = {"opened": c["n"]}
    for h in HORIZONS:
        # a cohort is only observable if the horizon has fully elapsed
        row[f"survive_{h}y_pct"] = (
            round((1 - c["closed_by"][h] / c["n"]) * 100, 1)
            if c["n"] >= 30 and y + h <= TODAY_Y else None
        )
    table[y] = row

# ---- coordinate check --------------------------------------------------
with_xy = [r for r in rows if str(r.get("X") or "").strip()]
uptae = Counter(r.get("UPTAENM") for r in rows)

out = {
    "rows_analyzed": len(rows),
    "cohort_survival": table,
    "note_on_method": (
        "survive_Ny_pct = 1 - (closed within N years of permit) / (cohort size). "
        "Cohorts whose horizon has not fully elapsed are None. "
        "This is NOT the same as 'share of closed shops that lasted <N years'."
    ),
    "coords_pct": round(len(with_xy) / len(rows) * 100, 1),
    "uptae_distinct": len(uptae),
}
save("p5_cohort", out)

print("\n연도별 개업 코호트 생존율 (서울 일반음식점)")
print(f"{'개업연도':>8} {'개업수':>7} {'1년':>7} {'2년':>7} {'3년':>7} {'5년':>7}")
for y in sorted(table):
    r = table[y]
    if r["opened"] < 30:
        continue
    def f(v):
        return f"{v:>6.1f}%" if v is not None else "     -"
    print(f"{y:>8} {r['opened']:>7} {f(r['survive_1y_pct'])} {f(r['survive_2y_pct'])} "
          f"{f(r['survive_3y_pct'])} {f(r['survive_5y_pct'])}")
