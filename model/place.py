"""지명 패널 — Part B·C·D 실험의 공통 입력.

단위가 지명인 것이 이 모듈의 요점이다. §6·§6-B·§8-G 는 전부 격자 x 점포생존을
쟀고 세 번 다 기각됐다. 트렌드는 지명 단위 신호인데 100m 격자를 구분하라고
시킨 셈이었다. 여기서는 신호와 타깃의 단위를 맞춘다.

모든 예측변수는 기준연도 t 시점까지만 관측된 값으로 만든다. 정의는
docs/unstructured-plan.md §E-1 에 등록되어 있고 여기서 그대로 따른다.
"""
import sqlite3
from collections import defaultdict

import numpy as np

from pipeline.config import DB_PATH

# §E-0. 승하차가 2022-12 에서 끝나고 타깃 t+1~t+3 이 완전해야 한다
YEARS = [2017, 2018, 2019, 2020, 2021, 2022]
MIN_OPERATING = 50        # §E-3
MIN_COHORT = 20           # §E-3
K = 40                    # model.concept 와 같은 값


def _ym(y, m):
    return y * 12 + m


def _months(rows):
    """trend 의 'YYYY-MM-01' 을 year*12+month 로."""
    out = {}
    for place, period, rel in rows:
        y, m, _ = period.split("-")
        out.setdefault(place, {})[_ym(int(y), int(m))] = rel
    return out


def build(con=None):
    """-> (panel, concepts_present)

    panel: list of dict. 지명 x 기준연도 한 행.
    """
    own = con is None
    if own:
        con = sqlite3.connect(DB_PATH)

    # --- 격자 -> 지명
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place").fetchall())

    # --- 점포: 개업/폐업/컨셉
    shops = con.execute(
        "SELECT l.grid_id, l.open_y, l.open_m, l.close_y, l.close_m, l.is_closed, "
        "       c.concept "
        "FROM licence l LEFT JOIN shop_concept c ON c.mgtno = l.mgtno "
        "WHERE l.grid_id IS NOT NULL AND l.open_y IS NOT NULL"
    ).fetchall()

    opens = defaultdict(list)          # place -> [(open_ym, close_ym|None, concept)]
    for gid, oy, om, cy, cm, closed, cpt in shops:
        p = g2p.get(gid)
        if p is None:
            continue
        o = _ym(oy, om or 6)
        c = _ym(cy, cm or 6) if (closed == 1 and cy) else None
        opens[p].append((o, c, cpt))

    # --- 트렌드
    tr = _months(con.execute("SELECT place, period, rel FROM trend").fetchall())

    # --- 승하차: 지명 -> 그 지명 격자들이 지목한 서로 다른 역 집합
    p2st = defaultdict(set)
    for gid, st in con.execute(
            "SELECT grid_id, station_name FROM grid_access WHERE station_name IS NOT NULL"):
        p = g2p.get(gid)
        if p:
            p2st[p].add(st)
    ride = defaultdict(dict)           # station -> {ym: riders}
    for st, ym, r in con.execute("SELECT station, ym, riders FROM station_ride"):
        ride[st][ym] = r

    if own:
        con.close()

    def mean_window(series, lo, hi):
        """[lo, hi) 구간 평균. 관측이 절반 미만이면 None."""
        v = [series[t] for t in range(lo, hi) if t in series]
        return float(np.mean(v)) if len(v) >= (hi - lo) // 2 else None

    def ride_window(place, lo, hi):
        sts = p2st.get(place)
        if not sts:
            return None
        tot = []
        for t in range(lo, hi):
            s = sum(ride[st][t] for st in sts if t in ride.get(st, {}))
            if s > 0:
                tot.append(s)
        return float(np.mean(tot)) if len(tot) >= (hi - lo) // 2 else None

    panel = []
    for place, lst in opens.items():
        for t in YEARS:
            t0 = _ym(t, 1)                     # 기준 시점: t년 1월
            operating = sum(1 for o, c, _ in lst if o < t0 and (c is None or c >= t0))
            if operating < MIN_OPERATING:
                continue

            base3 = _ym(t - 3, 1)
            op3 = sum(1 for o, c, _ in lst if base3 <= o < t0)
            operating3 = sum(1 for o, c, _ in lst if o < base3 and (c is None or c >= base3))
            past_inflow = op3 / operating3 if operating3 else None

            nxt = sum(1 for o, c, _ in lst if t0 <= o < _ym(t + 3, 1))
            inflow_next = nxt / operating

            # 컨셉 구성: t-3~t 개업의 컨셉 비중, 그리고 그 이전 3년 대비 변화
            def shares(lo, hi):
                cnt = np.zeros(K)
                n = 0
                for o, c, cpt in lst:
                    if lo <= o < hi and cpt is not None:
                        cnt[cpt] += 1
                        n += 1
                return (cnt / n if n else None), n

            s_now, n_now = shares(base3, t0)
            s_prev, n_prev = shares(_ym(t - 6, 1), base3)

            # 코호트(B1): t년 개업, 3년 생존
            coh = [(o, c) for o, c, _ in lst if _ym(t, 1) <= o < _ym(t + 1, 1)]
            if len(coh) >= MIN_COHORT:
                surv = np.mean([0.0 if (c is not None and c - o < 36) else 1.0
                                for o, c in coh])
                coh_n = len(coh)
            else:
                surv, coh_n = None, len(coh)

            row = {
                "place": place, "year": t,
                "operating": operating,
                "size": float(np.log(operating)),
                "past_inflow": past_inflow,
                "inflow_next": inflow_next,
                "surv3": surv, "cohort_n": coh_n,
                "trend_12m": mean_window(tr.get(place, {}), _ym(t - 1, 1), t0),
                "trend_prev": mean_window(tr.get(place, {}), _ym(t - 2, 1), _ym(t - 1, 1)),
                "ride_12m": ride_window(place, _ym(t - 1, 1), t0),
                "ride_prev": ride_window(place, _ym(t - 2, 1), _ym(t - 1, 1)),
                "share_now": s_now, "share_prev": s_prev,
                "n_now": n_now, "n_prev": n_prev,
            }
            row["trend_growth"] = (row["trend_12m"] / row["trend_prev"] - 1
                                   if row["trend_12m"] and row["trend_prev"] else None)
            row["ride_growth"] = (row["ride_12m"] / row["ride_prev"] - 1
                                  if row["ride_12m"] and row["ride_prev"] else None)
            row["ride_log"] = float(np.log(row["ride_12m"])) if row["ride_12m"] else None
            panel.append(row)

    return panel


def summary(panel):
    ys = sorted({r["year"] for r in panel})
    print(f"패널 {len(panel):,}행 · 지명 {len({r['place'] for r in panel})} · 연도 {ys}")
    for k in ("trend_12m", "trend_growth", "ride_log", "ride_growth",
              "past_inflow", "inflow_next", "surv3"):
        n = sum(1 for r in panel if r.get(k) is not None)
        print(f"  {k:14s} 비결측 {n:5,} / {len(panel):,}")


if __name__ == "__main__":
    summary(build())
