"""Stage 1 of the market screener: good financial statements.

Finds the companies worth owning, before any thought of price. Settings in
config/screeners.toml; every rule, threshold and source is explained in report 13 and
the methods doc.

  1. Universe: every primary-listed stock above the minimum market value in the US and
     European markets, from TradingView's screener (current figures, 20 years of yearly
     EPS, revenue, EBITDA and dividends). Market values converted to US dollars at ECB
     rates.
  2. Gap filling: debt, cash, EBITDA and interest figures TradingView leaves blank are
     filled from Yahoo where it has them. Each filled value is named in `filled`.
  3. Peter Lynch's category (One Up on Wall Street, ch. 7): turnaround, cyclical, asset
     play, fast grower, stalwart or slow grower, from the EPS history, industry and
     balance sheet.
  4. Rules: banks, insurers and REITs get rules for their kind of business; every other
     company gets the rules of its Lynch category (utilities without the Altman score).
     A stock must pass every rule. Missing data = "incomplete", not a pass.

Writes data/screener/stage1.csv (every company: category, status, failed rules, filled
values) and .cache/screener/stage1_full.pkl (the same with the yearly history lists),
which Stage 2 reads.

Usage: uv run python analysis/stage1.py [--refresh]
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import yfinance as yf

from stock_analysis import ecb, tradingview

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen_common import (  # noqa: E402
    ABSOLUTE,
    CACHE,
    OUT,
    STAGE1_FULL,
    load_config,
    to_usd,
)

COLUMNS = [
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
    "book_tangible_per_share_fq",
    "dividends_yield",
    "earnings_per_share_forecast_next_fy",
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
]
FILTERS = [
    {"left": "is_primary", "operation": "equal", "right": True},
    {"left": "type", "operation": "equal", "right": "stock"},
    {"left": "subtype", "operation": "equal", "right": "common"},
    # market values are in local currency; a low floor here, the real one after conversion
    {"left": "market_cap_basic", "operation": "greater", "right": 5e7},
]

# TradingView exchange -> Yahoo suffix. Euronext depends on the market it was listed in.
YAHOO_SUFFIX = {
    "NYSE": "",
    "NASDAQ": "",
    "AMEX": "",
    "CBOE": "",
    "NYSE ARCA": "",
    "LSE": ".L",
    "XETR": ".DE",
    "FWB": ".F",
    "DUS": ".DU",
    "MIL": ".MI",
    "BME": ".MC",
    "SIX": ".SW",
    "OMXSTO": ".ST",
    "OMXCOP": ".CO",
    "OMXHEX": ".HE",
    "OSL": ".OL",
    "VIE": ".VI",
    "GPW": ".WA",
    "ATHEX": ".AT",
}
EURONEXT_SUFFIX = {
    "france": ".PA",
    "netherlands": ".AS",
    "belgium": ".BR",
    "portugal": ".LS",
    "ireland": ".IR",
    "norway": ".OL",
}


# --- configuration -------------------------------------------------------------------


def yahoo_symbol(tv_symbol: str, market: str) -> str | None:
    """'MIL:UCG' -> 'UCG.MI', 'NYSE:BRK.B' -> 'BRK-B', 'OMXSTO:INVE_A' -> 'INVE-A.ST'."""
    exchange, ticker = tv_symbol.split(":", 1)
    suffix = EURONEXT_SUFFIX.get(market) if exchange == "EURONEXT" else YAHOO_SUFFIX.get(exchange)
    if suffix is None:
        return None
    ticker = ticker.replace(".", "-").replace("_", "-")
    if exchange == "LSE":
        ticker = ticker.rstrip("-")
    return ticker + suffix


def screener_type(sector: str | None, industry: str | None, types: dict) -> str | None:
    """Which screener a company gets; None = skipped (funds and trusts)."""
    if industry in types.get("exclude", []):
        return None
    for name in ("banks", "insurers", "reits"):
        if industry in types.get(name, []):
            return name
    if sector in types.get("utilities_sector", []):
        return "utilities"
    return "general"


# --- step 1: universe ----------------------------------------------------------------


def fetch_universe(cfg: dict, today: str, refresh: bool = False) -> pd.DataFrame:
    """Every market of every region from TradingView, cached for the day."""
    cache = CACHE / f"tradingview_{today}.pkl"
    if cache.exists() and not refresh:
        return pd.read_pickle(cache)
    frames = []
    with httpx.Client(timeout=60) as client:
        for region, markets in cfg["regions"].items():
            for m in markets:
                d = tradingview.scan(m, COLUMNS, FILTERS, client=client)
                d["market"], d["region"] = m, region
                frames.append(d)
    d = pd.concat(frames)
    d = d[~d.index.duplicated()]
    CACHE.mkdir(parents=True, exist_ok=True)
    d.to_pickle(cache)
    return d


def yearly_growth(values, years: int) -> list[float]:
    """Year-on-year growth over the last `years` years from a newest-first list."""
    if not isinstance(values, list | tuple):
        return []
    v = [x for x in values[: years + 1]]
    out = []
    for new, old in zip(v, v[1:], strict=False):
        if new is None or old is None or old <= 0:
            continue
        out.append(new / old - 1)
    return out


def prepare(raw: pd.DataFrame, cfg: dict, fx: dict[str, float]) -> pd.DataFrame:
    """Convert to US dollars, derive ratios and pick each company's screener."""
    d = raw.copy()
    d["yahoo"] = [yahoo_symbol(s, m) for s, m in zip(d.index, d["market"], strict=False)]
    d["fx_fund"] = d["fundamental_currency_code"].map(fx)  # USD per unit of statements
    d["fx_price"] = d["currency"].map(fx)  # USD per unit of price
    d = d[d["fx_fund"].notna() & d["fx_price"].notna()]
    to_usd(d)
    d = d[d["cap_usd_bn"] * 1e9 >= cfg["min_market_cap_usd"]].copy()
    d["type"] = [
        screener_type(s, i, cfg["types"]) for s, i in zip(d["sector"], d["industry"], strict=False)
    ]
    d = d[d["type"].notna()].copy()
    d["filled"] = ""
    derive_short_term_debt(d)
    ratios(d)
    years = cfg["lynch"]["growth_years"]
    for col, key in (("total_revenue_fy_h", "revenue"), ("earnings_per_share_diluted_fy_h", "eps")):
        g = d[col].map(lambda v: yearly_growth(v, years))
        d[f"{key}_growth_avg"] = g.map(lambda x: float(np.mean(x)) if len(x) >= 3 else np.nan)
        d[f"{key}_growth_median"] = g.map(lambda x: float(np.median(x)) if len(x) >= 3 else np.nan)
        d[f"{key}_growth_years"] = g.map(len)
    d["eps"] = d["earnings_per_share_diluted_ttm"]
    # price in the statements' currency, so P/E works for London pence and foreign reporters
    d["price_fund"] = d["close"] * d["fx_price"] / d["fx_fund"]
    history_measures(d, cfg["lynch"])
    d["category"] = lynch_category(d, cfg["lynch"])
    return d


def _clean(values, n: int) -> list[float]:
    """The newest `n` entries of a newest-first history list, blanks dropped."""
    if not isinstance(values, list | tuple):
        return []
    return [float(v) for v in values[:n] if v is not None]


def history_measures(d: pd.DataFrame, lynch: dict) -> None:
    """Measures from the yearly history that Lynch's categories and rules need."""
    eps_h = d["earnings_per_share_diluted_fy_h"]
    years_h = d["fiscal_period_fy_h"]

    def cagr(v, n: int) -> float:
        if not isinstance(v, list | tuple) or len(v) <= n or v[0] is None or v[n] is None:
            return np.nan
        new, old = v[0], v[n]
        return (new / old) ** (1 / n) - 1 if new > 0 and old > 0 else np.nan

    def peak(v) -> float:
        x = _clean(v, 5)
        return max(x) if len(x) >= 3 else np.nan

    def big_drops(v) -> int:
        x = [e for e in (v or [])[:11] if e is not None] if isinstance(v, list) else []
        cut = -lynch["cyclical_drop_size"]
        return sum(1 for new, old in zip(x, x[1:], strict=False) if old > 0 and new / old - 1 < cut)

    def recession_drop(eps, years) -> float:
        """Worst EPS change in the fiscal years of the last two recessions (2009, 2020)."""
        if not isinstance(eps, list) or not isinstance(years, list):
            return np.nan
        by_year = {int(y): e for y, e in zip(years, eps, strict=False) if y and e is not None}
        moves = [
            by_year[y] / by_year[y - 1] - 1
            for y in lynch["recession_years"]
            if y in by_year and y - 1 in by_year and by_year[y - 1] > 0
        ]
        return min(moves) if moves else np.nan

    d["eps_growth_3y"] = eps_h.map(lambda v: cagr(v, 3))
    # Today's EPS against the best of the last 5 fiscal years. Both the 12-month figure and
    # the latest fiscal year must be down, so one bad quarter or one write-down year doesn't
    # make a turnaround.
    latest = eps_h.map(lambda v: _clean(v, 1)[0] if _clean(v, 1) else np.nan)
    best = eps_h.map(peak)
    d["eps_vs_5y_peak"] = (np.fmax(d["eps"], latest) / best - 1).where(best > 0)
    d["loss_now"] = (d["eps"] <= 0) | (latest <= 0)
    d["no_profit_5y"] = best <= 0
    d["eps_big_drops_10y"] = eps_h.map(big_drops)
    d["eps_avg_10y"] = eps_h.map(
        lambda v: float(np.mean(_clean(v, 10))) if len(_clean(v, 10)) >= 5 else np.nan
    )
    d["recession_eps_change"] = [recession_drop(e, y) for e, y in zip(eps_h, years_h, strict=False)]
    d["dividend_years_10y"] = d["dps_common_stock_prim_issue_fy_h"].map(
        lambda v: sum(1 for x in _clean(v, 10) if x > 0) if _clean(v, 10) else np.nan
    )
    avg_ebitda = d["ebitda_fy_h"].map(
        lambda v: float(np.mean(_clean(v, 10))) if len(_clean(v, 10)) >= 5 else np.nan
    )
    d["net_debt_to_avg_ebitda"] = (d["net_debt_fq"] / avg_ebitda).where(avg_ebitda > 0)
    d["net_cash_to_cap"] = -d["net_debt_fq"] / d["market_cap_basic"]
    d["debt_to_equity"] = d["debt_to_equity_fq"]
    total = d["total_debt_fq"]
    d["cash_to_total_debt"] = np.where(total == 0, np.inf, d["cash_n_short_term_invest_fq"] / total)
    d.loc[total.isna() | d["cash_n_short_term_invest_fq"].isna(), "cash_to_total_debt"] = np.nan


CATEGORIES = ["turnaround", "cyclical", "asset_play", "fast_grower", "stalwart", "slow_grower"]


def lynch_category(d: pd.DataFrame, lynch: dict) -> pd.Series:
    """Peter Lynch's six categories (One Up on Wall Street, ch. 7), tested in order.

    1. cyclical by industry (autos, airlines, steel, chemicals, oil...)
    2. turnaround: profitable in the last 5 years but losing money now, or EPS (both 12
       months and the latest fiscal year) less than half its 5-year peak
    3. cyclical by history: EPS fell sharply in several of the last 10 years, and the
       company isn't a fast grower
    "no_profit": no profit in any of the last 5 fiscal years. Not one of Lynch's
    categories; he skipped such companies ("avoid long shots"), so Stage 1 fails them.
    4. asset play: price below book value, or net cash a large part of market value
    5. fast grower / 6. stalwart / 7. slow grower by median yearly EPS growth (5 years)
    Blank when there isn't enough history to tell.
    """
    g = d["eps_growth_median"]
    conditions = [
        d["no_profit_5y"] == True,  # noqa: E712
        d["industry"].isin(lynch["cyclical_industries"]),
        (d["loss_now"] == True) | (d["eps_vs_5y_peak"] < -lynch["turnaround_drop"]),  # noqa: E712
        (d["eps_big_drops_10y"] >= lynch["cyclical_drops"]) & ~(g >= lynch["fast_growth"]),
        (d["price_book_fq"] < lynch["asset_price_to_book"])
        | (d["net_cash_to_cap"] > lynch["asset_net_cash"]),
        g >= lynch["fast_growth"],
        g >= lynch["stalwart_growth"],
        g.notna(),
    ]
    names = ["no_profit", "cyclical", "turnaround", "cyclical", "asset_play", "fast_grower"]
    names.append("stalwart")
    names.append("slow_grower")
    return pd.Series(np.select(conditions, names, default=""), index=d.index)


def derive_short_term_debt(d: pd.DataFrame) -> None:
    """Short-term debt left blank but total and long-term debt known: the difference."""
    gap = d["short_term_debt_fq"].isna() & d["total_debt_fq"].notna()
    gap &= d["long_term_debt_fq"].notna()
    d.loc[gap, "short_term_debt_fq"] = (
        d.loc[gap, "total_debt_fq"] - d.loc[gap, "long_term_debt_fq"]
    ).clip(lower=0)
    d.loc[gap, "filled"] += "short-term debt (total minus long-term); "
    no_debt = d["total_debt_fq"].fillna(np.nan) == 0
    for c in ("short_term_debt_fq", "long_term_debt_fq"):
        d.loc[no_debt & d[c].isna(), c] = 0.0


def ratios(d: pd.DataFrame) -> None:
    cash, std = d["cash_n_short_term_invest_fq"], d["short_term_debt_fq"]
    ltd, ebitda = d["long_term_debt_fq"], d["ebitda_ttm"]
    d["cash_to_short_term_debt"] = np.where(std == 0, np.inf, cash / std)
    d.loc[cash.isna() | std.isna(), "cash_to_short_term_debt"] = np.nan
    d["cash_to_long_term_debt"] = np.where(ltd == 0, np.inf, cash / ltd)
    d.loc[cash.isna() | ltd.isna(), "cash_to_long_term_debt"] = np.nan
    d["net_debt_to_ebitda"] = (d["net_debt_fq"] / ebitda).where(ebitda > 0)
    d["net_cash"] = d["net_debt_fq"] <= 0
    d["interest_cover"] = d["ebitda_interst_cover_ttm"]


# --- step 2: fill gaps from Yahoo ----------------------------------------------------


def _first(frame: pd.DataFrame, names: list[str]) -> float | None:
    for n in names:
        if n in frame.index:
            s = frame.loc[n].dropna()
            if not s.empty:
                return float(s.iloc[0])
    return None


def yahoo_figures(symbol: str) -> dict:
    """Latest debt, cash, EBITDA and interest from Yahoo statements (statement currency)."""
    try:
        t = yf.Ticker(symbol)
        bs = t.quarterly_balance_sheet
        inc = t.income_stmt
    except Exception:  # noqa: BLE001 - one bad symbol shouldn't stop the run
        return {}
    out = {}
    if bs is not None and not bs.empty:
        out["short_term_debt_fq"] = _first(
            bs, ["Current Debt", "Current Debt And Capital Lease Obligation"]
        )
        out["long_term_debt_fq"] = _first(
            bs, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]
        )
        out["cash_n_short_term_invest_fq"] = _first(
            bs, ["Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"]
        )
        out["total_debt_fq"] = _first(bs, ["Total Debt"])
    if inc is not None and not inc.empty:
        out["ebitda_ttm"] = _first(inc, ["EBITDA", "Normalized EBITDA"])
        out["interest_expense"] = _first(
            inc, ["Interest Expense", "Interest Expense Non Operating"]
        )
    return {k: v for k, v in out.items() if v is not None}


GAP_FIELDS = [
    "short_term_debt_fq",
    "long_term_debt_fq",
    "cash_n_short_term_invest_fq",
    "ebitda_ttm",
    "total_debt_fq",
]


def fill_gaps(d: pd.DataFrame, today: str, workers: int = 8) -> pd.DataFrame:
    """Fill debt, cash, EBITDA and interest cover from Yahoo for stocks whose screener needs
    them. Cached for the day."""
    debt_types = d["type"].isin(["general", "utilities", "reits"])
    need = d[GAP_FIELDS].isna().any(axis=1) | (
        d["interest_cover"].isna() & ~d["net_cash"].fillna(False)
    )
    todo = d[debt_types & need & d["yahoo"].notna()]
    cache = CACHE / f"yahoo_fill_{today}.pkl"
    got = pd.read_pickle(cache) if cache.exists() else {}
    missing = [s for s in todo["yahoo"] if s not in got]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for s, r in zip(missing, pool.map(yahoo_figures, missing), strict=False):
            got[s] = r
    CACHE.mkdir(parents=True, exist_ok=True)
    pd.to_pickle(got, cache)
    for idx, row in todo.iterrows():
        y = got.get(row["yahoo"], {})
        for f in GAP_FIELDS:
            if pd.isna(row[f]) and f in y:
                d.loc[idx, f] = y[f]
                d.loc[idx, "filled"] += f"{f} (Yahoo); "
        if pd.isna(row["interest_cover"]) and y.get("interest_expense"):
            ebitda = d.loc[idx, "ebitda_ttm"]
            if pd.notna(ebitda):
                d.loc[idx, "ebitda_interst_cover_ttm"] = ebitda / abs(y["interest_expense"])
                d.loc[idx, "filled"] += "interest cover (Yahoo); "
    if "net_debt_fq" in d:
        gap = d["net_debt_fq"].isna() & d["total_debt_fq"].notna()
        gap &= d["cash_n_short_term_invest_fq"].notna()
        d.loc[gap, "net_debt_fq"] = (
            d.loc[gap, "total_debt_fq"] - d.loc[gap, "cash_n_short_term_invest_fq"]
        )
    to_usd(d)
    ratios(d)
    return d


# --- step 3: screeners ---------------------------------------------------------------


NEGATIVE_EQUITY_MAX_NET_DEBT_TO_EBITDA = 2.0


def _rule(d: pd.DataFrame, name: str, value) -> pd.Series:
    """True / False per stock, NaN where the data is missing."""
    net_cash = d["net_cash"] == True  # noqa: E712 - NaN stays False

    def cmp(series: pd.Series, ok: pd.Series) -> pd.Series:
        return ok.astype(object).where(series.notna(), np.nan)

    if name == "cash_to_short_term_debt":
        s = d["cash_to_short_term_debt"]
        return cmp(s, s >= value)
    if name == "cash_to_long_term_debt":
        s = d["cash_to_long_term_debt"]
        return cmp(s, s >= value)
    if name == "max_net_debt_to_ebitda":
        s = d["net_debt_to_ebitda"]
        r = cmp(s, s <= value)
        r[net_cash] = True
        r[(d["ebitda_ttm"] <= 0) & ~net_cash] = False
        return r
    if name == "min_interest_cover":
        s = d["interest_cover"]
        r = cmp(s, s >= value)
        r[net_cash] = True
        return r
    if name == "profitable":
        cols = ["net_income_ttm", "eps"]
        if value and "ebitda" not in d.attrs.get("skip", []):
            cols.append("ebitda_ttm")
        parts = [cmp(d[c], d[c] > 0) for c in cols]
        return _all(parts)
    if name == "growth_years":
        parts = []
        for key in ("revenue", "eps"):
            avg, med = d[f"{key}_growth_avg"], d[f"{key}_growth_median"]
            parts += [cmp(avg, avg > 0), cmp(med, med > 0)]
        return _all(parts)
    if name == "min_roe":
        s = d["return_on_equity_fq"]
        return cmp(s, s >= value)
    if name == "min_piotroski":
        s = d["piotroski_f_score_ttm"]
        return cmp(s, s >= value)
    if name == "min_altman_z":
        s = d["altman_z_score_ttm"]
        return cmp(s, s > value)
    if name == "min_dividend_years":
        # Lynch's check is on the dividend record of companies that pay one; a company
        # that returns cash only through buybacks (no dividend in 10 years) passes
        s = d["dividend_years_10y"]
        return cmp(s, (s >= value) | (s == 0))
    if name == "max_payout":
        s = d["dividend_payout_ratio_ttm"]
        return cmp(s, s <= value * 100)
    if name == "max_recession_eps_drop":
        s = d["recession_eps_change"]
        return cmp(s, s >= -value)
    if name == "max_debt_to_equity":
        s = d["debt_to_equity"]
        r = cmp(s, s <= value)
        # TradingView leaves debt/equity blank when equity is negative, mostly from years
        # of buybacks (Booking, McDonald's). There the ratio means nothing: judge the debt
        # against EBITDA instead, at S&P's "modest" level (2x)
        neg = s.isna() & d["price_book_fq"].isna() & (d["total_debt_fq"] > 0)
        nd = d["net_debt_to_ebitda"]
        r[neg] = cmp(nd, nd <= NEGATIVE_EQUITY_MAX_NET_DEBT_TO_EBITDA)[neg]
        r[net_cash] = True
        return r
    if name == "min_eps_growth_3y":
        s = d["eps_growth_3y"]
        return cmp(s, s >= value)
    if name == "max_net_debt_to_avg_ebitda":
        s = d["net_debt_to_avg_ebitda"]
        r = cmp(s, s <= value)
        r[net_cash] = True
        return r
    if name == "profitable_10y_avg":
        s = d["eps_avg_10y"]
        return cmp(s, s > 0)
    if name == "min_cash_to_total_debt":
        s = d["cash_to_total_debt"]
        return cmp(s, s >= value)
    if name == "positive_ocf":
        s = d["cash_f_operating_activities_ttm"]
        return cmp(s, s > 0)
    raise KeyError(f"unknown screener rule: {name}")


def _all(parts: list[pd.Series]) -> pd.Series:
    """False if any part is False, else NaN if any is missing, else True."""
    frame = pd.concat(parts, axis=1)
    out = pd.Series(True, index=frame.index, dtype=object)
    out[frame.isna().any(axis=1)] = np.nan
    out[(frame == False).any(axis=1)] = False  # noqa: E712
    return out


RULE_LABELS = {
    "cash_to_short_term_debt": "cash covers short-term debt",
    "cash_to_long_term_debt": "cash vs long-term debt",
    "max_net_debt_to_ebitda": "net debt / EBITDA",
    "min_interest_cover": "interest cover",
    "profitable": "profitable",
    "growth_years": "revenue and EPS growth",
    "min_roe": "return on equity",
    "min_piotroski": "Piotroski score",
    "min_altman_z": "Altman Z-score",
    "min_dividend_years": "dividend paid every year (payers)",
    "max_payout": "payout ratio",
    "max_recession_eps_drop": "EPS held up in recessions",
    "max_debt_to_equity": "debt / equity",
    "min_eps_growth_3y": "EPS growth, last 3 years",
    "max_net_debt_to_avg_ebitda": "net debt / 10-year average EBITDA",
    "profitable_10y_avg": "profitable on average over 10 years",
    "min_cash_to_total_debt": "cash vs total debt",
    "positive_ocf": "positive operating cash flow",
}


def rules_for(kind: str, category: str, cfg: dict) -> dict | None:
    """Banks, insurers and REITs: rules for their kind of business. Everyone else: the
    rules of their Lynch category (utilities without the Altman score, which doesn't fit
    regulated companies). None = no category, so the stock can't be judged."""
    if kind in cfg["screener"]:
        return cfg["screener"][kind]
    if not category:
        return None
    rules = dict(cfg["category"][category])
    if kind == "utilities":
        rules.pop("min_altman_z", None)
    return rules


def apply_screeners(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Status per stock: pass, fail (with the rules failed) or incomplete (missing data)."""
    d["status"], d["failed"], d["missing"], d["flags"] = "", "", "", ""
    d["rule_set"] = ""
    for (kind, category), sub in d.groupby(["type", "category"]):
        if category == "no_profit" and kind not in cfg["screener"]:
            d.loc[sub.index, ["status", "failed"]] = ["fail", "no profit in the last 5 years; "]
            d.loc[sub.index, "rule_set"] = category
            continue
        rules = rules_for(kind, category, cfg)
        if rules is None:
            d.loc[sub.index, ["status", "missing"]] = ["incomplete", "too little EPS history; "]
            continue
        sub = sub.copy()
        if kind in ("banks", "insurers"):
            sub.attrs["skip"] = ["ebitda"]
        optional = set(rules.get("optional", []))
        results = {n: _rule(sub, n, v) for n, v in rules.items() if n != "optional"}
        failed = pd.Series("", index=sub.index)
        missing = pd.Series("", index=sub.index)
        flags = pd.Series("", index=sub.index)
        for n, r in results.items():
            failed[r == False] += RULE_LABELS[n] + "; "  # noqa: E712
            if n in optional:
                flags[r.isna()] += f"no {RULE_LABELS[n]}; "
            else:
                missing[r.isna()] += RULE_LABELS[n] + "; "
        status = np.where(failed != "", "fail", np.where(missing != "", "incomplete", "pass"))
        d.loc[sub.index, "status"] = status
        d.loc[sub.index, "failed"] = failed
        d.loc[sub.index, "missing"] = missing
        d.loc[sub.index, "flags"] = flags
        d.loc[sub.index, "rule_set"] = kind if kind in cfg["screener"] else category
    return d


# --- outputs -------------------------------------------------------------------------

STAGE1_COLUMNS = [
    "description",
    "region",
    "sector",
    "industry",
    "type",
    "category",
    "rule_set",
    "status",
    "failed",
    "missing",
    "flags",
    "filled",
    *ABSOLUTE,
    "cash_to_short_term_debt",
    "cash_to_long_term_debt",
    "net_debt_to_ebitda",
    "net_debt_to_avg_ebitda",
    "interest_cover",
    "debt_to_equity",
    "return_on_equity_fq",
    "revenue_growth_median",
    "eps_growth_median",
    "eps_growth_3y",
    "eps_vs_5y_peak",
    "eps_big_drops_10y",
    "recession_eps_change",
    "dividend_years_10y",
    "dividend_payout_ratio_ttm",
    "piotroski_f_score_ttm",
    "altman_z_score_ttm",
]


def run(cfg: dict, refresh: bool = False) -> pd.DataFrame:
    today = date.today().isoformat()
    d = prepare(fetch_universe(cfg, today, refresh), cfg, ecb.usd_per_unit())
    d = fill_gaps(d, today)
    return apply_screeners(d, cfg)


def save(d: pd.DataFrame) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    d.attrs["date"] = date.today().isoformat()
    d.to_pickle(STAGE1_FULL)
    order = d.sort_values(["region", "sector", "cap_usd_bn"], ascending=[True, True, False])
    order[STAGE1_COLUMNS].round(4).to_csv(OUT / "stage1.csv")


def counts(d: pd.DataFrame, by: str) -> pd.DataFrame:
    """Companies screened and passed, per `by` (sector or category) and region."""
    g = d.groupby([by, "region"])["status"]
    out = pd.DataFrame({"screened": g.size(), "passed": g.apply(lambda s: (s == "pass").sum())})
    return out.unstack("region", fill_value=0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="download again, ignore today's cache")
    args = ap.parse_args()
    d = run(load_config(), refresh=args.refresh)
    save(d)
    pd.set_option("display.width", 250)
    print("Stage 1: good financial statements")
    print(counts(d, "category").to_string())
    print()
    print(counts(d, "sector").to_string())
    print(f"\n{(d['status'] == 'pass').sum()} of {len(d)} pass. Saved data/screener/stage1.csv")


if __name__ == "__main__":
    main()
