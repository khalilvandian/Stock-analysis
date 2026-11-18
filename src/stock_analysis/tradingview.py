"""TradingView's stock screener: current fundamentals, 20 years of yearly figures and
technicals for every listed company, one request per market (no key needed).

This is the public interface behind tradingview.com/screener; it is not an official API, so
field names can change. Market values and statements are in each company's own currency
(see `fundamental_currency_code`); prices are in the trading currency (`currency`, which for
London is GBX, pence).
"""

from __future__ import annotations

import httpx
import pandas as pd

SCAN_URL = "https://scanner.tradingview.com/{market}/scan"
PAGE = 2000


def scan(
    market: str,
    columns: list[str],
    filters: list[dict] | None = None,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    """All rows of one market's screener matching `filters`, one column per field.

    The index is TradingView's "EXCHANGE:TICKER" symbol.
    """
    own = client is None
    client = client or httpx.Client(timeout=60)
    rows, start, total = [], 0, None
    try:
        while total is None or start < total:
            body = {
                "columns": columns,
                "filter": filters or [],
                "range": [start, start + PAGE],
                "sort": {"sortBy": "market_cap_basic", "sortOrder": "desc"},
            }
            r = client.post(SCAN_URL.format(market=market), json=body)
            r.raise_for_status()
            data = r.json()
            total = data.get("totalCount", 0)
            page = data.get("data") or []
            rows += [
                {"tv_symbol": x["s"], **dict(zip(columns, x["d"], strict=False))} for x in page
            ]
            if not page:
                break
            start += PAGE
    finally:
        if own:
            client.close()
    if not rows:
        return pd.DataFrame(columns=["tv_symbol", *columns]).set_index("tv_symbol")
    return pd.DataFrame(rows).set_index("tv_symbol")


PRIMARY_FILTER = {"left": "is_primary", "operation": "equal", "right": True}


def company_key(description: pd.Series) -> pd.Series:
    """The company behind a listing: its description without the share class
    ("Alphabet Inc. Class C" -> "Alphabet Inc.")."""
    return description.fillna("").str.replace(r"\s+Class [A-Z]\b.*$", "", regex=True).str.strip()


def one_per_company(d: pd.DataFrame) -> pd.DataFrame:
    """One listing per company among the rows of an index (needs `description`,
    `is_primary` and `market_cap_basic`): the primary listing where it is a member, otherwise
    the member listing itself. Berkshire's primary listing is BRK.A but the S&P 500 holds
    BRK.B (Brown-Forman likewise), and GM's member listing is not marked primary, so keeping
    primary listings only would leave those companies out."""
    if d.empty:
        return d
    d = d.assign(_key=company_key(d["description"]), _p=d["is_primary"].fillna(False).astype(bool))
    d = d.sort_values(["_p", "market_cap_basic"], ascending=False)
    d = d[~d["_key"].duplicated() | (d["_key"] == "")]
    return d.drop(columns=["_key", "_p"])
