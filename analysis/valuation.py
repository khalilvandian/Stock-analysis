"""Valuation snapshot across tickers saved under data/<SYMBOL>/.

Mixes Yahoo's snapshot fields (info.json) with ratios computed from the saved
statements, plus each stock's P/E at past year-ends for context.

Usage: uv run python analysis/valuation.py CEG VST NRG TLN NEE DUK SO
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

BN = 1e9


def load(symbol: str, name: str) -> pd.DataFrame:
    df = pd.read_csv(Path("data") / symbol / f"{name}.csv", index_col=0, parse_dates=True)
    return df.sort_index()


def ttm(df: pd.DataFrame, name: str) -> float:
    s = df[name].dropna() if name in df else pd.Series(dtype=float)
    return s.iloc[-4:].sum() if len(s) >= 4 else np.nan


def snapshot(symbol: str) -> dict[str, float]:
    info = json.loads((Path("data") / symbol / "info.json").read_text())
    get = lambda k: info.get(k) if info.get(k) is not None else np.nan  # noqa: E731
    bs_q = load(symbol, "balance_sheet_quarterly").dropna(subset=["Total Debt"])
    inc_q, cf_q = load(symbol, "income_quarterly"), load(symbol, "cash_flow_quarterly")

    price, mcap = get("currentPrice"), get("marketCap")
    last = bs_q.iloc[-1]
    ev = mcap + last["Total Debt"] - last["Cash And Cash Equivalents"]
    return {
        "price": price,
        "trailing_pe": get("trailingPE"),
        "forward_pe": get("forwardPE"),
        "peg (yahoo)": get("pegRatio"),
        "ev/ebitda_ttm": ev / ttm(inc_q, "EBITDA"),
        "price/sales": get("priceToSalesTrailing12Months"),
        "price/book": get("priceToBook"),
        "fcf_yield_ttm": ttm(cf_q, "Free Cash Flow") / mcap,
        "dividend_yield": get("dividendYield") / 100,
        "vs_52w_high": price / get("fiftyTwoWeekHigh") - 1,
        "vs_200d_avg": price / get("twoHundredDayAverage") - 1,
        "analyst_upside": get("targetMeanPrice") / price - 1,
        "analyst_view": info.get("recommendationKey"),
        "beta": get("beta"),
    }


def year_end_pe(symbol: str) -> pd.Series:
    """GAAP P/E at each fiscal year-end: year-end close / that year's diluted EPS."""
    eps = load(symbol, "income_annual")["Diluted EPS"].dropna()
    close = load(symbol, "prices_daily")["Close"]
    pe = {
        d.year: close[close.index <= d].iloc[-1] / e
        for d, e in eps.items()
        if e > 0 and d >= close.index[0]
    }
    return pd.Series(pe, dtype=float)


if __name__ == "__main__":
    symbols = [s.upper() for s in sys.argv[1:]] or ["CEG", "VST", "NRG", "TLN", "NEE", "DUK", "SO"]
    pd.set_option("display.width", 200)
    snap = pd.DataFrame({s: snapshot(s) for s in symbols})
    print(snap.to_string(float_format=lambda x: f"{x:,.2f}"))
    print("\nGAAP P/E at fiscal year-end (loss years omitted)\n")
    print(pd.DataFrame({s: year_end_pe(s) for s in symbols}).T.round(1).to_string())
