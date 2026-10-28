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


GROWTH_LABELS = {
    "trend_growth": "Trend growth of the investment (%/yr)",
    "excess_trend": "Trend growth minus the S&P 500's",
    "trend_r2": "Steadiness of the climb (R2 of the trend)",
    "k_ratio": "K-ratio: trend growth per unit of wobble",
    "steady_growth": "Trend growth x steadiness",
    "win_12m": "Share of 12-month periods with a gain",
    "worst_12m": "Worst 12-month return",
    "underwater": "Share of days >10% below the peak (lower is better)",
    "eps_cagr_fwd": "EPS growth, next 5 fiscal years",
    "revenue_cagr_fwd": "Revenue growth, next 5 fiscal years",
    "eps_r2_fwd": "Steadiness of EPS growth (R2)",
    "eps_down_years": "Years EPS fell, of 5 (lower is better)",
    "cagr": "Raw total return (for comparison)",
    "martin": "Martin ratio (for comparison)",
}


def growth_label_study(df: pd.DataFrame, fixed: pd.Series) -> pd.DataFrame:
    """For each growth label: out-of-sample learnability (Ridge, gradient boosting),
    rank correlation with a fixed score in every year, persistence, how it ranks volatile
    winners, and how closely it follows raw return."""
    top = df.y5_cagr.groupby(df.cohort).rank(pct=True) > 0.8
    vw = top & (df.y5_dd_vs_index > 0.15)
    rows = []
    for lab, desc in GROWTH_LABELS.items():
        col = f"y5_{lab}"
        d = df[df[col].notna()]
        ms = models.regressors(7)
        ms = {k: ms[k] for k in ("Ridge", "Gradient boosting")}
        sc, _ = models.walk_forward(d, col, 5, "regression", models=ms)
        ics = np.array(
            [spearmanr(fixed[g.index], g[col]).statistic for _, g in d.groupby("cohort")]
        )
        a = d[["cohort", "cik", col]]
        b = a.assign(cohort=a.cohort - 5).rename(columns={col: "later"})
        m = a.merge(b, on=["cohort", "cik"])
        pers = [spearmanr(g[col], g.later).statistic for _, g in m.groupby("cohort") if len(g) > 30]
        pct = d[col].groupby(d.cohort).rank(pct=True)
        if lab in ("underwater", "eps_down_years"):
            pct = 1 - pct
        rows.append(
            {
                "label": lab,
                "description": desc,
                "rows": len(d),
                "ic_ridge": sc[sc.model == "Ridge"].ic.mean(),
                "ic_gradient_boosting": sc[sc.model == "Gradient boosting"].ic.mean(),
                "gb_positive_years": (sc[sc.model == "Gradient boosting"].ic > 0).mean(),
                "ic_quality_calm_all_years": ics.mean(),
                "quality_calm_positive_years": (ics > 0).mean(),
                "persistence": float(np.mean(pers)) if pers else np.nan,
                "volatile_winners_avg_percentile": float(
                    pct[vw.reindex(d.index, fill_value=False)].mean()
                ),
                "corr_with_raw_return": float(
                    np.mean(
                        [spearmanr(g[col], g.y5_cagr).statistic for _, g in d.groupby("cohort")]
                    )
                ),
            }
        )
    return pd.DataFrame(rows)
