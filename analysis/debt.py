"""Debt and leverage summary for a ticker saved under data/<SYMBOL>/.

Usage: uv run python analysis/debt.py CEG
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BN = 1e9


def load(symbol: str, name: str) -> pd.DataFrame:
    return pd.read_csv(Path("data") / symbol / f"{name}.csv", index_col=0, parse_dates=True)


def leverage(symbol: str, period: str = "annual") -> pd.DataFrame:
    """Debt levels and coverage ratios per period.

    Flow items (EBITDA, interest, cash flows) are annual figures for ``annual``
    and trailing-twelve-month sums for ``quarterly``.
    """
    bs = load(symbol, f"balance_sheet_{period}")
    inc = load(symbol, f"income_{period}")
    cf = load(symbol, f"cash_flow_{period}")
    if period == "quarterly":
        inc, cf = inc.rolling(4).sum(), cf.rolling(4).sum()

    df = pd.DataFrame(
        {
            "total_debt": bs["Total Debt"],
            "current_debt": bs["Current Debt And Capital Lease Obligation"],
            "long_term_debt": bs["Long Term Debt And Capital Lease Obligation"],
            "cash": bs["Cash And Cash Equivalents"],
            "equity": bs["Stockholders Equity"],
            "ebitda": inc["EBITDA"],
            "interest_expense": inc["Interest Expense"],
            "operating_cf": cf["Operating Cash Flow"],
            "free_cf": cf["Free Cash Flow"],
        }
    ).dropna(subset=["total_debt"])
    df["net_debt"] = df["total_debt"] - df["cash"]
    df["net_debt_to_ebitda"] = df["net_debt"] / df["ebitda"]
    df["debt_to_equity"] = df["total_debt"] / df["equity"]
    df["interest_coverage"] = df["ebitda"] / df["interest_expense"]
    df["current_share_of_debt"] = df["current_debt"] / df["total_debt"]
    return df


def show(df: pd.DataFrame) -> str:
    money = [c for c in df.columns if df[c].abs().max() > 1e6]
    out = df.copy()
    out[money] = out[money] / BN
    out.index = out.index.date
    return out.T.round(2).to_string()


if __name__ == "__main__":
    symbol = (sys.argv[1] if len(sys.argv) > 1 else "CEG").upper()
    for period in ("annual", "quarterly"):
        note = " (flows are trailing 12 months)" if period == "quarterly" else ""
        print(f"\n{symbol} {period} leverage, $bn except ratios{note}\n")
        print(show(leverage(symbol, period)))
    cf = load(symbol, "cash_flow_annual")
    cols = [
        "Issuance Of Debt",
        "Repayment Of Debt",
        "Repurchase Of Capital Stock",
        "Cash Dividends Paid",
        "Capital Expenditure",
    ]
    print(f"\n{symbol} annual capital allocation, $bn\n")
    alloc = cf[cols].dropna(how="all") / BN
    alloc.index = alloc.index.date
    print(alloc.T.round(2).to_string())
