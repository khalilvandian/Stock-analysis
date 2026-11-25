"""The absolute values of companies, the first step of every analysis: the list in
config/absolute_values.toml, read from the database (stock_analysis.stocks), as the watch list's
PDFs and Claude's tool (claude/tools/absolute.py) show them: the latest 12 months, and every
fiscal year on record (SEC filings back to 2016, Yahoo for gaps)."""

from __future__ import annotations

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
