"""Step 1 of every company analysis: screen the absolute values.

Reads the list of absolute values from config/absolute_values.toml and shows them for
the requested companies (or all of them), grouped as in the config. Also writes
data/sector/absolute_values.csv.

Usage:
    uv run python analysis/absolute.py                 # every company
    uv run python analysis/absolute.py CEG VST UGI     # selected companies
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/absolute_values.toml"
DATA = ROOT / "data/sector/utilities.csv"


def load_config(path: Path = CONFIG) -> list[dict]:
    with path.open("rb") as f:
        return tomllib.load(f)["group"]


def columns(groups: list[dict]) -> list[dict]:
    return [v | {"group": g["name"]} for g in groups for v in g["values"]]


def absolute_values(symbols: list[str] | None = None) -> pd.DataFrame:
    df = pd.read_csv(DATA, index_col=0)
    cols = columns(load_config())
    missing = [c["column"] for c in cols if c["column"] not in df.columns]
    if missing:
        raise KeyError(f"Configured columns missing from {DATA.name}: {missing}")
    out = df[["name", "industry"] + [c["column"] for c in cols]]
    if symbols:
        unknown = [s for s in symbols if s not in out.index]
        if unknown:
            raise KeyError(f"Not in the sector data: {unknown}")
        out = out.loc[symbols]
    return out


def fmt(value: float, unit: str) -> str:
    if pd.isna(value):
        return "–"
    if unit == "$bn":
        return f"{'-' if value < 0 else ''}${abs(value):,.2f}bn"
    return f"{'-' if value < 0 else ''}${abs(value):,.2f}"


def main() -> None:
    symbols = [s.upper() for s in sys.argv[1:]]
    table = absolute_values(symbols or None)
    table.to_csv(ROOT / "data/sector/absolute_values.csv")
    pd.set_option("display.width", 220)
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
