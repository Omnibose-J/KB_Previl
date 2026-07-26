"""E6 — peer commercial-area clustering. Contract: docs/experiment-plan.md E6,
spec: docs/goodwill-report-design.md §4.

The one rule that decides whether this is worth anything: the clustering may not
see sales or closure rates. A benchmark built from sales and then used to judge
whether sales are excessive is circular, and the goodwill report would be
measuring its own input. So the variables are structural only - size, footfall
shape, tenant composition, franchise share, accessibility, resident and worker
population - and sales enters exactly once, afterwards, as the thing the
clusters are asked to explain.

Three pre-registered checks, all from the design doc, none editable after the
run: silhouette >= 0.25 (the clusters are separated), eta^2 >= 0.20 (structure
explains sales dispersion within an industry), bootstrap ARI >= 0.60 (the
partition is stable under resampling). Failing any of them demotes the goodwill
report's benchmark to Level 4 (Seoul-wide industry average) rather than killing
it - the report states which level it used.
"""
import argparse
import sys

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from pipeline.db import init

SIL_MIN, ETA2_MIN, ARI_MIN = 0.25, 0.20, 0.60
K_RANGE = (6, 7, 8)
TOURIST = "관광특구"
FORBIDDEN = ("sales_amt", "sales_cnt", "opbiz_rt", "clsbiz_rt")   # circularity guard


def load(con):
    """One row per 상권: structural variables only."""
    areas = {r["trdar_cd"]: dict(r) for r in con.execute(
        "SELECT trdar_cd, trdar_nm, trdar_se_nm, adstrd_cd, area_m2, "
        "center_lon, center_lat FROM trdar_area")}
    for r in con.execute("SELECT * FROM trdar_flpop"):
        a = areas.get(r["trdar_cd"])
        if a:
            a.update({k: r[k] for k in r.keys() if k.startswith("tz_") or k == "tot_flpop"})

    stores = {}
    for r in con.execute("SELECT trdar_cd, induty_cd, stor_co, frc_stor_co FROM trdar_store"):
        d = stores.setdefault(r["trdar_cd"], {"tot": 0.0, "frc": 0.0, "mix": {}})
        d["tot"] += r["stor_co"] or 0
        d["frc"] += r["frc_stor_co"] or 0
        d["mix"][r["induty_cd"]] = r["stor_co"] or 0

    dong = {r["adm_cd"]: dict(r) for r in con.execute(
        "SELECT adm_cd, tot_ppltn, ppltn_dnsty, tot_worker, corp_cnt FROM sgis_dong")}

    # nearest station distance in metres, from the area centroid
    st = [(r["lon"], r["lat"]) for r in con.execute("SELECT lon, lat FROM station")]
    stx = np.array(st)

    induty = sorted({i for d in stores.values() for i in d["mix"]})
    rows, keys, names, kinds = [], [], [], []
    for cd, a in areas.items():
        s = stores.get(cd)
        if not s or not s["tot"] or a.get("tot_flpop") is None or not a.get("area_m2"):
            continue
        d = dong.get(str(a["adstrd_cd"])) or {}
        flp = a["tot_flpop"] or 1.0
        dx = (stx[:, 0] - a["center_lon"]) * 88_000
        dy = (stx[:, 1] - a["center_lat"]) * 111_000
        dist = float(np.sqrt(dx * dx + dy * dy).min())
        rows.append([
            np.log1p(a["area_m2"]), np.log1p(flp), np.log1p(s["tot"]),
            np.log1p(flp / a["area_m2"]),                       # footfall density
            *[(a.get(f"tz_{z}") or 0) / flp for z in
              ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")],
            s["frc"] / s["tot"],                                # franchise share
            *[s["mix"].get(i, 0) / s["tot"] for i in induty],   # tenant composition
            np.log1p(dist),
            np.log1p(d.get("tot_ppltn") or 0), np.log1p(d.get("tot_worker") or 0),
        ])
        keys.append(cd)
        names.append(a["trdar_nm"])
        kinds.append(a["trdar_se_nm"])
    cols = (["log_area", "log_flpop", "log_stores", "log_flpop_density"]
            + [f"tz_share_{z}" for z in ("00_06", "06_11", "11_14", "14_17", "17_21", "21_24")]
            + ["franchise_share"] + [f"mix_{i}" for i in induty]
            + ["log_station_dist", "log_resident", "log_worker"])
    assert not any(f in c for c in cols for f in FORBIDDEN), "매출·개폐업률이 군집 변수에 들어갔다"
    return np.asarray(rows, float), keys, names, kinds, cols


def eta2_by_industry(con, labels_of, min_areas=40):
    """Share of between-cluster variance in log sales-per-store, per industry.

    Per industry rather than pooled: industries differ in absolute revenue, so a
    pooled figure would credit the clusters for a difference that is really the
    industry mix. The headline is the median across industries.
    """
    per = {}
    for r in con.execute(
            "SELECT s.trdar_cd, s.induty_cd, s.sales_amt, t.stor_co FROM trdar_sales s "
            "JOIN trdar_store t ON s.trdar_cd=t.trdar_cd AND s.induty_cd=t.induty_cd "
            "AND s.quarter=t.quarter WHERE t.stor_co>0 AND s.sales_amt>0"):
        g = labels_of.get(r["trdar_cd"])
        if g is None:
            continue
        per.setdefault(r["induty_cd"], []).append((g, np.log(r["sales_amt"] / r["stor_co"])))

    out = {}
    for ind, vals in per.items():
        if len(vals) < min_areas:
            continue
        y = np.array([v for _, v in vals])
        g = np.array([c for c, _ in vals])
        gm = y.mean()
        sst = ((y - gm) ** 2).sum()
        ssb = sum(len(y[g == c]) * (y[g == c].mean() - gm) ** 2 for c in set(g.tolist()))
        out[ind] = float(ssb / sst) if sst else 0.0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=30)
    a = ap.parse_args()
    con = init()

    X, keys, names, kinds, cols = load(con)
    tour = np.array([k == TOURIST for k in kinds])
    print(f"E6 동급 상권 군집화 — 상권 {len(keys):,} · 구조 변수 {len(cols)}개 "
          f"(매출·개폐업률 제외)")
    print(f"  관광특구 {tour.sum()}곳은 분리 (성격이 달라 군집을 끌어당긴다)")

    Z = StandardScaler().fit_transform(X[~tour])
    sub_keys = [k for k, t in zip(keys, tour) if not t]

    print(f"\n  {'k':>3} {'실루엣':>9}")
    best = None
    for k in K_RANGE:
        lab = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(Z)
        s = silhouette_score(Z, lab)
        print(f"  {k:>3} {s:>9.4f}")
        if not best or s > best[1]:
            best = (k, s, lab)
    k, sil, lab = best
    print(f"  -> k={k} 채택 (실루엣 {sil:.4f})")

    labels_of = dict(zip(sub_keys, lab.tolist()))
    eta = eta2_by_industry(con, labels_of)
    med = float(np.median(list(eta.values()))) if eta else 0.0
    print(f"\n  업종별 η² (군집이 설명하는 점포당 매출 분산 비율) — 매출은 군집에 미사용")
    for i, v in sorted(eta.items(), key=lambda kv: -kv[1]):
        print(f"    {i}  {v:.4f}")
    print(f"    중앙값 {med:.4f}")

    base = KMeans(n_clusters=k, n_init=10, random_state=0).fit(Z)
    rng = np.random.default_rng(0)
    aris = []
    for b in range(a.boot):
        idx = rng.integers(0, len(Z), len(Z))
        m = KMeans(n_clusters=k, n_init=10, random_state=b).fit(Z[idx])
        aris.append(adjusted_rand_score(base.labels_, m.predict(Z)))
    ari = float(np.mean(aris))
    print(f"\n  부트스트랩 ARI {ari:.4f} (재표본 {a.boot}회 · 전체 재예측 대비)")

    checks = [(f"실루엣 >= {SIL_MIN}", sil >= SIL_MIN, f"{sil:.4f}"),
              (f"η² 중앙값 >= {ETA2_MIN}", med >= ETA2_MIN, f"{med:.4f}"),
              (f"부트스트랩 ARI >= {ARI_MIN}", ari >= ARI_MIN, f"{ari:.4f}")]
    print(f"\n  사전 등록 검증 3종")
    for nm, ok, v in checks:
        print(f"    {nm:<22} {v:>8}  {'PASS' if ok else 'FAIL'}")
    ok = all(c[1] for c in checks)
    print(f"\n  -> E6 {'통과' if ok else '실패'} · 권리금 리포트 벤치마크 = "
          f"{'동급 군집 x 업종 (Level 1~3)' if ok else '서울 전체 x 동일 업종 (Level 4)로 강등'}")

    print(f"\n  군집 구성 (k={k})")
    for c in range(k):
        mem = [n for n, l in zip([n for n, t in zip(names, tour) if not t], lab) if l == c]
        print(f"    {c}: {len(mem):>4}곳  예) " + ", ".join(mem[:4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
