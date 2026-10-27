"""Market screener: cheap or close-to-cheap stocks in the US and Europe, top 3 per sector.

Steps (settings in config/screeners.toml):
  1. Universe: every primary-listed stock above the minimum market value in the US and
     European markets, from TradingView's screener (current figures, 20 years of yearly
     EPS and revenue, technicals). Market values converted to US dollars at ECB rates.
  2. Gap filling: debt, cash and interest figures TradingView leaves blank are filled from
     Yahoo where it has them. Each filled value is listed in the `filled` column.
  3. Screener by kind of business (general, utilities, banks, insurers, REITs): a stock
     must pass every rule of its screener to be ranked. Missing data = "incomplete".
  4. Cheap price: the stock's own cheap multiple (bottom quarter of its yearly P/E over
     10 fiscal years, on Yahoo average prices and TradingView diluted EPS) times today's
     EPS. For the stocks near the top, Yahoo's adjusted EPS replaces diluted EPS where it
     has at least 6 years (the watch list's method).
  5. Rank inside each region and sector by price against the cheap price, lowest first.
     Below it = "cheap"; within 15% above = "close". Technicals (trend, RSI, 52-week
     range, TradingView rating) are shown for timing, not used in the ranking.
  6. US stocks' latest-year EPS is checked against SEC EDGAR; a mismatch is flagged.

Writes data/screener/YYYY-MM-DD.csv (every stock with its status) and
data/screener/top.csv (the top per region and sector). Raw downloads are cached for the
day in .cache/screener/.

Usage:
    uv run python analysis/screener.py               # full run, prints the top list
    uv run python analysis/screener.py --no-adjusted # skip the adjusted-EPS refinement
"""

from __future__ import annotations

import argparse
import os
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import yfinance as yf

from stock_analysis import ecb, tradingview

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watchlist as w  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/screeners.toml"
OUT = ROOT / "data/screener"
CACHE = ROOT / ".cache/screener"
SEC_UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "stock-analysis research project")}

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

# Absolute values shown first, in US dollars (billions) or per share in the trading currency
ABSOLUTE = {
    "close": "Price",
    "cap_usd_bn": "Market value ($bn)",
    "total_debt_usd_bn": "Total debt ($bn)",
    "net_debt_usd_bn": "Net debt ($bn)",
    "short_term_debt_usd_bn": "Short-term debt ($bn)",
    "long_term_debt_usd_bn": "Long-term debt ($bn)",
    "cash_usd_bn": "Cash ($bn)",
    "revenue_usd_bn": "Revenue 12m ($bn)",
    "ebitda_usd_bn": "EBITDA 12m ($bn)",
    "net_income_usd_bn": "Net income 12m ($bn)",
    "eps": "EPS 12m",
    "ocf_usd_bn": "Operating cash flow ($bn)",
    "capex_usd_bn": "Capex ($bn)",
    "fcf_usd_bn": "Free cash flow ($bn)",
}
USD_FIELDS = {
    "market_cap_basic": "cap_usd_bn",
    "total_debt_fq": "total_debt_usd_bn",
    "net_debt_fq": "net_debt_usd_bn",
    "short_term_debt_fq": "short_term_debt_usd_bn",
    "long_term_debt_fq": "long_term_debt_usd_bn",
    "cash_n_short_term_invest_fq": "cash_usd_bn",
    "total_revenue_ttm": "revenue_usd_bn",
    "ebitda_ttm": "ebitda_usd_bn",
    "net_income_ttm": "net_income_usd_bn",
    "cash_f_operating_activities_ttm": "ocf_usd_bn",
    "capital_expenditures_ttm": "capex_usd_bn",
    "free_cash_flow_ttm": "fcf_usd_bn",
}

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


def load_config(path: Path = CONFIG) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


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
    for src, dst in USD_FIELDS.items():
        d[dst] = d[src] * d["fx_fund"] / 1e9
    d = d[d["cap_usd_bn"] * 1e9 >= cfg["min_market_cap_usd"]].copy()
    d["type"] = [
        screener_type(s, i, cfg["types"]) for s, i in zip(d["sector"], d["industry"], strict=False)
    ]
    d = d[d["type"].notna()].copy()
    d["filled"] = ""
    derive_short_term_debt(d)
    ratios(d)
    years = max(c.get("growth_years", 0) for c in cfg["screener"].values())
    for col, key in (("total_revenue_fy_h", "revenue"), ("earnings_per_share_diluted_fy_h", "eps")):
        g = d[col].map(lambda v: yearly_growth(v, years))
        d[f"{key}_growth_avg"] = g.map(lambda x: float(np.mean(x)) if len(x) >= 3 else np.nan)
        d[f"{key}_growth_median"] = g.map(lambda x: float(np.median(x)) if len(x) >= 3 else np.nan)
        d[f"{key}_growth_years"] = g.map(len)
    d["eps"] = d["earnings_per_share_diluted_ttm"]
    # price in the statements' currency, so P/E works for London pence and foreign reporters
    d["price_fund"] = d["close"] * d["fx_price"] / d["fx_fund"]
    return d


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
    for src, dst in USD_FIELDS.items():
        d[dst] = d[src] * d["fx_fund"] / 1e9
    ratios(d)
    return d


CASH_FLOW_ROWS = {
    "cash_f_operating_activities_ttm": ["Operating Cash Flow"],
    "capital_expenditures_ttm": ["Capital Expenditure"],
    "free_cash_flow_ttm": ["Free Cash Flow"],
}


def fill_cash_flows(d: pd.DataFrame, rows: pd.Index) -> None:
    """Fill blank cash flows of the listed stocks from Yahoo (last four quarters)."""
    gaps = d.loc[rows, list(CASH_FLOW_ROWS)].isna().any(axis=1)
    for idx in gaps[gaps].index:
        sym = d.loc[idx, "yahoo"]
        try:
            cf = yf.Ticker(sym).quarterly_cashflow if sym else None
        except Exception:  # noqa: BLE001
            cf = None
        if cf is None or cf.empty or cf.shape[1] < 4:
            continue
        for col, names in CASH_FLOW_ROWS.items():
            if pd.notna(d.loc[idx, col]):
                continue
            for n in names:
                if n in cf.index and cf.loc[n].iloc[:4].notna().all():
                    d.loc[idx, col] = float(cf.loc[n].iloc[:4].sum())
                    d.loc[idx, "filled"] += f"{col} (Yahoo); "
                    break
    for src, dst in USD_FIELDS.items():
        d[dst] = d[src] * d["fx_fund"] / 1e9


# --- step 3: screeners ---------------------------------------------------------------


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
}


def apply_screeners(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Status per stock: pass, fail (with the rules failed) or incomplete (missing data)."""
    d["status"], d["failed"], d["missing"], d["flags"] = "", "", "", ""
    for kind, rules in cfg["screener"].items():
        rows = d["type"] == kind
        if not rows.any():
            continue
        sub = d[rows].copy()
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
        d.loc[rows, "status"] = status
        d.loc[rows, "failed"] = failed
        d.loc[rows, "missing"] = missing
        d.loc[rows, "flags"] = flags
    return d


# --- step 4: cheap price -------------------------------------------------------------


def monthly_prices(symbols: list[str], today: str, years: int) -> pd.DataFrame:
    """Monthly closes (split-adjusted) for many symbols, cached for the day."""
    cache = CACHE / f"prices_{today}.pkl"
    have = pd.read_pickle(cache) if cache.exists() else pd.DataFrame()
    todo = [s for s in symbols if s not in have.columns]
    frames = [have]
    for i in range(0, len(todo), 200):
        chunk = todo[i : i + 200]
        px = yf.download(
            chunk,
            period=f"{years + 2}y",
            interval="1mo",
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="column",
        )
        if px is None or px.empty:
            continue
        close = px["Close"] if isinstance(px.columns, pd.MultiIndex) else px[["Close"]]
        if not isinstance(px.columns, pd.MultiIndex):
            close.columns = chunk[:1]
        frames.append(close)
    out = pd.concat(frames, axis=1)
    out = out.loc[:, ~out.columns.duplicated()]
    CACHE.mkdir(parents=True, exist_ok=True)
    out.to_pickle(cache)
    return out


def fiscal_pe(
    prices: pd.Series, eps_h: list, years_h: list, fy_end: pd.Timestamp, n: int
) -> pd.DataFrame:
    """Yearly P/E: average monthly close over each fiscal year / that year's EPS.

    `eps_h` and `years_h` are newest first (TradingView's yearly history); `fy_end` is the
    end date of the latest fiscal year. Prices must be in the EPS currency.
    """
    rows = []
    prices = prices.dropna()
    for k, (year, eps) in enumerate(zip(years_h[:n], eps_h[:n], strict=False)):
        if eps is None or year is None:
            continue
        end = fy_end - pd.DateOffset(years=k)
        window = prices[(prices.index > end - pd.DateOffset(years=1)) & (prices.index <= end)]
        if len(window) < 9:
            continue
        avg = float(window.mean())
        rows.append({"year": int(year), "avg_price": avg, "eps": eps})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["year", "avg_price", "eps", "pe"])
    out["pe"] = (out["avg_price"] / out["eps"]).where(out["eps"] > 0)
    return out


def cheap_multiple(pe: pd.Series, percentile: float, min_years: int) -> float:
    """The stock's own cheap P/E: a low percentile of its positive yearly P/Es."""
    pe = pe.dropna()
    pe = pe[pe > 0]
    if len(pe) < min_years:
        return np.nan
    return float(pe.quantile(percentile))


def add_cheap_price(d: pd.DataFrame, prices: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    n, pct, need = cfg["history_years"], cfg["cheap_percentile"], cfg["min_history_years"]
    out = {}
    for idx, r in d.iterrows():
        sym = r["yahoo"]
        if sym not in prices.columns or not isinstance(r["earnings_per_share_diluted_fy_h"], list):
            continue
        fy_end = pd.to_datetime(r["fiscal_period_end_fy"], unit="s", errors="coerce")
        if pd.isna(fy_end):
            continue
        px = prices[sym] * r["fx_price"] / r["fx_fund"]
        h = fiscal_pe(px, r["earnings_per_share_diluted_fy_h"], r["fiscal_period_fy_h"], fy_end, n)
        out[idx] = {
            "pe_years": int(h["pe"].notna().sum()),
            "pe_median_10y": float(h["pe"].median()) if h["pe"].notna().any() else np.nan,
            "pe_low_10y": float(h["pe"].min()) if h["pe"].notna().any() else np.nan,
            "cheap_pe": cheap_multiple(h["pe"], pct, need),
        }
    h = pd.DataFrame.from_dict(out, orient="index")
    for c in ("pe_years", "pe_median_10y", "pe_low_10y", "cheap_pe"):
        d[c] = h[c] if c in h else np.nan
    d["eps_basis"] = "diluted"
    set_cheap_price(d)
    return d


def set_cheap_price(d: pd.DataFrame) -> None:
    """Cheap multiple = the lower of the stock's own cheap P/E and its sector's median P/E.

    The sector cap keeps a stock whose whole history was priced for hyper-growth (Amazon,
    Netflix) from looking cheap at a multiple its peers never get.
    """
    d["pe_now"] = (d["price_fund"] / d["eps"]).where(d["eps"] > 0)
    d["sector_pe"] = d.groupby(["region", "sector"])["pe_now"].transform("median")
    d["cheap_basis"] = np.where(d["cheap_pe"] > d["sector_pe"], "sector median", "own history")
    d["cheap_multiple"] = d[["cheap_pe", "sector_pe"]].min(axis=1).where(d["cheap_pe"].notna())
    d.loc[d["cheap_multiple"].isna(), "cheap_basis"] = ""
    # cheap price in the trading currency
    d["cheap_price"] = d["cheap_multiple"] * d["eps"] * d["fx_fund"] / d["fx_price"]
    d.loc[d["eps"] <= 0, "cheap_price"] = np.nan
    d["vs_cheap"] = d["close"] / d["cheap_price"] - 1


def adjusted_eps_plausible(adjusted: float, diluted: float) -> bool:
    """Adjusted EPS within a factor of 2 of diluted EPS.

    Further apart is almost always a data problem (a split Yahoo hasn't applied to its
    earnings history, or EPS in a different currency), not one-off items.
    """
    if not (diluted > 0 and adjusted > 0):
        return False
    return 0.5 <= adjusted / diluted <= 2.0


def adjusted_refine(d: pd.DataFrame, rows: pd.Index, cfg: dict) -> None:
    """Swap in Yahoo's adjusted EPS (and its own adjusted P/E history) where it has 6+ years.

    Same method as the watch list: quarterly reported EPS, trailing four quarters, yearly
    P/E on the calendar-year average price.
    """
    pct, need = cfg["cheap_percentile"], cfg["min_history_years"]

    def one(sym: str) -> dict | None:
        try:
            t = yf.Ticker(sym)
            q = w.quarterly_eps(t.get_earnings_dates(limit=60))
            px = t.history(period=f"{cfg['history_years'] + 2}y", auto_adjust=False)["Close"]
        except Exception:  # noqa: BLE001
            return None
        if px.empty or len(q) < 8:
            return None
        px.index = px.index.tz_localize(None).normalize()
        ttm = w.trailing_eps(q)
        if len(ttm) < 5 or ttm.iloc[-1] <= 0:
            return None
        yearly = w.yearly_pe(px, ttm, years=cfg["history_years"])
        if yearly.empty:
            return None
        return {"eps": float(ttm.iloc[-1]), "pe": yearly["pe"]}

    syms = d.loc[rows, "yahoo"].dropna()
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(zip(syms.index, pool.map(one, syms.values), strict=False))
    for idx, res in results.items():
        if not res:
            continue
        cheap = cheap_multiple(res["pe"], pct, need)
        if np.isnan(cheap):
            continue
        # Yahoo's EPS is per share in the trading currency (pence for London)
        r = d.loc[idx]
        eps = res["eps"] * r["fx_price"] / r["fx_fund"]
        if not adjusted_eps_plausible(eps, r["eps"]):
            d.loc[idx, "flags"] += f"Yahoo adjusted EPS {res['eps']:.2f} ignored (vs diluted); "
            continue
        d.loc[idx, ["eps", "cheap_pe", "eps_basis"]] = [eps, cheap, "adjusted"]
        d.loc[idx, "pe_median_10y"] = float(res["pe"].median())
        d.loc[idx, "pe_low_10y"] = float(res["pe"].min())
        d.loc[idx, "pe_years"] = int(res["pe"].notna().sum())
    set_cheap_price(d)


# --- step 5: ranking and technicals --------------------------------------------------


def technicals(d: pd.DataFrame) -> None:
    c, s50, s200 = d["close"], d["SMA50"], d["SMA200"]
    trend = np.where(
        (c > s200) & (s50 > s200),
        "uptrend",
        np.where((c < s200) & (s50 < s200), "downtrend", "mixed"),
    )
    d["trend"] = np.where(s200.isna(), "", trend)
    d["rsi_read"] = np.select(
        [d["RSI"] < 30, d["RSI"] > 70], ["oversold", "overbought"], default=""
    )
    rng = d["price_52_week_high"] - d["price_52_week_low"]
    d["in_52w_range"] = ((c - d["price_52_week_low"]) / rng).where(rng > 0)
    rec = d["Recommend.All"]
    d["tv_rating"] = np.select(
        [rec >= 0.5, rec >= 0.1, rec <= -0.5, rec <= -0.1],
        ["strong buy", "buy", "strong sell", "sell"],
        default="neutral",
    )
    d.loc[rec.isna(), "tv_rating"] = ""


def label(vs_cheap: float, close: float) -> str:
    if pd.isna(vs_cheap):
        return ""
    if vs_cheap <= 0:
        return "cheap"
    return "close" if vs_cheap <= close else ""


def peer_measures(d: pd.DataFrame) -> None:
    """P/E and EV/EBITDA against the median of the same region and sector."""
    g = d.groupby(["region", "sector"])
    d["pe_vs_sector"] = d["pe_now"] / g["pe_now"].transform("median") - 1
    ev = d["enterprise_value_ebitda_ttm"].where(d["enterprise_value_ebitda_ttm"] > 0)
    d["ev_ebitda_vs_sector"] = ev / ev.groupby([d["region"], d["sector"]]).transform("median") - 1
    d["fcf_yield"] = d["free_cash_flow_ttm"] / d["market_cap_basic"]


def reason(r: pd.Series) -> str:
    bits = [f"{r['pe_now']:.1f}x P/E vs cheap {r['cheap_multiple']:.1f}x ({r['cheap_basis']})"]
    if pd.notna(r.get("pe_median_10y")):
        bits.append(f"10-yr median {r['pe_median_10y']:.1f}x")
    if r.get("net_cash"):
        bits.append("net cash")
    elif pd.notna(r.get("net_debt_to_ebitda")):
        bits.append(f"net debt {r['net_debt_to_ebitda']:.1f}x EBITDA")
    if pd.notna(r.get("eps_growth_median")):
        bits.append(f"EPS growth median {r['eps_growth_median']:.0%}/yr")
    if r.get("trend"):
        bits.append(r["trend"])
    return ", ".join(bits)


def rank(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Top N per region and sector among passing stocks that are cheap or close to it."""
    ok = d[(d["status"] == "pass") & (d["vs_cheap"] <= cfg["close_to_cheap"])].copy()
    ok = ok.sort_values("vs_cheap")
    ok["rank_in_sector"] = ok.groupby(["region", "sector"]).cumcount() + 1
    top = ok[ok["rank_in_sector"] <= cfg["top_per_sector"]].copy()
    top["cheapness"] = [label(v, cfg["close_to_cheap"]) for v in top["vs_cheap"]]
    top["why"] = top.apply(reason, axis=1)
    return top.sort_values(["region", "sector", "rank_in_sector"])


# --- step 6: SEC cross-check ---------------------------------------------------------


def sec_check(d: pd.DataFrame, rows: pd.Index) -> None:
    """Flag US stocks whose latest-year diluted EPS differs from SEC EDGAR by over 10%."""
    try:
        with httpx.Client(timeout=60, headers=SEC_UA) as c:
            tickers = c.get("https://www.sec.gov/files/company_tickers.json").json()
            cik = {v["ticker"].upper(): int(v["cik_str"]) for v in tickers.values()}
            frames = {}
            for y in sorted({int(v[0]) for v in d.loc[rows, "fiscal_period_fy_h"] if v}):
                url = (
                    "https://data.sec.gov/api/xbrl/frames/us-gaap/"
                    f"EarningsPerShareDiluted/USD-per-shares/CY{y}.json"
                )
                r = c.get(url)
                if r.status_code == 200:
                    frames[y] = {x["cik"]: x["val"] for x in r.json()["data"]}
    except Exception:  # noqa: BLE001 - the check is a bonus, not a requirement
        return
    d["sec_eps"] = d.get("sec_eps", np.nan)
    for idx in rows:
        r = d.loc[idx]
        if r["region"] != "US" or not r["fiscal_period_fy_h"]:
            continue
        k = cik.get(idx.split(":", 1)[1].replace(".", "-"))
        year = int(r["fiscal_period_fy_h"][0])
        sec = frames.get(year, {}).get(k)
        tv = r["earnings_per_share_diluted_fy_h"][0]
        if sec is None or tv is None:
            continue
        d.loc[idx, "sec_eps"] = sec
        if abs(sec - tv) > 0.1 * max(abs(sec), 0.01):
            d.loc[idx, "flags"] += f"EPS {year}: TradingView {tv:.2f} vs SEC {sec:.2f}; "


# --- run -----------------------------------------------------------------------------


def run(cfg: dict, adjusted: bool = True, refresh: bool = False) -> tuple[pd.DataFrame, ...]:
    today = date.today().isoformat()
    fx = ecb.usd_per_unit()
    d = prepare(fetch_universe(cfg, today, refresh), cfg, fx)
    d = fill_gaps(d, today)
    d = apply_screeners(d, cfg)
    passed = d[d["status"] == "pass"]
    prices = monthly_prices(passed["yahoo"].dropna().tolist(), today, cfg["history_years"])
    d = add_cheap_price(d, prices, cfg)
    technicals(d)
    peer_measures(d)
    if adjusted:
        # refine the closest names: enough per sector that a swap in order is caught
        near = d[(d["status"] == "pass") & d["vs_cheap"].notna()].sort_values("vs_cheap")
        near = near.groupby(["region", "sector"]).head(cfg["top_per_sector"] * 3).index
        adjusted_refine(d, near, cfg)
        peer_measures(d)
    top = rank(d, cfg)
    sec_check(d, top.index)
    fill_cash_flows(d, top.index)
    top = rank(d, cfg)
    return d, top


SHOW = [
    "description",
    "close",
    "currency",
    "cap_usd_bn",
    "net_debt_usd_bn",
    "fcf_usd_bn",
    "pe_now",
    "cheap_multiple",
    "cheap_basis",
    "cheap_price",
    "vs_cheap",
    "cheapness",
    "eps_basis",
    "trend",
    "tv_rating",
]


def save(d: pd.DataFrame, top: pd.DataFrame) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    keep = [c for c in d.columns if not c.endswith("_fy_h")]
    path = OUT / f"{date.today().isoformat()}.csv"
    d[keep].round(4).to_csv(path)
    top[[c for c in top.columns if not c.endswith("_fy_h")]].round(4).to_csv(OUT / "top.csv")
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-adjusted", action="store_true", help="skip Yahoo adjusted EPS")
    ap.add_argument("--refresh", action="store_true", help="download again, ignore today's cache")
    args = ap.parse_args()
    cfg = load_config()
    d, top = run(cfg, adjusted=not args.no_adjusted, refresh=args.refresh)
    path = save(d, top)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(d.groupby(["region", "type", "status"]).size().unstack(fill_value=0).to_string())
    print()
    for (region, sector), g in top.groupby(["region", "sector"]):
        print(f"{region} / {sector}")
        print(g[SHOW].round(2).to_string(header=False))
    print(f"\nSaved {path.relative_to(ROOT)} and data/screener/top.csv")


if __name__ == "__main__":
    main()
