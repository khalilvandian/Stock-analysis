"""Screen stocks for low debt and cheapness: passing the debt rules, strict, or weighted.

Without an option: the stocks with low debt, by cheap score. --strict ranks those passing every
debt requirement by cheapness; --balanced blends debt, profitability and cash, and cheapness.
The rules are in stock_analysis/screen.py.

Usage: uv run python -m claude screen NEE DUK SO ... [--balanced | --strict]
"""

from __future__ import annotations

import argparse

import pandas as pd

from stock_analysis import screen
from stock_analysis.screen import peer_table as table


def main(argv: list[str] | None = None, data=None) -> None:
    ap = argparse.ArgumentParser(prog="claude screen")
    ap.add_argument("symbols", nargs="+", help="the stocks to screen")
    ap.add_argument("--max-leverage", type=float, default=3.5)
    ap.add_argument("--min-cap", type=float, default=1.0, help="minimum market value, $bn")
    ap.add_argument("--strict", action="store_true", help="rank the top 5 with strict debt rules")
    ap.add_argument("--balanced", action="store_true", help="weighted debt + cheapness score")
    ap.add_argument("--debt-weight", type=float, default=0.50)
    ap.add_argument("--quality-weight", type=float, default=0.25)
    args = ap.parse_args(argv)
    t = table([x.upper() for x in args.symbols], data)
    if args.balanced:
        pd.set_option("display.width", 220)
        cols = ["name", "total_score", "debt_score", "quality_score", "cheap_score"]
        print(
            screen.balanced(args.debt_weight, args.quality_weight, d=t)[cols].round(1).to_string()
        )
        return
    if args.strict:
        pd.set_option("display.width", 220)
        cols = [
            "name",
            "cash_to_short_term_debt",
            "cash_to_long_term_debt",
            "net_debt_to_ebitda",
            "ebitda_to_interest",
            *screen.CHEAPNESS,
            "cheap_rank",
        ]
        print(screen.strict(10, d=t)[cols].round(3).to_string())
        return
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
    s = screen.screen(args.max_leverage, args.min_cap, d=t)
    hits = s[s["low_debt"]].sort_values(
        ["cheap_score", "pe_change_expected"], ascending=[False, True]
    )
    print(hits[cols].round(2).to_string())


if __name__ == "__main__":
    main()
