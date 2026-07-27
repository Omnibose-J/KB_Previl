"""H-4 검정 — 텍스트 시간대 언급 vs 실제 시간대별 유동인구. 설계는 §H-10.

§15-H가 닫은 것과 무엇이 다른가: 거기서는 텍스트의 **입지 조건** 서술을
정형(역거리·밀도)과 맞췄고 상관이 0이었다. 정형이 이미 정확히 아는 것을
텍스트로 다시 재려 했으니 당연한 결과다.

여기서는 **수요 성격**을 맞춘다. 정형의 `tz_*`는 몇 명이 지나갔는지만 알고
무엇을 하러 왔는지는 모른다 — 그 부분이 텍스트에만 있다.

    python -m model.demand_test
"""
import argparse
import sqlite3
import sys
from collections import defaultdict

import numpy as np

from pipeline.config import DB_PATH

SEED = 0
NBOOT = 2000
FDR_Q = 0.10
MIN_MENTION = 10
MIN_PLACES = 30

# 텍스트 라벨 ↔ trdar_flpop 시간대 구간 (§H-10)
PAIRS = [("lunch", "tz_11_14", "점심"),
         ("dinner", "tz_17_21", "저녁·회식"),
         ("night", "tz_21_24", "야간·술")]


def spearman(a, b):
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    argparse.ArgumentParser().parse_args()
    con = sqlite3.connect(DB_PATH)

    # --- 텍스트: 지명별 시간대 비율
    # LLM 이 JSON null 대신 문자열 "null" 을 돌려준 경우가 섞인다. SQL 의
    # IS NOT NULL 로는 안 걸러지므로 유효값 화이트리스트로 막는다.
    VALID = {"morning", "lunch", "afternoon", "dinner", "night"}
    per = defaultdict(lambda: defaultdict(int))
    tot = defaultdict(int)
    for place, tm in con.execute(
            "SELECT place, time FROM demand_label WHERE time IS NOT NULL"):
        if tm not in VALID:
            continue
        per[place][tm] += 1
        tot[place] += 1
    txt = {p: {k: v / tot[p] for k, v in d.items()}
           for p, d in per.items() if tot[p] >= MIN_MENTION}
    print(f"텍스트 지명 {len(txt)} (시간대 판정 {MIN_MENTION}건 이상)")

    # --- 정형: 지명별 시간대 유동인구 비율 (상권 경유, 상권 밖은 결측)
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place"))
    cols = ["tz_00_06", "tz_06_11", "tz_11_14", "tz_14_17", "tz_17_21", "tz_21_24"]
    acc = defaultdict(lambda: np.zeros(len(cols)))
    seen = defaultdict(set)
    q = (f"SELECT gf.grid_id, gf.trdar_cd, {','.join('f.'+c for c in cols)} "
         "FROM grid_feature gf JOIN trdar_flpop f ON f.trdar_cd = gf.trdar_cd")
    for row in con.execute(q):
        gid, tcd = row[0], row[1]
        p = g2p.get(gid)
        if not p or tcd in seen[p]:
            continue          # 같은 상권을 여러 격자가 물면 한 번만
        seen[p].add(tcd)
        acc[p] += np.array([v or 0.0 for v in row[2:]])
    fl = {p: v / v.sum() for p, v in acc.items() if v.sum() > 0}
    print(f"정형 지명 {len(fl)} (상권 매칭)\n")
    con.close()

    common = sorted(set(txt) & set(fl))
    print(f"교집합 {len(common)} 지명"
          f"{'  → §H-10 최소 30 미달, 판정 보류' if len(common) < MIN_PLACES else ''}")
    if len(common) < MIN_PLACES:
        return 1

    rng = np.random.default_rng(SEED)
    res = []
    print(f"\n{'텍스트':<12s}{'정형':<12s}{'n':>5s}{'텍스트평균':>11s}"
          f"{'정형평균':>10s}{'rho':>8s}{'95% CI':>20s}")
    for lab, col, ko in PAIRS:
        i = cols.index(col)
        x = np.array([txt[p].get(lab, 0.0) for p in common])
        y = np.array([fl[p][i] for p in common])
        r = spearman(x, y)
        boot = []
        for _ in range(NBOOT):
            k = rng.integers(0, len(common), len(common))
            boot.append(spearman(x[k], y[k]))
        lo, hi = np.percentile(boot, [2.5, 97.5])
        p = max(2 * min((np.array(boot) <= 0).mean(),
                        (np.array(boot) >= 0).mean()), 1 / NBOOT)
        res.append({"lab": ko, "rho": r, "lo": lo, "hi": hi, "p": p})
        print(f"{ko:<12s}{col:<12s}{len(common):>5d}{x.mean():>11.1%}"
              f"{y.mean():>10.1%}{r:>+8.3f}   [{lo:+.3f},{hi:+.3f}]")

    # BH FDR
    res.sort(key=lambda d: d["p"])
    m = len(res)
    for rank, d in enumerate(res, 1):
        d["bh"] = d["p"] * m / rank
    run = 1.0
    for d in reversed(res):
        run = min(run, d["bh"])
        d["bh"] = run

    print(f"\n{'':<12s}{'p':>8s}{'BH q':>8s}")
    for d in sorted(res, key=lambda x: x["p"]):
        print(f"{d['lab']:<12s}{d['p']:>8.4f}{d['bh']:>8.4f}")

    # §H-10 판정: 최소 2쌍에서 CI가 0 배제 AND 부호 양
    ok_pairs = [d for d in res if d["lo"] > 0]
    passed_fdr = [d for d in res if d["bh"] <= FDR_Q and d["rho"] > 0]
    ok = len(ok_pairs) >= 2 and len(passed_fdr) >= 2
    print("\n" + "=" * 60)
    print(f"CI가 0을 배제하고 부호가 양인 쌍: {len(ok_pairs)}/3  (기준 2)")
    print(f"BH FDR q<={FDR_Q} 통과(양의 부호): {len(passed_fdr)}/3  (기준 2)")
    print(f"H-4 판정: {'통과' if ok else '기각'}")
    if ok:
        print("=> §H-10 대로 score_meta 에 demand_profile_by_place 를 추가한다.")
        print("   등급·생존율과 연결짓지 않고 관측 사실로만 노출한다.")
    else:
        print("=> §H-10 대로 키를 만들지 않는다. 9-A(트렌드 비노출)와 같은 처리.")
        print("   비정형은 이 문제에서 종료한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
