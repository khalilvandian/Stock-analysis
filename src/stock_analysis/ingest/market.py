"""The universe and exchange rates: TradingView's list of the index members (one screener
request for the whole market, filtered to the index) and the ECB's reference rates."""

from __future__ import annotations

import io

import httpx
import pandas as pd
from sqlalchemy.engine import Connection

from .. import ecb, tradingview
from ..db import insert_df
from ..db.raw import TV_COLUMNS, as_json, finish_fetch, store_changed
from .common import NoData, Outcome, RateLimited, sha256, start_fetch

TV_FIELDS = [
    "name",
    "description",
    "exchange",
    "sector",
    "industry",
    "country",
    "currency",
    "market_cap_basic",
    "fundamental_currency_code",
    "indexes",
]
TV_FILTERS = [
    {"left": "is_primary", "operation": "equal", "right": True},
    {"left": "type", "operation": "equal", "right": "stock"},
    {"left": "market_cap_basic", "operation": "greater", "right": 1e9},
]
# Every field the screener reads is kept with the snapshot (extra_json).
TV_FIELDS += [f for f in tradingview.SCREENER_FIELDS if f not in TV_FIELDS]
WATCHLIST_KEY = "watchlist"  # request key of the snapshot of the watch list's own symbols


def in_index(indexes, code: str) -> bool:
    return isinstance(indexes, list) and any(
        isinstance(i, dict) and i.get("proname") == code for i in indexes
    )


def scan(http: httpx.Client, market: str, filters: list[dict]) -> pd.DataFrame:
    try:
        return tradingview.scan(market, TV_FIELDS, filters, client=http)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise RateLimited(f"TradingView 429: {exc}") from exc
        raise


def store_snapshot(conn: Connection, d: pd.DataFrame, market: str, key: str) -> Outcome:
    """One snapshot (a fetch) of TradingView rows: the main fields in columns, the rest of
    the screener's fields (not the index list) in extra_json."""
    out = Outcome(requests=1)
    tv = d[list(TV_COLUMNS)].rename(columns=TV_COLUMNS)
    tv = tv.drop_duplicates("tv_symbol").sort_values("tv_symbol")
    url = tradingview.SCAN_URL.format(market=market)
    extra = d.loc[tv.index, [c for c in d.columns if c not in TV_COLUMNS and c != "indexes"]]
    tv["extra_json"] = as_json(extra)
    fetch_id = start_fetch(
        conn, "tradingview", key, url, sha256(tv.to_csv(index=False)),
        payload=d.to_json(orient="records").encode(),  # every field the scan returned
    )  # fmt: skip
    if fetch_id is None:
        return out
    tv.insert(0, "fetch_id", fetch_id)
    insert_df(conn, "raw_tv_constituent", tv)
    finish_fetch(conn, fetch_id, len(tv), len(tv))
    out.received = out.stored = len(tv)
    out.fetch_ids.append(fetch_id)
    return out


def load_constituents(conn: Connection, http: httpx.Client, market: str, index: str) -> Outcome:
    d = scan(http, market, TV_FILTERS)
    d = d[d["indexes"].map(lambda v: in_index(v, index))].reset_index()
    if d.empty:
        raise NoData(f"TradingView lists no members of {index} in {market}")
    return store_snapshot(conn, d, market, index)


def load_watch_companies(
    conn: Connection, http: httpx.Client, market: str, symbols: list[str]
) -> Outcome:
    """The watch list's stocks and peers that aren't in the index (foreign listings, smaller
    companies): one request for all of them. A ticker listed on several exchanges keeps its
    largest listing; the primary flag isn't required (a US ADR is often not primary)."""
    if not symbols:
        raise NoData("the watch list is empty")
    d = scan(http, market, [{"left": "name", "operation": "in_range", "right": sorted(symbols)}])
    if d.empty:
        raise NoData(f"TradingView has none of {', '.join(sorted(symbols))}")
    d = d.sort_values("market_cap_basic", ascending=False, na_position="last")
    d = d[~d["name"].duplicated()].reset_index()
    return store_snapshot(conn, d, market, WATCHLIST_KEY)


def rates_frame(text: str) -> pd.DataFrame:
    """The ECB's CSV (units per euro) as US dollars per unit, per currency and day."""
    d = pd.read_csv(io.StringIO(text))
    d = d[["CURRENCY", "TIME_PERIOD", "OBS_VALUE"]].dropna()
    per_eur = d.pivot_table(index="TIME_PERIOD", columns="CURRENCY", values="OBS_VALUE")
    per_eur["EUR"] = 1.0
    usd = per_eur.rdiv(per_eur["USD"], axis=0)  # USD per unit = (USD per EUR) / (X per EUR)
    usd.columns.name = None
    long = usd.rename_axis("date").reset_index().melt(id_vars="date", var_name="currency")
    long = long.rename(columns={"value": "usd_per_unit"}).dropna()
    return long[["currency", "date", "usd_per_unit"]]


def load_rates(conn: Connection, http: httpx.Client, days: int = 10) -> Outcome:
    r = http.get(ecb.URL, params={"lastNObservations": days, "format": "csvdata"})
    if r.status_code == 429:
        raise RateLimited("ECB 429")
    r.raise_for_status()
    out = Outcome(requests=1)
    df = rates_frame(r.text)
    fetch_id = start_fetch(
        conn, "ecb_rates", "EUR", ecb.URL, sha256(r.content), payload=r.content,
        media_type="text/csv",
    )  # fmt: skip
    if fetch_id is None:
        return out
    stored = 0
    for _, g in df.groupby("currency"):
        stored += store_changed(
            conn, "raw_ecb_rate", g, ["currency", "date"], ["usd_per_unit"], fetch_id
        )
    finish_fetch(conn, fetch_id, len(df), stored)
    out.received, out.stored = len(df), stored
    out.fetch_ids.append(fetch_id)
    return out
