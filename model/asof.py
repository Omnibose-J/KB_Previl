"""Reconstruct what a grid cell looked like at a past point in time.

This module exists to make one guarantee: a feature computed for month T uses
only facts observable at T. The licensing table carries an open date and a close
date per shop, which is enough to replay the state of any cell at any month -
"operating at T" is `open <= T and (close is null or close > T)`.

Why this matters more than the model: if today's shop count leaks into a 2019
feature row, the model learns from the future and every downstream number - AUC,
weights, the whole "we can validate our recommendation" claim - becomes false in
a way that looks like success. FEATURES below documents the observability of each
field, and --selftest checks the replay against a direct count.
"""
import argparse
from collections import defaultdict

from pipeline.db import connect_ro
from pipeline.grid import neighbors

# Single source for the OSM column set - osm.py builds the table, this module
# reads it, and a mismatch between the two would be a silent column shift.
from .osm import COLUMNS as OSM_COLUMNS
from .osm import FEATURES as OSM_FEATURES

# horizon (months) used for "recent" windows
RECENT_M = 36

# Business types grouped by what they compete for. A 한식 next to another 한식
# splits the same lunch demand; a 한식 next to a 까페 does not. The existing
# same_uptae features cannot express this because 업태 labels are too granular
# (통닭(치킨) and 호프/통닭 are near-identical, 까페 and 전통찻집 are not rivals
# of 한식 at all).
UPTAE_GROUP = {
    "한식": "식사", "중국식": "식사", "일식": "식사", "경양식": "식사",
    "분식": "식사", "횟집": "식사", "식육(숯불구이)": "식사", "냉면집": "식사",
    "탕류(보신용)": "식사", "외국음식전문점(인도,태국등)": "식사", "뷔페식": "식사",
    "김밥(도시락)": "간편", "패스트푸드": "간편", "출장조리": "간편",
    "까페": "음료", "전통찻집": "음료", "다방": "음료", "제과점영업": "음료",
    "호프/통닭": "주류", "정종/대포집/소주방": "주류", "통닭(치킨)": "주류",
    "라이브카페": "주류", "단란주점": "주류",
}


def group_of(uptae):
    return UPTAE_GROUP.get(uptae, "기타")

FEATURES = {
    "open_cnt":        "격자 내 T 시점 영업 중 음식점 수 — 개업일≤T, 폐업일>T",
    "open_cnt_r1":     "3x3 이웃 포함 영업 중 수 — 위와 동일 조건",
    "same_uptae_cnt":  "격자 내 동일 업태 영업 중 수",
    "same_uptae_r1":   "3x3 이웃 동일 업태 영업 중 수",
    "openings_36m":    "직전 36개월 격자 개업 건수 — 개업일이 (T-36, T]",
    "closures_36m":    "직전 36개월 격자 폐업 건수 — 폐업일이 (T-36, T]",
    "churn_36m":       "closures_36m / (open_cnt + closures_36m) — 자리 교체율",
    "prior_surv_3y":   "T 이전에 이미 3년이 경과한 과거 코호트의 3년 생존율(3x3, n>=20)",
    "prior_surv_n":    "위 생존율의 표본 수",
    "growth_36m":      "open_cnt(T) / open_cnt(T-36) — 밀도 추세",
    "median_area":     "격자 내 T 시점 영업 점포 시설면적 중앙값",
    # shop-level, known at opening
    "prior_surv_1y":   "이웃 과거 코호트의 1년 생존율 (단기 실패율)",
    "same_group_r1":    "이웃 중 같은 수요군(식사/음료/주류/간편) 점포 수 = 직접 경쟁",
    "other_group_r1":   "이웃 중 다른 수요군 점포 수 = 집객 보완",
    "group_share_r1":   "직접 경쟁 비중 = same_group / 전체",
    "median_tenure_r1": "이웃 영업 중 점포의 영업 연수 중앙값 = 자리의 안정성",
    "veteran_share_r1": "10년 이상 영업 점포 비율",
    "uptae_entropy_r1": "이웃 업태 다양성 (섀넌 엔트로피)",
    "close_accel_r1":   "최근12개월 폐업 / 직전24개월 연평균 폐업 = 악화 가속",
    "site_area":       "본인 점포 시설면적 — 인허가 시점 기록",
    "open_month":      "개업 월 (1-12) — 계절성",
    "uptae":           "업태 (범주형)",
}

TREND_FEATURES = {
    "trend_12m":     "개업 직전 12개월 평균 검색관심도 (서울 대비 상대값)",
    "trend_growth":  "직전 12개월 평균 / 그 이전 12개월 평균 — 관심도 추세",
}

LEAKY = {
    # things that would be trivially wrong to use, named so reviewers can check
    "grid_feature.food_store_cnt": "현재 시점 점포수",
    "grid_feature.survive_3y_local": "현재까지의 생존율",
    "trdar_sales.*": "2021년 이후만 존재, 과거 시점 재구성 불가",
    "lvpop_profile.*": "최근 7일 평균, 과거 값 없음",
}


def ym(y, m):
    return y * 12 + (m or 1)


def load_shops(con):
    """All gridded restaurants as flat tuples. ~477k rows, fits in memory."""
    rows = con.execute(
        "SELECT grid_id, uptae, open_y, open_m, close_y, close_m, is_closed, site_area "
        "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL").fetchall()
    out = []
    for r in rows:
        o = ym(r["open_y"], r["open_m"])
        c = ym(r["close_y"], r["close_m"]) if (r["is_closed"] and r["close_y"]) else None
        out.append((r["grid_id"], r["uptae"] or "기타", o, c, r["site_area"]))
    return out


class TrendIndex:
    """Monthly search interest per neighbourhood, queried strictly backwards.

    Only months strictly before T are read, so a shop that opened in 2019-03
    never sees 2019-03 onwards - the same rule as every other as-of feature.
    """

    def __init__(self, con):
        self.series = defaultdict(dict)
        self.place_of = {}
        try:
            for p, per, v in con.execute("SELECT place, period, rel FROM trend"):
                y, m = int(per[:4]), int(per[5:7])
                self.series[p][y * 12 + m] = v
            for gid, p in con.execute("SELECT grid_id, place FROM grid_place"):
                self.place_of[gid] = p
        except Exception:
            pass

    def features(self, cell, t):
        p = self.place_of.get(cell)
        s = self.series.get(p) if p else None
        if not s:
            return {"trend_12m": None, "trend_growth": None}
        recent = [s[k] for k in range(t - 12, t) if k in s]
        prior = [s[k] for k in range(t - 24, t - 12) if k in s]
        if len(recent) < 6:
            return {"trend_12m": None, "trend_growth": None}
        r = sum(recent) / len(recent)
        g = (r / (sum(prior) / len(prior))) if len(prior) >= 6 and sum(prior) else None
        return {"trend_12m": r, "trend_growth": g}


class MentionIndex:
    """Blog mentions of the shops already present around a candidate cell.

    A shop's own mentions start only after it opens, so they can never be a
    feature for its own opening. What IS reconstructable: how much attention the
    EXISTING neighbours had attracted, counting only posts dated before month T.

    Truncated shops (mention count above what one API request returns) have an
    unreliable date distribution - `sort=date` means their 100 returned posts are
    all recent, hiding older ones. They are counted as "famous neighbour present"
    rather than folded into the volume sum.
    """

    def __init__(self, con):
        self.by_shop = defaultdict(dict)     # mgtno -> {period: count}
        self.truncated = set()
        self.cell_shops = defaultdict(list)  # cell -> [(mgtno, open, close)]
        try:
            for m, p, c in con.execute("SELECT mgtno, period, cnt FROM mention"):
                self.by_shop[m][p] = c
            for (m,) in con.execute("SELECT mgtno FROM mention_shop WHERE truncated=1"):
                self.truncated.add(m)
            for r in con.execute(
                    "SELECT mgtno, grid_id, open_y, open_m, close_y, close_m, is_closed "
                    "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL"):
                o = ym(r["open_y"], r["open_m"])
                c = ym(r["close_y"], r["close_m"]) if (r["is_closed"] and r["close_y"]) else None
                self.cell_shops[r["grid_id"]].append((r["mgtno"], o, c))
        except Exception:
            pass
        self.available = bool(self.by_shop)

    def features(self, cell, t):
        if not self.available:
            return {"mention_r1_12m": None, "famous_r1": None, "mentioned_shops_r1": None}
        vol = famous = shops = 0
        seen_any = False
        for c in neighbors(cell, 1):
            for mgtno, o, cl in self.cell_shops.get(c, ()):
                if o > t or (cl is not None and cl <= t):
                    continue                      # not operating at t
                if mgtno not in self.by_shop and mgtno not in self.truncated:
                    continue                      # never collected
                seen_any = True
                if mgtno in self.truncated:
                    famous += 1
                    continue
                s = self.by_shop.get(mgtno) or {}
                v = sum(n for p, n in s.items() if t - 12 < p <= t)
                if v:
                    vol += v
                    shops += 1
        if not seen_any:
            return {"mention_r1_12m": None, "famous_r1": None, "mentioned_shops_r1": None}
        return {"mention_r1_12m": vol, "famous_r1": famous, "mentioned_shops_r1": shops}


MENTION_FEATURES = {
    "mention_r1_12m":     "3x3 이웃 기존 점포들의 T 이전 12개월 블로그 언급 수 합",
    "famous_r1":          "이웃 중 언급량 상한 초과(=널리 회자되는) 점포 수",
    "mentioned_shops_r1": "이웃 중 언급이 하나라도 있는 점포 수",
}


class RideIndex:
    """Tier 3 — monthly ridership of a cell's nearest subway station.

    Unlike station distance, this one moves with time, so it is the first
    external feature that can say a location's catchment was growing. Coverage
    starts 2015-01 (CardSubwayTime), which is why it is measured on the
    2017-2018 sub-bench rather than the confirmed 2005-2018 bench - on the wide
    bench most training rows would be imputed and the result would be a
    coverage artefact wearing the clothes of a negative finding.

    The value is a STATION-unit value attached through the nearest station, so
    cells sharing a station tie on it. That is the deliberate alternative to
    interpolating a per-cell number the data cannot support.
    """

    def __init__(self, con):
        self.series = defaultdict(dict)
        self.station_of = {}
        try:
            for st, t, v in con.execute("SELECT station, ym, riders FROM station_ride"):
                self.series[st][t] = v
            for gid, st in con.execute(
                    "SELECT grid_id, station_name FROM grid_access WHERE station_name IS NOT NULL"):
                self.station_of[gid] = st
        except Exception:
            pass
        self.available = bool(self.series)

    def features(self, cell, t):
        s = self.series.get(self.station_of.get(cell))
        if not s:
            return {"ride_12m": None, "ride_growth": None}
        recent = [s[k] for k in range(t - 12, t) if k in s]
        prior = [s[k] for k in range(t - 24, t - 12) if k in s]
        if len(recent) < 6:
            return {"ride_12m": None, "ride_growth": None}
        r = sum(recent) / len(recent)
        g = (r / (sum(prior) / len(prior))) if len(prior) >= 6 and sum(prior) else None
        return {"ride_12m": r, "ride_growth": g}


RIDE_FEATURES = {
    "ride_12m":     "최근접 지하철역의 직전 12개월 평균 월 승하차 인원 (역 단위 값)",
    "ride_growth":  "직전 12개월 평균 / 그 이전 12개월 평균 — 역 이용 추세",
}


class AccessIndex:
    """Transit distance per cell. Time-invariant over the study window, so it
    is as-of valid by construction (with the noted exception of lines opened
    mid-window, which the source does not date)."""

    def __init__(self, con):
        self.by_cell = {}
        try:
            for r in con.execute(
                    "SELECT grid_id, station_dist_m, stations_500m, stations_1km, "
                    "transfer_dist_m FROM grid_access"):
                self.by_cell[r[0]] = (r[1], r[2], r[3], r[4])
        except Exception:
            pass
        self.available = bool(self.by_cell)

    def features(self, cell, t=None):
        v = self.by_cell.get(cell)
        if not v:
            return {"station_dist_m": None, "stations_500m": None,
                    "stations_1km": None, "transfer_dist_m": None}
        return {"station_dist_m": v[0], "stations_500m": v[1],
                "stations_1km": v[2], "transfer_dist_m": v[3]}


ACCESS_FEATURES = {
    "station_dist_m":  "최근접 지하철역까지 직선거리 (m)",
    "stations_500m":   "반경 500m 내 역 수",
    "stations_1km":    "반경 1km 내 역 수",
    "transfer_dist_m": "최근접 환승역까지 거리 (m)",
}


# Seoul's three designated city centres (2030 서울플랜 3도심). Representative
# points, not polygon centroids - the feature is "how far from a centre", and a
# few hundred metres of centre definition does not change a 100m-grid ranking.
CBD = {"jongno": (126.9784, 37.5665),    # 한양도성 (서울시청)
       "gangnam": (127.0276, 37.4979),   # 강남 (강남역)
       "yeouido": (126.9244, 37.5215)}   # 여의도·영등포 (여의도역)

CBD_LAT_M = 111_320.0
CBD_LON_M = 111_320.0 * 0.79281          # cos(37.55 deg)


class CbdIndex:
    """Straight-line distance from each cell to Seoul's three city centres.

    Why this source: a three-city panel study of retail decline ranks centrality
    (metric distance to downtown) second only to agglomeration, ahead of street
    connectivity. Our 20 features cover agglomeration thoroughly and centrality
    not at all - and unlike road geometry, centrality is not implied by shop
    density, because a dense outer 상권 and a dense downtown block look the same
    to a count of neighbours.

    Time-invariant: Seoul's three centres were established well before the 2005
    study window, so `<=T` truncation is vacuous.

    This is metric distance, matching the cited study - not network distance.
    """

    def __init__(self, con):
        self.by_cell = {}
        for grid_id, lon, lat in con.execute(
                "SELECT grid_id, center_lon, center_lat FROM grid"):
            if lon is None or lat is None:
                continue
            d = {}
            for name, (clon, clat) in CBD.items():
                dx = (lon - clon) * CBD_LON_M
                dy = (lat - clat) * CBD_LAT_M
                d[f"cbd_dist_{name}"] = (dx * dx + dy * dy) ** 0.5
            d["cbd_dist_min"] = min(d.values())
            self.by_cell[grid_id] = d
        if not self.by_cell:
            raise RuntimeError("grid table is empty - cannot build CBD distances")

    def features(self, cell, t=None):
        v = self.by_cell.get(cell)
        if v is None:
            return dict.fromkeys(CBD_COLUMNS)
        return dict(v)


CBD_COLUMNS = [f"cbd_dist_{n}" for n in CBD] + ["cbd_dist_min"]

CBD_FEATURES = {
    "cbd_dist_jongno":  "한양도성 도심까지 직선거리 (m)",
    "cbd_dist_gangnam": "강남 도심까지 직선거리 (m)",
    "cbd_dist_yeouido": "여의도·영등포 도심까지 직선거리 (m)",
    "cbd_dist_min":     "3도심 중 최근접까지 직선거리 (m)",
}


class OsmIndex:
    """Road geometry per cell, built by `model/osm.py`.

    Time-invariant over the study window, so `<=T` truncation is vacuous and the
    as-of self-test passes by construction. The cost of that is an anachronism -
    a road built in 2015 is credited to a 2010 opening - documented in osm.py.

    Unlike AccessIndex this raises when the table is missing instead of degrading
    to `available=False`. A run that asked for OSM features and silently got none
    would report "no contribution" for an experiment that never happened.
    """

    def __init__(self, con):
        cols = ", ".join(OSM_COLUMNS)
        self.by_cell = {r[0]: tuple(r[1:]) for r in
                        con.execute(f"SELECT grid_id, {cols} FROM grid_osm")}
        if not self.by_cell:
            raise RuntimeError(
                "grid_osm is empty - run `python -m model.osm --build` first")

    def features(self, cell, t=None):
        v = self.by_cell.get(cell)
        if v is None:
            return dict.fromkeys(OSM_COLUMNS)   # cell outside the built set: missing, not zero
        return dict(zip(OSM_COLUMNS, v))


CHAIN_N = 3          # shops under one 상호 before it counts as a chain
VACANCY_CAP_M = 24   # months a vacancy is followed for; see ExtraIndex


def load_shop_details(con):
    """Shops with the address and trade name the Tier-1 features need."""
    rows = con.execute(
        "SELECT grid_id, uptae, bplcnm, addr, open_y, open_m, close_y, close_m, is_closed "
        "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL").fetchall()
    out = []
    for r in rows:
        o = ym(r["open_y"], r["open_m"])
        c = ym(r["close_y"], r["close_m"]) if (r["is_closed"] and r["close_y"]) else None
        out.append((r["grid_id"], r["uptae"] or "기타", r["bplcnm"] or "",
                    r["addr"] or "", o, c))
    return out


class ExtraIndex:
    """Tier 1 — re-derivations of the licensing table on mechanisms the existing
    features do not express: how fast a premises refills, how old the pitch is,
    how much of the block is chain-operated.

    Every window is closed at or before T by construction, which is stricter than
    it looks. `reoccupy_12m` only counts closures at or before T-12 so its
    12-month window cannot extend past T; `vacancy_fill_m` only counts closures at
    or before T-24 and caps the answer at 24 months, so a premises still empty at
    T is a fully observed "24", not a missing value that would otherwise have to
    be imputed from the future. Chain membership is evaluated as of T too - a
    brand that reached three branches in 2020 is not a chain in 2013.

    The existing leakage guard checks the base NUM set at an AUC 0.90 threshold
    and would not notice a +0.02 leak from a new feature, so each of these is
    additionally covered by the cut-at-T self-test in `selftest_cut`.
    """

    def __init__(self, con=None, rows=None):
        import bisect
        self._bisect = bisect
        self.by_cell = defaultdict(list)      # cell -> [(addr, uptae, open, close, name)]
        chain_opens = defaultdict(list)
        for gid, ut, nm, addr, o, c in (rows if rows is not None else load_shop_details(con)):
            self.by_cell[gid].append((addr, ut, o, c, nm))
            if nm:
                chain_opens[nm].append(o)
        self.chain_opens = {k: sorted(v) for k, v in chain_opens.items()
                            if len(v) >= CHAIN_N}
        self.available = bool(self.by_cell)

    def _is_chain_at(self, name, t):
        opens = self.chain_opens.get(name)
        if not opens:
            return False
        return self._bisect.bisect_right(opens, t) >= CHAIN_N

    def features(self, cell, t):
        """All Tier-1 values for one (cell, month). Uptae-independent."""
        ring = neighbors(cell, 1)
        by_addr = defaultdict(list)
        operating = chain = 0
        close_ages, opens_12m = [], 0
        for c in ring:
            for addr, ut, o, cl, nm in self.by_cell.get(c, ()):
                if o > t:
                    continue                      # not yet licensed at t
                if cl is None or cl > t:
                    operating += 1
                    if self._is_chain_at(nm, t):
                        chain += 1
                if cl is not None and cl <= t:
                    close_ages.append(cl - o)
                if c == cell and t - 12 < o <= t:
                    opens_12m += 1
                by_addr[addr].append((o, cl, ut))

        refill, switch_n, switch_diff, fills = [0, 0], 0, 0, []
        for addr, evs in by_addr.items():
            if len(evs) < 2 or not addr:
                continue
            evs.sort(key=lambda e: e[0])      # by opening; close may be None
            for o, cl, ut in evs:
                if cl is None or cl > t:
                    continue
                nxt = next(((o2, u2) for o2, _, u2 in evs if o2 > cl), None)
                if cl <= t - 12:
                    refill[1] += 1
                    if nxt and nxt[0] - cl <= 12:
                        refill[0] += 1
                if cl <= t - VACANCY_CAP_M:
                    gap = (nxt[0] - cl) if nxt else VACANCY_CAP_M + 1
                    fills.append(min(gap, VACANCY_CAP_M))
                if nxt and nxt[0] <= t:
                    switch_n += 1
                    switch_diff += 1 if nxt[1] != ut else 0

        # density gradient: 5x5 per-cell density against 3x3 per-cell density
        n_r1 = sum(1 for c in ring for _, _, o, cl, _ in self.by_cell.get(c, ())
                   if o <= t and (cl is None or cl > t))
        r2 = neighbors(cell, 2)
        n_r2 = sum(1 for c in r2 for _, _, o, cl, _ in self.by_cell.get(c, ())
                   if o <= t and (cl is None or cl > t))
        cell_opens = [o for _, _, o, _, _ in self.by_cell.get(cell, ()) if o <= t]

        close_ages.sort()
        fills.sort()
        return {
            "chain_share_r1": (chain / operating) if operating else None,
            "reoccupy_12m": (refill[0] / refill[1]) if refill[1] >= 5 else None,
            "vacancy_fill_m": (fills[len(fills) // 2]) if len(fills) >= 5 else None,
            "close_age_m": (close_ages[len(close_ages) // 2]) if len(close_ages) >= 5 else None,
            "grid_age_y": ((t - min(cell_opens)) / 12.0) if cell_opens else None,
            "uptae_switch_r1": (switch_diff / switch_n) if switch_n >= 5 else None,
            "density_grad": ((n_r2 / len(r2)) / (n_r1 / len(ring))) if n_r1 else None,
            "openings_12m": opens_12m,
        }


G2X_FEATURES = {
    "openings_6m":   "직전 6개월 격자 개업 수 — 개업일이 (T-6, T]",
    "openings_24m":  "직전 24개월 격자 개업 수",
    "closures_6m":   "직전 6개월 격자 폐업 수 — 폐업일이 (T-6, T]",
    "closures_12m":  "직전 12개월 격자 폐업 수",
    "closures_24m":  "직전 24개월 격자 폐업 수",
    "churn_12m":     "closures_12m / (open_cnt + closures_12m) — 단기 자리 교체율",
    "growth_12m":    "open_cnt(T) / open_cnt(T-12) — 단기 밀도 추세",
    "open_accel":    "최근 12개월 개업 / 36개월 연평균 개업 — >1이면 개업이 가속 중",
    "close_accel":   "최근 12개월 폐업 / 36개월 연평균 폐업 — >1이면 폐업이 가속 중",
    "net_flow_12m":  "(직전 12개월 개업 − 폐업) / 영업 점포 수 — 순유입 강도",
}

EXTRA_FEATURES = {
    "chain_share_r1":  "이웃 영업 점포 중 체인(서울에 동일 상호 3곳 이상, 개업<=T만 집계) 비중",
    "reoccupy_12m":    "이웃 주소 중 폐업(<=T-12) 후 12개월 내 재개업 비율 — 창이 T 이전에 닫힌다",
    "vacancy_fill_m":  "이웃 주소 공실 회전 개월 중앙값 (폐업<=T-24만, 24개월 상한 = 미충원도 관측값)",
    "close_age_m":     "이웃 폐업 점포(<=T)의 영업 개월 중앙값 — 일찍 죽는 자리 vs 오래 살다 바뀌는 자리",
    "grid_age_y":      "격자 첫 인허가(<=T) 이후 경과 연수 — 상권 성숙도",
    "uptae_switch_r1": "이웃 주소 재개업(<=T) 중 업태가 바뀐 비율 — 자리 정체성 불안정",
    "density_grad":    "5x5 셀당 밀도 / 3x3 셀당 밀도 (<=T 영업) — <1이면 상권 핵심부",
    "openings_12m":    "격자 직전 12개월 개업 수 — 36m 지표의 단기판",
}


def load_rest(con):
    """휴게음식점 as (cell, open, close). Empty if Tier 2 was never loaded."""
    try:
        rows = con.execute(
            "SELECT grid_id, open_y, open_m, close_y, close_m, is_closed "
            "FROM licence_rest WHERE grid_id IS NOT NULL AND open_y IS NOT NULL").fetchall()
    except Exception:
        return []
    out = []
    for r in rows:
        o = ym(r["open_y"], r["open_m"])
        c = ym(r["close_y"], r["close_m"]) if (r["is_closed"] and r["close_y"]) else None
        out.append((r["grid_id"], o, c))
    return out


class RestIndex:
    """Tier 2 — 휴게음식점 (cafes, fast food, bakeries) as a second licensing
    source. The main table is 일반음식점 only, so every cafe on the block is
    currently invisible to the competition and agglomeration features: a street
    of coffee shops reads as an empty street. Same LOCALDATA format and the same
    open/close dates, so the as-of reconstruction is the identical replay.
    """

    def __init__(self, con=None, rows=None):
        self.by_cell = defaultdict(list)
        for gid, o, c in (rows if rows is not None else load_rest(con)):
            self.by_cell[gid].append((o, c))
        self.available = bool(self.by_cell)

    def features(self, cell, t):
        if not self.available:
            return {k: None for k in REST_FEATURES}
        op = openings = closures = op_past = 0
        for c in neighbors(cell, 1):
            for o, cl in self.by_cell.get(c, ()):
                if o <= t and (cl is None or cl > t):
                    op += 1
                if t - RECENT_M < o <= t:
                    openings += 1
                if cl is not None and t - RECENT_M < cl <= t:
                    closures += 1
                if o <= t - RECENT_M and (cl is None or cl > t - RECENT_M):
                    op_past += 1
        denom = op + closures
        return {
            "rest_cnt_r1": op,
            "rest_openings_36m": openings,
            "rest_closures_36m": closures,
            "rest_churn_36m": (closures / denom) if denom else None,
            "rest_growth_36m": (op / op_past) if op_past else None,
        }


REST_FEATURES = {
    "rest_cnt_r1":       "3x3 이웃 휴게음식점 T 시점 영업 수 — 카페·패스트푸드 경쟁/집적",
    "rest_openings_36m": "이웃 휴게음식점 직전 36개월 개업 수",
    "rest_closures_36m": "이웃 휴게음식점 직전 36개월 폐업 수",
    "rest_churn_36m":    "휴게음식점 자리 교체율",
    "rest_growth_36m":   "휴게음식점 밀도 추세 (T / T-36)",
}


# Every feature the model may see must carry an observability note here; the
# leakage guard fails the build on any set member that is missing one.
FEATURES.update(G2X_FEATURES)
FEATURES.update(ACCESS_FEATURES)
FEATURES.update(EXTRA_FEATURES)
FEATURES.update(REST_FEATURES)
FEATURES.update(RIDE_FEATURES)
FEATURES.update(TREND_FEATURES)
FEATURES.update(CBD_FEATURES)


class AsOf:
    """Index shops by cell once, then answer state queries for any month T."""

    def __init__(self, shops):
        self.by_cell = defaultdict(list)
        for s in shops:
            self.by_cell[s[0]].append(s)

    def _operating(self, cell, t):
        return [s for s in self.by_cell.get(cell, ()) if s[2] <= t and (s[3] is None or s[3] > t)]

    def cell_state(self, cell, t, uptae=None):
        """State of one cell at month t. Never touches anything after t.

        The short windows (6/12/24m) exist because the ablation table said the
        dynamics group carries more than any other information source, and the
        v1 set expressed it at one time scale only. A block that is churning
        this year and a block that churned three years ago look identical under
        a 36-month window; they are not the same location.
        """
        shops = self.by_cell.get(cell, ())
        op = [s for s in shops if s[2] <= t and (s[3] is None or s[3] > t)]
        op_past = [s for s in shops if s[2] <= t - RECENT_M
                   and (s[3] is None or s[3] > t - RECENT_M)]
        op_past12 = [s for s in shops if s[2] <= t - 12
                     and (s[3] is None or s[3] > t - 12)]
        openings = [s for s in shops if t - RECENT_M < s[2] <= t]
        closures = [s for s in shops if s[3] is not None and t - RECENT_M < s[3] <= t]
        areas = sorted(s[4] for s in op if s[4])

        d = {
            "open_cnt": len(op),
            "same_uptae_cnt": sum(1 for s in op if s[1] == uptae) if uptae else 0,
            "openings_36m": len(openings),
            "closures_36m": len(closures),
            # 이력이 없으면 None. 1.0 을 넣으면 "변화 없음", 0.0 을 넣으면
            # "이탈 최저" 라는 관측하지 않은 주장이 된다 — churn_36m 은 GBM 이
            # 가장 크게 쓰는 피처라 빈 격자가 최유리 값을 받는다. Encoder 가
            # None 을 학습셋 중앙값으로 대치하므로 ring_state 와 같은 규약이다.
            "growth_36m": (len(op) / len(op_past)) if op_past else None,
            "median_area": areas[len(areas) // 2] if areas else None,
            # --- G2X: same events, finer time resolution -------------------
            "openings_6m": sum(1 for s in openings if s[2] > t - 6),
            "openings_24m": sum(1 for s in openings if s[2] > t - 24),
            "closures_6m": sum(1 for s in closures if s[3] > t - 6),
            "closures_12m": sum(1 for s in closures if s[3] > t - 12),
            "closures_24m": sum(1 for s in closures if s[3] > t - 24),
            "growth_12m": (len(op) / len(op_past12)) if op_past12 else None,
        }
        denom = d["open_cnt"] + d["closures_36m"]
        d["churn_36m"] = d["closures_36m"] / denom if denom else None
        d12 = d["open_cnt"] + d["closures_12m"]
        d["churn_12m"] = d["closures_12m"] / d12 if d12 else None
        # acceleration: last 12 months against the 36-month annual average. >1 =
        # the block is opening/closing faster now than it has been.
        op12 = sum(1 for s in openings if s[2] > t - 12)
        d["open_accel"] = (op12 / (d["openings_36m"] / 3.0)) if d["openings_36m"] else None
        d["close_accel"] = ((d["closures_12m"] / (d["closures_36m"] / 3.0))
                            if d["closures_36m"] else None)
        d["net_flow_12m"] = ((op12 - d["closures_12m"]) / d["open_cnt"]) if d["open_cnt"] else None
        return d

    def ring_state(self, cell, t, uptae=None):
        """3x3 aggregates: competition, tenure, diversity, survival history.

        One pass over the ring computes all of them - these are cheap once the
        shops are already being visited, and each answers a different question
        a location poses.
        """
        import math
        cells = neighbors(cell, 1)
        grp = group_of(uptae) if uptae else None
        cnt = same = same_grp = other_grp = 0
        obs = closed = 0
        obs1 = closed1 = 0
        tenures = []
        mix = defaultdict(int)
        recent_close = old_close = 0

        for c in cells:
            for s in self.by_cell.get(c, ()):
                _, ut, o, cl, _ = s
                operating = o <= t and (cl is None or cl > t)
                if operating:
                    cnt += 1
                    tenures.append(t - o)          # months in business at t
                    mix[ut] += 1
                    if uptae and ut == uptae:
                        same += 1
                    if grp:
                        if group_of(ut) == grp:
                            same_grp += 1
                        else:
                            other_grp += 1
                if o + 36 <= t:
                    obs += 1
                    if cl is not None and cl - o <= 36:
                        closed += 1
                if o + 12 <= t:
                    obs1 += 1
                    if cl is not None and cl - o <= 12:
                        closed1 += 1
                if cl is not None:
                    if t - 12 < cl <= t:
                        recent_close += 1
                    elif t - 36 < cl <= t - 12:
                        old_close += 1

        tenures.sort()
        n = len(tenures)
        ent = 0.0
        if cnt:
            for v in mix.values():
                q = v / cnt
                ent -= q * math.log(q)

        return {
            "open_cnt_r1": cnt,
            "same_uptae_r1": same,
            "prior_surv_3y": (1 - closed / obs) if obs >= 20 else None,
            "prior_surv_n": obs,
            # --- added ---
            "prior_surv_1y": (1 - closed1 / obs1) if obs1 >= 20 else None,
            "same_group_r1": same_grp,
            "other_group_r1": other_grp,
            "group_share_r1": (same_grp / cnt) if cnt else None,
            "median_tenure_r1": (tenures[n // 2] / 12.0) if n else None,
            "veteran_share_r1": (sum(1 for x in tenures if x >= 120) / n) if n else None,
            "uptae_entropy_r1": ent if cnt else None,
            # closure acceleration: recent 12m vs the 24m before it, annualised
            "close_accel_r1": (recent_close / max(0.5, old_close / 2.0)) if cnt else None,
        }

    def features(self, cell, t, uptae, site_area, open_month):
        f = self.cell_state(cell, t, uptae)
        f.update(self.ring_state(cell, t, uptae))
        f["site_area"] = site_area
        f["open_month"] = open_month
        f["uptae"] = uptae
        return f


def selftest(con):
    """Prove the replay is time-dependent and matches a direct count."""
    ao = AsOf(load_shops(con))
    # pick a busy cell
    cell = con.execute(
        "SELECT grid_id FROM licence WHERE grid_id IS NOT NULL "
        "GROUP BY grid_id ORDER BY count(*) DESC LIMIT 1").fetchone()[0]

    print(f"테스트 격자: {cell}")
    seen = []
    for y in (2015, 2019, 2023):
        t = ym(y, 6)
        st = ao.cell_state(cell, t)
        direct = con.execute(
            "SELECT count(*) FROM licence WHERE grid_id=? AND open_y IS NOT NULL "
            "AND (open_y*12+COALESCE(open_m,1)) <= ? "
            "AND (is_closed=0 OR close_y IS NULL OR (close_y*12+COALESCE(close_m,1)) > ?)",
            (cell, t, t)).fetchone()[0]
        ok = st["open_cnt"] == direct
        print(f"  T={y}-06  영업중={st['open_cnt']:>4} (직접집계 {direct:>4}) "
              f"개업36m={st['openings_36m']:>3} 폐업36m={st['closures_36m']:>3} "
              f"{'MATCH' if ok else 'MISMATCH'}")
        if not ok:
            raise AssertionError(f"as-of replay != direct count at {y}")
        seen.append(st["open_cnt"])

    if len(set(seen)) == 1:
        raise AssertionError("시점을 바꿔도 값이 동일 - 시간 의존성 없음")

    # a future-dated month must never reduce to the same state as an earlier one
    late = ao.cell_state(cell, ym(2026, 1))
    print(f"  T=2026-01 영업중={late['open_cnt']:>4}")
    print("\n시간 의존성 PASS · 직접집계 일치 PASS")
    return True


def selftest_cut(con, n_cells=40, months=((2011, 6), (2015, 6), (2019, 6))):
    """Prove each new feature is a function of the past only.

    The test deletes every event after T - shops opened later stop existing, and
    a closure dated after T becomes "still operating", which is exactly what an
    observer standing at T would see - then recomputes. Any feature whose value
    moves was reading the future. This is the guard the existing RED/GREEN test
    cannot provide: that one only checks the base NUM set, and only fires above
    AUC 0.90, so a new feature leaking +0.02 passes it silently.
    """
    shops = load_shop_details(con)
    rest = load_rest(con)
    plain = load_shops(con)
    cells = [r[0] for r in con.execute(
        "SELECT grid_id FROM licence WHERE grid_id IS NOT NULL GROUP BY grid_id "
        "ORDER BY count(*) DESC LIMIT ?", (n_cells,))]

    full_x, full_r, full_a = ExtraIndex(rows=shops), RestIndex(rows=rest), AsOf(plain)
    bad = defaultdict(int)
    checked = 0
    for y, m in months:
        t = ym(y, m)
        cut_x = ExtraIndex(rows=[(g, u, nm, a, o, (c if (c is not None and c <= t) else None))
                                 for g, u, nm, a, o, c in shops if o <= t])
        cut_r = RestIndex(rows=[(g, o, (c if (c is not None and c <= t) else None))
                                for g, o, c in rest if o <= t])
        cut_a = AsOf([(g, u, o, (c if (c is not None and c <= t) else None), ar)
                      for g, u, o, c, ar in plain if o <= t])
        for cell in cells:
            for a, b in ((full_x.features(cell, t), cut_x.features(cell, t)),
                         (full_r.features(cell, t), cut_r.features(cell, t)),
                         (full_a.cell_state(cell, t), cut_a.cell_state(cell, t))):
                for k in a:
                    checked += 1
                    if a[k] != b[k]:
                        bad[k] += 1

    print(f"≤T 셀프테스트 — 격자 {len(cells)} × 시점 {len(months)} × 피처 "
          f"{len(EXTRA_FEATURES) + len(REST_FEATURES) + len(G2X_FEATURES)} = {checked:,}회 비교")
    for k in list(G2X_FEATURES) + list(EXTRA_FEATURES) + list(REST_FEATURES):
        n = bad.get(k, 0)
        print(f"  {k:<20} {'PASS' if n == 0 else f'FAIL — T 이후 행에 의존 {n}회'}")
    ok = not bad
    print(f"-> ≤T 불변성 {'PASS' if ok else 'FAIL'}")
    return ok


def describe():
    print("as-of 피처 — 각 항목이 T 시점에 관측 가능한 근거\n")
    for k, v in FEATURES.items():
        print(f"  {k:<16} {v}")
    print("\n의도적으로 배제한 것 (누수)\n")
    for k, v in LEAKY.items():
        print(f"  {k:<28} {v}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--describe", action="store_true")
    ap.add_argument("--selftest-cut", action="store_true",
                    help="신규 피처: T 이후 행을 지워도 값이 불변인지")
    a = ap.parse_args()
    if a.describe:
        describe()
    if a.selftest:
        selftest(connect_ro())
    if a.selftest_cut:
        raise SystemExit(0 if selftest_cut(connect_ro()) else 1)
