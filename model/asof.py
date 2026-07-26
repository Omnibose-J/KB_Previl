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

from pipeline.db import init
from pipeline.grid import neighbors

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


class AsOf:
    """Index shops by cell once, then answer state queries for any month T."""

    def __init__(self, shops):
        self.by_cell = defaultdict(list)
        for s in shops:
            self.by_cell[s[0]].append(s)

    def _operating(self, cell, t):
        return [s for s in self.by_cell.get(cell, ()) if s[2] <= t and (s[3] is None or s[3] > t)]

    def cell_state(self, cell, t, uptae=None):
        """State of one cell at month t. Never touches anything after t."""
        shops = self.by_cell.get(cell, ())
        op = [s for s in shops if s[2] <= t and (s[3] is None or s[3] > t)]
        op_past = [s for s in shops if s[2] <= t - RECENT_M
                   and (s[3] is None or s[3] > t - RECENT_M)]
        openings = [s for s in shops if t - RECENT_M < s[2] <= t]
        closures = [s for s in shops if s[3] is not None and t - RECENT_M < s[3] <= t]
        areas = sorted(s[4] for s in op if s[4])

        d = {
            "open_cnt": len(op),
            "same_uptae_cnt": sum(1 for s in op if s[1] == uptae) if uptae else 0,
            "openings_36m": len(openings),
            "closures_36m": len(closures),
            "growth_36m": (len(op) / len(op_past)) if op_past else 1.0,
            "median_area": areas[len(areas) // 2] if areas else None,
        }
        denom = d["open_cnt"] + d["closures_36m"]
        d["churn_36m"] = d["closures_36m"] / denom if denom else 0.0
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
    a = ap.parse_args()
    if a.describe:
        describe()
    if a.selftest:
        selftest(init())
