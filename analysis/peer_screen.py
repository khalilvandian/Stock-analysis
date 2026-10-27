"""Run the sector metrics and screens on a hand-picked peer group outside utilities.

Calls analysis/sector.py's analyse() for each symbol, writes data/peers/<name>.csv, then
applies the strict and weighted screens from analysis/screen.py to that group (one peer
median for P/E and EV / EBITDA).

Usage: uv run python analysis/peer_screen.py medtech BSX ABT MDT SYK ...
"""

from __future__ import annotations

import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import screen  # noqa: E402
import sector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def peer_table(symbols: list[str]) -> pd.DataFrame:
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda s: sector.analyse({"symbol": s}), symbols))
    for r in rows:
        r.pop("_history", None)
    df = pd.DataFrame(rows).set_index("symbol")
    df["data_flag"] = ""
    return df


def run_screens(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """screen.py reads data/sector/utilities.csv, so point it at the peer table."""
    d = df.copy()
    d["industry"] = "Peers"
    cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "data/sector").mkdir(parents=True)
        d.to_csv(Path(tmp) / "data/sector/utilities.csv")
        os.chdir(tmp)
        try:
            return screen.strict(len(d)), screen.balanced(top=len(d))
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    name, symbols = sys.argv[1], sys.argv[2:]
    table = peer_table(symbols)
    out = ROOT / "data/peers"
    out.mkdir(parents=True, exist_ok=True)
    table.to_csv(out / f"{name}.csv")
    strict, balanced = run_screens(table)
    pd.set_option("display.width", 220)
    print("Strict screen (passing every debt rule):")
    print(strict[["name", "net_debt_to_ebitda", "ebitda_to_interest", "cheap_rank"]].round(2))
    print("\nWeighted screen (debt 50%, profitability and cash 25%, cheapness 25%):")
    cols = ["name", "total_score", "debt_score", "quality_score", "cheap_score", "rank"]
    print(balanced[cols].round(1).to_string())
