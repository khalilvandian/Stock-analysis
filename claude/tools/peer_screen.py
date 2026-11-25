"""Compare a hand-picked peer group: the strict and the weighted screen within the group.

Uses one peer median for P/E and EV / EBITDA (stock_analysis.screen.run_screens). Stocks the
database lacks are listed; add them to the watch list's peers or to extra_symbols in
config/ingest.toml so the ingest fetches them.

Usage: uv run python -m claude peer_screen medtech BSX ABT MDT SYK ...
"""

from __future__ import annotations

import sys

import pandas as pd

from stock_analysis import screen


def main(argv: list[str] | None = None, data=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        raise SystemExit("Name the group and its stocks: ... peer_screen medtech BSX ABT MDT")
    name, symbols = argv[0], [s.upper() for s in argv[1:]]
    table = screen.peer_table(symbols, data)
    missing = sorted(set(symbols) - set(table.index))
    strict, balanced = screen.run_screens(table)
    pd.set_option("display.width", 220)
    note = f"; not in the database: {', '.join(missing)}" if missing else ""
    print(f"Peer group {name}: {len(table)} stocks{note}")
    print("Strict screen (passing every debt rule):")
    print(strict[["name", "net_debt_to_ebitda", "ebitda_to_interest", "cheap_rank"]].round(2))
    print("\nWeighted screen (debt 50%, profitability and cash 25%, cheapness 25%):")
    cols = ["name", "total_score", "debt_score", "quality_score", "cheap_score", "rank"]
    print(balanced[cols].round(1).to_string())


if __name__ == "__main__":
    main()
