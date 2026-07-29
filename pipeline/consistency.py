"""Logical consistency checks - does the data mean what we claim it means?

verify.py answers "did it load". This answers "is it coherent". The distinction
matters because every failure mode that actually threatens this project is a
silent semantic one: a survival curve that goes the wrong way, coordinates that
land in the wrong district, a succession filter that makes failure look worse
instead of better.

Each check is an invariant that must hold for *any* correct load, derived from
the meaning of the fields rather than from a remembered number.
"""
import argparse
import json
import sys
from collections import Counter

from .db import connect_ro

CHECKS = {}


def check(name, desc):
    def deco(fn):
        fn.desc = desc
        CHECKS[name] = fn
        return fn
    return deco


# ---------------------------------------------------------------- cohort
@check("monotone", "생존율은 기간이 길수록 낮아져야 한다")
def c_monotone(con):
    """survive_1y >= survive_2y >= survive_3y >= survive_5y, always.

    A shop that failed within 2 years also failed within 3, so the curve can
    only descend. An ascent means the horizon filter or the denominator is wrong.
    """
    bad = []
    for r in con.execute(
            "SELECT open_year,survive_1y,survive_2y,survive_3y,survive_5y "
            "FROM cohort_survival WHERE scope='seoul' AND succession_excluded=0 "
            "ORDER BY open_year"):
        vals = [(h, r[f"survive_{h}y"]) for h in (1, 2, 3, 5) if r[f"survive_{h}y"] is not None]
        for (h1, v1), (h2, v2) in zip(vals, vals[1:]):
            if v1 < v2 - 1e-9:
                bad.append((r["open_year"], h1, v1, h2, v2))
    print(f"  코호트 검사 대상: {con.execute(chr(39).join(['SELECT count(*) FROM cohort_survival WHERE scope=', 'seoul', ' AND succession_excluded=0'])).fetchone()[0]}개 연도")
    for y, h1, v1, h2, v2 in bad[:5]:
        print(f"  위반 {y}: {h1}년 {v1}% < {h2}년 {v2}%")
    return not bad


@check("observable", "관측 가능 표본은 기간이 길수록 줄어야 한다")
def c_observable(con):
    """A longer horizon can only be elapsed for fewer shops, never more."""
    bad = []
    for r in con.execute(
            "SELECT open_year,observable_1y,observable_2y,observable_3y,observable_5y "
            "FROM cohort_survival WHERE scope='seoul' AND succession_excluded=0"):
        v = [r[f"observable_{h}y"] for h in (1, 2, 3, 5)]
        for a, b in zip(v, v[1:]):
            if a < b:
                bad.append((r["open_year"], v))
                break
    for y, v in bad[:5]:
        print(f"  위반 {y}: observable={v}")
    return not bad


@check("censoring", "최근 코호트는 관측 표본이 개업수보다 작아야 한다")
def c_censoring(con):
    """Right-censoring must actually bite. If the most recent cohort's 3y
    observable equals its size, the horizon filter is not running and the
    survival rate is inflated - the single most likely way this number lies.
    """
    r = con.execute(
        "SELECT open_year,opened,observable_3y FROM cohort_survival "
        "WHERE scope='seoul' AND succession_excluded=0 ORDER BY open_year DESC LIMIT 1"
    ).fetchone()
    if not r:
        print("  코호트 없음")
        return False
    print(f"  최신 코호트 {r['open_year']}: 개업 {r['opened']:,}, 3년 관측가능 {r['observable_3y']:,}")
    ok = r["observable_3y"] < r["opened"]
    print(f"  우편절단 작동: {ok}")
    return ok


@check("succession", "승계 제외 시 생존율은 올라가야 한다")
def c_succession(con):
    """Excluding handovers removes closures that were not failures, so the
    survival rate must rise (or stay equal), never fall.
    """
    rows = con.execute(
        "SELECT a.open_year, a.survive_3y inc, b.survive_3y exc "
        "FROM cohort_survival a JOIN cohort_survival b "
        "  ON a.open_year=b.open_year AND a.scope=b.scope "
        "WHERE a.scope='seoul' AND a.succession_excluded=0 AND b.succession_excluded=1 "
        "  AND a.survive_3y IS NOT NULL AND b.survive_3y IS NOT NULL").fetchall()
    bad = [(r["open_year"], r["inc"], r["exc"]) for r in rows if r["exc"] < r["inc"] - 1e-9]
    if rows:
        d = sum(r["exc"] - r["inc"] for r in rows) / len(rows)
        print(f"  비교 연도 {len(rows)}개, 3년 생존율 평균 변화 {d:+.2f}%p")
    for y, i, e in bad[:5]:
        print(f"  위반 {y}: 포함 {i}% -> 제외 {e}% (내려감)")
    return bool(rows) and not bad


@check("dates", "개업일이 폐업일보다 늦을 수 없다")
def c_dates(con):
    bad = con.execute(
        "SELECT count(*) FROM licence WHERE close_y IS NOT NULL AND open_y IS NOT NULL "
        "AND (close_y*12+COALESCE(close_m,1)) < (open_y*12+COALESCE(open_m,1))"
    ).fetchone()[0]
    tot = con.execute("SELECT count(*) FROM licence WHERE close_y IS NOT NULL").fetchone()[0]
    print(f"  폐업일 < 개업일 : {bad:,} / {tot:,}")
    # a handful of clerical errors is expected in 40 years of municipal records
    return bad / max(1, tot) < 0.01


@check("state", "영업상태와 폐업일 존재가 일치해야 한다")
def c_state(con):
    open_with_close = con.execute(
        "SELECT count(*) FROM licence WHERE is_closed=0 AND close_y IS NOT NULL").fetchone()[0]
    closed_no_close = con.execute(
        "SELECT count(*) FROM licence WHERE is_closed=1 AND close_y IS NULL").fetchone()[0]
    closed = con.execute("SELECT count(*) FROM licence WHERE is_closed=1").fetchone()[0]
    print(f"  영업중인데 폐업일 있음 : {open_with_close:,}")
    print(f"  폐업인데 폐업일 없음   : {closed_no_close:,} / {closed:,} "
          f"({closed_no_close/max(1,closed)*100:.1f}%)")
    # closures missing a date are excluded from cohorts, so they must be rare
    return open_with_close == 0 and closed_no_close / max(1, closed) < 0.05


# ---------------------------------------------------------------- spatial
@check("district", "변환 좌표를 역지오코딩한 자치구가 원본 주소와 같아야 한다")
def c_district(con, sample=200):
    """The one check that can catch a wrong CRS.

    EPSG:2097 (Bessel) and EPSG:5174/5181 (GRS80) share an origin and differ by
    only a few hundred metres, so picking the wrong one still yields points that
    sit plausibly inside Seoul - every internal check passes while every location
    is quietly displaced. Kakao's reverse geocoder is an independent witness:
    transform our stored lon/lat back to an address and compare the 구 against
    the address the row came with.
    """
    import io as _io
    import random

    import requests

    from .config import ENV_PATH, ROOT
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    kk = env.get("KAKAO_REST_API_KEY")
    if not kk:
        print("  KAKAO_REST_API_KEY 없음 - 외부 검증 불가")
        return None

    rows = con.execute(
        "SELECT addr, lon, lat FROM licence "
        "WHERE lon IS NOT NULL AND addr LIKE '서울%'").fetchall()
    random.seed(3)
    picks = random.sample(rows, min(sample, len(rows)))

    match = mismatch = skipped = 0
    bad = []
    for r in picks:
        gu = next((p for p in r["addr"].split() if p.endswith("구")), None)
        if not gu:
            skipped += 1
            continue
        try:
            resp = requests.get(
                "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
                headers={"Authorization": f"KakaoAK {kk}"},
                params={"x": r["lon"], "y": r["lat"]}, timeout=15).json()
            docs = resp.get("documents") or []
        except Exception:
            skipped += 1
            continue
        if not docs:
            skipped += 1
            continue
        got = docs[0].get("region_2depth_name") or ""
        if got.strip() == gu:
            match += 1
        else:
            mismatch += 1
            if len(bad) < 5:
                bad.append((r["addr"][:34], got))

    tested = match + mismatch
    pct = match / tested * 100 if tested else 0
    print(f"  역지오코딩 표본 {tested}건 (건너뜀 {skipped})")
    print(f"  자치구 일치 {match} / 불일치 {mismatch}  ({pct:.1f}%)")
    for a, g in bad:
        print(f"    불일치: '{a}' -> 역지오코딩 '{g}'")
    # a wrong CRS displaces everything and would score far below this;
    # boundary-straddling addresses account for the small residual
    return tested >= 50 and pct >= 97.0


@check("gridflag", "has_sales_data 플래그와 상권코드 존재가 일치해야 한다")
def c_gridflag(con):
    a = con.execute("SELECT count(*) FROM grid WHERE has_sales_data=1 AND trdar_cd IS NULL").fetchone()[0]
    b = con.execute("SELECT count(*) FROM grid WHERE has_sales_data=0 AND trdar_cd IS NOT NULL").fetchone()[0]
    print(f"  플래그1인데 상권코드 없음 : {a}")
    print(f"  플래그0인데 상권코드 있음 : {b}")
    return a == 0 and b == 0


@check("gridxy", "격자 중심좌표가 서울 범위 안이어야 한다")
def c_gridxy(con):
    from .config import SEOUL_BBOX
    lo_min, la_min, lo_max, la_max = SEOUL_BBOX
    bad = con.execute(
        "SELECT count(*) FROM grid_feature WHERE center_lon NOT BETWEEN ? AND ? "
        "OR center_lat NOT BETWEEN ? AND ?", (lo_min, lo_max, la_min, la_max)).fetchone()[0]
    tot = con.execute("SELECT count(*) FROM grid_feature").fetchone()[0]
    print(f"  서울 bbox 밖 격자: {bad:,} / {tot:,}")
    return bad == 0


# ---------------------------------------------------------------- volume
@check("competition", "격자 경쟁 점포 합계가 원천 점포수와 같은 자릿수여야 한다")
def c_competition(con):
    """Independent count of the same thing: our per-cell tally of operating
    restaurants vs the raw licensing table. They should agree exactly for the
    gridded subset - a gap means cells are double-counted or dropped.
    """
    cell_sum = con.execute("SELECT SUM(food_store_cnt) FROM grid_feature").fetchone()[0] or 0
    src = con.execute(
        "SELECT count(*) FROM licence WHERE is_closed=0 AND grid_id IS NOT NULL").fetchone()[0]
    print(f"  격자 합계 {cell_sum:,}  vs  원천 영업중+좌표보유 {src:,}")
    return cell_sum == src


@check("history", "격자 개업/폐업 이력 합계가 원천과 같아야 한다")
def c_history(con):
    o = con.execute("SELECT SUM(hist_open_cnt) FROM grid_feature").fetchone()[0] or 0
    c = con.execute("SELECT SUM(hist_close_cnt) FROM grid_feature").fetchone()[0] or 0
    so = con.execute("SELECT count(*) FROM licence WHERE grid_id IS NOT NULL").fetchone()[0]
    sc = con.execute(
        "SELECT count(*) FROM licence WHERE grid_id IS NOT NULL AND is_closed=1").fetchone()[0]
    print(f"  개업 격자합 {o:,} vs 원천 {so:,}")
    print(f"  폐업 격자합 {c:,} vs 원천 {sc:,}")
    return o == so and c == sc


@check("salesstore", "매출이 있는 상권은 점포도 있어야 한다")
def c_salesstore(con):
    orphan = con.execute(
        "SELECT count(DISTINCT s.trdar_cd) FROM trdar_sales s "
        "LEFT JOIN trdar_store t ON s.trdar_cd=t.trdar_cd AND s.induty_cd=t.induty_cd "
        "AND s.quarter=t.quarter WHERE t.trdar_cd IS NULL AND s.sales_amt>0").fetchone()[0]
    tot = con.execute("SELECT count(DISTINCT trdar_cd) FROM trdar_sales").fetchone()[0]
    print(f"  매출은 있는데 점포 레코드 없는 상권: {orphan} / {tot}")
    return orphan == 0


@check("area", "음식점 시설면적이 상식적 범위여야 한다")
def c_area(con):
    r = con.execute(
        "SELECT count(*) n, SUM(site_area<=0) z, SUM(site_area>5000) big, "
        "MIN(site_area) mn, MAX(site_area) mx FROM licence WHERE site_area IS NOT NULL"
    ).fetchone()
    med = con.execute(
        "SELECT site_area FROM licence WHERE site_area>0 ORDER BY site_area "
        "LIMIT 1 OFFSET (SELECT count(*)/2 FROM licence WHERE site_area>0)").fetchone()[0]
    print(f"  면적 보유 {r['n']:,}건  중앙값 {med:.1f}㎡  범위 {r['mn']:.1f}~{r['mx']:.1f}")
    print(f"  0 이하 {r['z']:,}  5000㎡ 초과 {r['big']:,}")
    return 10 <= med <= 200 and (r["big"] or 0) / max(1, r["n"]) < 0.01


@check("lvpop", "생활인구 주간/야간 값이 모두 존재하고 양수여야 한다")
def c_lvpop(con):
    n = con.execute("SELECT count(*) FROM grid_feature WHERE lvpop_day IS NOT NULL").fetchone()[0]
    tot = con.execute("SELECT count(*) FROM grid_feature").fetchone()[0]
    neg = con.execute(
        "SELECT count(*) FROM grid_feature WHERE lvpop_day<=0 OR lvpop_night<=0").fetchone()[0]
    dongs = con.execute("SELECT count(DISTINCT adstrd_cd) FROM lvpop_profile").fetchone()[0]
    tz = con.execute("SELECT count(DISTINCT tmzon) FROM lvpop_profile").fetchone()[0]
    print(f"  생활인구 보유 격자 {n:,}/{tot:,}  |  원천 {dongs}개 행정동 x {tz}개 시간대")
    print(f"  0 이하 값: {neg}")
    return neg == 0 and tz == 24 and n > 0


@check("nullnotzero", "매출 없는 격자는 NULL이며 0이 아니어야 한다")
def c_nullnotzero(con):
    bad = con.execute(
        "SELECT count(*) FROM grid_feature WHERE has_sales_data=0 AND "
        "(sales_amt IS NOT NULL OR flpop IS NOT NULL)").fetchone()[0]
    have = con.execute(
        "SELECT count(*) FROM grid_feature WHERE sales_amt IS NOT NULL").fetchone()[0]
    tot = con.execute("SELECT count(*) FROM grid_feature").fetchone()[0]
    print(f"  매출값 보유 격자 {have:,}/{tot:,} ({have/tot*100:.1f}%)")
    print(f"  플래그0인데 값 있음: {bad}")
    return bad == 0


@check("dongaccuracy", "격자 행정동이 역지오코딩 결과와 일치해야 한다")
def c_dongaccuracy(con, sample=200):
    """Independent re-check of the dong assignment.

    The earlier commercial-area-derived mapping scored 75.5% here, which is why
    the pipeline switched to reverse geocoding. This check exists so a silent
    regression back to a proximity heuristic is caught immediately.
    """
    import io as _io
    import random

    import requests

    from .config import ENV_PATH, ROOT
    env = {}
    for line in ENV_PATH.open(encoding="utf-8-sig"):
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip()
    kk = env.get("KAKAO_REST_API_KEY")
    if not kk:
        print("  KAKAO_REST_API_KEY 없음")
        return None

    rows = con.execute(
        "SELECT grid_id,center_lon,center_lat,adstrd_cd FROM grid_feature "
        "WHERE adstrd_cd IS NOT NULL").fetchall()
    if not rows:
        print("  표본 없음")
        return False
    random.seed(4)
    ok = miss = err = 0
    bad = []
    for r in random.sample(rows, min(sample, len(rows))):
        try:
            docs = requests.get(
                "https://dapi.kakao.com/v2/local/geo/coord2regioncode.json",
                headers={"Authorization": f"KakaoAK {kk}"},
                params={"x": r["center_lon"], "y": r["center_lat"]}, timeout=15
            ).json().get("documents") or []
        except Exception:
            err += 1
            continue
        h = [d for d in docs if d.get("region_type") == "H"]
        if not h:
            err += 1
            continue
        if (h[0].get("code") or "")[:8] == r["adstrd_cd"]:
            ok += 1
        else:
            miss += 1
            if len(bad) < 3:
                bad.append((r["grid_id"], r["adstrd_cd"],
                            h[0].get("code", "")[:8], h[0].get("region_3depth_name")))
    t = ok + miss
    pct = ok / t * 100 if t else 0
    print(f"  표본 {t}건 일치 {ok} / 불일치 {miss}  ({pct:.1f}%)   실패 {err}")
    for g, a_, b, n in bad:
        print(f"    {g}: 저장={a_} 실제={b}({n})")
    return t >= 50 and pct >= 99.0


@check("crosssource", "인허가 점포 밀도와 소상공인 점포 밀도가 상관해야 한다")
def c_crosssource(con):
    """Two independently produced datasets describing the same reality.

    LOCALDATA (municipal licensing) and SEMAS (NTS/card-derived store registry)
    are built by different agencies from different sources. If our grid assignment
    were wrong - bad CRS, off-by-one cell - the two would decorrelate. Agreement
    per cell is evidence the spatial join is sound, in a way no internal check is.
    """
    rows = con.execute(
        "SELECT f.grid_id, f.food_store_cnt a, "
        "  (SELECT count(*) FROM store s WHERE s.grid_id=f.grid_id) b "
        "FROM grid_feature f").fetchall()
    pairs = [(r["a"], r["b"]) for r in rows]
    if not pairs:
        print("  데이터 없음")
        return False
    n = len(pairs)
    ma = sum(a for a, _ in pairs) / n
    mb = sum(b for _, b in pairs) / n
    num = sum((a - ma) * (b - mb) for a, b in pairs)
    da = sum((a - ma) ** 2 for a, _ in pairs) ** .5
    db = sum((b - mb) ** 2 for _, b in pairs) ** .5
    r = num / (da * db) if da and db else 0
    both0 = sum(1 for a, b in pairs if a == 0 and b == 0)
    onlya = sum(1 for a, b in pairs if a > 0 and b == 0)
    onlyb = sum(1 for a, b in pairs if a == 0 and b > 0)
    print(f"  격자 {n:,}개 · 피어슨 상관 r={r:.3f}")
    print(f"  둘 다 0: {both0:,} · 인허가만: {onlya:,} · 소상공인만: {onlyb:,}")
    print(f"  (총계 인허가 {sum(a for a,_ in pairs):,} vs 소상공인 {sum(b for _,b in pairs):,} "
          f"— 소상공인은 카페·주점 포함이라 더 큼)")
    return r >= 0.70


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("checks", nargs="*")
    a = ap.parse_args()
    names = a.checks or list(CHECKS)
    con = connect_ro()
    res = {}
    for nm in names:
        fn = CHECKS.get(nm)
        if not fn:
            print(f"unknown check: {nm}")
            return 2
        print(f"\n[{nm}] {fn.desc}")
        try:
            r = fn(con)
        except Exception as e:
            print(f"  ERROR {type(e).__name__}: {e}")
            r = False
        res[nm] = r
        print(f"  -> {'SKIP' if r is None else ('PASS' if r else 'FAIL')}")
    bad = [k for k, v in res.items() if v is False]
    skip = [k for k, v in res.items() if v is None]
    print("\n" + "=" * 56)
    print(f"{sum(1 for v in res.values() if v is True)}/{len(res)-len(skip)} PASS"
          + (f"  SKIP: {skip}" if skip else "") + (f"  FAILED: {bad}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
