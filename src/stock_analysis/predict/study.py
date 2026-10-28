"""Label study: how the candidate "goodness" labels behave on real S&P 500 data.

Criteria (docs/PREDICT.md explains why each matters):
  1. Interpretable in one sentence.
  2. Penalises the "volatile winner" (high return reached through a deep crash).
  3. Independent of the market regime (a label that says "everything was good" in a bull
     market measures the market, not the stock).
  4. Persistent: a stock that was good in one 5-year window tends to be good in the next
     (evidence the label measures a trait of the company rather than luck).
  5. Learnable from information known on the decision date (out-of-sample).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from stock_analysis.predict import models

CANDIDATES = {
    "cagr": "Raw total return (annual)",
    "excess_cagr": "Return minus the S&P 500",
    "excess_vs_sector": "Return minus the sector median",
    "sharpe": "Sharpe ratio",
    "sortino": "Sortino ratio",
    "calmar": "Calmar ratio (return / worst fall)",
    "martin": "Martin ratio (return / ulcer index)",
    "info_ratio": "Information ratio vs the S&P 500",
    "beat_index": "Beat the S&P 500 (yes/no)",
    "good": "Beat the S&P 500 without a much deeper fall (yes/no)",
}


def _within_cohort_spearman(df: pd.DataFrame, a: str, b: str) -> float:
    vals = []
    for _, g in df.groupby("cohort"):
        ok = g[a].notna() & g[b].notna()
        if ok.sum() > 30:
            vals.append(spearmanr(g.loc[ok, a], g.loc[ok, b]).statistic)
    return float(np.mean(vals)) if vals else np.nan


def label_correlations(df: pd.DataFrame, key: str = "y5") -> pd.DataFrame:
    cols = [f"{key}_{c}" for c in CANDIDATES] + [f"{key}_max_dd"]
    names = list(CANDIDATES) + ["max_dd"]
    out = pd.DataFrame(index=names, columns=names, dtype=float)
    for i, a in enumerate(cols):
        for j, b in enumerate(cols):
            out.iloc[i, j] = 1.0 if i == j else _within_cohort_spearman(df, a, b)
    return out


def volatile_winners(df: pd.DataFrame, key: str = "y5") -> tuple[pd.DataFrame, float]:
    """Stocks in the top fifth by return whose worst fall was > 15 points deeper than the
    index's. For each label: their average within-cohort percentile and share called good."""
    top = df[f"{key}_cagr"].groupby(df.cohort).rank(pct=True) > 0.8
    crash = df[f"{key}_dd_vs_index"] > 0.15
    vw = df[top & crash]
    share = len(vw) / max(top.sum(), 1)
    rows = []
    for c, desc in CANDIDATES.items():
        col = f"{key}_{c}"
        pct = df[col].groupby(df.cohort).rank(pct=True)
        rows.append(
            {
                "label": c,
                "description": desc,
                "avg_percentile_of_volatile_winners": float(pct[vw.index].mean()),
                "share_in_top_fifth": float((pct[vw.index] > 0.8).mean())
                if df[col].nunique() > 2
                else float(vw[col].mean()),
            }
        )
    return pd.DataFrame(rows), share


def regime_dependence(df: pd.DataFrame, key: str = "y5") -> pd.DataFrame:
    """Cohort averages of each label: a regime-free label has a stable average."""
    cols = [f"{key}_{c}" for c in CANDIDATES]
    t = df.groupby("cohort")[cols].mean()
    t.columns = list(CANDIDATES)
    return t


def persistence(df: pd.DataFrame, key: str = "y5", lag: int = 5) -> pd.Series:
    """Within-cohort Spearman between a stock's label in cohort t and in cohort t+lag
    (non-overlapping windows when lag >= horizon)."""
    out = {}
    for c in CANDIDATES:
        col = f"{key}_{c}"
        a = df[["cohort", "cik", col]].dropna()
        b = a.assign(cohort=a.cohort - lag).rename(columns={col: "later"})
        m = a.merge(b, on=["cohort", "cik"])
        vals = [
            spearmanr(g[col], g["later"]).statistic
            for _, g in m.groupby("cohort")
            if len(g) > 30 and g[col].nunique() > 1
        ]
        out[c] = float(np.mean(vals)) if vals else np.nan
    return pd.Series(out)


def learnability(df: pd.DataFrame, key: str = "y5", horizon: int = 5) -> pd.DataFrame:
    """Out-of-sample skill of the same two models (Ridge, gradient boosting) on each label."""
    rows = []
    for c in CANDIDATES:
        col = f"{key}_{c}"
        binary = c in ("beat_index", "good")
        if binary:
            ms = models.classifiers(7)
            ms = {k: ms[k] for k in ("Logistic (L2)", "Gradient boosting")}
            sc, preds = models.walk_forward(df, col, horizon, "classification", models=ms)
        else:
            ms = models.regressors(7)
            ms = {k: ms[k] for k in ("Ridge", "Gradient boosting")}
            sc, preds = models.walk_forward(df, col, horizon, "regression", models=ms)
        # rank skill comparable across label types: Spearman of prediction vs outcome
        ic = preds.groupby(["model", "cohort"]).apply(
            lambda g: spearmanr(g.pred, g.y).statistic if g.y.nunique() > 1 else np.nan
        )
        for m in ms:
            rows.append(
                {
                    "label": c,
                    "model": m,
                    "ic": float(ic.loc[m].mean()),
                    "ic_positive_cohorts": float((ic.loc[m] > 0).mean()),
                    "auc": float(sc[sc.model == m].auc.mean()) if binary else np.nan,
                    "excess_top_minus_bottom": float(
                        (sc[sc.model == m].excess_top_q - sc[sc.model == m].excess_bottom_q).mean()
                    ),
                }
            )
    return pd.DataFrame(rows)
