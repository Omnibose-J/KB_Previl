"""Precompute location grades for every (업태, 격자) pair.

A UI cannot wait for the model to train per request - `model.recommend` takes
minutes because it rebuilds the training set, fits, and scores 21k cells. Most
of the as-of state does not depend on 업태, so it is computed once and only the
competition terms are recomputed per 업태. Results land in `grid_score`, which
the API reads directly.

Grades are stored rather than raw probabilities: the model's probabilities run
optimistic (its training era was kinder than the validation era), so the API
reports the survival rate actually observed in that grade on held-out data.
"""
import argparse
import sys
import time

import numpy as np

from model.asof import AsOf, group_of, load_shops
from model.evaluate import TEST_YEARS, TRAIN_YEARS, load_split
from model.recommend import MIN_RING_HISTORY, current_month
from model.train import NUM, fit_predict
from pipeline.db import init
from pipeline.grid import neighbors

# 업태 offered in the UI; anything else is served by 기타.
UPTAE = ["한식", "기타", "호프/통닭", "경양식", "분식", "일식", "중국식",
         "외국음식전문점(인도,태국등)", "정종/대포집/소주방", "통닭(치킨)",
         "식육(숯불구이)", "까페"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS grid_score (
  uptae      TEXT,
  grid_id    TEXT,
  score      REAL,
  grade      INTEGER,      -- 1 = top 10%
  observed   REAL,         -- measured 3y survival of that grade (held-out)
  PRIMARY KEY (uptae, grid_id)
);
CREATE INDEX IF NOT EXISTS ix_score_uptae ON grid_score(uptae, grade);
CREATE TABLE IF NOT EXISTS score_meta (
  k TEXT PRIMARY KEY,
  v TEXT
);
"""


def calibration(con, rank_cols):
    """Grade boundaries + observed survival per grade, from the held-out split."""
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, 3, verbose=False)
    p, _ = fit_predict("gbm", train, test, num=rank_cols)
    yte = test[1]
    order = np.argsort(-p)
    n = len(p)
    edges, observed = [], []
    for i in range(10):
        seg = order[int(n * i / 10):int(n * (i + 1) / 10)]
        edges.append(float(p[seg].min()))
        observed.append(float(yte[seg].mean()))
    return train, test, edges, observed


def uptae_terms(ao, gid, t, uptae):
    """The only features that change with 업태 — one pass over the 3x3 ring."""
    grp = group_of(uptae)
    same_cell = same_ring = same_grp = other_grp = 0
    for nb in neighbors(gid, 1):
        for _, ut, o, cl, _ in ao.by_cell.get(nb, ()):
            if o > t or (cl is not None and cl <= t):
                continue
            if ut == uptae:
                same_ring += 1
                if nb == gid:
                    same_cell += 1
            if group_of(ut) == grp:
                same_grp += 1
            else:
                other_grp += 1
    return same_cell, same_ring, same_grp, other_grp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uptae", nargs="*", default=UPTAE)
    a = ap.parse_args()

    t0 = time.time()
    con = init()
    con.executescript(SCHEMA)

    rank_cols = [c for c in NUM if c != "site_area"]
    print("보정 기준 계산 (홀드아웃)...")
    train, test, edges, observed = calibration(con, rank_cols)
    print(f"  등급별 실측 생존율: 1등급 {observed[0]*100:.1f}% ... "
          f"10등급 {observed[-1]*100:.1f}%")

    Xtr = train[0] + test[0]
    ytr = np.concatenate([train[1], test[1]])

    t = current_month(con)
    ao = AsOf(load_shops(con))
    cells = [r["grid_id"] for r in con.execute("SELECT grid_id FROM grid")]

    print(f"격자 {len(cells):,}개 기준상태 계산 (T={t//12}-{t%12 or 12:02d})...")
    base = {}
    for i, gid in enumerate(cells):
        f = ao.cell_state(gid, t, None)
        f.update(ao.ring_state(gid, t, None))
        if (f["prior_surv_n"] or 0) >= MIN_RING_HISTORY:
            base[gid] = f
        if (i + 1) % 5000 == 0:
            print(f"  {i+1:,}/{len(cells):,}", flush=True)
    print(f"  평가 대상 {len(base):,}격자 (이웃 이력 {MIN_RING_HISTORY}건 미만 제외)")

    def grade_of(score):
        for i, e in enumerate(edges):
            if score >= e:
                return i + 1, observed[i]
        return 10, observed[-1]

    con.execute("DELETE FROM grid_score")
    for u in a.uptae:
        X, keep = [], []
        for gid, b in base.items():
            sc, sr, sg, og = uptae_terms(ao, gid, t, u)
            f = dict(b)
            f["same_uptae_cnt"] = sc
            f["same_uptae_r1"] = sr
            f["same_group_r1"] = sg
            f["other_group_r1"] = og
            f["group_share_r1"] = (sg / f["open_cnt_r1"]) if f["open_cnt_r1"] else None
            f["site_area"] = None          # excluded from ranking by design
            f["open_month"] = (t % 12) or 12
            f["uptae"] = u
            X.append(f)
            keep.append(gid)

        p, _ = fit_predict("gbm", (Xtr, ytr, None), (X, None, None), num=rank_cols)
        rows = []
        for gid, s in zip(keep, p):
            g, obs = grade_of(float(s))
            rows.append((u, gid, float(s), g, obs))
        con.executemany("INSERT OR REPLACE INTO grid_score VALUES(?,?,?,?,?)", rows)
        con.commit()
        print(f"  {u:<22} {len(rows):,}격자")

    con.executemany("INSERT OR REPLACE INTO score_meta VALUES(?,?)", [
        ("as_of", f"{t//12}-{t%12 or 12:02d}"),
        ("observed_by_grade", ",".join(f"{o:.4f}" for o in observed)),
        ("overall_survival", f"{float(test[1].mean()):.4f}"),
        ("rank_features", ",".join(rank_cols)),
    ])
    con.commit()
    n = con.execute("SELECT count(*) FROM grid_score").fetchone()[0]
    print(f"\ngrid_score: {n:,}행 · {time.time()-t0:.0f}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
