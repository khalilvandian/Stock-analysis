"""Experiments: correlation analysis and walk-forward models on the panel.

Features are converted to percentile ranks within each cohort (0 = lowest in that year's
S&P 500, 1 = highest; missing = 0.5). That makes every feature comparable across years and
industries, makes outliers harmless, and keeps coefficients readable: "moving from the
cheapest to the most expensive decile changes the predicted percentile by ...".

Targets are also within-cohort: the percentile rank of a continuous label, or a binary
label. So the models answer "which stocks will do better than the other S&P 500 members
bought on the same day", not "will the market go up", which fundamentals cannot predict.

Validation is walk-forward with purging: a test cohort T is predicted by a model trained
only on cohorts c with c + horizon <= T, i.e. whose outcome was fully known on date T.
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
)
from sklearn.inspection import permutation_importance
from sklearn.linear_model import (
    ElasticNet,
    Lasso,
    LinearRegression,
    LogisticRegression,
    Ridge,
)
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from stock_analysis.predict.features import FUNDAMENTAL, PRICE

EXCLUDE = {"market_cap", "enterprise_value", "years_of_history"}  # raw $ levels / bookkeeping
NUMERIC = [c for c in FUNDAMENTAL + PRICE + ["ey_vs_own_median"] if c not in EXCLUDE]
BINARY_FEATURES = ["loss_now"]
SECTORS = [
    "Communication",
    "Consumer discretionary",
    "Consumer staples",
    "Energy",
    "Financials",
    "Health care",
    "Industrials",
    "Materials",
    "Real estate",
    "Technology",
    "Utilities",
]
LYNCH = ["fast_grower", "stalwart", "slow_grower", "cyclical", "turnaround", "asset_play"]


def strict_screen(df: pd.DataFrame) -> pd.Series:
    """Babak's strict must-haves (analysis/screen.py) from the point-in-time features."""
    return (
        (df.cash_to_short_term_debt >= 1)
        & (df.cash_to_long_term_debt >= 0.05)
        & (df.net_debt_to_ebitda.fillna(np.inf) <= 4.5)
        & (df.interest_cover >= 4)
        & (df.earnings_yield > 0)
    ).astype(float)


def design(df: pd.DataFrame, numeric: list[str] | None = None) -> pd.DataFrame:
    """Within-cohort percentile ranks of the numeric features plus sector and Lynch dummies.

    Yes/no features stay 0/1: ranking them would give "no" a value that depends on how many
    companies said "yes" that year.
    """
    numeric = [c for c in (numeric or NUMERIC) if c not in BINARY_FEATURES]
    ranks = df.groupby("cohort")[numeric].rank(pct=True).fillna(0.5)
    dummies = pd.DataFrame(index=df.index)
    for c in BINARY_FEATURES:
        dummies[c] = df[c].fillna(0.0)
    for s in SECTORS:
        dummies[f"sector={s}"] = (df.sector == s).astype(float)
    for c in LYNCH:
        dummies[f"lynch={c}"] = (df.lynch_category == c).astype(float)
    dummies["strict_screen"] = strict_screen(df)
    return pd.concat([ranks, dummies], axis=1)


def target(df: pd.DataFrame, label: str) -> pd.Series:
    y = df[label]
    if set(y.dropna().unique()) <= {0.0, 1.0}:
        return y
    return y.groupby(df.cohort).rank(pct=True)


# ---------------------------------------------------------------- univariate correlations


def univariate_ic(df: pd.DataFrame, label: str, features: list[str] | None = None) -> pd.DataFrame:
    """Spearman correlation of each feature with the label, per cohort, then summarised.

    ic_mean: average correlation; hit: share of cohorts with the same sign as the average;
    t: ic_mean / std * sqrt(cohorts) (overstated when label windows overlap).
    """
    features = features or NUMERIC
    rows = []
    for f in features:
        ics = []
        for _, g in df.groupby("cohort"):
            x, y = g[f], g[label]
            ok = x.notna() & y.notna()
            if ok.sum() >= 50 and x[ok].nunique() > 2:
                ics.append(spearmanr(x[ok], y[ok]).statistic)
        if not ics:
            continue
        ics = np.array(ics)
        mean = ics.mean()
        sd = ics.std(ddof=1) if len(ics) > 1 else np.nan
        rows.append(
            {
                "feature": f,
                "ic_mean": mean,
                "ic_std": sd,
                "t": mean / sd * np.sqrt(len(ics)) if sd and sd > 0 else np.nan,
                "hit": float(np.mean(np.sign(ics) == np.sign(mean))),
                "cohorts": len(ics),
                "coverage": float(df[f].notna().mean()),
            }
        )
    return pd.DataFrame(rows).sort_values("ic_mean", key=abs, ascending=False)


def quintile_table(df: pd.DataFrame, feature: str, label: str) -> pd.Series:
    """Average label in each within-cohort quintile of the feature (1 = lowest)."""
    q = df.groupby("cohort")[feature].transform(
        lambda s: (
            pd.qcut(s.rank(method="first"), 5, labels=False) + 1
            if s.notna().sum() >= 25
            else np.nan
        )
    )
    return df.groupby(q)[label].mean()


# ---------------------------------------------------------------- fixed scores

# Fixed, unfitted scores built from factors documented in the literature before this study
# (sign: +1 = higher is better). Nothing is estimated, so every cohort is out of sample
# for the weights; the choice of features is the only judgement (see report 15).
FIXED_SCORES = {
    "Quality + calm": {"roa": 1, "max_dd_3y": -1, "share_change": -1, "eps_big_drops": -1},
    "Profitability + low drawdown": {"roa": 1, "max_dd_3y": -1},
    "Low volatility only": {"vol_1y": -1},
    "Profitability only": {"roa": 1},
}


def fixed_score(df: pd.DataFrame, spec: dict[str, int]) -> pd.Series:
    """Equal-weight average of within-cohort percentiles (flipped where lower is better)."""
    parts = []
    for f, sign in spec.items():
        r = df.groupby("cohort")[f].rank(pct=True).fillna(0.5)
        parts.append(r if sign > 0 else 1 - r)
    return sum(parts) / len(parts)


def evaluate_score(df: pd.DataFrame, score: pd.Series, key: str = "y5") -> pd.DataFrame:
    """Per cohort: AUC for "good", rank correlation with excess return and Martin ratio,
    share "good" and average outcome in the top fifth versus everyone."""
    rows = []
    for c, g in df.assign(_s=score).groupby("cohort"):
        top = g._s >= g._s.quantile(0.8)
        bottom = g._s <= g._s.quantile(0.2)
        rows.append(
            {
                "cohort": c,
                "auc_good": roc_auc_score(g[f"{key}_good"], g._s),
                "ic_excess_cagr": spearmanr(g._s, g[f"{key}_excess_cagr"]).statistic,
                "ic_martin": spearmanr(g._s, g[f"{key}_martin"]).statistic,
                "good_top_fifth": g[f"{key}_good"][top].mean(),
                "good_all": g[f"{key}_good"].mean(),
                "excess_top_fifth": g[f"{key}_excess_cagr"][top].mean(),
                "excess_bottom_fifth": g[f"{key}_excess_cagr"][bottom].mean(),
                "excess_all": g[f"{key}_excess_cagr"].mean(),
                "max_dd_top_fifth": g[f"{key}_max_dd"][top].mean(),
                "max_dd_all": g[f"{key}_max_dd"].mean(),
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- models


class RankComposite:
    """Transparent baseline: average of the k features most correlated with the target in
    the training cohorts, each signed by its correlation (a "factor score").

    Because features are within-cohort percentiles, the score is itself a percentile-like
    number and the model is a list of k features with + or - signs.
    """

    def __init__(self, k: int = 10):
        self.k = k

    def fit(self, X: pd.DataFrame, y: pd.Series):
        ics = X.apply(lambda c: spearmanr(c, y).statistic if c.nunique() > 1 else 0.0)
        ics = ics.fillna(0.0)
        self.weights_ = np.sign(ics[ics.abs().nlargest(self.k).index])
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (X[self.weights_.index] @ self.weights_).to_numpy() / self.k

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        s = (self.predict(X) + 1) / 2
        return np.column_stack([1 - s, s])


def regressors(seed: int) -> dict:
    return {
        "Factor score (top 10)": RankComposite(10),
        "OLS": LinearRegression(),
        "Ridge": Ridge(alpha=30.0),
        "Lasso": Lasso(alpha=0.002, max_iter=5000),
        "ElasticNet": ElasticNet(alpha=0.004, l1_ratio=0.5, max_iter=5000),
        "Tree (depth 3)": DecisionTreeRegressor(
            max_depth=3, min_samples_leaf=100, random_state=seed
        ),
        "Random forest": RandomForestRegressor(
            n_estimators=300,
            max_depth=6,
            min_samples_leaf=40,
            max_features=0.33,
            n_jobs=-1,
            random_state=seed,
        ),
        "Gradient boosting": HistGradientBoostingRegressor(
            max_depth=3,
            learning_rate=0.04,
            max_iter=250,
            min_samples_leaf=60,
            l2_regularization=1.0,
            random_state=seed,
        ),
    }


def classifiers(seed: int) -> dict:
    return {
        "Factor score (top 10)": RankComposite(10),
        "Logistic (L2)": LogisticRegression(C=0.1, max_iter=2000),
        "Logistic (L1)": LogisticRegression(C=0.05, penalty="l1", solver="liblinear"),
        "Tree (depth 3)": DecisionTreeClassifier(
            max_depth=3, min_samples_leaf=100, random_state=seed
        ),
        "Random forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=6,
            min_samples_leaf=40,
            max_features=0.33,
            n_jobs=-1,
            random_state=seed,
        ),
        "Gradient boosting": HistGradientBoostingClassifier(
            max_depth=3,
            learning_rate=0.04,
            max_iter=250,
            min_samples_leaf=60,
            l2_regularization=1.0,
            random_state=seed,
        ),
    }


def test_cohorts(df: pd.DataFrame, horizon: int, min_train: int) -> list[int]:
    cohorts = sorted(df.cohort.unique())
    return [t for t in cohorts if sum(c + horizon <= t for c in cohorts) >= min_train]


def walk_forward(
    df: pd.DataFrame,
    label: str,
    horizon: int,
    kind: str = "regression",
    seed: int = 7,
    min_train: int = 2,
    models: dict | None = None,
    numeric: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Out-of-sample predictions and per-cohort scores for every model.

    Returns (scores, predictions). Scores per (model, test cohort):
      regression: ic (Spearman of prediction vs actual), r2 (vs predicting the train mean),
                  top_q (mean actual percentile of the top predicted fifth; 0.5 = no skill)
      classification: auc, brier_skill (vs the base rate), top_q (share "good" in the top
                  predicted fifth), base (share "good" in the cohort)
    Plus excess_top_q / excess_bottom_q: average 5-year excess return over the index of the
    top and bottom predicted fifth (what the ranking would have meant in money).
    """
    df = df[df[label].notna()].copy()
    X = design(df, numeric)
    y = target(df, label)
    models = models or (regressors(seed) if kind == "regression" else classifiers(seed))
    excess_col = label.split("_")[0] + "_excess_cagr"
    rows, preds = [], []
    for t in test_cohorts(df, horizon, min_train):
        tr = df.cohort + horizon <= t
        te = df.cohort == t
        if te.sum() < 50:
            continue
        for name, model in models.items():
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model.fit(X[tr], y[tr])
                p = (
                    model.predict_proba(X[te])[:, 1]
                    if kind == "classification"
                    else model.predict(X[te])
                )
            yt = y[te]
            top = p >= np.quantile(p, 0.8)
            bottom = p <= np.quantile(p, 0.2)
            row = {"model": name, "cohort": t, "n_train": int(tr.sum()), "n_test": int(te.sum())}
            if kind == "regression":
                row["ic"] = spearmanr(p, yt).statistic if np.std(p) > 0 else 0.0
                base = y[tr].mean()
                row["r2"] = 1 - ((yt - p) ** 2).sum() / ((yt - base) ** 2).sum()
                row["top_q"] = yt[top].mean()
            else:
                row["auc"] = roc_auc_score(yt, p) if yt.nunique() == 2 else np.nan
                base = y[tr].mean()
                row["brier_skill"] = 1 - brier_score_loss(yt, p) / brier_score_loss(
                    yt, np.full(len(yt), base)
                )
                row["top_q"] = yt[top].mean()
                row["base"] = yt.mean()
            ex = df.loc[te, excess_col]
            row["excess_top_q"] = ex[top].mean()
            row["excess_bottom_q"] = ex[bottom].mean()
            row["excess_all"] = ex.mean()
            rows.append(row)
            preds.append(
                pd.DataFrame(
                    {"model": name, "cohort": t, "ticker": df.loc[te, "ticker"], "pred": p, "y": yt}
                )
            )
    return pd.DataFrame(rows), pd.concat(preds, ignore_index=True)


def summarise(scores: pd.DataFrame) -> pd.DataFrame:
    metric_cols = [c for c in scores.columns if c not in ("model", "cohort", "n_train", "n_test")]
    agg = scores.groupby("model")[metric_cols].mean()
    main = "ic" if "ic" in scores else "auc"
    centre = 0.0 if main == "ic" else 0.5
    agg[f"{main}_positive_cohorts"] = scores.groupby("model")[main].apply(
        lambda s: (s > centre).mean()
    )
    agg["cohorts"] = scores.groupby("model").size()
    return agg.sort_values(main, ascending=False)


def importance(
    df: pd.DataFrame, label: str, horizon: int, kind: str, seed: int = 7, min_train: int = 2
) -> pd.DataFrame:
    """Permutation importance of the gradient-boosting model on each walk-forward test
    cohort (out of sample), averaged; plus Ridge/Logistic coefficients fitted on all rows."""
    df = df[df[label].notna()].copy()
    X = design(df)
    y = target(df, label)
    gb = (regressors if kind == "regression" else classifiers)(seed)["Gradient boosting"]
    scoring = None if kind == "regression" else "roc_auc"
    imps = []
    for t in test_cohorts(df, horizon, min_train):
        tr = df.cohort + horizon <= t
        te = df.cohort == t
        gb.fit(X[tr], y[tr])
        r = permutation_importance(
            gb, X[te], y[te], n_repeats=5, random_state=seed, scoring=scoring
        )
        imps.append(pd.Series(r.importances_mean, index=X.columns))
    perm = pd.concat(imps, axis=1).mean(axis=1)
    lin = Ridge(alpha=30.0) if kind == "regression" else LogisticRegression(C=0.1, max_iter=2000)
    lin.fit(X, y)
    coef = pd.Series(np.ravel(lin.coef_), index=X.columns)
    out = pd.DataFrame({"permutation": perm, "linear_coef": coef})
    return out.sort_values("permutation", ascending=False)
