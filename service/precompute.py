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
from collections import defaultdict
import sys
import time

import numpy as np

from model.asof import (
    AccessIndex,
    AsOf,
    ExtraIndex,
    RestIndex,
    RideIndex,
    group_of,
    load_shops,
    ym,
)
from model.cache import cached_split
from model.recommend import MIN_RING_HISTORY, current_month
from model.train import (
    CONFIRMED_TEST_YEARS,
    CONFIRMED_TRAIN_YEARS,
    DEPLOY,
    SCALED,
    WINNER,
    fit_predict,
)
from pipeline.db import init
from pipeline.grid import neighbors
from service.curve_contract import (
    CURVE_KEY,
    CURVE_MONTHS,
    serialize_curve_payload,
)

# 업태 offered in the UI; anything else is served by 기타.
UPTAE = [
    "한식",
    "기타",
    "호프/통닭",
    "경양식",
    "분식",
    "일식",
    "중국식",
    "외국음식전문점(인도,태국등)",
    "정종/대포집/소주방",
    "통닭(치킨)",
    "식육(숯불구이)",
    "까페",
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS grid_score (
  uptae      TEXT,
  grid_id    TEXT,
  score      REAL,
  grade      INTEGER,      -- 1 = best
  observed   REAL,         -- measured 3y survival of that grade (held-out)
  PRIMARY KEY (uptae, grid_id)
);
CREATE INDEX IF NOT EXISTS ix_score_uptae ON grid_score(uptae, grade);
CREATE TABLE IF NOT EXISTS score_meta (
  k TEXT PRIMARY KEY,
  v TEXT
);
"""


def wilson(k, n, z=1.96):
    """95% CI for a proportion. Wilson rather than normal-approximation because
    the grade cells are proportions near 0.75 where the naive interval is
    asymmetric in the wrong direction and can exceed 1."""
    if not n:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((c - r) / d, (c + r) / d)


def calibration(con, rank_cols, model="gbm"):
    """Grade boundaries + observed survival per grade, from the held-out split.

    The interval is computed here, off the same segmentation that produces the
    point estimate, so the UI can never show a rate and an interval that were
    derived from different splits (A1).
    """
    train, test = cached_split(con, CONFIRMED_TRAIN_YEARS, CONFIRMED_TEST_YEARS, 3)
    p, fitted_ranker = fit_predict(model, train, test, num=rank_cols)
    yte = test[1]
    order = np.argsort(-p)
    n = len(p)
    edges = []
    for i in range(10):
        seg = order[int(n * i / 10) : int(n * (i + 1) / 10)]
        edges.append(float(p[seg].min()))

    grade_by_index = np.array(
        [
            next(
                (grade for grade, edge in enumerate(edges, 1) if score >= edge),
                10,
            )
            for score in p
        ],
        dtype=int,
    )
    observed, ci, seg_n = [], [], []
    for grade in range(1, 11):
        seg = np.flatnonzero(grade_by_index == grade)
        if not len(seg):
            raise RuntimeError(f"홀드아웃 {grade}등급 표본이 없습니다.")
        observed.append(float(yte[seg].mean()))
        ci.append(wilson(int(yte[seg].sum()), len(seg)))
        seg_n.append(len(seg))
    return train, test, edges, observed, ci, seg_n, grade_by_index, fitted_ranker


def predict_with_fitted_ranker(fitted_ranker, model, features):
    """Score current cells with the exact estimator that produced grade edges."""

    ranker, encoder = fitted_ranker
    encoded = encoder.transform(features, scale=model in SCALED)
    return ranker.predict_proba(encoded)[:, 1]


def measured_survival_curves(con, test_metadata, grade_by_index):
    """Measure S(0)..S(36) from the same held-out grade segmentation."""

    licences = defaultdict(list)
    for row in con.execute(
        "SELECT grid_id, uptae, open_y, open_m, close_y, close_m, is_closed "
        "FROM licence WHERE grid_id IS NOT NULL AND open_y IS NOT NULL"
    ):
        opened = ym(row["open_y"], row["open_m"])
        closed = (
            ym(row["close_y"], row["close_m"])
            if row["is_closed"] and row["close_y"]
            else None
        )
        licences[(row["grid_id"], row["uptae"] or "기타", opened)].append(closed)

    grade_by_key = {}
    for index, metadata in enumerate(test_metadata):
        key = (metadata["grid_id"], metadata["uptae"], metadata["open_ym"])
        grade = int(grade_by_index[index])
        previous = grade_by_key.setdefault(key, grade)
        if previous != grade:
            raise RuntimeError("같은 점포 코호트 키가 둘 이상의 등급에 배정됐습니다.")

    durations_by_grade = defaultdict(list)
    for key, grade in grade_by_key.items():
        candidates = licences.get(key)
        if not candidates:
            continue
        opened = key[2]
        durations_by_grade[grade].extend(
            closed - opened if closed is not None else None for closed in candidates
        )

    missing = [grade for grade in range(1, 11) if len(durations_by_grade[grade]) < 200]
    if missing:
        raise RuntimeError(
            "실측 생존곡선 표본이 200개 미만인 등급: "
            + ", ".join(str(grade) for grade in missing)
        )

    curves = {}
    sample_sizes = {}
    for grade in range(1, 11):
        durations = durations_by_grade[grade]
        sample_sizes[grade] = len(durations)
        curves[grade] = [
            sum(1 for duration in durations if duration is None or duration > month)
            / len(durations)
            for month in range(CURVE_MONTHS + 1)
        ]
    if sum(sample_sizes.values()) != len(test_metadata):
        raise RuntimeError(
            "실측 생존곡선 표본수와 홀드아웃 표본수가 일치하지 않습니다."
        )
    return curves, sample_sizes


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
    ap.add_argument(
        "--model",
        default=WINNER,
        help="ranking model — defaults to the E-M tournament winner",
    )
    a = ap.parse_args()

    t0 = time.time()
    con = init()
    con.executescript(SCHEMA)

    # The deployed ranking set lives in model.train.DEPLOY so the served scores
    # and the documented headline can never drift apart (E0).
    rank_cols = list(DEPLOY)
    print(f"모델 {a.model} · 순위 피처 {len(rank_cols)}개")
    print("보정 기준 계산 (홀드아웃)...")
    (
        _train,
        test,
        edges,
        observed,
        ci,
        seg_n,
        grade_by_index,
        fitted_ranker,
    ) = calibration(con, rank_cols, a.model)
    print(
        f"  등급별 실측 생존율: 1등급 {observed[0] * 100:.1f}% "
        f"({ci[0][0] * 100:.1f}-{ci[0][1] * 100:.1f}) ... 10등급 {observed[-1] * 100:.1f}% "
        f"({ci[-1][0] * 100:.1f}-{ci[-1][1] * 100:.1f})"
    )
    curves, curve_n = measured_survival_curves(con, test[2], grade_by_index)
    if any(
        abs(curves[grade][CURVE_MONTHS] - observed[grade - 1]) > 1e-12
        for grade in range(1, 11)
    ):
        raise RuntimeError("36개월 생존곡선과 등급별 실측 생존율이 다릅니다.")
    print(
        "  등급별 36개월 실측 생존곡선: "
        f"1등급 n={curve_n[1]:,} ... 10등급 n={curve_n[10]:,}"
    )

    t = current_month(con)
    ao = AsOf(load_shops(con))
    ai = AccessIndex(con)
    xi, ri, di = ExtraIndex(con), RestIndex(con), RideIndex(con)
    if not ai.available and any(
        c.startswith("station") or c.startswith("transfer") for c in rank_cols
    ):
        raise SystemExit(
            "grid_access 없음 — 접근성 피처가 전부 중앙값 대치되어 "
            "배포 점수가 학습 세트와 어긋난다. 파이프라인 먼저 실행할 것."
        )
    cells = [r["grid_id"] for r in con.execute("SELECT grid_id FROM grid")]

    print(f"격자 {len(cells):,}개 기준상태 계산 (T={t // 12}-{t % 12 or 12:02d})...")
    base = {}
    for i, gid in enumerate(cells):
        f = ao.cell_state(gid, t, None)
        f.update(ao.ring_state(gid, t, None))
        f.update(ai.features(gid))
        f.update(xi.features(gid, t))
        f.update(ri.features(gid, t))
        f.update(di.features(gid, t))
        if (f["prior_surv_n"] or 0) >= MIN_RING_HISTORY:
            base[gid] = f
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1:,}/{len(cells):,}", flush=True)
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
            f["site_area"] = None  # excluded from ranking by design
            f["open_month"] = (t % 12) or 12
            f["uptae"] = u
            X.append(f)
            keep.append(gid)

        p = predict_with_fitted_ranker(fitted_ranker, a.model, X)
        rows = []
        for gid, s in zip(keep, p):
            g, obs = grade_of(float(s))
            rows.append((u, gid, float(s), g, obs))
        con.executemany("INSERT OR REPLACE INTO grid_score VALUES(?,?,?,?,?)", rows)
        print(f"  {u:<22} {len(rows):,}격자")

    rank_features = ",".join(rank_cols)
    con.executemany(
        "INSERT OR REPLACE INTO score_meta VALUES(?,?)",
        [
            ("as_of", f"{t // 12}-{t % 12 or 12:02d}"),
            ("observed_by_grade", ",".join(f"{o:.4f}" for o in observed)),
            # 아래 세 키의 이름은 service/api.py meta() 가 읽는 이름이다. 같은 값을
            # 다른 모양으로 한 번 더 쓰지 않는다 — 두 표현이 생기면 조용히 갈라진다.
            ("observed_by_grade_n", ",".join(str(v) for v in seg_n)),
            ("observed_by_grade_ci_low", ",".join(f"{lo:.4f}" for lo, _ in ci)),
            ("observed_by_grade_ci_high", ",".join(f"{hi:.4f}" for _, hi in ci)),
            ("overall_survival", f"{float(test[1].mean()):.4f}"),
            ("rank_features", rank_features),
            ("rank_model", a.model),
            (
                "rank_train_years",
                ",".join(str(year) for year in CONFIRMED_TRAIN_YEARS),
            ),
            (
                "rank_test_years",
                ",".join(str(year) for year in CONFIRMED_TEST_YEARS),
            ),
            (
                CURVE_KEY,
                serialize_curve_payload(
                    curves,
                    curve_n,
                    a.model,
                    rank_cols,
                    CONFIRMED_TRAIN_YEARS,
                    CONFIRMED_TEST_YEARS,
                ),
            ),
        ],
    )
    con.commit()
    n = con.execute("SELECT count(*) FROM grid_score").fetchone()[0]
    print(f"\ngrid_score: {n:,}행 · {time.time() - t0:.0f}초")
    return 0


if __name__ == "__main__":
    sys.exit(main())
