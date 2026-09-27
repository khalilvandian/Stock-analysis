"""Download a ticker's market and fundamental data from Yahoo Finance to CSV.

Usage: uv run python -m stock_analysis.fetch CEG [--out data]
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yfinance as yf


def _statement(df: pd.DataFrame) -> pd.DataFrame:
    """Yahoo returns line items as rows and periods as columns; flip to one row per period."""
    out = df.T.sort_index()
    out.index = pd.to_datetime(out.index).date
    out.index.name = "period_end"
    return out


def fetch(symbol: str, out_dir: Path | str = "data") -> Path:
    """Save prices, dividends, financial statements and company info for ``symbol``.

    Returns the directory the files were written to.
    """
    symbol = symbol.upper()
    dest = Path(out_dir) / symbol
    dest.mkdir(parents=True, exist_ok=True)
    ticker = yf.Ticker(symbol)

    prices = ticker.history(period="max", auto_adjust=False, actions=True)
    if prices.empty:
        raise ValueError(f"No price data returned for {symbol!r}")
    prices.index = prices.index.tz_localize(None).date
    prices.index.name = "date"
    prices.to_csv(dest / "prices_daily.csv")

    dividends = prices.loc[prices["Dividends"] > 0, ["Dividends"]]
    dividends.to_csv(dest / "dividends.csv")

    statements = {
        "income_annual": ticker.income_stmt,
        "income_quarterly": ticker.quarterly_income_stmt,
        "balance_sheet_annual": ticker.balance_sheet,
        "balance_sheet_quarterly": ticker.quarterly_balance_sheet,
        "cash_flow_annual": ticker.cashflow,
        "cash_flow_quarterly": ticker.quarterly_cashflow,
    }
    for name, df in statements.items():
        if df is not None and not df.empty:
            _statement(df).to_csv(dest / f"{name}.csv")

    info = ticker.info
    (dest / "info.json").write_text(json.dumps(info, indent=2, default=str))

    meta = {
        "symbol": symbol,
        "source": "Yahoo Finance (yfinance)",
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (dest / "_meta.json").write_text(json.dumps(meta, indent=2))
    return dest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("symbols", nargs="+")
    parser.add_argument("--out", default="data")
    args = parser.parse_args()
    for symbol in args.symbols:
        dest = fetch(symbol, args.out)
        print(f"{symbol.upper()}: saved to {dest}")
        for f in sorted(dest.iterdir()):
            print(f"  {f.name}")


if __name__ == "__main__":
    main()
