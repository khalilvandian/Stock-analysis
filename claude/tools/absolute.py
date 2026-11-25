"""Step 1 of every company analysis: the absolute values of any companies in the database.

Shows the values of config/absolute_values.toml, grouped as in the config. With --history,
each company's values for every fiscal year on record next to the latest 12 months.

Usage:
    uv run python -m claude absolute CEG VST UGI            # latest 12 months
    uv run python -m claude absolute --history CEG VST      # yearly history
"""

from __future__ import annotations

import sys

import pandas as pd

from stock_analysis import stocks
from stock_analysis.absolute import absolute_values, fmt, history_table, latest, load_config


def main(argv: list[str] | None = None, data=None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    symbols = [a.upper() for a in argv if not a.startswith("--")]
    if not symbols:
        raise SystemExit("Name the companies: uv run python -m claude absolute NEE DUK")
    data = data or stocks.default_data()
    pd.set_option("display.width", 250)
    if "--history" in argv:
        rows = latest(symbols, data)
        hist = stocks.history(data, symbols)
        for sym in symbols:
            print(f"\n{sym}\n")
            print(history_table(sym, hist, rows.loc[sym]).droplevel(0).to_string())
        return
    table = absolute_values(symbols, data)
    for group in load_config():
        view = pd.DataFrame(
            {
                v["label"]: table[v["column"]].map(lambda x, u=v["unit"]: fmt(x, u))
                for v in group["values"]
            }
        )
        print(f"\n{group['name']}\n")
        print(view.to_string())


if __name__ == "__main__":
    main()
