"""How S&P 500 stocks behaved over 5 years: distributions and path shapes (report 15, 2.7).

Every labelled member-year is one 5-year holding (bought on June 30, dividends reinvested).
`paths` turns each holding into 61 month-end values (start = 1); `shape` puts each path in
one of five plain-language shapes; the rest summarise the spread.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from stock_analysis.predict.prices import Prices

MONTHS = 60

# measures summarised in the distribution table: column -> (description, higher is better)
MEASURES = {
    "y5_cagr": ("Total return per year", True),
    "y5_excess_cagr": ("Return per year minus the S&P 500's", True),
    "wealth": ("Value of $1 after 5 years", True),
    "y5_max_dd": ("Worst fall from a peak", False),
    "y5_dd_vs_index": ("Worst fall minus the S&P 500's", False),
    "y5_vol": ("Volatility per year", False),
    "y5_trend_r2": ("Steadiness of the climb (R²)", True),
    "y5_k_ratio": ("K-ratio (growth per unit of wobble)", True),
    "y5_win_12m": ("Share of 12-month periods with a gain", True),
    "y5_worst_12m": ("Worst 12-month return", True),
    "y5_underwater": ("Share of days >10% below the peak", False),
    "y5_revenue_cagr_fwd": ("Revenue growth per year (business)", True),
    "y5_eps_cagr_fwd": ("EPS growth per year (business)", True),
}
QUANTILES = [0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95]

SHAPES = {
    "steady_climb": "Steady climb: gained, straight path (R² ≥ 0.8), never fell more than 30%",
    "bumpy_climb": "Bumpy climb: gained and ended within 10% of its high, with deeper wobbles",
    "faded": "Rose then faded: gained, but ended more than 10% below its high",
    "round_trip": "Round trip: was up 20% or more at some point, ended with a loss",
    "decline": "Decline: lost money and was never up 20%",
}


def path(p: Prices, start, months: int = MONTHS) -> pd.Series | None:
    """Month-end total-return values for `months` months after `start`, first value = 1."""
    start = pd.Timestamp(start)
    s0 = p.on(start)
    s = p.window(start + pd.Timedelta(days=1), start + pd.DateOffset(months=months))
    if s0 is None or s.empty:
        return None
    m = s.resample("ME").last().dropna()
    if len(m) < months - 1:
        return None
    v = np.r_[1.0, (m.to_numpy() / s0)[:months]]
    return pd.Series(v, index=range(len(v)))


def paths(panel: pd.DataFrame, load) -> pd.DataFrame:
    """One row per holding (same index as `panel`), columns 0..60 = month-end value."""
    cache: dict = {}
    rows = {}
    for i, r in panel.iterrows():
        sym = r["yahoo"]
        if sym not in cache:
            cache[sym] = load(sym)
        v = path(cache[sym], r["date"])
        if v is not None and len(v) == MONTHS + 1:
            rows[i] = v
    return pd.DataFrame.from_dict(rows, orient="index")


def shape(values: pd.Series | np.ndarray, r2: float, max_dd: float) -> str:
    v = np.asarray(values, dtype=float)
    end, peak = v[-1], v.max()
    if end < 1:
        return "round_trip" if peak >= 1.2 else "decline"
    if r2 >= 0.8 and max_dd <= 0.30:
        return "steady_climb"
    return "bumpy_climb" if end >= 0.9 * peak else "faded"


def distribution(u: pd.DataFrame) -> pd.DataFrame:
    d = u.assign(wealth=(1 + u.y5_cagr) ** 5)
    rows = []
    for col, (desc, _) in MEASURES.items():
        s = d[col].dropna()
        row = {"measure": col, "description": desc, "holdings": len(s)}
        row.update({f"p{int(q * 100):02d}": s.quantile(q) for q in QUANTILES})
        row["mean"] = s.mean()
        rows.append(row)
    return pd.DataFrame(rows)


def wealth_bands(u: pd.DataFrame) -> pd.DataFrame:
    w = (1 + u.y5_cagr) ** 5
    bins = [0, 0.5, 1, 1.5, 2, 3, 5, np.inf]
    labels = ["lost half or more", "lost up to half", "1-1.5x", "1.5-2x", "2-3x", "3-5x", ">5x"]
    out = pd.cut(w, bins, labels=labels, right=False).value_counts(normalize=True)
    return out.reindex(labels).rename("share").to_frame()


def concentration(u: pd.DataFrame) -> pd.Series:
    """With $1 in every holding: share of the total gain from the best 1%, 5%, 10%."""
    gain = ((1 + u.y5_cagr) ** 5 - 1).sort_values(ascending=False)
    n = len(gain)
    return pd.Series(
        {f"top_{k}pct": gain.head(max(n * k // 100, 1)).sum() / gain.sum() for k in (1, 5, 10)}
        | {"bottom_half": gain.tail(n // 2).sum() / gain.sum()}
    )


def by_cohort(u: pd.DataFrame) -> pd.DataFrame:
    g = u.groupby("cohort")
    out = pd.DataFrame(
        {
            "holdings": g.size(),
            "return_p10": g.y5_cagr.quantile(0.1),
            "return_median": g.y5_cagr.median(),
            "return_p90": g.y5_cagr.quantile(0.9),
            "sp500_return": g.apply(lambda x: (x.y5_cagr - x.y5_excess_cagr).median()),
            "share_lost_money": g.y5_cagr.apply(lambda s: (s < 0).mean()),
            "share_beat_sp500": g.y5_beat_index.mean(),
            "worst_fall_median": g.y5_max_dd.median(),
            "sp500_worst_fall": g.apply(lambda x: (x.y5_max_dd - x.y5_dd_vs_index).median()),
            "steadiness_median": g.y5_trend_r2.median(),
        }
    )
    return out


def by_sector(u: pd.DataFrame) -> pd.DataFrame:
    g = u.groupby("sector")
    return pd.DataFrame(
        {
            "holdings": g.size(),
            "return_median": g.y5_cagr.median(),
            "share_beat_sp500": g.y5_beat_index.mean(),
            "worst_fall_median": g.y5_max_dd.median(),
            "steadiness_median": g.y5_trend_r2.median(),
            "k_ratio_median": g.y5_k_ratio.median(),
            "share_steady_climb": g["shape"].apply(lambda s: (s == "steady_climb").mean()),
        }
    ).sort_values("k_ratio_median", ascending=False)


def shape_table(u: pd.DataFrame) -> pd.DataFrame:
    g = u.groupby("shape")
    out = pd.DataFrame(
        {
            "share": g.size() / len(u),
            "return_median": g.y5_cagr.median(),
            "share_beat_sp500": g.y5_beat_index.mean(),
            "worst_fall_median": g.y5_max_dd.median(),
            "worst_12m_median": g.y5_worst_12m.median(),
            "revenue_growth_median": g.y5_revenue_cagr_fwd.median(),
            "eps_growth_median": g.y5_eps_cagr_fwd.median(),
        }
    ).reindex(list(SHAPES))
    out.insert(0, "description", [SHAPES[k] for k in out.index])
    return out


def persistence_of_shape(u: pd.DataFrame) -> pd.DataFrame:
    """Shape of the same company 5 years later (non-overlapping windows), row-normalised."""
    a = u[["cohort", "cik", "shape"]]
    b = a.assign(cohort=a.cohort - 5).rename(columns={"shape": "later"})
    m = a.merge(b, on=["cohort", "cik"])
    t = pd.crosstab(m["shape"], m["later"], normalize="index")
    return t.reindex(index=list(SHAPES), columns=list(SHAPES))
