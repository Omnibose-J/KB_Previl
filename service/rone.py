"""부동산원(R-ONE) 참고값 조회 — 표기 전용.

여기서 나오는 값은 점수·등급·추천 순위 어디에도 들어가지 않는다. 공간단위가
시도(권리금)와 부동산원 상권(임대료·공실률)이라 100m 격자에 붙일 근거가 없다.
그래서 격자와 조인하지 않고, 사용자가 이미 아는 자기 숫자를 대볼 **기준선**으로만
쓴다 — 방향이 반대라 해상도 문제가 생기지 않는다.

`rone_ref` 는 선택 수집분이라 없을 수 있다. 없으면 전부 None 을 내고 호출부가
필드를 NULL 로 낸다. 서울 평균으로 메우거나 0 을 넣지 않는다 — 참고값이 없는
것과 참고값이 0 인 것은 다른 사실이다.

키는 snake_case 로 낸다. 응답 모델(`ApiModel`)이 to_camel 로 바꾼다.
"""
import sqlite3

from service import api

GOODWILL_INDUSTRY = "숙박 및 음식점업"
GOODWILL_ITEMS = {
    "권리금 수준_중위수": "median",
    "권리금 수준_평균": "mean",
    "권리금 수준_㎡당 평균": "per_m2",
    "권리금 유 비율": "has_goodwill_rate",
}
# 부동산원이 층별로 조사하는 것은 이 셋뿐이다. 3층·지하2층은 원천에 없으므로
# 참고값도 없다 — 인접 층에서 끌어다 쓰지 않는다.
FLOOR_LABELS = {1: "1층", 2: "2층", -1: "지하1층"}
RENT_SOURCE = "한국부동산원 상업용부동산 임대동향조사"
GOODWILL_SOURCE = "한국부동산원 상가건물 임대차 실태조사"


def _rows(con, kind, item=None):
    """kind 의 행. 테이블 자체가 없으면 빈 목록 — 수집을 건너뛴 설치다."""
    sql = "SELECT region_nm, axis, item, unit, period, value FROM rone_ref WHERE kind = ?"
    args = [kind]
    if item is not None:
        sql += " AND item = ?"
        args.append(item)
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def market_anchor():
    """서울 음식점업 권리금 실태 — `/goodwill` 추정가를 대볼 외부 기준선."""
    with api.base.readonly_connection() as con:
        rows = [r for r in _rows(con, "goodwill")
                if r["axis"] == GOODWILL_INDUSTRY and r["region_nm"] == "서울"]
    values = {GOODWILL_ITEMS[r["item"]]: r["value"] for r in rows if r["item"] in GOODWILL_ITEMS}
    if len(values) != len(GOODWILL_ITEMS):
        return None
    return {**values, "region": "서울", "industry": GOODWILL_INDUSTRY,
            "period": rows[0]["period"], "source": GOODWILL_SOURCE}


def floor_reference(floor):
    """이 층의 1층 대비 임대료 비율. 계산에 쓰지 않고 표기만 한다 — 층으로 보이던
    차이가 면적으로 층화하면 사라진다는 것이 이 프로젝트의 실측 결론이다(F-A5)."""
    label = FLOOR_LABELS.get(floor)
    if label is None:
        return None
    with api.base.readonly_connection() as con:
        rows = [r for r in _rows(con, "floor_ratio") if r["region_nm"] == "서울"]
    ratio = next((r for r in rows if r["axis"] == label and r["item"] == "효용비율"), None)
    base = next((r for r in rows if r["axis"] == "1층" and r["item"] == "임대료"), None)
    if ratio is None or base is None:
        return None
    return {"floor": label, "utility_ratio": ratio["value"],
            "first_floor_rent": base["value"], "unit": base["unit"],
            "period": ratio["period"], "source": RENT_SOURCE}


def market_rent(monthly_rent=None, area_m2=None):
    """서울 소규모 상가 기준선 + 사용자 임대료가 주요 상권 분포에서 서는 위치.

    원천 단위는 천원/㎡·월이고 이 API 의 금액 단위는 만원이다(화면 «월 임대료
    예: 250»). 만원 = 10천원이므로 ㎡당 천원 = 임대료 × 10 / 면적.

    조사 상권은 부동산원이 고른 **주요 상권**이라 서울 대표 표본이 아니다 —
    골목 상권은 조사 대상이 아니므로 «주요 상권 대비»로만 읽어야 한다.
    """
    with api.base.readonly_connection() as con:
        rent = _rows(con, "rent", "임대료")
        vacancy = [r for r in _rows(con, "vacancy", "공실률") if r["region_nm"] == "서울"]
    if not rent:
        return None
    areas = sorted(r["value"] for r in rent if r["region_nm"].count(">") == 2)
    seoul = next((r for r in rent if r["region_nm"] == "서울"), None)
    if not areas or seoul is None:
        return None

    per_m2 = percentile = None
    if monthly_rent and area_m2 and monthly_rent > 0 and area_m2 > 0:
        per_m2 = monthly_rent * 10.0 / area_m2
        percentile = sum(1 for v in areas if v <= per_m2) / len(areas) * 100.0
    return {
        "user_per_m2": per_m2,
        "seoul_avg": seoul["value"],
        "vacancy": vacancy[0]["value"] if vacancy else None,
        "period": seoul["period"],
        "unit": seoul["unit"],
        "area_count": len(areas),
        "min": areas[0],
        "max": areas[-1],
        "percentile": percentile,
        "source": RENT_SOURCE,
    }
