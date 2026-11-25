"""Step 1 of every company analysis: screen the absolute values.

Reads the list of absolute values from config/absolute_values.toml (the watch list's PDFs
show the same list) and shows them for the companies named (any company in the database),
grouped as in the config. Everything comes from the database (stock_analysis.stocks).

With --history, shows each company's values for every fiscal year on record (SEC filings
back to 2016, Yahoo for gaps) next to the latest 12 months.

Usage:
    uv run python -m stock_analysis.absolute CEG VST UGI            # latest 12 months
    uv run python -m stock_analysis.absolute --history CEG VST      # yearly history
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pandas as pd

from . import stocks
from .db import ROOT

CONFIG = ROOT / "config/absolute_values.toml"


def load_config(path: Path = CONFIG) -> list[dict]:
    with path.open("rb") as f:
        return tomllib.load(f)["group"]


def columns(groups: list[dict]) -> list[dict]:
    return [v | {"group": g["name"]} for g in groups for v in g["values"]]


def latest(symbols: list[str], data=None) -> pd.DataFrame:
    """The latest rows of the named companies."""
    df = stocks.rows(data or stocks.default_data(), symbols)
    unknown = df.index[df["error"].notna()].tolist() if "error" in df else []
    if unknown:
        raise KeyError(f"Not in the database: {unknown}")
    return df


def absolute_values(symbols: list[str], data=None) -> pd.DataFrame:
    df = latest(symbols, data)
    cols = columns(load_config())
    missing = [c["column"] for c in cols if c["column"] not in df.columns]
    if missing:
        raise KeyError(f"Configured columns missing from the rows: {missing}")
    return df[["name", "industry"] + [c["column"] for c in cols]]


def fmt(value: float, unit: str) -> str:
    if pd.isna(value):
        return "–"
    if unit == "$bn":
        return f"{'-' if value < 0 else ''}${abs(value):,.2f}bn"
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


def history_table(symbol: str, hist: pd.DataFrame, row: pd.Series) -> pd.DataFrame:
    """Rows = configured values, columns = fiscal years plus 'Latest 12m'."""
    h = hist[hist["symbol"] == symbol].copy()
    h["year"] = "FY" + h["fiscal_year_end"].str[:4]
    wide = h.pivot_table(index="column", columns="year", values="value", aggfunc="last")
    rows = {}
    for v in columns(load_config()):
        key = v.get("history", v["column"])
        yearly = wide.loc[key] if key and key in wide.index else pd.Series(dtype=float)
        r = {y: fmt(x, v["unit"]) for y, x in yearly.items()}
        r["Latest 12m"] = fmt(row.get(v["column"]), v["unit"])
        rows[(v["group"], v["label"])] = r
    table = pd.DataFrame(rows).T
    years = sorted(c for c in table.columns if c.startswith("FY"))
    return table[years + ["Latest 12m"]].fillna("–")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    symbols = [s.upper() for s in args]
    if not symbols:
        raise SystemExit("Name the companies: uv run python -m stock_analysis.absolute NEE DUK")
    pd.set_option("display.width", 250)
    if "--history" in sys.argv:
        rows = latest(symbols)
        hist = stocks.history(stocks.default_data(), symbols)
        for sym in symbols:
            print(f"\n{sym}\n")
            print(history_table(sym, hist, rows.loc[sym]).droplevel(0).to_string())
        return
    table = absolute_values(symbols)
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
