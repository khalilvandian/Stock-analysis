"""Intraday quotes (issue #35): python -m stock_analysis.db quotes.

One TradingView request (its "global" screener, so any exchange works) for every company in
the database: each one in core_company, by its listing in the latest snapshot that names it,
else its exchange and symbol, plus every listing of the newest index snapshot. Stored in
raw_tv_quote with the payload kept in raw_payload. The site reads the newest quote per company
(v_quote_latest) through the web API's GET /quotes; analysis/live.js recomputes every
price-dependent value on the pages from it.

It runs as its own Azure Container Apps Job (stock-quotes, deploy/quotes-job.ps1), every hour
on weekdays, around the clock, so every market's session is covered; when no market has moved,
the prices are the same as last time and nothing is stored (raw_fetch skips a digest seen
before; the digest covers the listings, prices and session, not the volume, which still
ticks after the close).
"""

from __future__ import annotations

import httpx
import pandas as pd
from sqlalchemy.engine import Connection

from .. import tradingview
from ..db import frame, insert_df
from ..db.load_files import UNIVERSE, finish_fetch
from .common import NoData, Outcome, RateLimited, log_error, sha256, start_fetch

SOURCE = "tradingview_quotes"
MARKET = "global"  # TradingView's screener across every exchange
REQUEST_KEY = "all"
FIELDS = [
    "name",
    "close",
    "change",
    "change_abs",
    "volume",
    "currency",
    "update_mode",
    "current_session",
]


LISTINGS = """
SELECT DISTINCT ON (tv_symbol) tv_symbol, symbol FROM (
    SELECT COALESCE(
               (SELECT r.tv_symbol FROM raw_tv_constituent r
                WHERE r.symbol = c.symbol ORDER BY r.fetch_id DESC LIMIT 1),
               NULLIF(c.exchange, '') || ':' || c.symbol) AS tv_symbol,
           c.symbol
    FROM core_company c
    UNION ALL
    SELECT tv_symbol, symbol FROM raw_tv_constituent
    WHERE fetch_id = (SELECT MAX(f.fetch_id) FROM raw_fetch f
                      JOIN raw_tv_constituent t ON t.fetch_id = f.fetch_id
                      WHERE f.source = 'tradingview' AND f.request_key = :u)
) x
WHERE tv_symbol IS NOT NULL
ORDER BY tv_symbol"""


def listings(conn: Connection, index: str = UNIVERSE) -> dict[str, str]:
    """Every company in the database as {TradingView listing ("NYSE:NEE"): our symbol}: the
    companies in core_company (members, past members, the other share classes) and the
    listings of the newest snapshot of the index (before the first build)."""
    df = frame(conn, LISTINGS, {"u": index})
    return dict(zip(df["tv_symbol"], df["symbol"], strict=True))


def quote_rows(d: pd.DataFrame, symbols: dict[str, str] | None = None) -> pd.DataFrame:
    """TradingView's rows as raw_tv_quote rows, under our symbol for each listing (TradingView's
    own name where we have none); a listing without a positive price is left out."""
    ours = symbols or {}
    out = pd.DataFrame(
        {
            "tv_symbol": d.index,
            "symbol": [ours.get(t, n) for t, n in zip(d.index, d["name"], strict=True)],
            "price": pd.to_numeric(d["close"], errors="coerce").to_numpy(),
            "change_pct": pd.to_numeric(d["change"], errors="coerce").to_numpy(),
            "change_abs": pd.to_numeric(d["change_abs"], errors="coerce").to_numpy(),
            "volume": pd.to_numeric(d["volume"], errors="coerce").to_numpy(),
            "currency": d["currency"].to_numpy(),
            "session": d["current_session"].to_numpy(),
            "delay_s": [tradingview.delay_seconds(m) for m in d["update_mode"]],
        }
    )
    out = out[out["price"] > 0].dropna(subset=["symbol"])
    return out.drop_duplicates("tv_symbol").sort_values("tv_symbol").reset_index(drop=True)


def load_quotes(
    conn: Connection, http: httpx.Client, index: str = UNIVERSE, symbols: list[str] | None = None
) -> Outcome:
    """Fetch and store one set of quotes. `symbols` limits it to those companies (a sample)."""
    known = listings(conn, index)
    if symbols:
        wanted = {s.upper() for s in symbols}
        known = {t: s for t, s in known.items() if s.upper() in wanted}
    if not known:
        raise NoData("no companies in the database: run the ingest job first")
    try:
        d, body = tradingview.lookup(MARKET, sorted(known), FIELDS, client=http)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise RateLimited(f"TradingView 429: {exc}") from exc
        raise
    out = Outcome(requests=1)
    rows = quote_rows(d, known)
    if rows.empty:
        raise NoData("TradingView returned no prices")
    key = REQUEST_KEY if not symbols else f"{REQUEST_KEY}:{','.join(sorted(symbols))}"
    url = tradingview.SCAN_URL.format(market=MARKET)
    # The prices decide whether this is new: after the close the volume still ticks.
    digest = sha256(rows[["tv_symbol", "price", "session"]].to_csv(index=False))
    fetch_id = start_fetch(conn, SOURCE, key, url, digest, payload=body)
    if fetch_id is None:  # the same prices as last time: the market is closed
        out.received = len(rows)
        return out
    rows.insert(0, "fetch_id", fetch_id)
    insert_df(conn, "raw_tv_quote", rows)
    finish_fetch(conn, fetch_id, len(d), len(rows))
    out.received, out.stored = len(d), len(rows)
    out.fetch_ids.append(fetch_id)
    return out


def fetch_quotes(db, symbols: list[str] | None = None, http: httpx.Client | None = None) -> dict:
    """One run: the quotes in one transaction; a failure is a raw_fetch row with the error.
    status: ok (stored), unchanged (same prices as last time), error."""
    own = http is None
    http = http or httpx.Client(timeout=60, headers={"User-Agent": "stock-analysis"})
    try:
        with db.begin() as conn:
            out = load_quotes(conn, http, symbols=symbols)
        status = "ok" if out.stored else "unchanged"
        return {"status": status, "received": out.received, "stored": out.stored,
                "fetch_ids": out.fetch_ids}  # fmt: skip
    except (httpx.HTTPError, NoData, RateLimited) as exc:
        with db.begin() as conn:
            url = tradingview.SCAN_URL.format(market=MARKET)
            log_error(conn, SOURCE, REQUEST_KEY, url, str(exc))
        return {"status": "error", "error": str(exc)}
    finally:
        if own:
            http.close()
