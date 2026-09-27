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


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-leverage", type=float, default=3.5)
    ap.add_argument("--min-cap", type=float, default=1.0, help="minimum market value, $bn")
    ap.add_argument("--strict", action="store_true", help="rank the top 5 with strict debt rules")
    args = ap.parse_args()
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
