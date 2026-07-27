"""법정동 패널 — 실거래가 결과변수용 (Part F).

지명(행정동) 패널과 단위가 다르다. 실거래가 API 는 법정동(`umdNm`)으로
나오고, `licence.addr` 에서도 법정동이 99.9% 추출된다. **같은 단위라 매핑표
없이 직접 조인된다** — 행정동↔법정동 매핑은 N:M 이라 어느 쪽으로든 배분이
생기고, 배분은 이 프로젝트가 금지한 것이다.

변수 정의는 docs/unstructured-plan.md §F-3 에 실행 전 등록되어 있다.
"""
import re
import sqlite3
from collections import defaultdict

import numpy as np

from pipeline.config import DB_PATH

YEARS = [2017, 2018, 2019, 2020, 2021, 2022]     # §F-4
MIN_DEALS = 5          # 각 가격 구간(3년)당 최소 거래 건수
MIN_OPENS = 20         # 컨셉 구성 산출 최소 개업 건수
K = 40

# 행정표준코드 앞 5자리 ↔ 자치구명. licence.addr 는 구명 문자열이고
# realprice 는 코드라 둘을 잇는 데 필요하다.
SGG = {
    "11110": "종로구", "11140": "중구", "11170": "용산구", "11200": "성동구",
    "11215": "광진구", "11230": "동대문구", "11260": "중랑구", "11290": "성북구",
    "11305": "강북구", "11320": "도봉구", "11350": "노원구", "11380": "은평구",
    "11410": "서대문구", "11440": "마포구", "11470": "양천구", "11500": "강서구",
    "11530": "구로구", "11545": "금천구", "11560": "영등포구", "11590": "동작구",
    "11620": "관악구", "11650": "서초구", "11680": "강남구", "11710": "송파구",
    "11740": "강동구",
}

ADDR = re.compile(r"서울특별시\s+(\S+구)\s+(\S+?[동가])(?:\s|$)")


def _ym(y, m):
    return y * 12 + (m or 6)


# 요식업이 들어가는 건물 용도. §F-5-4 는 "전체 용도를 쓰고 잔여 교란은 한계로
# 기록"으로 등록했으므로 기본값은 필터 없음(None)이다. 이 필터를 켠 결과는
# **사후 추가**이며 탐색으로만 표기한다 — 사전 등록된 D2 의 판정은 바뀌지 않는다.
FOOD_USE = ("제1종근린생활", "제2종근린생활")


def build(con=None, uses=None):
    own = con is None
    if own:
        con = sqlite3.connect(DB_PATH)

    # --- 점포: 주소에서 법정동 파싱 + 컨셉
    shops = defaultdict(list)          # (구,동) -> [(open_ym, close_ym|None, concept)]
    miss = 0
    for addr, oy, om, cy, cm, closed, cpt in con.execute(
            "SELECT l.addr, l.open_y, l.open_m, l.close_y, l.close_m, l.is_closed, "
            "       c.concept "
            "FROM licence l LEFT JOIN shop_concept c ON c.mgtno = l.mgtno "
            "WHERE l.addr IS NOT NULL AND l.open_y IS NOT NULL"):
        m = ADDR.search(addr + " ")
        if not m:
            miss += 1
            continue
        key = (m.group(1), m.group(2))
        o = _ym(oy, om)
        c = _ym(cy, cm) if (closed == 1 and cy) else None
        shops[key].append((o, c, cpt))

    # --- 실거래: ㎡당 단가
    deals = defaultdict(list)          # (구,동) -> [(deal_ym, 만원/㎡)]
    q = ("SELECT sgg_cd, umd_nm, deal_ym, amount, area, bldg_use FROM realprice "
         "WHERE amount IS NOT NULL AND area IS NOT NULL AND area > 0")
    for sgg_cd, umd, dym, amt, area, use in con.execute(q):
        if uses and (use or "").strip() not in uses:
            continue
        gu = SGG.get(sgg_cd)
        if not gu or not umd:
            continue
        deals[(gu, umd.strip())].append((dym, amt / area))

    if own:
        con.close()

    def med_price(key, lo, hi):
        """[lo, hi) 구간 거래의 ㎡당 단가 중앙값. 건수 미달이면 None.

        중앙값을 쓰는 이유는 §F-3 — 대형 빌딩 한 건이 평균을 지배하고,
        중앙값은 사후에 절사 기준을 고르는 자유도도 없앤다.
        """
        v = [p for t, p in deals.get(key, ()) if lo <= t < hi]
        return (float(np.median(v)), len(v)) if len(v) >= MIN_DEALS else (None, len(v))

    panel = []
    for key, lst in shops.items():
        for t in YEARS:
            t0 = _ym(t, 1)
            operating = sum(1 for o, c, _ in lst if o < t0 and (c is None or c >= t0))
            if operating < 50:
                continue

            p_now, n_now_d = med_price(key, _ym(t - 3, 1), t0)
            p_prev, _ = med_price(key, _ym(t - 6, 1), _ym(t - 3, 1))
            p_next, n_next_d = med_price(key, _ym(t + 1, 1), _ym(t + 4, 1))
            if not (p_now and p_prev and p_next):
                continue

            base3 = _ym(t - 3, 1)
            op3 = sum(1 for o, c, _ in lst if base3 <= o < t0)
            operating3 = sum(1 for o, c, _ in lst
                             if o < base3 and (c is None or c >= base3))
            if not operating3:
                continue

            def shares(lo, hi):
                cnt = np.zeros(K)
                n = 0
                for o, _c, cpt in lst:
                    if lo <= o < hi and cpt is not None:
                        cnt[cpt] += 1
                        n += 1
                return (cnt / n if n else None), n

            s_now, k_now = shares(base3, t0)
            s_prev, k_prev = shares(_ym(t - 6, 1), base3)
            if k_now < MIN_OPENS or k_prev < MIN_OPENS:
                continue

            panel.append({
                "dong": f"{key[0]} {key[1]}", "year": t,
                "operating": operating,
                "size": float(np.log(operating)),
                "past_inflow": op3 / operating3,
                "price_now": p_now, "price_prev": p_prev, "price_next": p_next,
                "past_price_growth": float(np.log(p_now / p_prev)),
                "price_growth_next": float(np.log(p_next / p_now)),
                "deals_now": n_now_d, "deals_next": n_next_d,
                "share_now": s_now, "share_prev": s_prev,
            })

    return panel, miss


def summary(panel, miss):
    print(f"패널 {len(panel):,}행 · 법정동 {len({r['dong'] for r in panel})} "
          f"· 연도 {sorted({r['year'] for r in panel})}")
    print(f"주소 파싱 실패 {miss:,}건")
    if not panel:
        return
    g = np.array([r["price_growth_next"] for r in panel])
    print(f"결과변수 log(price_next/price_now): 평균 {g.mean():+.4f} · "
          f"중앙값 {np.median(g):+.4f} · SD {g.std():.4f}")
    d = np.array([r["deals_now"] for r in panel])
    print(f"구간당 거래 건수: 중앙값 {np.median(d):.0f} · 최소 {d.min():.0f}")


if __name__ == "__main__":
    import sys
    uses = FOOD_USE if "--food-use" in sys.argv else None
    if uses:
        print(f"[사후 필터] 건물 용도 {uses} 만 사용 — 탐색용이다")
    summary(*build(uses=uses))
