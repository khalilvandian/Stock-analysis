"""Yahoo Finance through yfinance: daily prices, the financial statements and the earnings
dates (estimated and reported EPS). Yahoo publishes no limit; it answers "too many requests"
when it is called too often, which yfinance raises as YFRateLimitError.

All calls go through `YahooClient`, so the tests can swap in a fake one (yfinance talks
to Yahoo through curl_cffi, which respx can't mock).
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.engine import Connection

from ..db import scalar
from ..db.raw import PRICE_COLUMNS, STATEMENT_FILES, finish_fetch, store_changed
from .common import NoData, Outcome, RateLimited, sha256, start_fetch

STATEMENTS = {
    ("income", "annual"): "income_stmt",
    ("income", "quarterly"): "quarterly_income_stmt",
    ("balance_sheet", "annual"): "balance_sheet",
    ("balance_sheet", "quarterly"): "quarterly_balance_sheet",
    ("cash_flow", "annual"): "cashflow",
    ("cash_flow", "quarterly"): "quarterly_cashflow",
}
assert set(STATEMENTS) == set(STATEMENT_FILES.values())
PRICE_VALUES = ["open", "high", "low", "close", "volume", "dividends", "stock_splits"]


def yahoo_symbol(symbol: str) -> str:
    """BRK.B on TradingView is BRK-B on Yahoo; an exchange suffix (FTSEMIB.MI) stays."""
    return re.sub(r"\.([A-Z])$", r"-\1", symbol)


class YahooClient:
    """The few yfinance calls the loaders need. Rate limits become RateLimited."""

    def __init__(self):
        import yfinance as yf
        from yfinance.exceptions import YFRateLimitError

        self.yf, self.limit_error = yf, YFRateLimitError

    def _call(self, fn):
        try:
            return fn()
        except self.limit_error as exc:
            raise RateLimited(f"Yahoo: {exc}") from exc

    def prices(self, symbol: str, start: str) -> pd.DataFrame:
        t = self.yf.Ticker(yahoo_symbol(symbol))
        return self._call(
            lambda: t.history(start=start, auto_adjust=False, actions=True, raise_errors=True)
        )

    def statement(self, symbol: str, attribute: str) -> pd.DataFrame | None:
        t = self.yf.Ticker(yahoo_symbol(symbol))
        return self._call(lambda: getattr(t, attribute))

    def earnings(self, symbol: str) -> pd.DataFrame | None:
        t = self.yf.Ticker(yahoo_symbol(symbol))
        return self._call(lambda: t.get_earnings_dates(limit=40))


# ---------------------------------------------------------------- prices


def price_frame(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["symbol", "date", *PRICE_VALUES])
    p = raw.copy()
    idx = pd.DatetimeIndex(p.index)
    p.index = (idx.tz_localize(None) if idx.tz is not None else idx).strftime("%Y-%m-%d")
    p = p.rename_axis("date").reset_index()
    for col in PRICE_COLUMNS:
        if col not in p:
            p[col] = 0.0 if col in ("Dividends", "Stock Splits") else None
    p = p.rename(columns=PRICE_COLUMNS)[list(PRICE_COLUMNS.values())]
    p["volume"] = pd.to_numeric(p["volume"]).round().astype("Int64")
    p = p.dropna(subset=["close"]).drop_duplicates("date", keep="last")
    p.insert(0, "symbol", symbol)
    return p


def load_prices(
    conn: Connection, yahoo: YahooClient, symbol: str, first: str, overlap_days: int
) -> Outcome:
    """New days since the newest stored one (with an overlap, to catch corrections). A split
    since then rescales the whole history, so the full history is fetched again."""
    newest = scalar(conn, "SELECT MAX(date) FROM raw_yahoo_price WHERE symbol = :s", {"s": symbol})
    start = first
    if newest:
        start = max(first, (pd.Timestamp(newest) - timedelta(days=overlap_days)).strftime("%F"))
    out = Outcome(requests=1)
    raw = yahoo.prices(symbol, start)
    df = price_frame(raw, symbol)
    if newest and start != first and (df["stock_splits"].fillna(0) > 0).any():
        raw = yahoo.prices(symbol, first)
        df = price_frame(raw, symbol)
        out.requests += 1
    if df.empty:
        raise NoData(f"Yahoo has no prices for {symbol} since {start}")
    url = f"yfinance:history?symbol={yahoo_symbol(symbol)}&start={start}"
    fetch_id = start_fetch(
        conn, "yahoo_prices", symbol, url, sha256(df.to_csv(index=False)),
        payload=raw.to_csv().encode(), media_type="text/csv",  # yfinance's table as returned
    )  # fmt: skip
    if fetch_id is None:
        return out
    stored = store_changed(conn, "raw_yahoo_price", df, ["symbol", "date"], PRICE_VALUES, fetch_id)
    finish_fetch(conn, fetch_id, len(df), stored)
    out.received, out.stored = len(df), stored
    out.fetch_ids.append(fetch_id)
    return out


# ---------------------------------------------------------------- statements


def statement_frame(
    raw: pd.DataFrame | None, symbol: str, statement: str, frequency: str
) -> pd.DataFrame:
    """yfinance's statement (line items as rows, periods as columns) in raw_yahoo_statement's
    long form."""
    cols = ["symbol", "statement", "frequency", "period_end", "line_item", "value"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    wide = raw.T.sort_index()
    wide.index = pd.to_datetime(wide.index).strftime("%Y-%m-%d")
    long = (
        wide.rename_axis("period_end")
        .reset_index()
        .melt(id_vars="period_end", var_name="line_item", value_name="value")
    )
    long["value"] = pd.to_numeric(long["value"], errors="coerce")
    long = long.dropna(subset=["value"])
    return long.assign(symbol=symbol, statement=statement, frequency=frequency)[cols]


def load_statements(conn: Connection, yahoo: YahooClient, symbol: str) -> Outcome:
    out = Outcome()
    frames, raw = [], {}
    for (statement, frequency), attribute in STATEMENTS.items():
        table = yahoo.statement(symbol, attribute)
        raw[attribute] = None if table is None else table.to_csv()
        frames.append(statement_frame(table, symbol, statement, frequency))
        out.requests += 1
    df = pd.concat(frames, ignore_index=True)
    if df.empty:
        raise NoData(f"Yahoo has no statements for {symbol}")
    url = f"yfinance:statements?symbol={yahoo_symbol(symbol)}"
    fetch_id = start_fetch(
        conn, "yahoo_statements", symbol, url, sha256(df.to_csv(index=False)),
        payload=json.dumps(raw).encode(),  # each yfinance statement table, as CSV
    )  # fmt: skip
    if fetch_id is None:
        return out
    stored = 0
    key = ["symbol", "statement", "frequency", "period_end", "line_item"]
    for _, g in df.groupby(["statement", "frequency"]):
        stored += store_changed(conn, "raw_yahoo_statement", g, key, ["value"], fetch_id)
    finish_fetch(conn, fetch_id, len(df), stored)
    out.received, out.stored = len(df), stored
    out.fetch_ids.append(fetch_id)
    return out


# ---------------------------------------------------------------- earnings dates


def earnings_frame(raw: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    cols = ["symbol", "report_date", "eps_estimate", "eps_reported", "surprise_pct"]
    if raw is None or raw.empty:
        return pd.DataFrame(columns=cols)
    idx = pd.DatetimeIndex(raw.index)
    if idx.tz is not None:
        idx = idx.tz_convert("America/New_York").tz_localize(None)
    e = pd.DataFrame(
        {
            "symbol": symbol,
            "report_date": idx.strftime("%Y-%m-%d"),
            "eps_estimate": pd.to_numeric(raw.get("EPS Estimate"), errors="coerce").to_numpy(),
            "eps_reported": pd.to_numeric(raw.get("Reported EPS"), errors="coerce").to_numpy(),
            "surprise_pct": pd.to_numeric(raw.get("Surprise(%)"), errors="coerce").to_numpy(),
        }
    )
    # A report listed twice (Yahoo does that): keep the row with a reported EPS.
    e = e.sort_values(["report_date", "eps_reported"], na_position="first")
    return e.drop_duplicates("report_date", keep="last")[cols]


def load_earnings(conn: Connection, yahoo: YahooClient, symbol: str) -> Outcome:
    out = Outcome(requests=1)
    table = yahoo.earnings(symbol)
    df = earnings_frame(table, symbol)
    if df.empty:
        raise NoData(f"Yahoo has no earnings dates for {symbol}")
    url = f"yfinance:earnings_dates?symbol={yahoo_symbol(symbol)}"
    fetch_id = start_fetch(
        conn, "yahoo_earnings", symbol, url, sha256(df.to_csv(index=False)),
        payload=table.to_csv().encode(), media_type="text/csv",
    )  # fmt: skip
    if fetch_id is None:
        return out
    values = ["eps_estimate", "eps_reported", "surprise_pct"]
    stored = store_changed(
        conn, "raw_yahoo_earnings", df, ["symbol", "report_date"], values, fetch_id
    )
    finish_fetch(conn, fetch_id, len(df), stored)
    out.received, out.stored = len(df), stored
    out.fetch_ids.append(fetch_id)
    return out


def today() -> date:
    return date.today()
