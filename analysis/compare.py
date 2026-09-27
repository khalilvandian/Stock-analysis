"""Compare debt and growth across tickers saved under data/<SYMBOL>/.

Usage: uv run python analysis/compare.py CEG VST NRG TLN NEE DUK SO
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BN = 1e9


def load(symbol: str, name: str) -> pd.DataFrame:
    return pd.read_csv(Path("data") / symbol / f"{name}.csv", index_col=0, parse_dates=True)


def col(df: pd.DataFrame, name: str) -> pd.Series:
    return df[name] if name in df else pd.Series(np.nan, index=df.index)


def ttm(df: pd.DataFrame, name: str) -> float:
    """Sum of the last four quarters, or NaN if any are missing."""
    s = col(df, name).dropna()
    return s.iloc[-4:].sum() if len(s) >= 4 else np.nan


def cagr(s: pd.Series) -> float:
    s = s.dropna()
    s = s[s > 0]
    if len(s) < 2:
        return np.nan
    years = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1


def price_return(prices: pd.DataFrame, years: int) -> float:
    close = prices["Adj Close"].dropna()
    start = close.index[-1] - pd.DateOffset(years=years)
    if close.index[0] > start:
        return np.nan
    return close.iloc[-1] / close[close.index >= start].iloc[0] - 1


def metrics(symbol: str) -> dict[str, float]:
    bs_q = load(symbol, "balance_sheet_quarterly").sort_index()
    inc_q = load(symbol, "income_quarterly").sort_index()
    cf_q = load(symbol, "cash_flow_quarterly").sort_index()
    inc_a = load(symbol, "income_annual").sort_index()
    prices = load(symbol, "prices_daily")
    info = json.loads((Path("data") / symbol / "info.json").read_text())

    last = bs_q.dropna(subset=["Total Debt"]).iloc[-1]
    debt = last["Total Debt"]
    cash = last.get("Cash And Cash Equivalents", np.nan)
    ebitda = ttm(inc_q, "EBITDA")
    interest = ttm(inc_q, "Interest Expense")
    debt_1y_ago = bs_q["Total Debt"].dropna()
    debt_1y_ago = debt_1y_ago[debt_1y_ago.index <= last.name - pd.DateOffset(months=11)]

    return {
        "market_cap": info.get("marketCap", np.nan) / BN,
        "total_debt": debt / BN,
        "net_debt": (debt - cash) / BN,
        "net_debt/ebitda": (debt - cash) / ebitda,
        "debt/equity": debt / last.get("Stockholders Equity", np.nan),
        "ebitda/interest": ebitda / interest,
        "fcf_ttm": ttm(cf_q, "Free Cash Flow") / BN,
        "debt_growth_1y": debt / debt_1y_ago.iloc[-1] - 1 if len(debt_1y_ago) else np.nan,
        "revenue_cagr": cagr(col(inc_a, "Total Revenue")),
        "ebitda_cagr": cagr(col(inc_a, "EBITDA")),
        "eps_cagr": cagr(col(inc_a, "Diluted EPS")),
        "rev_growth_yoy_q": info.get("revenueGrowth", np.nan),
        "trailing_pe": info.get("trailingPE", np.nan),
        "forward_pe": info.get("forwardPE", np.nan),
        "fwd_eps_growth": info.get("forwardEps", np.nan) / info.get("trailingEps", np.nan) - 1,
        "return_1y": price_return(prices, 1),
        "return_3y": price_return(prices, 3),
        "balance_sheet_date": last.name.date().isoformat(),
    }


if __name__ == "__main__":
    symbols = [s.upper() for s in sys.argv[1:]] or ["CEG", "VST", "NRG", "TLN", "NEE", "DUK", "SO"]
    table = pd.DataFrame({s: metrics(s) for s in symbols})
    pd.set_option("display.width", 200)
    print(table.to_string(float_format=lambda x: f"{x:,.2f}"))
