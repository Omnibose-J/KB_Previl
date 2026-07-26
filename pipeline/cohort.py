"""Cohort survival - the evidence the whole recommendation rests on.

Definition, fixed:
    survive_Ny = 1 - (opened in year Y and closed within N years of opening)
                     / (opened in year Y and already N years past opening)

The denominator is the *observable* part of the cohort, not the whole cohort.
A shop that opened in 2025-11 cannot yet have failed its 3-year test, so it
belongs in neither numerator nor denominator. Counting it as a survivor is the
standard way this number gets quietly inflated.

What this is NOT: "share of closed shops that lasted under N years". That
conditions on failure and is meaningless for prediction. Do not substitute it.
"""
import argparse
import json

from .config import COHORT_TOL_PP, ROOT
from .db import init

HORIZONS = (1, 2, 3, 5)


def as_of(con):
    """Observation cut-off, derived from the data rather than the wall clock."""
    r = con.execute(
        "SELECT MAX(open_y*12+open_m) FROM licence WHERE open_y IS NOT NULL").fetchone()[0]
    return (r // 12, r % 12 or 12)


def compute(con, exclude_succession=False, scope="seoul", scope_key="", where="", params=()):
    cut_y, cut_m = as_of(con)
    cut = cut_y * 12 + cut_m

    sql = ("SELECT open_y, open_m, close_y, close_m, is_closed, succession_suspect "
           "FROM licence WHERE open_y IS NOT NULL")
    if exclude_succession:
        sql += " AND succession_suspect=0"
    if where:
        sql += f" AND {where}"
    rows = con.execute(sql, params).fetchall()

    agg = {}
    for r in rows:
        y = r["open_y"]
        if y < 2005:
            continue
        om = y * 12 + (r["open_m"] or 1)
        a = agg.setdefault(y, {"opened": 0,
                               **{h: {"obs": 0, "closed": 0} for h in HORIZONS}})
        a["opened"] += 1
        cm = ((r["close_y"] * 12 + (r["close_m"] or 1))
              if r["is_closed"] and r["close_y"] else None)
        for h in HORIZONS:
            if om + h * 12 > cut:
                continue                      # horizon not elapsed -> not observable
            a[h]["obs"] += 1
            if cm is not None and cm - om <= h * 12:
                a[h]["closed"] += 1

    out = []
    for y in sorted(agg):
        a = agg[y]
        row = {"open_year": y, "opened": a["opened"]}
        for h in HORIZONS:
            o, c = a[h]["obs"], a[h]["closed"]
            row[f"survive_{h}y"] = round((1 - c / o) * 100, 1) if o >= 30 else None
            row[f"observable_{h}y"] = o
        out.append(row)

    con.execute("DELETE FROM cohort_survival WHERE scope=? AND scope_key=? "
                "AND succession_excluded=?", (scope, scope_key, int(exclude_succession)))
    con.executemany(
        "INSERT INTO cohort_survival(scope,scope_key,open_year,opened,"
        "survive_1y,observable_1y,survive_2y,observable_2y,"
        "survive_3y,observable_3y,survive_5y,observable_5y,succession_excluded)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(scope, scope_key, r["open_year"], r["opened"],
          r["survive_1y"], r["observable_1y"], r["survive_2y"], r["observable_2y"],
          r["survive_3y"], r["observable_3y"], r["survive_5y"], r["observable_5y"],
          int(exclude_succession)) for r in out])
    con.commit()
    return out, (cut_y, cut_m)


def show(rows, cut, title):
    print(f"\n{title}   (관측 기준일 {cut[0]}-{cut[1]:02d})")
    print(f"{'개업연도':>8} {'개업수':>7} {'1년':>16} {'2년':>16} {'3년':>16} {'5년':>16}")
    for r in rows:
        if r["opened"] < 30:
            continue
        cells = []
        for h in HORIZONS:
            v, o = r[f"survive_{h}y"], r[f"observable_{h}y"]
            cells.append(f"{v:>6.1f}% (n={o:>5})" if v is not None else f"{'-':>15}")
        print(f"{r['open_year']:>8} {r['opened']:>7} " + " ".join(cells))


def compare_probe(rows):
    """Guard: full-population result must agree with the 100k-sample probe."""
    p = ROOT / "probe" / "results" / "p5_cohort.json"
    if not p.exists():
        print("\n[compare] probe result absent - skipped")
        return True
    ref = json.load(open(p, encoding="utf-8"))["cohort_survival"]
    now = {r["open_year"]: r for r in rows}
    worst, bad = 0.0, []
    for ys, rr in ref.items():
        y = int(ys)
        a, b = rr.get("survive_3y_pct"), (now.get(y) or {}).get("survive_3y")
        if a is None or b is None:
            continue
        d = abs(a - b)
        worst = max(worst, d)
        if d > COHORT_TOL_PP:
            bad.append((y, a, b, round(d, 1)))
    ok = not bad
    print(f"\n[compare vs probe sample] 3년 생존율 최대 편차 {worst:.1f}%p "
          f"(허용 {COHORT_TOL_PP}%p) -> {'PASS' if ok else 'FAIL'}")
    for y, a, b, d in bad:
        print(f"  {y}: probe {a}% vs full {b}%  (편차 {d}%p)")
    return ok


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--split-succession", action="store_true")
    ap.add_argument("--by-uptae", help="e.g. 한식")
    a = ap.parse_args()
    con = init()

    rows, cut = compute(con)
    show(rows, cut, "연도별 개업 코호트 생존율 — 서울 일반음식점 (전량, 승계 포함)")
    ok = compare_probe(rows)

    if a.split_succession:
        r2, _ = compute(con, exclude_succession=True)
        show(r2, cut, "동일 — 양도양수 추정분 제외")
        n = con.execute("SELECT count(*) FROM licence WHERE succession_suspect=1").fetchone()[0]
        print(f"\n제외된 승계 추정 레코드: {n:,}건")

    if a.by_uptae:
        r3, _ = compute(con, scope="uptae", scope_key=a.by_uptae,
                        where="uptae=?", params=(a.by_uptae,))
        show(r3, cut, f"업태별 — {a.by_uptae}")

    raise SystemExit(0 if ok else 1)
