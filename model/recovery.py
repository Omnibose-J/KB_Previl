"""Time-split succession model experiment and probability calibration.

The target starts when a tenancy closes. Features are therefore replayed at
the month before closure, and the split follows closure year. Post-closure
fields from addr_tenancy are labels only and never enter the feature set.
"""

import argparse
from functools import lru_cache
import hashlib
import io
import inspect
import json
import pickle
import sqlite3
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

from pipeline.config import DB_PATH

from .asof import AsOf, load_shops
from .cache import CACHE_DIR
from .evaluate import baseline_by_uptae
from .train import LOC2, build_model, Encoder


TRAIN_YEARS = tuple(range(2005, 2022))
CALIBRATION_YEARS = (2022,)
HOLDOUT_YEARS = (2023,)
RECOVERY_FEATURES = tuple(name for name in LOC2 if name != "open_month")
MODEL_KIND = "gbm"
MIN_AUC_GAIN = 0.005
CALIBRATION_BINS = 10
DATASET_CACHE_VERSION = "close-year-loc2-v1"
MODEL_VERSION = "m2-gbm-close-2005-2021-cal-2022-v1"
SERVING_TABLE_SQL = """
CREATE TABLE succession_score_next (
  grid_id          TEXT NOT NULL,
  uptae            TEXT NOT NULL,
  succession_prob  REAL NOT NULL CHECK (
    succession_prob >= 0 AND succession_prob <= 1
  ),
  recovery_source  TEXT NOT NULL CHECK (recovery_source = 'm2'),
  as_of_ym         INTEGER NOT NULL,
  model_version    TEXT NOT NULL,
  PRIMARY KEY (grid_id, uptae)
)
"""


def _connect_read_only():
    path = DB_PATH.resolve()
    if not path.exists():
        raise FileNotFoundError(f"KB_DB not found: {path}")
    con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _validate_split():
    groups = (set(TRAIN_YEARS), set(CALIBRATION_YEARS), set(HOLDOUT_YEARS))
    if any(left & right for i, left in enumerate(groups) for right in groups[i + 1:]):
        raise ValueError("recovery year splits overlap")
    if not max(TRAIN_YEARS) < min(CALIBRATION_YEARS) < min(HOLDOUT_YEARS):
        raise ValueError("recovery split is not chronological")


def _dataset_fingerprint(con):
    h = hashlib.sha256()
    root = __file__.rsplit("\\", 1)[0] if "\\" in __file__ else __file__.rsplit("/", 1)[0]
    with io.open(f"{root}/asof.py", "rb") as source:
        h.update(source.read())
    contract = {
        "version": DATASET_CACHE_VERSION,
        "train_years": TRAIN_YEARS,
        "calibration_years": CALIBRATION_YEARS,
        "holdout_years": HOLDOUT_YEARS,
        "features": RECOVERY_FEATURES,
        "builder": inspect.getsource(_build_datasets),
        "feature_at": inspect.getsource(features_before_closure),
    }
    h.update(
        json.dumps(contract, sort_keys=True, ensure_ascii=True).encode()
    )
    for row in con.execute(
        """
        SELECT
          mgtno, uptae, open_y, open_m, close_y, close_m,
          is_closed, site_area, grid_id
        FROM licence
        ORDER BY mgtno
        """
    ):
        h.update(repr(tuple(row)).encode())
    for row in con.execute(
        """
        SELECT mgtno, close_ym, succeeded
        FROM addr_tenancy
        ORDER BY mgtno
        """
    ):
        h.update(repr(tuple(row)).encode())
    h.update(str(DB_PATH.resolve()).encode())
    return h.hexdigest()[:16]


def features_before_closure(asof, grid_id, uptae, close_ym):
    year, month = divmod(close_ym, 100)
    if year < 1 or not 1 <= month <= 12:
        raise ValueError(f"invalid close_ym: {close_ym}")
    # model.asof month index is year * 12 + month. The successor may open in
    # the closure month, so the latest safe feature month is one month earlier.
    cutoff = year * 12 + month - 1
    features = asof.cell_state(grid_id, cutoff, uptae)
    features.update(asof.ring_state(grid_id, cutoff, uptae))
    features["uptae"] = uptae
    return features


def _build_datasets(con):
    shops = load_shops(con)
    asof = AsOf(shops)

    @lru_cache(maxsize=None)
    def location_state(grid_id, close_ym, uptae):
        return features_before_closure(asof, grid_id, uptae, close_ym)

    years = TRAIN_YEARS + CALIBRATION_YEARS + HOLDOUT_YEARS
    placeholders = ",".join("?" for _ in years)
    rows = con.execute(
        f"""
        SELECT
          a.mgtno,
          a.close_ym,
          a.succeeded,
          l.grid_id,
          COALESCE(l.uptae, '기타') AS uptae
        FROM addr_tenancy a
        JOIN licence l ON l.mgtno = a.mgtno
        WHERE a.succeeded IS NOT NULL
          AND a.close_ym / 100 IN ({placeholders})
          AND l.grid_id IS NOT NULL
        ORDER BY a.close_ym, a.mgtno
        """,
        years,
    )

    output = {
        "train": ([], [], []),
        "calibration": ([], [], []),
        "holdout": ([], [], []),
    }
    for row in rows:
        year = row["close_ym"] // 100
        if year in TRAIN_YEARS:
            split = "train"
        elif year in CALIBRATION_YEARS:
            split = "calibration"
        else:
            split = "holdout"
        features = dict(
            location_state(row["grid_id"], row["close_ym"], row["uptae"])
        )
        X, y, meta = output[split]
        X.append(features)
        y.append(int(row["succeeded"]))
        meta.append(
            {
                "mgtno": row["mgtno"],
                "grid_id": row["grid_id"],
                "close_ym": row["close_ym"],
            }
        )

    built = {}
    for split, (X, y, meta) in output.items():
        if not X or len(set(y)) != 2:
            raise RuntimeError(f"{split} recovery cohort is missing or single-class")
        built[split] = (X, np.asarray(y, dtype=np.int8), meta)
    return built


def _load_datasets(con):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = CACHE_DIR / f"recovery_{_dataset_fingerprint(con)}.pkl"
    if path.exists():
        with io.open(path, "rb") as source:
            return pickle.load(source)
    datasets = _build_datasets(con)
    with io.open(path, "wb") as target:
        pickle.dump(datasets, target, protocol=4)
    return datasets


def _encode(encoder, X):
    values = encoder.transform(X, scale=False)
    return pd.DataFrame(
        values,
        columns=[f"f{index}" for index in range(values.shape[1])],
    )


def _predict(model, encoder, split):
    X, _y, _meta = split
    return model.predict_proba(_encode(encoder, X))[:, 1]


def _fit_calibration(y, probabilities, bins=CALIBRATION_BINS):
    probabilities = np.asarray(probabilities, dtype=float)
    interior = np.unique(
        np.quantile(probabilities, np.linspace(0, 1, bins + 1)[1:-1])
    )
    assignments = np.searchsorted(interior, probabilities, side="right")
    rates = []
    rows = []
    for index in range(len(interior) + 1):
        mask = assignments == index
        if not mask.any():
            raise RuntimeError(f"empty calibration bin: {index}")
        rate = float(np.mean(y[mask]))
        rates.append(rate)
        rows.append(
            {
                "bin": index + 1,
                "raw_mean": float(np.mean(probabilities[mask])),
                "observed": rate,
                "n": int(mask.sum()),
            }
        )
    return interior, np.asarray(rates), rows


def _apply_calibration(probabilities, interior, rates):
    assignments = np.searchsorted(interior, probabilities, side="right")
    return rates[assignments], assignments


@lru_cache(maxsize=1)
def experiment():
    _validate_split()
    with _connect_read_only() as con:
        datasets = _load_datasets(con)

    train = datasets["train"]
    calibration = datasets["calibration"]
    holdout = datasets["holdout"]
    encoder = Encoder(RECOVERY_FEATURES).fit(train[0])
    model = build_model(MODEL_KIND, seed=0)
    model.fit(_encode(encoder, train[0]), train[1])

    calibration_raw = _predict(model, encoder, calibration)
    holdout_raw = _predict(model, encoder, holdout)
    edges, rates, calibration_rows = _fit_calibration(
        calibration[1], calibration_raw
    )
    holdout_calibrated, holdout_bins = _apply_calibration(
        holdout_raw, edges, rates
    )

    by_uptae = baseline_by_uptae(train[0], train[1], holdout[0])
    previous_rate = float(np.mean(calibration[1]))
    previous_constant = np.full(len(holdout[1]), previous_rate)
    model_auc = roc_auc_score(holdout[1], holdout_raw)
    baseline_auc = roc_auc_score(holdout[1], by_uptae)
    calibrated_brier = brier_score_loss(holdout[1], holdout_calibrated)
    baseline_brier = brier_score_loss(holdout[1], previous_constant)

    holdout_rows = []
    for index, calibration_row in enumerate(calibration_rows):
        mask = holdout_bins == index
        holdout_rows.append(
            {
                **calibration_row,
                "applied": rates[index],
                "holdout_observed": (
                    float(np.mean(holdout[1][mask])) if mask.any() else None
                ),
                "holdout_n": int(mask.sum()),
            }
        )

    auc_gain = model_auc - baseline_auc
    brier_gain = baseline_brier - calibrated_brier
    return {
        "datasets": datasets,
        "model": model,
        "encoder": encoder,
        "calibration_edges": edges,
        "calibration_rates": rates,
        "model_auc": model_auc,
        "model_raw_brier": brier_score_loss(holdout[1], holdout_raw),
        "baseline_auc": baseline_auc,
        "baseline_uptae_brier": brier_score_loss(holdout[1], by_uptae),
        "baseline_brier": baseline_brier,
        "calibrated_brier": calibrated_brier,
        "auc_gain": auc_gain,
        "brier_gain": brier_gain,
        "adopted": auc_gain >= MIN_AUC_GAIN and brier_gain >= 0,
        "previous_rate": previous_rate,
        "calibration_rows": holdout_rows,
    }


def build_serving_table(result):
    if not result["adopted"]:
        raise RuntimeError(
            "M2 failed the holdout gate; refusing to replace serving data"
        )
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        cutoff = con.execute(
            "SELECT MAX(open_y * 12 + COALESCE(open_m, 1)) FROM licence "
            "WHERE open_y IS NOT NULL"
        ).fetchone()[0]
        if cutoff is None:
            raise RuntimeError("licence observation cutoff is unavailable")
        as_of_ym = (cutoff // 12) * 100 + (cutoff % 12)
        if cutoff % 12 == 0:
            as_of_ym = (cutoff // 12 - 1) * 100 + 12

        shops = load_shops(con)
        asof = AsOf(shops)
        pairs = con.execute(
            "SELECT grid_id, uptae FROM grid_score ORDER BY grid_id, uptae"
        ).fetchall()
        if not pairs:
            raise RuntimeError("grid_score has no serving candidates")

        con.execute("DROP TABLE IF EXISTS succession_score_next")
        con.execute(SERVING_TABLE_SQL)
        model = result["model"]
        encoder = result["encoder"]
        edges = result["calibration_edges"]
        rates = result["calibration_rates"]
        batch_size = 5000
        written = 0
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start:start + batch_size]
            features = []
            for row in batch:
                state = asof.cell_state(row["grid_id"], cutoff, row["uptae"])
                state.update(asof.ring_state(row["grid_id"], cutoff, row["uptae"]))
                state["uptae"] = row["uptae"]
                features.append(state)
            raw = model.predict_proba(_encode(encoder, features))[:, 1]
            calibrated, _assignments = _apply_calibration(raw, edges, rates)
            con.executemany(
                """
                INSERT INTO succession_score_next (
                  grid_id, uptae, succession_prob, recovery_source,
                  as_of_ym, model_version
                ) VALUES (?, ?, ?, 'm2', ?, ?)
                """,
                [
                    (
                        row["grid_id"],
                        row["uptae"],
                        float(probability),
                        as_of_ym,
                        MODEL_VERSION,
                    )
                    for row, probability in zip(batch, calibrated)
                ],
            )
            written += len(batch)

        invalid = con.execute(
            """
            SELECT COUNT(*) FROM succession_score_next
            WHERE succession_prob NOT BETWEEN 0 AND 1
               OR recovery_source <> 'm2'
               OR model_version <> ?
            """,
            (MODEL_VERSION,),
        ).fetchone()[0]
        distinct_probabilities = con.execute(
            "SELECT COUNT(DISTINCT succession_prob) "
            "FROM succession_score_next"
        ).fetchone()[0]
        if invalid or written != len(pairs):
            raise RuntimeError(
                f"serving table invariant failed: written={written}, "
                f"expected={len(pairs)}, invalid={invalid}"
            )
        if distinct_probabilities != len(rates):
            raise RuntimeError(
                "serving table does not contain every calibrated bin rate: "
                f"{distinct_probabilities} != {len(rates)}"
            )

        con.execute("DROP TABLE IF EXISTS succession_score")
        con.execute(
            "ALTER TABLE succession_score_next RENAME TO succession_score"
        )
        con.commit()
        print(
            f"succession_score built: rows={written:,}"
            f" · calibrated_rates={distinct_probabilities}"
            f" · as_of_ym={as_of_ym}"
            f" · model={MODEL_VERSION}"
        )
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def _cohort_line(name, years, split):
    _X, y, _meta = split
    span = str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"
    return f"  {name:<10} close_year={span}  n={len(y):,}  succession={y.mean():.4f}"


def print_holdout(result):
    datasets = result["datasets"]
    print("분할 축: 폐업연도(close_ym), random split 사용 안 함")
    print(_cohort_line("train", TRAIN_YEARS, datasets["train"]))
    print(
        _cohort_line(
            "calibration", CALIBRATION_YEARS, datasets["calibration"]
        )
    )
    print(_cohort_line("holdout", HOLDOUT_YEARS, datasets["holdout"]))
    print(f"피처 시점: close_ym - 1 · observable LOC2 {len(RECOVERY_FEATURES)}개")
    print("\n2023 holdout")
    print(
        "  by_uptae(train only)"
        f"  AUC={result['baseline_auc']:.4f}"
        f"  Brier={result['baseline_uptae_brier']:.4f}"
    )
    print(
        f"  M2 raw               AUC={result['model_auc']:.4f}"
        f"  Brier={result['model_raw_brier']:.4f}"
    )
    print(
        f"  2022 rate constant   AUC=0.5000"
        f"  Brier={result['baseline_brier']:.4f}"
    )
    print(
        f"  M2 calibrated        Brier={result['calibrated_brier']:.4f}"
    )
    print(
        f"\n채택 문턱: ΔAUC >= {MIN_AUC_GAIN:.3f}"
        " and calibrated Brier <= previous-year constant"
    )
    print(
        f"실측: ΔAUC={result['auc_gain']:+.4f}"
        f" · ΔBrier={result['brier_gain']:+.4f}"
        f" -> {'ADOPT' if result['adopted'] else 'NEGATIVE_RESULT'}"
    )


def print_calibration(result):
    print(
        "보정 학습: 2022 raw score 분위별 실측 승계율"
        " · 적용 검증: 2023 holdout"
    )
    print(
        f"  {'bin':>3} {'cal raw':>9} {'applied':>9} {'cal n':>8}"
        f" {'holdout obs':>12} {'holdout n':>10}"
    )
    for row in result["calibration_rows"]:
        observed = row["holdout_observed"]
        holdout_text = "null" if observed is None else f"{observed:.4f}"
        print(
            f"  {row['bin']:>3} {row['raw_mean']:>9.4f}"
            f" {row['applied']:>9.4f} {row['n']:>8,}"
            f" {holdout_text:>12} {row['holdout_n']:>10,}"
        )
    print(
        f"\n2023 Brier: previous-year constant={result['baseline_brier']:.4f}"
        f" · calibrated={result['calibrated_brier']:.4f}"
    )
    print("서빙 후보 확률은 raw score가 아니라 applied 실측률이다.")


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--holdout", action="store_true")
    mode.add_argument("--calibration", action="store_true")
    mode.add_argument("--build-serving", action="store_true")
    args = parser.parse_args()
    result = experiment()
    if args.holdout:
        print_holdout(result)
    elif args.calibration:
        print_calibration(result)
    else:
        build_serving_table(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
