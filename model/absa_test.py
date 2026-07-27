"""H-3 검정 — 입지 측면 지표 → 지명 2019 코호트 3년 생존율.

설계는 §H-9(실행 전 등록). 지표는 전부 비율이고, 지명당 해당 주제 언급이
10건 이상일 때만 산출한다(미만은 결측, 0으로 채우지 않는다).

단위가 지명 × 단일 연도(2019)라 지명당 1행이다. 따라서 §H-9-⑤의 "지명 클러스터
부트스트랩"은 일반 부트스트랩과 동일하고, 연도 고정효과는 쓰지 않는다.

    python -m model.absa_test
"""
import argparse
import re
import sqlite3
import sys
from collections import defaultdict

import numpy as np

from pipeline.config import DB_PATH

SEED = 0
NBOOT = 2000
NPLACEBO = 200
FDR_Q = 0.10
MIN_MENTION = 10
YEAR = 2019
SPEC = {"crowd": "many", "access": "hard",
        "visibility": "hidden", "surround": "lively"}
MIN_PLACES = 30          # §H-9-⑥


def ym(y, m):
    return y * 12 + (m or 6)


def panel(con):
    g2p = dict(con.execute("SELECT grid_id, place FROM grid_place"))
    shops = defaultdict(list)
    for gid, oy, om, cy, cm, closed in con.execute(
            "SELECT grid_id, open_y, open_m, close_y, close_m, is_closed "
            "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL"):
        p = g2p.get(gid)
        if p:
            shops[p].append((ym(oy, om),
                             ym(cy, cm) if (closed == 1 and cy) else None))
    t0 = ym(YEAR, 1)
    base = ym(YEAR - 3, 1)
    out = {}
    for p, lst in shops.items():
        oper = sum(1 for o, c in lst if o < t0 and (c is None or c >= t0))
        oper3 = sum(1 for o, c in lst if o < base and (c is None or c >= base))
        coh = [(o, c) for o, c in lst if t0 <= o < t0 + 12]
        if oper < 50 or len(coh) < 20 or not oper3:
            continue
        surv = np.mean([0.0 if (c is not None and c - o < 36) else 1.0
                        for o, c in coh])
        out[p] = {
            "surv3": float(surv), "n_coh": len(coh),
            "size": float(np.log(oper)),
            "past_inflow": sum(1 for o, c in lst if base <= o < t0) / oper3,
        }
    return out


def ratios(con):
    per = {k: defaultdict(lambda: [0, 0]) for k in SPEC}
    for col, tgt in SPEC.items():
        for place, v in con.execute(
                f"SELECT place, {col} FROM absa_label WHERE {col} IS NOT NULL"):
            per[col][place][1] += 1
            if v == tgt:
                per[col][place][0] += 1
    return {col: {p: (a / b, b) for p, (a, b) in d.items() if b >= MIN_MENTION}
            for col, d in per.items()}


def ols(X, y):
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return b


def design(rows, key):
    X = np.column_stack([np.ones(len(rows)),
                         np.array([r[key] for r in rows]),
                         np.array([r["size"] for r in rows]),
                         np.array([r["past_inflow"] for r in rows])])
    y = np.array([r["surv3"] for r in rows])
    return X, y


def zs(rows, keys):
    for k in keys:
        v = np.array([r[k] for r in rows], dtype=float)
        s = v.std()
        if s > 0:
            for r, z in zip(rows, (v - v.mean()) / s):
                r[k] = float(z)


def main():
    ap = argparse.ArgumentParser()
    ap.parse_args()
    con = sqlite3.connect(DB_PATH)
    pan = panel(con)
    rat = ratios(con)
    print(f"지명 패널 {len(pan)} · 타깃 = {YEAR} 개업 코호트 3년 생존율\n")

    res = []
    for col, tgt in SPEC.items():
        name = f"{col}_{tgt}"
        rows = []
        for p, v in rat[col].items():
            if p in pan:
                r = dict(pan[p])
                r[name] = v[0]
                r["_mention"] = v[1]
                rows.append(r)
        if len(rows) < MIN_PLACES:
            print(f"{name:22s} 지명 {len(rows):2d} < {MIN_PLACES} → §H-9-⑥ 제외")
            continue
        raw = np.array([r[name] for r in rows])
        cv = raw.std() / raw.mean() if raw.mean() else float("nan")
        zs(rows, [name, "size", "past_inflow"])
        X, y = design(rows, name)
        b = ols(X, y)
        rng = np.random.default_rng(SEED)
        boot = []
        for _ in range(NBOOT):
            idx = rng.integers(0, len(rows), len(rows))
            try:
                boot.append(ols(X[idx], y[idx])[1])
            except np.linalg.LinAlgError:
                pass
        boot = np.array(boot)
        lo, hi = np.percentile(boot, [2.5, 97.5])
        p = max(2 * min((boot <= 0).mean(), (boot >= 0).mean()), 1 / NBOOT)
        res.append({"name": name, "n": len(rows), "coef": b[1], "lo": lo,
                    "hi": hi, "p": p, "cv": cv, "rows": rows,
                    "mention": float(np.mean([r["_mention"] for r in rows]))})

    if not res:
        print("검정 가능한 지표 없음 — §H-9-⑥에 따라 전면 중단")
        return 1

    # BH FDR
    res.sort(key=lambda d: d["p"])
    m = len(res)
    for rank, d in enumerate(res, 1):
        d["bh"] = d["p"] * m / rank
    run = 1.0
    for d in reversed(res):
        run = min(run, d["bh"])
        d["bh"] = run

    print(f"{'지표':<22s}{'지명':>5s}{'언급/지명':>10s}{'CV':>7s}"
          f"{'계수':>9s}{'95% CI':>22s}{'p':>7s}{'BH q':>7s}")
    for d in res:
        print(f"{d['name']:<22s}{d['n']:>5d}{d['mention']:>10.1f}{d['cv']:>7.2f}"
              f"{d['coef']:>+9.4f} [{d['lo']:+.4f},{d['hi']:+.4f}]"
              f"{d['p']:>7.4f}{d['bh']:>7.4f}")

    passed = [d for d in res if d["bh"] <= FDR_Q]
    print(f"\nBH FDR q<={FDR_Q} 통과: {len(passed)}개")

    ok = False
    if passed:
        top = max(passed, key=lambda d: abs(d["coef"]))
        rows = top["rows"]
        X, y = design(rows, top["name"])
        obs = ols(X, y)[1]
        rng = np.random.default_rng(SEED + 1)
        col = X[:, 1].copy()
        null = []
        for _ in range(NPLACEBO):
            Xp = X.copy()
            Xp[:, 1] = col[rng.permutation(len(col))]
            null.append(ols(Xp, y)[1])
        null = np.array(null)
        pp = float((np.abs(null) >= abs(obs)).mean())
        ok = pp <= 0.05
        print(f"위약 대조 ({top['name']}, 지명 라벨 셔플 {NPLACEBO}회): "
              f"p={pp:.3f} → {'PASS' if ok else 'FAIL'}")
        for d in passed:
            print(f"  {d['name']} {d['coef']:+.4f}  "
                  f"(1SD 증가당 생존율 {d['coef']*100:+.2f}%p)")
    else:
        print("  없음 — 보정 후 살아남는 지표가 없다.")

    print("\n" + "=" * 62)
    print(f"H-3 판정: {'채택' if ok else '기각'}"
          f"  (FDR 통과 {len(passed)}개{' · 위약 PASS' if ok else ''})")
    print("2차 판정 일치율(§H-9-⑤)은 model.absa_verify 로 별도 확인한다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
