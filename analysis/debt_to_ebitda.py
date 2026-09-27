"""Debt / EBITDA history across tickers saved under data/<SYMBOL>/.

Annual ratios use year-end debt and full-year EBITDA; the latest column uses
June 2026 debt and trailing-twelve-month EBITDA.

Usage: uv run python analysis/debt_to_ebitda.py CEG VST NRG TLN NEE DUK SO
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BN = 1e9


def load(symbol: str, name: str) -> pd.DataFrame:
    df = pd.read_csv(Path("data") / symbol / f"{name}.csv", index_col=0, parse_dates=True)
    return df.sort_index()


def ratios(symbol: str) -> pd.DataFrame:
    bs, inc = load(symbol, "balance_sheet_annual"), load(symbol, "income_annual")
    bs_q, inc_q = load(symbol, "balance_sheet_quarterly"), load(symbol, "income_quarterly")

    rows = pd.DataFrame(
        {
            "debt": bs["Total Debt"],
            "cash": bs["Cash And Cash Equivalents"],
            "ebitda": inc["EBITDA"],
        }
    )
    rows.index = rows.index.year.astype(str)

    last = bs_q.dropna(subset=["Total Debt"]).iloc[-1]
    ebitda_q = inc_q["EBITDA"].dropna()
    rows.loc["TTM " + last.name.strftime("%b %Y")] = {
        "debt": last["Total Debt"],
        "cash": last["Cash And Cash Equivalents"],
        "ebitda": ebitda_q.iloc[-4:].sum() if len(ebitda_q) >= 4 else float("nan"),
    }
    rows = rows.dropna(subset=["debt", "ebitda"])
    rows = rows[rows.index != "2021"]
    rows["debt/ebitda"] = rows["debt"] / rows["ebitda"]
    rows["net_debt/ebitda"] = (rows["debt"] - rows["cash"]) / rows["ebitda"]
    return rows


if __name__ == "__main__":
    symbols = [s.upper() for s in sys.argv[1:]] or ["CEG", "VST", "NRG", "TLN", "NEE", "DUK", "SO"]
    data = {s: ratios(s) for s in symbols}
    for field in ("debt/ebitda", "net_debt/ebitda"):
        print(f"\n{field} (x)\n")
        print(pd.DataFrame({s: d[field] for s, d in data.items()}).T.round(1).to_string())
    print("\nEBITDA ($bn)\n")
    print((pd.DataFrame({s: d["ebitda"] for s, d in data.items()}).T / BN).round(2).to_string())
    print("\nQuarterly EBITDA ($bn)\n")
    q = {s: load(s, "income_quarterly")["EBITDA"] / BN for s in symbols}
    q = pd.DataFrame(q).T.round(2)
    q.columns = [c.strftime("%Y-%m") for c in q.columns]
    print(q.to_string())
