"""The universe and exchange rates: TradingView's list of the index members (one screener
request for the whole market, filtered to the index) and the ECB's reference rates."""

from __future__ import annotations

import io

import httpx
import pandas as pd
from sqlalchemy.engine import Connection

from .. import ecb, tradingview
from ..db import insert_df
from ..db.load_files import TV_COLUMNS, as_json, finish_fetch, store_changed
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
    "is_primary",
]
# Every listing, not only primary ones: the index sometimes holds a secondary listing
# (BRK.B, BF.B, GM); tradingview.one_per_company then keeps one listing per company.
TV_FILTERS = [
    {"left": "type", "operation": "equal", "right": "stock"},
    {"left": "market_cap_basic", "operation": "greater", "right": 1e9},
]


def in_index(indexes, code: str) -> bool:
    return isinstance(indexes, list) and any(
        isinstance(i, dict) and i.get("proname") == code for i in indexes
    )


def load_constituents(conn: Connection, http: httpx.Client, market: str, index: str) -> Outcome:
    try:
        d = tradingview.scan(market, TV_FIELDS, TV_FILTERS, client=http)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 429:
            raise RateLimited(f"TradingView 429: {exc}") from exc
        raise
    d = d[d["indexes"].map(lambda v: in_index(v, index))]
    d = tradingview.one_per_company(d).sort_index().reset_index()
    out = Outcome(requests=1)
    if d.empty:
        raise NoData(f"TradingView lists no members of {index} in {market}")
    tv = d[list(TV_COLUMNS)].rename(columns=TV_COLUMNS)
    tv = tv.drop_duplicates("tv_symbol").sort_values("tv_symbol")
    url = tradingview.SCAN_URL.format(market=market)
    fetch_id = start_fetch(
        conn, "tradingview", index, url, sha256(tv.to_csv(index=False)),
        payload=d.to_json(orient="records").encode(),  # every field the scan returned
    )  # fmt: skip
    if fetch_id is None:
        return out
    extra = d.loc[tv.index, ["fundamental_currency_code"]]
    tv["extra_json"] = as_json(extra)
    tv.insert(0, "fetch_id", fetch_id)
    insert_df(conn, "raw_tv_constituent", tv)
    finish_fetch(conn, fetch_id, len(tv), len(tv))
    out.received = out.stored = len(tv)
    out.fetch_ids.append(fetch_id)
    return out


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
