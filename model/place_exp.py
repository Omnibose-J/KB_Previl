"""Part B·C·D 실험 — 지명 단위에서 비정형의 용도를 검정한다.

임계·통제·보정은 전부 docs/unstructured-plan.md §E 에 실행 전 등록되어 있다.
여기서는 그 값을 읽어 실행할 뿐이고, 결과를 보고 바꾸지 않는다.

불확실성은 전부 지명 단위 클러스터 부트스트랩이다. 같은 지명의 여러 연도는
독립이 아니므로 행 단위로 재표집하면 표준오차가 실제보다 좁아진다.

    python -m model.place_exp --exp b1
    python -m model.place_exp --exp b2c1
    python -m model.place_exp --exp d1
    python -m model.place_exp --exp c2
"""
import argparse
import sqlite3
import sys
from collections import defaultdict

import numpy as np

from model.place import K, build
from pipeline.config import DB_PATH

SEED = 0
NBOOT = 2000          # §E-4
NPLACEBO = 200        # §E-7
FDR_Q = 0.10          # §E-6


# ---------------------------------------------------------------- 회귀 유틸

def ols(X, y):
    """계수만. 절편은 호출자가 X 에 넣는다."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def design(rows, cols, year_fe=True):
    """-> (X, y_key 없이 X만, 열이름). 절편 포함, 연도 더미 포함."""
    names = ["const"] + list(cols)
    X = [np.ones(len(rows))]
    for c in cols:
        X.append(np.array([r[c] for r in rows], dtype=float))
    if year_fe:
        ys = sorted({r["year"] for r in rows})
        for y in ys[1:]:                      # 기준연도 하나는 뺀다
            X.append(np.array([1.0 if r["year"] == y else 0.0 for r in rows]))
            names.append(f"year_{y}")
    return np.column_stack(X), names


def zscore(rows, cols):
    """제자리 표준화 — 계수를 '1SD 증가당'으로 읽기 위해."""
    for c in cols:
        v = np.array([r[c] for r in rows], dtype=float)
        s = v.std()
        if s > 0:
            for r, z in zip(rows, (v - v.mean()) / s):
                r[c] = float(z)


def complete(panel, keys):
    return [dict(r) for r in panel if all(r.get(k) is not None for k in keys)]


def cluster_boot(rows, cols, target, idx_of_interest, nboot=NBOOT, seed=SEED,
                 key="place"):
    """클러스터(지명/법정동)째로 재표집해 관심 계수의 분포를 낸다."""
    rng = np.random.default_rng(seed)
    by_place = defaultdict(list)
    for i, r in enumerate(rows):
        by_place[r[key]].append(i)
    places = list(by_place)
    y = np.array([r[target] for r in rows], dtype=float)
    X, _ = design(rows, cols)
    out = []
    for _ in range(nboot):
        pick = rng.choice(len(places), size=len(places), replace=True)
        idx = np.concatenate([by_place[places[p]] for p in pick])
        try:
            b = ols(X[idx], y[idx])
        except np.linalg.LinAlgError:
            continue
        out.append(b[idx_of_interest])
    return np.array(out)


def loyo_r2(rows, cols, target):
    """leave-one-year-out 교차검증 R^2. in-sample R^2 는 컬럼을 더하면 항상 오른다."""
    ys = sorted({r["year"] for r in rows})
    y = np.array([r[target] for r in rows], dtype=float)
    X, _ = design(rows, cols, year_fe=False)     # 연도를 빼야 연도 홀드아웃이 성립
    pred = np.full(len(rows), np.nan)
    yr = np.array([r["year"] for r in rows])
    for hold in ys:
        tr, te = yr != hold, yr == hold
        if te.sum() == 0 or tr.sum() <= X.shape[1]:
            continue
        b = ols(X[tr], y[tr])
        pred[te] = X[te] @ b
    ok = ~np.isnan(pred)
    ss_res = ((y[ok] - pred[ok]) ** 2).sum()
    ss_tot = ((y[ok] - y[ok].mean()) ** 2).sum()
    return 1 - ss_res / ss_tot, int(ok.sum())


def placebo_p(rows, cols, target, idx, observed, shuffle_cols,
              nplacebo=NPLACEBO, seed=SEED):
    """지명 라벨을 섞어 귀무분포. 여러 열은 같은 순열로 함께 섞는다.

    따로 섞으면 위약이 실제보다 무의미해져 귀무분포가 좁아지고, 없는 유의성이
    생긴다 (§8-G 에서 실측으로 확인한 함정).
    """
    rng = np.random.default_rng(seed + 1)
    y = np.array([r[target] for r in rows], dtype=float)
    orig = {c: np.array([r[c] for r in rows], dtype=float) for c in shuffle_cols}
    null = []
    work = [dict(r) for r in rows]
    for _ in range(nplacebo):
        perm = rng.permutation(len(work))
        for c in shuffle_cols:
            v = orig[c][perm]
            for r, x in zip(work, v):
                r[c] = float(x)
        X, _ = design(work, cols)
        null.append(ols(X, y)[idx])
    null = np.array(null)
    # 양측: 관측 절댓값 이상이 귀무에서 얼마나 나오는가
    return float((np.abs(null) >= abs(observed)).mean()), null


def fmt_ci(arr, q=(2.5, 97.5)):
    lo, hi = np.percentile(arr, q)
    return f"[{lo:+.4f}, {hi:+.4f}]"


# ---------------------------------------------------------------- B1

B1_COHORTS = [2017, 2018, 2020, 2021, 2022]      # §E-0. 2019 는 탐색에 소진


def exp_b1(panel):
    print("=" * 72)
    print("B1 — 화제성 x 3년 생존 (5코호트)")
    print("=" * 72)
    keys = ["surv3", "trend_12m", "size", "past_inflow"]
    rows = [r for r in complete(panel, keys) if r["year"] in B1_COHORTS]
    print(f"대상 {len(rows)}행 · 지명 {len({r['place'] for r in rows})} "
          f"· 코호트 {sorted({r['year'] for r in rows})}")
    print(f"통제: size(log 영업점포) · past_inflow · 연도 고정효과\n")

    # 코호트별 부호
    print("코호트별 (각 연도 단독 회귀, trend 계수)")
    signs = []
    for y in B1_COHORTS:
        sub = [dict(r) for r in rows if r["year"] == y]
        if len(sub) < 20:
            print(f"  {y}  표본 부족 n={len(sub)}")
            continue
        zscore(sub, ["trend_12m", "size", "past_inflow"])
        X, names = design(sub, ["trend_12m", "size", "past_inflow"], year_fe=False)
        b = ols(X, np.array([r["surv3"] for r in sub], dtype=float))
        signs.append(np.sign(b[1]))
        # 참고용 분할 차이 (등록된 노출 정의)
        med = np.median([r["trend_12m"] for r in sub])
        hi = [r for r in sub if r["trend_12m"] >= med]
        lo = [r for r in sub if r["trend_12m"] < med]
        wm = lambda g: (sum(r["surv3"] * r["cohort_n"] for r in g)
                        / sum(r["cohort_n"] for r in g))
        print(f"  {y}  n={len(sub):3d}  계수 {b[1]:+.4f}   "
              f"상위절반 {wm(hi):.3f} / 하위절반 {wm(lo):.3f}  "
              f"차이 {wm(hi)-wm(lo):+.3f}")

    agree = max(signs.count(1.0), signs.count(-1.0)) if signs else 0
    print(f"\n부호 일치 {agree}/{len(signs)}  (기준 >= 4)")

    # 통합 (연도 고정효과)
    pooled = [dict(r) for r in rows]
    zscore(pooled, ["trend_12m", "size", "past_inflow"])
    cols = ["trend_12m", "size", "past_inflow"]
    X, names = design(pooled, cols)
    b = ols(X, np.array([r["surv3"] for r in pooled], dtype=float))
    boot = cluster_boot(pooled, cols, "surv3", 1)
    p, _ = placebo_p(pooled, cols, "surv3", 1, b[1], ["trend_12m"])
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"\n통합 trend 계수 {b[1]:+.4f}  클러스터 CI {fmt_ci(boot)}  "
          f"위약 p={p:.3f}")
    print(f"  (해석: 관심도 1SD 증가당 3년 생존율 {b[1]*100:+.2f}%p)")

    ok_sign = agree >= 4
    ok_ci = (lo > 0) or (hi < 0)
    ok_p = p <= 0.05
    print(f"\n판정  부호 {'PASS' if ok_sign else 'FAIL'} · "
          f"CI {'PASS' if ok_ci else 'FAIL'} · 위약 {'PASS' if ok_p else 'FAIL'}"
          f"  =>  {'채택' if (ok_sign and ok_ci and ok_p) else '기각'}")
    return {"coef": b[1], "ci": (lo, hi), "p": p, "agree": agree, "n": len(pooled)}


# ---------------------------------------------------------------- B2 + C1

def exp_b2c1(panel):
    print("=" * 72)
    print("B2 + C1 — 상권 성장 예측, 트렌드 vs 실제 인파 경쟁")
    print("=" * 72)
    keys = ["inflow_next", "past_inflow", "size", "trend_12m", "trend_growth",
            "ride_log", "ride_growth"]
    rows = complete(panel, keys)
    print(f"대상 {len(rows)}행 · 지명 {len({r['place'] for r in rows})} "
          f"· 연도 {sorted({r['year'] for r in rows})}")
    print("타깃: inflow_next = (t+1~t+3 개업) / (t 영업점포)\n")

    zscore(rows, ["past_inflow", "size", "trend_12m", "trend_growth",
                  "ride_log", "ride_growth"])
    base = ["past_inflow", "size"]
    models = {
        "기저 (과거유입+규모+연도FE)": base,
        "+ 승하차 (정형 대조)": base + ["ride_log", "ride_growth"],
        "+ 트렌드 (비정형)": base + ["trend_12m", "trend_growth"],
        "결합": base + ["ride_log", "ride_growth", "trend_12m", "trend_growth"],
    }
    print(f"{'모델':32s} {'LOYO-CV R2':>12s}")
    r2 = {}
    for name, cols in models.items():
        v, n = loyo_r2(rows, cols, "inflow_next")
        r2[name] = v
        print(f"{name:32s} {v:12.4f}   (n={n})")

    print(f"\n증분 — 기저 대비")
    for name in list(models)[1:]:
        print(f"  {name:30s} {r2[name]-r2['기저 (과거유입+규모+연도FE)']:+.4f}")

    print(f"\n결합 모델 계수 (지명 클러스터 부트스트랩 {NBOOT}회)")
    cols = models["결합"]
    X, names = design(rows, cols)
    b = ols(X, np.array([r["inflow_next"] for r in rows], dtype=float))
    verdict = {}
    for i, nm in enumerate(names):
        if nm in ("const",) or nm.startswith("year_"):
            continue
        boot = cluster_boot(rows, cols, "inflow_next", i)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        excl = (lo > 0) or (hi < 0)
        verdict[nm] = excl
        print(f"  {nm:14s} {b[i]:+.4f}  CI {fmt_ci(boot)}  "
              f"{'0 배제' if excl else '0 포함'}")

    # 위약: 트렌드 두 열을 같은 순열로
    i_tr = names.index("trend_12m")
    p, _ = placebo_p(rows, cols, "inflow_next", i_tr, b[i_tr],
                     ["trend_12m", "trend_growth"])
    print(f"\n위약 대조 (트렌드 2열 동일 순열 {NPLACEBO}회): p={p:.3f}")

    tr_ci = verdict.get("trend_12m") or verdict.get("trend_growth")
    rd_ci = verdict.get("ride_log") or verdict.get("ride_growth")
    dr2 = r2["+ 트렌드 (비정형)"] - r2["기저 (과거유입+규모+연도FE)"]

    # §E-5: B2 는 세 조건 '전부' 충족이어야 채택이다. CI 하나만 보면 안 된다 —
    # §8-G 가 남긴 규칙("CI 하한이 겨우 0을 넘긴 행은 그 자체로 채택 근거가 못
    # 된다")이 정확히 이 경우를 위해 있다.
    b2 = (dr2 > 0) and tr_ci and (p <= 0.05)
    print(f"\nB2 판정  CV R2 증분 {dr2:+.4f} {'PASS' if dr2 > 0 else 'FAIL'} · "
          f"트렌드 CI {'PASS' if tr_ci else 'FAIL'} · "
          f"위약 p={p:.3f} {'PASS' if p <= 0.05 else 'FAIL'}"
          f"  =>  {'채택' if b2 else '기각'}")
    print(f"C1 판정  예측력 증분 — 승하차 "
          f"{r2['+ 승하차 (정형 대조)']-r2['기저 (과거유입+규모+연도FE)']:+.4f} vs "
          f"트렌드 {dr2:+.4f}")
    if not b2:
        print("  => 트렌드가 등록 기준을 통과하지 못했으므로 '비정형이 고유한 "
              "것을 본다'고 말할 수 없다.")
    return {"r2": r2, "verdict": verdict, "placebo_p": p, "b2": b2, "n": len(rows)}


# ---------------------------------------------------------------- D1

def exp_d1(panel):
    print("=" * 72)
    print("D1 — 업종 구성 변화 → 상권 성장 (Glaeser 한국판)")
    print("=" * 72)
    keys = ["inflow_next", "past_inflow", "size", "share_now", "share_prev"]
    rows = [r for r in complete(panel, keys) if r["n_now"] >= 20 and r["n_prev"] >= 20]
    print(f"대상 {len(rows)}행 · 지명 {len({r['place'] for r in rows})} "
          f"(t-3~t 와 그 이전 3년 개업이 각 20건 이상)")
    print(f"예측변수: concept_delta_c = 컨셉 c 의 개업 비중 변화 (최근 3년 - 그 이전 3년)")
    print(f"통제: past_inflow · size · 연도 고정효과 | 보정: BH FDR q<={FDR_Q}\n")

    for r in rows:
        d = r["share_now"] - r["share_prev"]
        for c in range(K):
            r[f"d{c}"] = float(d[c])
    zscore(rows, ["past_inflow", "size"] + [f"d{c}" for c in range(K)])

    base = ["past_inflow", "size"]
    y = np.array([r["inflow_next"] for r in rows], dtype=float)
    res = []
    for c in range(K):
        cols = base + [f"d{c}"]
        X, names = design(rows, cols)
        b = ols(X, y)
        i = names.index(f"d{c}")
        boot = cluster_boot(rows, cols, "inflow_next", i, nboot=NBOOT)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        # 부트스트랩 양측 p (0 을 기준으로)
        p = 2 * min((boot <= 0).mean(), (boot >= 0).mean())
        res.append({"c": c, "coef": b[i], "lo": lo, "hi": hi, "p": max(p, 1 / NBOOT)})

    # Benjamini-Hochberg
    res.sort(key=lambda d: d["p"])
    m = len(res)
    passed = []
    for rank, d in enumerate(res, 1):
        d["bh"] = d["p"] * m / rank
    # BH 단조화
    run = 1.0
    for d in reversed(res):
        run = min(run, d["bh"])
        d["bh"] = run
        if run <= FDR_Q:
            passed.append(d)

    con = sqlite3.connect(DB_PATH)
    label = {}
    for c in range(K):
        rows_s = con.execute(
            "SELECT l.bplcnm FROM licence l JOIN shop_concept s ON s.mgtno=l.mgtno "
            "WHERE s.concept=? LIMIT 4", (c,)).fetchall()
        label[c] = " · ".join((x[0] or "") for x in rows_s)
    con.close()

    print(f"{'컨셉':>5s} {'계수':>9s} {'95% CI':>22s} {'p':>7s} {'BH q':>7s}  대표 상호명")
    for d in res[:12]:
        print(f"  c{d['c']:02d} {d['coef']:+9.4f} [{d['lo']:+.4f},{d['hi']:+.4f}] "
              f"{d['p']:7.4f} {d['bh']:7.4f}  {label[d['c']][:52]}")

    print(f"\nFDR q<={FDR_Q} 통과: {len(passed)}개")
    if passed:
        for d in sorted(passed, key=lambda x: -abs(x["coef"])):
            print(f"  c{d['c']:02d} {d['coef']:+.4f}  {label[d['c']][:60]}")
        # 위약: 통과한 것 중 가장 강한 컨셉으로
        top = max(passed, key=lambda x: abs(x["coef"]))
        cols = base + [f"d{top['c']}"]
        X, names = design(rows, cols)
        b = ols(X, y)
        i = names.index(f"d{top['c']}")
        p, _ = placebo_p(rows, cols, "inflow_next", i, b[i], [f"d{top['c']}"])
        print(f"\n위약 대조 (c{top['c']:02d}, {NPLACEBO}회): p={p:.3f} "
              f"=> {'PASS' if p <= 0.05 else 'FAIL'}")
    else:
        print("  없음 — 보정 후 살아남는 컨셉이 없다. negative 로 기록한다.")
    return {"passed": [d["c"] for d in passed], "res": res, "n": len(rows)}


# ---------------------------------------------------------------- C2

def exp_c2():
    print("=" * 72)
    print("C2 — 수렴 타당도: 검색 관심도 vs 실제 유동인구 (현재 시점)")
    print("=" * 72)
    con = sqlite3.connect(DB_PATH)
    # 지명 -> 상권 유동인구 (상권 밖은 NULL 로 남긴다. 0 을 넣지 않는다)
    rows = con.execute(
        "SELECT gp.place, AVG(f.tot_flpop) "
        "FROM grid_place gp JOIN grid_feature gf ON gf.grid_id = gp.grid_id "
        "JOIN trdar_flpop f ON f.trdar_cd = gf.trdar_cd "
        "GROUP BY gp.place").fetchall()
    flpop = {p: v for p, v in rows if v is not None}
    # 지명 -> 최근 12개월 트렌드
    tr = defaultdict(list)
    for p, period, rel in con.execute(
            "SELECT place, period, rel FROM trend WHERE period >= '2025-07-01'"):
        tr[p].append(rel)
    con.close()
    trend = {p: float(np.mean(v)) for p, v in tr.items() if len(v) >= 6}

    common = sorted(set(flpop) & set(trend))
    print(f"트렌드 지명 {len(trend)} · 상권 유동인구 매칭 지명 {len(flpop)} "
          f"· 교집합 {len(common)}")
    if len(common) < 30:
        print("표본 부족 — SKIP")
        return None
    x = np.array([trend[p] for p in common])
    z = np.array([flpop[p] for p in common])

    def spearman(a, b):
        ra = np.argsort(np.argsort(a)).astype(float)
        rb = np.argsort(np.argsort(b)).astype(float)
        return float(np.corrcoef(ra, rb)[0, 1])

    rho = spearman(x, z)
    rng = np.random.default_rng(SEED)
    boot = [spearman(x[i], z[i]) for i in
            (rng.choice(len(common), len(common), True) for _ in range(NBOOT))]
    lo, hi = np.percentile(boot, [2.5, 97.5])
    print(f"\nSpearman rho = {rho:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  (n={len(common)})")
    print("(§E-5: C2 에는 임계를 두지 않는다 — 기술통계로 보고한다)")
    hi_t = [p for p in common if trend[p] >= np.median(x)]
    print(f"\n관심도 상위 절반의 유동인구 중앙값 "
          f"{np.median([flpop[p] for p in hi_t]):,.0f} · "
          f"하위 절반 {np.median([flpop[p] for p in common if p not in hi_t]):,.0f}")
    return {"rho": rho, "ci": (lo, hi), "n": len(common)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exp", required=True, choices=["b1", "b2c1", "d1", "c2", "all"])
    a = ap.parse_args()
    if a.exp == "c2":
        exp_c2()
        return 0
    panel = build()
    print(f"패널 {len(panel):,}행\n")
    if a.exp in ("b1", "all"):
        exp_b1(panel)
        print()
    if a.exp in ("b2c1", "all"):
        exp_b2c1(panel)
        print()
    if a.exp in ("d1", "all"):
        exp_d1(panel)
        print()
    if a.exp == "all":
        exp_c2()
    return 0


if __name__ == "__main__":
    sys.exit(main())
