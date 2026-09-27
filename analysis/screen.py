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


MUST_HAVE = 4  # the first four rules are required; the rest measure cheapness
STRICT_RULES = {
    "market value >= $1bn": lambda d: d["market_cap"] >= 1,
    "reliable US-dollar data": lambda d: d["data_flag"].fillna("") == "",
    "profitable (net income and EBITDA > 0)": lambda d: (d["net_income"] > 0) & (d["ebitda"] > 0),
    "cash covers short-term debt": lambda d: d["cash_to_short_term_debt"] >= 1,
    "price below DCF fair value": lambda d: d["price_vs_fair_value"] < 0,
    "trailing P/E <= sub-industry median": lambda d: d["pe_rel"] <= 0,
    "EV / EBITDA <= sub-industry median": lambda d: d["ev_rel"] <= 0,
    "earnings expected to rise (forward P/E <= trailing)": lambda d: (
        (d["pe_fwd"] > 1) & (d["pe_change_expected"] <= 0)
    ),
}
# 1 = lower is better, -1 = higher is better
SCORE = {
    "cash_to_short_term_debt": -1,
    "price_vs_fair_value": 1,
    "pe_rel": 1,
    "ev_rel": 1,
    "pe_change_expected": 1,
}


def strict(top: int = 5) -> pd.DataFrame:
    """Rank companies that pass every must-have rule by how many cheapness rules they pass.

    Must-haves: size, reliable data, profitability and cash covering short-term debt.
    Ties are broken by the average rank across SCORE.
    """
    d = screen(max_leverage=99, min_cap=0)
    med = d.groupby("industry")[["pe_ttm", "ev_to_ebitda"]].transform("median")
    d["pe_rel"] = d["pe_ttm"] / med["pe_ttm"] - 1
    d["ev_rel"] = d["ev_to_ebitda"] / med["ev_to_ebitda"] - 1
    passed = pd.DataFrame({k: f(d).fillna(False) for k, f in STRICT_RULES.items()})
    must = passed.iloc[:, :MUST_HAVE].all(axis=1)
    c = d[must].copy()
    c["cheap_rules_passed"] = passed[must].iloc[:, MUST_HAVE:].sum(axis=1)
    c["failed"] = passed[must].apply(lambda r: ", ".join(r.index[~r]), axis=1)
    c["avg_rank"] = pd.DataFrame({k: (c[k] * s).rank() for k, s in SCORE.items()}).mean(axis=1)
    return c.sort_values(["cheap_rules_passed", "avg_rank"], ascending=[False, True]).head(top)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-leverage", type=float, default=3.5)
    ap.add_argument("--min-cap", type=float, default=1.0, help="minimum market value, $bn")
    ap.add_argument("--strict", action="store_true", help="rank the top 5 on the strict rules")
    args = ap.parse_args()
    if args.strict:
        pd.set_option("display.width", 220)
        cols = [
            "name",
            "net_debt_to_ebitda",
            "ebitda_to_interest",
            "price_vs_fair_value",
            "pe_rel",
            "ev_rel",
            "pe_change_expected",
            "cheap_rules_passed",
            "failed",
            "avg_rank",
        ]
        print(strict()[cols].round(3).to_string())
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
