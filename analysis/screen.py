"""Screen the utilities universe for low debt, cheapness and expected cheapening.

Reads data/sector/utilities.csv (run analysis/sector.py first).

- Low debt: net debt / EBITDA <= --max-leverage (or net cash) and EBITDA / interest >= 4x.
- Cheap score (0-3): trailing P/E below its sub-industry median, EV / EBITDA below
  its sub-industry median, and price below the standard DCF fair value.
- Getting cheaper: forward P/E at least 15% below trailing P/E, i.e. analysts expect
  earnings to rise enough to lower the P/E at today's price.

Usage: uv run python analysis/screen.py [--max-leverage 3.5] [--min-cap 1]
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd


def screen(max_leverage: float = 3.5, min_cap: float = 1.0) -> pd.DataFrame:
    d = pd.read_csv("data/sector/utilities.csv", index_col=0)
    d.loc[d["ebitda"] <= 0, ["net_debt_to_ebitda", "ev_to_ebitda"]] = np.nan
    med = d.groupby("industry")[["pe_ttm", "ev_to_ebitda"]].transform("median")
    net_cash = d["net_debt"] <= 0
    d["low_debt"] = ((d["net_debt_to_ebitda"] <= max_leverage) | net_cash) & (
        (d["ebitda_to_interest"] >= 4) | net_cash
    )
    d["cheap_score"] = (
        (d["pe_ttm"] < med["pe_ttm"]).astype(int)
        + (d["ev_to_ebitda"] < med["ev_to_ebitda"]).astype(int)
        + (d["price_vs_fair_value"] < 0).astype(int)
    )
    d["pe_change_expected"] = d["pe_fwd"] / d["pe_ttm"] - 1
    d["getting_cheaper"] = (
        (d["pe_fwd"] > 1) & (d["pe_ttm"] > 0) & (d["pe_change_expected"] <= -0.15)
    )
    return d[d["market_cap"] >= min_cap]


# Strict debt requirements: cash for near-term debt, and cash plus earnings for long-term debt
MUST_HAVE = {
    "market value >= $1bn": lambda d: d["market_cap"] >= 1,
    "reliable US-dollar data": lambda d: d["data_flag"].fillna("") == "",
    "profitable (net income and EBITDA > 0)": lambda d: (d["net_income"] > 0) & (d["ebitda"] > 0),
    "cash covers short-term debt": lambda d: d["cash_to_short_term_debt"] >= 1,
    "cash >= 5% of long-term debt": lambda d: d["cash_to_long_term_debt"] >= 0.05,
    "net debt / EBITDA <= 4.5x": lambda d: d["net_debt_to_ebitda"] <= 4.5,
    "EBITDA / interest >= 4x": lambda d: d["ebitda_to_interest"] >= 4,
}
# Cheapness is ranked, not required: lower is better for each
CHEAPNESS = ["price_vs_fair_value", "pe_rel", "ev_rel", "pe_change_expected"]


def strict(top: int = 5) -> pd.DataFrame:
    """Companies passing every debt requirement, ranked by average cheapness rank."""
    d = screen(max_leverage=99, min_cap=0)
    med = d.groupby("industry")[["pe_ttm", "ev_to_ebitda"]].transform("median")
    d["pe_rel"] = d["pe_ttm"] / med["pe_ttm"] - 1
    d["ev_rel"] = d["ev_to_ebitda"] / med["ev_to_ebitda"] - 1
    passed = pd.DataFrame({k: f(d).fillna(False) for k, f in MUST_HAVE.items()}).all(axis=1)
    c = d[passed].copy()
    c["cheap_rank"] = c[CHEAPNESS].rank().mean(axis=1)
    return c.sort_values("cheap_rank").head(top)


# Weighted score: percentile ranks (0-100) within the investable universe.
# 1 = higher is better, -1 = lower is better
DEBT_MEASURES = {
    "cash_to_short_term_debt": 1,
    "cash_to_long_term_debt": 1,
    "net_debt_to_ebitda": -1,
    "ebitda_to_interest": 1,
}
CHEAP_MEASURES = {
    "price_vs_fair_value": -1,
    "pe_rel": -1,
    "ev_rel": -1,
    "pe_change_expected": -1,
}


# Profitability and cash: (direction, weight within the component)
QUALITY_MEASURES = {
    "net_margin": (1, 2.0),  # how much of each dollar of revenue is profit
    "margin_change_avg": (1, 1.0),  # margin trend, percentage points a year
    "margin_change_median": (1, 1.0),
    "ocf_growth_avg": (1, 1.0),  # operating cash flow growth
    "ocf_growth_median": (1, 1.0),
    "cash_growth_avg": (1, 0.5),  # cash balances swing a lot, so lower weight
    "cash_growth_median": (1, 0.5),
}


def _score(d: pd.DataFrame, measures: dict, missing: float) -> pd.Series:
    parts, weights = [], []
    for col, spec in measures.items():
        direction, weight = spec if isinstance(spec, tuple) else (spec, 1.0)
        pct = (d[col].replace([np.inf], 1e9) * direction).rank(pct=True) * 100
        parts.append(pct.fillna(missing) * weight)
        weights.append(weight)
    return pd.concat(parts, axis=1).sum(axis=1) / sum(weights)


GROWTH_RULES = {
    "revenue growth: average > 0": lambda d: d["revenue_growth_avg"] > 0,
    "revenue growth: median > 0": lambda d: d["revenue_growth_median"] > 0,
    "EPS growth: average > 0": lambda d: d["eps_growth_avg"] > 0,
    "EPS growth: median > 0": lambda d: d["eps_growth_median"] > 0,
    "at least 2 years of growth data": lambda d: (
        (d["revenue_growth_years"] >= 2) & (d["eps_growth_years"] >= 2)
    ),
}


def balanced(
    debt_weight: float = 0.50,
    quality_weight: float = 0.25,
    top: int = 10,
    require_growth: bool = True,
) -> pd.DataFrame:
    """Blend debt, profitability-and-cash, and cheapness scores; debt weighted most.

    Universe: market value >= $1bn, reliable US-dollar data, profitable, and at least
    three of the four cheapness measures available. With require_growth, revenue and EPS
    must have grown on average and in the median year (yearly growth, last fiscal years).
    Scores are percentiles within that final group. Missing debt
    data scores 0 (strict); missing cheapness data scores 50 (neutral).
    """
    d = screen(max_leverage=99, min_cap=0)
    med = d.groupby("industry")[["pe_ttm", "ev_to_ebitda"]].transform("median")
    d["pe_rel"] = d["pe_ttm"] / med["pe_ttm"] - 1
    d["ev_rel"] = d["ev_to_ebitda"] / med["ev_to_ebitda"] - 1
    base = (
        (d["market_cap"] >= 1)
        & (d["data_flag"].fillna("") == "")
        & (d["net_income"] > 0)
        & (d["ebitda"] > 0)
    )
    u = d[base].copy()
    u["pe_change_expected"] = u["pe_change_expected"].where(u["pe_fwd"] > 1)
    u = u[u[list(CHEAP_MEASURES)].notna().sum(axis=1) >= 3]  # enough data to judge cheapness
    if require_growth:
        u = u[pd.DataFrame({k: f(u).fillna(False) for k, f in GROWTH_RULES.items()}).all(axis=1)]
    u["debt_score"] = _score(u, DEBT_MEASURES, missing=0)
    u["cheap_score"] = _score(u, CHEAP_MEASURES, missing=50)
    u["quality_score"] = _score(u, QUALITY_MEASURES, missing=50)
    cheap_weight = 1 - debt_weight - quality_weight
    u["total_score"] = (
        debt_weight * u["debt_score"]
        + quality_weight * u["quality_score"]
        + cheap_weight * u["cheap_score"]
    )
    u["rank"] = u["total_score"].rank(ascending=False).astype(int)
    return u.sort_values("total_score", ascending=False).head(top)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-leverage", type=float, default=3.5)
    ap.add_argument("--min-cap", type=float, default=1.0, help="minimum market value, $bn")
    ap.add_argument("--strict", action="store_true", help="rank the top 5 with strict debt rules")
    ap.add_argument("--balanced", action="store_true", help="weighted debt + cheapness score")
    ap.add_argument("--debt-weight", type=float, default=0.50)
    ap.add_argument("--quality-weight", type=float, default=0.25)
    args = ap.parse_args()
    if args.balanced:
        pd.set_option("display.width", 220)
        cols = ["name", "total_score", "debt_score", "quality_score", "cheap_score"]
        print(balanced(args.debt_weight, args.quality_weight)[cols].round(1).to_string())
        raise SystemExit
    if args.strict:
        pd.set_option("display.width", 220)
        cols = [
            "name",
            "cash_to_short_term_debt",
            "cash_to_long_term_debt",
            "net_debt_to_ebitda",
            "ebitda_to_interest",
            *CHEAPNESS,
            "cheap_rank",
        ]
        print(strict(10)[cols].round(3).to_string())
        raise SystemExit
    pd.set_option("display.width", 220)
    cols = [
        "name",
        "industry",
        "price",
        "net_debt_to_ebitda",
        "ebitda_to_interest",
        "pe_ttm",
        "pe_fwd",
        "pe_change_expected",
        "ev_to_ebitda",
        "dcf_fair_value",
        "price_vs_fair_value",
        "cheap_score",
        "getting_cheaper",
    ]
    s = screen(args.max_leverage, args.min_cap)
    hits = s[s["low_debt"]].sort_values(
        ["cheap_score", "pe_change_expected"], ascending=[False, True]
    )
    print(hits[cols].round(2).to_string())
