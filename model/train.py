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


def fit_predict(kind, train, test, num=None):
    """-> (test probabilities, fitted object). Nothing is fitted on test."""
    Xtr, ytr, _ = train
    Xte, _, _ = test
    enc = Encoder(num).fit(Xtr)

    if kind == "logit":
        m = LogisticRegression(max_iter=2000, C=1.0)
        m.fit(enc.transform(Xtr), ytr)
        return m.predict_proba(enc.transform(Xte))[:, 1], (m, enc)

    if kind == "gbm":
        import lightgbm as lgb
        m = lgb.LGBMClassifier(
            n_estimators=400, learning_rate=0.05, num_leaves=31,
            min_child_samples=100, subsample=0.9, colsample_bytree=0.9,
            random_state=0, verbose=-1)
        m.fit(enc.transform(Xtr, scale=False), ytr)
        return m.predict_proba(enc.transform(Xte, scale=False))[:, 1], (m, enc)

    raise ValueError(f"unknown model: {kind}")


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
