"""한국부동산원(R-ONE) 참고 통계 수집 — 표기 전용.

이 단계는 `pipeline.bootstrap --gates` 의 18단계에 들어가지 않는다. 콜드스타트
계약과 리허설 증거가 이미 서 있는 곳이라 단계를 늘리면 그 증거가 무효가 되고,
R-ONE 은 점수·등급·추천 어디에도 기여하지 않아 없어도 제품이 성립한다.
`RONE_API_KEY` 가 없거나 이 단계를 건너뛰면 `rone_ref` 가 비고, 서빙은 해당
필드를 NULL 로 낸다 — 합성값으로 메우지 않는다.

원천이 2024년 3분기에 통계표 ID 를 갈아서(`A_2024_*` → `T*`) 같은 지표가 두
계보로 나뉜다. 참고 표기는 최신 스냅샷만 필요하므로 신규 계보만 읽고, 옛 계보를
이어 붙이지 않는다 — 조사 설계가 바뀐 지점이라 시계열로 이으면 거짓이 된다.

지역축이 통계표마다 GRP 또는 CLS 로 갈리므로 표별로 어느 축이 지역인지 못박는다.
"""
import argparse
import io
import json
import urllib.parse
import urllib.request

from .config import CACHE_DIR, load_env
from .db import init

BASE = "https://www.reb.or.kr/r-one/openapi/SttsApiTblData.do"
PAGE = 1000
MAX_PAGES = 20
TIMEOUT = 60

# kind -> (통계표 ID, 주기, 지역축, 2차축)  2차축 None = 그 표에는 없다
SOURCES = {
    "goodwill": ("A_2024_00445", "YY", "GRP", "CLS"),
    "floor_ratio": ("T246233134891629", "QY", "GRP", "CLS"),
    "rent": ("T248223134698125", "QY", "CLS", None),
    "vacancy": ("T241833134686576", "QY", "CLS", None),
}
# 권리금만 전국 대조를 남긴다 — 서울 프리미엄이 서사의 일부다. 나머지는 서울만.
REGIONS = {"goodwill": ("서울", "전국")}
DEFAULT_REGIONS = ("서울",)
SEOUL_AREA_MIN = 50      # 부동산원이 서울에서 조사하는 주요 상권 수의 하한


def _fetch(statbl_id, cycle):
    """통계표 전체 행. 네트워크·JSON 실패는 호출자로 올린다(조용히 넘기지 않는다)."""
    rows = []
    for page in range(1, MAX_PAGES + 1):
        url = BASE + "?" + urllib.parse.urlencode({
            "KEY": _key(), "Type": "json", "STATBL_ID": statbl_id,
            "DTACYCLE_CD": cycle, "pIndex": page, "pSize": PAGE,
        })
        req = urllib.request.Request(url, headers={"User-Agent": "kb-previl/1.0"})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if "SttsApiTblData" not in body:
            code = (body.get("RESULT") or {}).get("CODE")
            raise RuntimeError(f"R-ONE {statbl_id} 응답에 데이터가 없다 (CODE={code})")
        got = next((b["row"] for b in body["SttsApiTblData"] if "row" in b), [])
        rows.extend(got)
        if len(got) < PAGE:
            break
    return rows


def _key():
    key = (load_env().get("RONE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("RONE_API_KEY 가 .env 에 없다 — reb.or.kr/r-one 에서 발급")
    return key


def _cached(kind, statbl_id, cycle):
    cache = CACHE_DIR / f"rone_{kind}.json"
    if cache.exists():
        rows = json.load(io.open(cache, encoding="utf-8"))
        print(f"  [cache] {kind}: {len(rows):,} rows")
        return rows
    rows = _fetch(statbl_id, cycle)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    json.dump(rows, io.open(cache, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"  [api]   {kind}: {len(rows):,} rows")
    return rows


def _select(rows, kind, region_axis, sub_axis):
    """최신 기간 × 대상 지역의 행만. 값이 결측인 행은 버린다(0 으로 채우지 않는다)."""
    if not rows:
        return []
    latest = max(r["WRTTIME_IDTFR_ID"] for r in rows)
    prefixes = REGIONS.get(kind, DEFAULT_REGIONS)
    region_nm, region_cd = f"{region_axis}_FULLNM", f"{region_axis}_ID"
    out = []
    for r in rows:
        if r["WRTTIME_IDTFR_ID"] != latest or r["DTA_VAL"] is None:
            continue
        name = str(r.get(region_nm) or "")
        if not any(name == p or name.startswith(p + ">") for p in prefixes):
            continue
        out.append((
            kind, str(r[region_cd]), name,
            str(r[f"{sub_axis}_FULLNM"]).strip() if sub_axis else "",
            r["ITM_NM"], r["UI_NM"], latest, float(r["DTA_VAL"]),
        ))
    return out


def collect():
    con = init()
    total = 0
    try:
        for kind, (statbl_id, cycle, region_axis, sub_axis) in SOURCES.items():
            picked = _select(_cached(kind, statbl_id, cycle), kind, region_axis, sub_axis)
            if not picked:
                raise RuntimeError(f"R-ONE {kind}: 최신 기간에 서울 행이 없다")
            con.execute("DELETE FROM rone_ref WHERE kind = ?", (kind,))
            con.executemany(
                "INSERT OR REPLACE INTO rone_ref "
                "(kind, region_cd, region_nm, axis, item, unit, period, value) "
                "VALUES (?,?,?,?,?,?,?,?)", picked)
            print(f"  {kind}: {len(picked):,} rows @ {picked[0][6]}")
            total += len(picked)
        con.commit()
    finally:
        con.close()
    print(f"rone_ref: {total:,} rows")
    return total


def verify():
    """적재가 쓸 만한지 — 상권 수 하한과 서울 평균이 분포 안에 드는지."""
    con = init()
    try:
        rows = con.execute(
            "SELECT region_nm, value FROM rone_ref WHERE kind='rent' AND item='임대료'"
        ).fetchall()
        areas = [r["value"] for r in rows if r["region_nm"].count(">") == 2]
        seoul = [r["value"] for r in rows if r["region_nm"] == "서울"]
        kinds = {r[0] for r in con.execute("SELECT DISTINCT kind FROM rone_ref")}
    finally:
        con.close()

    checks = [
        ("kinds", kinds == set(SOURCES), f"{sorted(kinds)}"),
        ("areacount", len(areas) >= SEOUL_AREA_MIN, f"{len(areas)} (>= {SEOUL_AREA_MIN})"),
        ("seoulinrange", bool(seoul) and min(areas or [0]) <= seoul[0] <= max(areas or [0]),
         f"{seoul[0] if seoul else None} in [{min(areas):.1f}, {max(areas):.1f}]"
         if areas else "no areas"),
    ]
    ok = True
    for name, passed, detail in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        ok &= passed
    return ok


def main():
    ap = argparse.ArgumentParser(description="R-ONE 참고 통계 수집 (표기 전용)")
    ap.add_argument("--verify", action="store_true", help="수집 없이 적재분만 검사")
    args = ap.parse_args()
    if args.verify:
        raise SystemExit(0 if verify() else 1)
    collect()
    raise SystemExit(0 if verify() else 1)


if __name__ == "__main__":
    main()
