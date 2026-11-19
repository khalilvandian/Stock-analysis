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

# The fields the ingest keeps for every company of its snapshots (raw_tv_constituent: the
# first few in columns of their own, the rest in extra_json). The market screener
# (stock_analysis.screener) and the watch list read them from there. Statements and market values
# are in the company's own currency (fundamental_currency_code), prices in the trading currency.
SCREENER_FIELDS = [
    "name",
    "description",
    "exchange",
    "country",
    "sector",
    "industry",
    "market_cap_basic",
    "fundamental_currency_code",
    "currency",
    "close",
    # absolute values (fundamental currency)
    "total_debt_fq",
    "net_debt_fq",
    "short_term_debt_fq",
    "long_term_debt_fq",
    "cash_n_short_term_invest_fq",
    "total_revenue_ttm",
    "ebitda_ttm",
    "net_income_ttm",
    "earnings_per_share_diluted_ttm",
    "cash_f_operating_activities_ttm",
    "capital_expenditures_ttm",
    "free_cash_flow_ttm",
    # ratios and scores
    "ebitda_interst_cover_ttm",
    "return_on_equity_fq",
    "net_margin_ttm",
    "piotroski_f_score_ttm",
    "altman_z_score_ttm",
    "price_earnings_ttm",
    "enterprise_value_ebitda_ttm",
    "price_book_fq",
    "total_equity_fq",
    "book_tangible_per_share_fq",
    "dividends_yield",
    "earnings_per_share_forecast_next_fy",
    "beta_1_year",
    "price_target_average",
    "recommendation_mark",
    # yearly history, newest first
    "fiscal_period_fy_h",
    "fiscal_period_end_fy",
    "earnings_per_share_diluted_fy_h",
    "total_revenue_fy_h",
    "ebitda_fy_h",
    "dps_common_stock_prim_issue_fy_h",
    "dividend_payout_ratio_ttm",
    "debt_to_equity_fq",
    # technicals
    "SMA50",
    "SMA200",
    "RSI",
    "price_52_week_high",
    "price_52_week_low",
    "Recommend.All",
    "Perf.Y",
    "indexes",
]


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


def lookup(
    market: str,
    tickers: list[str],
    columns: list[str],
    client: httpx.Client | None = None,
) -> tuple[pd.DataFrame, bytes]:
    """`columns` for exactly these listings ("NYSE:NEE", ...), in one request: TradingView
    drops the ones it doesn't know. Returns the rows (index: the TradingView symbol) and the
    response body as received."""
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        body = {"columns": columns, "symbols": {"tickers": tickers}}
        r = client.post(SCAN_URL.format(market=market), json=body)
        r.raise_for_status()
    finally:
        if own:
            client.close()
    rows = [
        {"tv_symbol": x["s"], **dict(zip(columns, x["d"], strict=False))}
        for x in r.json().get("data") or []
    ]
    d = pd.DataFrame(rows, columns=["tv_symbol", *columns]).set_index("tv_symbol")
    return d, r.content


def delay_seconds(update_mode) -> int:
    """How old a price is, from TradingView's update mode: 'delayed_streaming_900' -> 900,
    'streaming' (real time) -> 0."""
    tail = str(update_mode or "").rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


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
