"""Models fitted on the training years only.

Everything that learns anything - imputation values, the scaler, the category
list, the model itself - is fitted on train and merely applied to test. Fitting
a scaler on the full set is the quiet version of leakage: test-period
distribution shifts (and 2020-2022 shifted hard) would bleed into training.
"""
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

NUM = ["open_cnt", "open_cnt_r1", "same_uptae_cnt", "same_uptae_r1",
       "openings_36m", "closures_36m", "churn_36m", "growth_36m",
       "prior_surv_3y", "prior_surv_n", "median_area", "site_area", "open_month"]

# v2: ring features that answer questions the v1 set could not - who competes
# for the same demand, how long the neighbours have lasted, whether closures are
# accelerating. All reconstructable from licensing history alone.
NUM2 = NUM + ["prior_surv_1y", "same_group_r1", "other_group_r1", "group_share_r1",
              "median_tenure_r1", "veteran_share_r1", "uptae_entropy_r1",
              "close_accel_r1"]
LOC2 = [c for c in NUM2 if c != "site_area"]

# v3: transit accessibility - the first feature block sourced from outside the
# licensing table, added because licensing-derived aggregates had saturated.
ACCESS = ["station_dist_m", "stations_500m", "stations_1km", "transfer_dist_m"]
NUM3 = NUM2 + ACCESS
LOC3 = [c for c in NUM3 if c != "site_area"]

TREND = ["trend_12m", "trend_growth"]

# Extension candidates (docs/experiment-plan.md E-A "유니버스 확장 후보").
# Measured in the ablation table regardless; entering the deploy set is a
# separate gate decided on internal validation, then confirmed once as a bundle.
TIER1 = ["chain_share_r1", "reoccupy_12m", "vacancy_fill_m", "close_age_m",
         "grid_age_y", "uptae_switch_r1", "density_grad", "openings_12m"]
TIER2 = ["rest_cnt_r1", "rest_openings_36m", "rest_closures_36m",
         "rest_churn_36m", "rest_growth_36m"]
# Tier 3 coverage starts 2015-01, so it can only be judged on a sub-bench.
TIER3 = ["ride_12m", "ride_growth"]

# --- Stage 1 outcome (docs/experiment-plan.md E1·E2, measured 2026-07-27) -----
# E1 adopted: train reaches back to 2005 (holdout AUC 0.5884 -> 0.5982 on LOC2,
#   top decile 73.2% -> 75.0%). The plan's tie-break between "wide period, no
#   accessibility" and "current period, with accessibility" was settled on the
#   INTERNAL validation (2017-2018): LOC2/2005-2016 0.5590 > LOC3/2013-2016
#   0.5568. The wide period cannot carry ACCESS because asof.py has no line
#   opening dates, so a 2005 shop would see stations built after it opened.
# E2 rejected: succession-excluded labels drop the model's edge over prior_surv
#   to 0.0267, below the pre-registered 0.0350. Labels stay as they are.
CONFIRMED_TRAIN_YEARS = list(range(2005, 2019))
CONFIRMED_EXCLUDE_SUCCESSION = False

# --- Stage 2 outcome (docs/experiment-plan.md E-M, 2026-07-27) ----------------
# RandomForest(300, min_samples_leaf=50) won the internal validation (0.5685 vs
# the incumbent gbm's 0.5593) and cleared the holdout gate: paired-bootstrap
# dAUC +0.0043, 95% CI [+0.0022, +0.0063], deciles monotone. Its Brier is worse
# than gbm's (0.2334 vs 0.2317) - the API serves per-grade OBSERVED survival,
# not raw probabilities, so ranking quality is what the gate measures.
WINNER = "rf"

# The set actually served. service/precompute.py reads this and nothing else, so
# "what the UI ranks by" and "what the headline was measured on" cannot drift.
# Changing it requires re-running precompute and updating §4-C.
DEPLOY = LOC2


class Encoder:
    """Fit on train: median imputation + category vocabulary + scaling."""

    def __init__(self, num=None):
        self.NUM = list(num) if num else list(NUM)
        self.med = {}
        self.cats = []
        self.scaler = StandardScaler()

    def fit(self, X):
        for k in self.NUM:
            vals = [f.get(k) for f in X if f.get(k) is not None]
            self.med[k] = float(np.median(vals)) if vals else 0.0
        seen = {}
        for f in X:
            seen[f["uptae"]] = seen.get(f["uptae"], 0) + 1
        # keep categories with enough support; the rest fold into __other__
        self.cats = sorted(k for k, v in seen.items() if v >= 50)
        self.scaler.fit(self._raw(X))
        return self

    def _raw(self, X):
        rows = []
        for f in X:
            r = [float(f[k]) if f.get(k) is not None else self.med[k] for k in self.NUM]
            oh = [0.0] * (len(self.cats) + 1)
            try:
                oh[self.cats.index(f["uptae"])] = 1.0
            except ValueError:
                oh[-1] = 1.0
            rows.append(r + oh)
        return np.asarray(rows, dtype=float)

    def transform(self, X, scale=True):
        raw = self._raw(X)
        return self.scaler.transform(raw) if scale else raw

    @property
    def names(self):
        return self.NUM + [f"uptae={c}" for c in self.cats] + ["uptae=__other__"]


# Candidates for the E-M tournament. Trees read raw (median-imputed) columns;
# only the distance/gradient learners get the scaler. XGBoost is absent from the
# environment and is deliberately not installed - recorded as an excluded
# candidate rather than a silently missing one.
SCALED = {"logit", "mlp"}
# lbfgs on a fixed design is reproducible, so a seed sweep would fit the same
# model five times. Callers averaging over seeds short-circuit on this set.
DETERMINISTIC = {"logit"}


def build_model(kind, seed=0, params=None):
    """Construct an unfitted candidate. `seed` is threaded everywhere it matters
    so the ablation programme can average over seeds (E-A step 4)."""
    p = dict(params or {})

    if kind == "logit":
        return LogisticRegression(max_iter=2000, C=p.get("C", 1.0))

    if kind == "gbm":
        import lightgbm as lgb
        return lgb.LGBMClassifier(
            n_estimators=p.get("n_estimators", 400), learning_rate=p.get("learning_rate", 0.05),
            num_leaves=p.get("num_leaves", 31), min_child_samples=p.get("min_child_samples", 100),
            subsample=0.9, colsample_bytree=0.9, random_state=seed, verbose=-1, n_jobs=8)

    if kind in ("rf", "et"):
        # rf defaults ARE the E-M winner's settings, so `--model rf` anywhere in
        # the repo reproduces the tournament winner without threading params.
        from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
        cls = RandomForestClassifier if kind == "rf" else ExtraTreesClassifier
        return cls(n_estimators=p.get("n_estimators", 300),
                   min_samples_leaf=p.get("min_samples_leaf", 50 if kind == "rf" else 20),
                   max_features=p.get("max_features", "sqrt"),
                   random_state=seed, n_jobs=8)

    if kind == "hgb":
        from sklearn.ensemble import HistGradientBoostingClassifier
        return HistGradientBoostingClassifier(
            max_iter=p.get("max_iter", 400), learning_rate=p.get("learning_rate", 0.05),
            max_leaf_nodes=p.get("max_leaf_nodes", 31),
            min_samples_leaf=p.get("min_samples_leaf", 100), random_state=seed)

    if kind == "mlp":
        from sklearn.neural_network import MLPClassifier
        return MLPClassifier(hidden_layer_sizes=p.get("hidden_layer_sizes", (32,)),
                             alpha=p.get("alpha", 1e-3), max_iter=p.get("max_iter", 300),
                             early_stopping=True, n_iter_no_change=10, random_state=seed)

    raise ValueError(f"unknown model: {kind}")


def fit_predict(kind, train, test, num=None, seed=0, params=None, enc=None):
    """-> (test probabilities, (model, encoder)). Nothing is fitted on test.

    `enc` accepts a pre-fitted encoder so a seed sweep does not re-fit the
    imputer/scaler five times over the same training rows.
    """
    Xtr, ytr, _ = train
    Xte, _, _ = test
    enc = enc or Encoder(num).fit(Xtr)
    scale = kind in SCALED
    m = build_model(kind, seed, params)
    m.fit(enc.transform(Xtr, scale=scale), ytr)
    return m.predict_proba(enc.transform(Xte, scale=scale))[:, 1], (m, enc)


def weights(train, top=20, num=None):
    """Standardized logistic coefficients - the interpretable 'weights'."""
    Xtr, ytr, _ = train
    enc = Encoder(num).fit(Xtr)
    m = LogisticRegression(max_iter=2000, C=1.0)
    m.fit(enc.transform(Xtr), ytr)
    pairs = sorted(zip(enc.names, m.coef_[0]), key=lambda kv: -abs(kv[1]))
    return pairs[:top], m, enc


if __name__ == "__main__":
    import argparse

    from pipeline.db import init

    from .evaluate import TEST_YEARS, TRAIN_YEARS, load_split

    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="logit")
    ap.add_argument("--horizon", type=int, default=3)
    a = ap.parse_args()

    con = init()
    train, test = load_split(con, TRAIN_YEARS, TEST_YEARS, a.horizon, verbose=False)

    if a.model == "logit":
        pairs, m, enc = weights(train)
        base = train[1].mean()
        print(f"로지스틱 회귀 계수 (표준화, 양수=생존↑)   학습 n={len(train[1]):,} "
              f"기저 생존율 {base*100:.1f}%\n")
        print(f"  {'피처':<24} {'계수':>9}   해석")
        for n, c in pairs:
            arrow = "생존 ↑" if c > 0 else "생존 ↓"
            print(f"  {n:<24} {c:>+9.4f}   {arrow}")
    else:
        p, (m, enc) = fit_predict(a.model, train, test)
        if hasattr(m, "feature_importances_"):
            imp = sorted(zip(enc.names, m.feature_importances_), key=lambda kv: -kv[1])[:20]
            print(f"{a.model} 중요도\n")
            for n, v in imp:
                print(f"  {n:<24} {v:>8.0f}")
