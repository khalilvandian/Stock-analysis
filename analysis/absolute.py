"""Step 1 of every company analysis: screen the absolute values.

Reads the list of absolute values from config/absolute_values.toml and shows them for
the requested companies (or all of them), grouped as in the config. Also writes
data/sector/absolute_values.csv.

With --history, shows each company's values for every fiscal year on record (SEC filings
back to 2016, see analysis/history.py) next to the latest 12 months, and writes
data/sector/absolute_history.csv.

Usage:
    uv run python analysis/absolute.py                        # latest, every company
    uv run python analysis/absolute.py CEG VST UGI            # latest, selected companies
    uv run python analysis/absolute.py --history CEG VST      # yearly history
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/absolute_values.toml"
DATA = ROOT / "data/sector/utilities.csv"
HISTORY = ROOT / "data/sector/history.csv"


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


def history_table(symbol: str) -> pd.DataFrame:
    """Rows = configured values, columns = fiscal years plus 'Latest 12m'."""
    hist = pd.read_csv(HISTORY)
    hist = hist[hist["symbol"] == symbol]
    hist["year"] = "FY" + hist["fiscal_year_end"].str[:4]
    wide = hist.pivot_table(index="column", columns="year", values="value", aggfunc="last")
    latest = pd.read_csv(DATA, index_col=0).loc[symbol]
    rows = {}
    for v in columns(load_config()):
        key = v.get("history", v["column"])
        yearly = wide.loc[key] if key and key in wide.index else pd.Series(dtype=float)
        row = {y: fmt(x, v["unit"]) for y, x in yearly.items()}
        row["Latest 12m"] = fmt(latest[v["column"]], v["unit"])
        rows[(v["group"], v["label"])] = row
    table = pd.DataFrame(rows).T
    years = sorted(c for c in table.columns if c.startswith("FY"))
    return table[years + ["Latest 12m"]].fillna("–")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    symbols = [s.upper() for s in args]
    if "--history" in sys.argv:
        pd.set_option("display.width", 250)
        frames = []
        for sym in symbols or pd.read_csv(DATA, index_col=0).index.tolist():
            t = history_table(sym)
            frames.append(t.assign(symbol=sym))
            if symbols:
                print(f"\n{sym}\n")
                print(t.droplevel(0).to_string())
        pd.concat(frames).to_csv(ROOT / "data/sector/absolute_history.csv")
        return
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
