"""Run the sector metrics and screens on a hand-picked peer group outside utilities.

Reads each symbol's row from the database (stock_analysis.stocks.rows, the same columns as
the utilities table) and applies the strict and weighted screens of analysis/screen.py to
that group (one peer median for P/E and EV / EBITDA). Stocks the database lacks are listed;
add them to the watch list's peers or to extra_symbols in config/ingest.toml so the ingest
fetches them.

Usage: uv run python analysis/peer_screen.py medtech BSX ABT MDT SYK ...
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from stock_analysis import stocks

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screen  # noqa: E402


def peer_table(symbols: list[str], data=None) -> pd.DataFrame:
    df = stocks.rows(data or stocks.default_data(), symbols)
    if "error" in df:
        df = df[df["error"].isna()].drop(columns="error")
    return df


def run_screens(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = df.copy()
    d["industry"] = "Peers"
    d["data_flag"] = ""
    return screen.strict(len(d), d=d), screen.balanced(top=len(d), d=d)


if __name__ == "__main__":
    name, symbols = sys.argv[1], [s.upper() for s in sys.argv[2:]]
    table = peer_table(symbols)
    missing = sorted(set(symbols) - set(table.index))
    strict, balanced = run_screens(table)
    pd.set_option("display.width", 220)
    note = f"; not in the database: {', '.join(missing)}" if missing else ""
    print(f"Peer group {name}: {len(table)} stocks{note}")
    print("Strict screen (passing every debt rule):")
    print(strict[["name", "net_debt_to_ebitda", "ebitda_to_interest", "cheap_rank"]].round(2))
    print("\nWeighted screen (debt 50%, profitability and cash 25%, cheapness 25%):")
    cols = ["name", "total_score", "debt_score", "quality_score", "cheap_score", "rank"]
    print(balanced[cols].round(1).to_string())
