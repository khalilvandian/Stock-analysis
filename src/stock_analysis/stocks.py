"""The analyses' view of a stock, read from the database (issue #33): every analysis script
gets its numbers here instead of asking Yahoo, TradingView or SEC itself.

    from stock_analysis.data import Data
    from stock_analysis import stocks

    data = Data.open()
    rows = stocks.rows(data, ["NEE", "DUK"])     # one row per stock: absolute values,
                                                 # ratios, growth, standard DCF ($bn)
    years = stocks.history(data, ["NEE"])        # fiscal-year absolute values, long format
    px = stocks.closes(data, ["NEE"], "2016-01-01")
    eps = stocks.earnings(data, ["NEE"])         # report dates, estimated and reported EPS

Sources: the core layer (SEC first, Yahoo for gaps: config/db_items.toml), the daily prices,
Yahoo's earnings dates, the newest TradingView snapshot (forward EPS, beta, analysts' target
and rating, the company's reporting currency) and the ECB's rates. Money is in US dollars:
SEC values are, the others are converted from the company's reporting currency at the
newest ECB rate. Amounts are in billions, per-share values in dollars.

Every query takes the stocks in blocks, so no answer passes the web API's row limit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

import numpy as np
import pandas as pd

SYMBOL = re.compile(r"^[A-Z0-9.\-^=]{1,15}$")
RISK_FREE = 0.0518
EQUITY_PREMIUM = 0.05
TAX = 0.21
TERMINAL_GROWTH = 0.025
GROWTH_YEARS = 4  # fiscal years behind the growth measures (as Yahoo's four statements were)
BLOCK = 40

FLOWS = ["revenue", "operating_income", "ebitda", "d_and_a", "net_income", "eps_diluted",
         "interest_expense", "operating_cf", "capex"]  # fmt: skip
INSTANTS = ["cash", "short_term_debt", "long_term_debt", "total_debt", "total_assets",
            "total_liabilities", "equity", "shares_outstanding"]  # fmt: skip
PER_SHARE = {"eps_diluted"}
NOT_MONEY = {"shares_outstanding"}

# --- queries ------------------------------------------------------------------------------

Q_COMPANIES = """
SELECT c.symbol, c.name, c.exchange, c.sector, c.industry, c.currency, c.cik,
       t.country, t.extra_json,
       m.start_date AS in_index_since
FROM core_company c
LEFT JOIN (SELECT DISTINCT ON (symbol) symbol, country, extra_json FROM v_tv_latest
           ORDER BY symbol, CASE WHEN request_key = 'watchlist' THEN 1 ELSE 0 END) t
       ON t.symbol = c.symbol
LEFT JOIN core_index_member m ON m.company_id = c.company_id AND m.end_date IS NULL
WHERE c.symbol IN ({symbols})"""

Q_TTM = """
SELECT DISTINCT ON (t.company_id, t.item) c.symbol, t.item, t.period_end, t.basis, t.source,
       t.value_adj AS value
FROM core_fundamental_ttm t
JOIN core_company c ON c.company_id = t.company_id
WHERE c.symbol IN ({symbols})
ORDER BY t.company_id, t.item, t.period_end DESC, t.filed DESC"""

# Per-share values on today's share basis.
Q_FUNDAMENTALS = """
SELECT c.symbol, f.item, f.period_type, f.fiscal_year, f.fiscal_period, f.period_end,
       f.source,
       CASE WHEN f.item = 'eps_diluted' THEN f.value / f.split_factor
            WHEN f.item = 'shares_outstanding' THEN f.value * f.split_factor
            ELSE f.value END AS value
FROM v_fundamental_latest f
JOIN core_company c ON c.company_id = f.company_id
WHERE c.symbol IN ({symbols}) AND f.fiscal_year >= {first_year}"""

Q_PRICES = """
SELECT c.symbol, p.date, p.close, p.adj_close, p.dividend, p.split_ratio
FROM core_price_daily p
JOIN core_company c ON c.company_id = p.company_id
WHERE c.symbol IN ({symbols}) AND p.date >= '{start}'
ORDER BY c.symbol, p.date"""

Q_MONTHLY = """
SELECT symbol, month, close FROM (
    SELECT c.symbol, date_trunc('month', p.date)::date AS month, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.company_id, date_trunc('month', p.date)
                              ORDER BY p.date DESC) AS rn
    FROM core_price_daily p
    JOIN core_company c ON c.company_id = p.company_id
    WHERE c.symbol IN ({symbols}) AND p.date >= '{start}'
) m WHERE rn = 1"""

Q_EARNINGS = """
SELECT symbol, report_date, eps_estimate, eps_reported, surprise_pct, fetch_id
FROM v_earnings WHERE symbol IN ({symbols}) ORDER BY symbol, report_date"""

Q_MARKET = """
SELECT symbol, date, close FROM core_market_daily
WHERE symbol IN ({symbols}) AND date >= '{start}' ORDER BY symbol, date"""

Q_FX = """
SELECT DISTINCT ON (currency) currency, date, usd_per_unit FROM raw_ecb_rate
ORDER BY currency, date DESC, fetch_id DESC"""

Q_SPLITS = """
SELECT c.symbol, p.date, p.split_ratio FROM core_price_daily p
JOIN core_company c ON c.company_id = p.company_id
WHERE c.symbol IN ({symbols}) AND p.split_ratio IS NOT NULL ORDER BY c.symbol, p.date"""


_DATA = None


def default_data():
    """One Data.open() per process, for scripts that don't pass their own."""
    global _DATA
    if _DATA is None:
        from .data import Data

        _DATA = Data.open()
    return _DATA


def in_list(symbols: Iterable[str]) -> str:
    symbols = list(symbols)
    bad = [s for s in symbols if not SYMBOL.match(s or "")]
    if bad:
        raise ValueError(f"not a ticker: {bad[:3]}")
    return ", ".join("'" + s.replace("'", "") + "'" for s in symbols)


def blocks(symbols: list[str], size: int):
    for i in range(0, len(symbols), size):
        yield symbols[i : i + size]


def query(data, sql: str, symbols: Iterable[str], size: int = BLOCK, **fmt) -> pd.DataFrame:
    """One query per block of symbols, the answers concatenated."""
    symbols = sorted(set(symbols))
    frames = [data.sql(sql.format(symbols=in_list(b), **fmt)) for b in blocks(symbols, size)]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return np.nan
    return x if np.isfinite(x) else np.nan


def _div(a: float, b: float) -> float:
    a, b = num(a), num(b)
    return a / b if np.isfinite(a) and np.isfinite(b) and b != 0 else np.nan


# --- reads --------------------------------------------------------------------------------


def companies(data, symbols: Iterable[str]) -> pd.DataFrame:
    """Name, sector, industry, country and the TradingView fields (parsed extra_json)."""
    c = query(data, Q_COMPANIES, symbols)
    if c.empty:
        return pd.DataFrame(columns=["name", "tv"]).rename_axis("symbol")
    c["tv"] = [json.loads(x) if isinstance(x, str) and x else {} for x in c["extra_json"]]
    return c.drop(columns="extra_json").drop_duplicates("symbol").set_index("symbol")


def fx_rates(data) -> dict[str, float]:
    """US dollars per unit of each currency, at the ECB's newest rate."""
    fx = data.sql(Q_FX)
    out = {"USD": 1.0}
    if not fx.empty:
        out |= dict(zip(fx["currency"], fx["usd_per_unit"].astype(float), strict=True))
    if "GBP" in out:
        out["GBX"] = out["GBP"] / 100  # London prices are in pence
    return out


def reporting_currency(company: pd.Series) -> str:
    tv = company.get("tv") if isinstance(company.get("tv"), dict) else {}
    return (tv.get("fundamental_currency_code") or company.get("currency") or "USD").upper()


def to_usd(values: pd.DataFrame, fx_by_symbol: dict[str, float]) -> pd.DataFrame:
    """Values from a source other than SEC (Yahoo, derived) are in the reporting currency."""
    v = values.copy()
    if v.empty:
        return v
    rate = v["symbol"].map(fx_by_symbol).fillna(1.0)
    convert = ~v["source"].fillna("").str.startswith(("sec", "history")) & ~v["item"].isin(
        NOT_MONEY
    )
    v.loc[convert, "value"] = v.loc[convert, "value"].astype(float) * rate[convert]
    return v


def ttm(data, symbols: Iterable[str], fx_by_symbol: dict[str, float] | None = None):
    """The latest twelve months: flows over the last four quarters (or the fiscal year),
    the balance sheet at the latest date. One row per symbol, US dollars."""
    t = query(data, Q_TTM, symbols, size=60)
    if t.empty:
        return pd.DataFrame()
    t["value"] = t["value"].astype(float)
    t = to_usd(t, fx_by_symbol or {})
    wide = t.pivot_table(index="symbol", columns="item", values="value", aggfunc="last")
    wide["period_end"] = t.groupby("symbol")["period_end"].max()
    return wide


def fundamentals(data, symbols: Iterable[str], fx_by_symbol=None, first_year: int = 2014):
    """Every period of every item (latest filed version), long format, US dollars."""
    f = query(data, Q_FUNDAMENTALS, symbols, size=25, first_year=int(first_year))
    if f.empty:
        return f
    f["value"] = f["value"].astype(float)
    return to_usd(f, fx_by_symbol or {})


def prices(data, symbols: Iterable[str], start: str) -> pd.DataFrame:
    """Daily close (split-adjusted, as traded otherwise), adjusted close, dividend, split."""
    p = query(data, Q_PRICES, symbols, size=8, start=pd.Timestamp(start).strftime("%Y-%m-%d"))
    if p.empty:
        return pd.DataFrame(columns=["symbol", "date", "close", "adj_close", "dividend"])
    p["date"] = pd.to_datetime(p["date"])
    for col in ("close", "adj_close", "dividend", "split_ratio"):
        p[col] = pd.to_numeric(p[col], errors="coerce")
    return p


def closes(data, symbols: Iterable[str], start: str) -> pd.DataFrame:
    """Daily closes, one column per symbol."""
    p = prices(data, symbols, start)
    if p.empty:
        return pd.DataFrame()
    return p.pivot_table(index="date", columns="symbol", values="close").sort_index()


def monthly_closes(data, symbols: Iterable[str], start: str) -> pd.DataFrame:
    """The last close of each month, one column per symbol (indexed by the month's start)."""
    m = query(data, Q_MONTHLY, symbols, size=150, start=pd.Timestamp(start).strftime("%F"))
    if m.empty:
        return pd.DataFrame()
    m["month"] = pd.to_datetime(m["month"])
    m["close"] = m["close"].astype(float)
    return m.pivot_table(index="month", columns="symbol", values="close").sort_index()


def splits(data, symbols: Iterable[str]) -> pd.DataFrame:
    s = query(data, Q_SPLITS, symbols, size=200)
    if not s.empty:
        s["date"] = pd.to_datetime(s["date"])
        s["split_ratio"] = s["split_ratio"].astype(float)
    return s


def market_closes(data, symbols: Iterable[str], start: str) -> pd.DataFrame:
    """The market instruments' daily closes (config/market.toml), one column per symbol."""
    m = query(data, Q_MARKET, symbols, size=6, start=pd.Timestamp(start).strftime("%F"))
    if m.empty:
        return pd.DataFrame()
    m["date"] = pd.to_datetime(m["date"])
    m["close"] = m["close"].astype(float)
    return m.pivot_table(index="date", columns="symbol", values="close").sort_index()


def earnings(data, symbols: Iterable[str]) -> pd.DataFrame:
    """Yahoo's earnings dates as last fetched: report_date, eps_estimate, eps_reported."""
    e = query(data, Q_EARNINGS, symbols, size=100)
    if e.empty:
        return pd.DataFrame(columns=["symbol", "report_date", "eps_estimate", "eps_reported"])
    e["report_date"] = pd.to_datetime(e["report_date"])
    for col in ("eps_estimate", "eps_reported", "surprise_pct"):
        e[col] = pd.to_numeric(e[col], errors="coerce")
    return e


def earnings_dates(e: pd.DataFrame) -> pd.DataFrame:
    """One stock's earnings dates in yfinance's get_earnings_dates() shape (index: report
    date; columns "EPS Estimate" and "Reported EPS"), newest first. A future date that an
    older fetch left behind (the report moved) is dropped: of two unreported dates within 45
    days, the one from the newer fetch stays."""
    e = e.sort_values("report_date")
    future = e[e["eps_reported"].isna()]
    drop = set()
    for i, r in future.iterrows():
        near = future[(future["report_date"] - r["report_date"]).abs() < pd.Timedelta(days=45)]
        if (near["fetch_id"] > r["fetch_id"]).any():
            drop.add(i)
        reported = e[e["eps_reported"].notna()]
        if ((reported["report_date"] - r["report_date"]).abs() < pd.Timedelta(days=20)).any():
            drop.add(i)
    e = e.drop(index=list(drop))
    out = pd.DataFrame(
        {
            "EPS Estimate": e["eps_estimate"].to_numpy(),
            "Reported EPS": e["eps_reported"].to_numpy(),
        },
        index=pd.DatetimeIndex(e["report_date"], name="Earnings Date"),
    )
    return out.sort_index(ascending=False)


# --- the analyses' row per stock ------------------------------------------------------------


def _growth_stats(s: pd.Series, prefix: str) -> dict:
    s = s.dropna()
    prev = s.shift(1)
    g = ((s - prev) / prev)[prev > 0].dropna()
    return {
        f"{prefix}_growth_avg": g.mean() if len(g) else np.nan,
        f"{prefix}_growth_median": g.median() if len(g) else np.nan,
        f"{prefix}_growth_years": len(g),
        f"{prefix}_growth_years_positive": int((g > 0).sum()),
        f"{prefix}_growth_by_year": "; ".join(f"{d.year}: {v:+.1%}" for d, v in g.items()),
    }


def _margin_stats(m: pd.Series) -> dict:
    m = m.dropna()
    chg = m.diff().dropna()
    return {
        "net_margin_latest_fy": m.iloc[-1] if len(m) else np.nan,
        "net_margin_avg": m.mean() if len(m) else np.nan,
        "margin_change_avg": chg.mean() if len(chg) else np.nan,
        "margin_change_median": chg.median() if len(chg) else np.nan,
        "margin_years_up": int((chg > 0).sum()),
        "margin_change_years": len(chg),
        "net_margin_by_year": "; ".join(f"{d.year}: {v:.1%}" for d, v in m.items()),
    }


def _cagr(s: pd.Series) -> float:
    s = s.dropna()
    s = s[s > 0]
    if len(s) < 2:
        return np.nan
    years = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1 if years > 0.5 else np.nan


def dcf_equity(fcff: float, net_debt: float, wacc: float) -> float:
    """Standard enterprise DCF on cash flow before growth investment: FCFF grows at
    TERMINAL_GROWTH forever, value = FCFF x (1 + g) / (WACC - g), minus net debt."""
    if not (np.isfinite(fcff) and fcff > 0 and np.isfinite(wacc)) or wacc <= TERMINAL_GROWTH + 0.01:
        return np.nan
    return fcff * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH) - net_debt


ANALYST_VIEW = [(1.5, "strong_buy"), (2.5, "buy"), (3.5, "hold"), (4.5, "sell")]


def analyst_view(mark: float) -> str | None:
    """TradingView's recommendation mark (1 = strong buy ... 5 = strong sell) as Yahoo's
    words."""
    mark = num(mark)
    if not np.isfinite(mark):
        return None
    return next((name for top, name in ANALYST_VIEW if mark <= top), "strong_sell")


def yearly(f: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """One stock's fiscal years: flows of the year, the balance sheet at its end (US dollars,
    per share on today's basis), indexed by the fiscal year's end."""
    g = f[f["symbol"] == symbol]
    fy = g[(g["period_type"] == "FY") & g["item"].isin(FLOWS)]
    inst = g[(g["period_type"] == "I") & (g["fiscal_period"] == "Q4") & g["item"].isin(INSTANTS)]
    ends = fy.groupby("fiscal_year")["period_end"].max()
    both = pd.concat([fy, inst])
    if both.empty:
        return pd.DataFrame()
    wide = both.pivot_table(index="fiscal_year", columns="item", values="value", aggfunc="last")
    end = ends.reindex(wide.index)
    q4 = inst.groupby("fiscal_year")["period_end"].max().reindex(wide.index)
    wide.index = pd.to_datetime(end.fillna(q4))
    wide = wide[wide.index.notna()].sort_index()
    return wide[~wide.index.duplicated(keep="last")]


def quarter_growth(f: pd.DataFrame, symbol: str, item: str) -> float:
    """The latest quarter against the same quarter a year before."""
    q = f[(f["symbol"] == symbol) & (f["period_type"] == "Q") & (f["item"] == item)]
    if len(q) < 5:
        return np.nan
    q = q.assign(end=pd.to_datetime(q["period_end"])).sort_values("end")
    last = q.iloc[-1]
    before = q[(q["end"] < last["end"] - pd.Timedelta(days=330))]
    before = before[before["end"] > last["end"] - pd.Timedelta(days=400)]
    if before.empty:
        return np.nan
    prev = float(before.iloc[-1]["value"])
    return (float(last["value"]) - prev) / abs(prev) if prev else np.nan


def stock_row(
    symbol: str,
    company: pd.Series,
    t: pd.Series,
    years: pd.DataFrame,
    f: pd.DataFrame,
    px: pd.DataFrame,
    fx: float,
) -> dict:
    """The analyses' row for one stock: absolute values ($bn), ratios, growth, standard DCF."""
    tv = company.get("tv") if isinstance(company.get("tv"), dict) else {}
    bn = 1e9

    def tt(item):
        return num(t.get(item)) if t is not None else np.nan

    price = float(px["close"].iloc[-1]) if not px.empty else num(tv.get("close"))
    price_date = px["date"].iloc[-1].date().isoformat() if not px.empty else None
    shares = tt("shares_outstanding")
    currency = reporting_currency(company)
    if currency == "USD" and np.isfinite(shares) and np.isfinite(price):
        mcap = price * shares / bn
    else:
        mcap = num(tv.get("market_cap_basic")) * fx / bn
    revenue, net_income, ebitda = tt("revenue") / bn, tt("net_income") / bn, tt("ebitda") / bn
    interest = abs(tt("interest_expense")) / bn
    ocf, capex, da = tt("operating_cf") / bn, tt("capex") / bn, tt("d_and_a") / bn
    fcf = ocf + capex if np.isfinite(ocf) and np.isfinite(capex) else np.nan
    total_known = tt("total_debt") / bn
    short_debt, long_debt = tt("short_term_debt") / bn, tt("long_term_debt") / bn
    cash = tt("cash") / bn
    equity = tt("equity") / bn
    if not np.isfinite(total_known) and (np.isfinite(short_debt) or np.isfinite(long_debt)):
        total_known = np.nansum([short_debt, long_debt])
    if not np.isfinite(short_debt) and np.isfinite(long_debt) and np.isfinite(total_known):
        short_debt = max(total_known - long_debt, 0.0)
    if not np.isfinite(long_debt) and np.isfinite(short_debt) and np.isfinite(total_known):
        long_debt = max(total_known - short_debt, 0.0)
    if not np.isfinite(total_known) or total_known == 0:
        short_debt = 0.0 if not np.isfinite(short_debt) else short_debt
        long_debt = 0.0 if not np.isfinite(long_debt) else long_debt
    debt = 0.0 if not np.isfinite(total_known) else total_known
    liquid = cash
    cash0 = 0.0 if not np.isfinite(cash) else cash
    net_debt = debt - cash0

    rec = years.tail(GROWTH_YEARS) if not years.empty else years

    def hist(item):
        return rec[item] if item in rec else pd.Series(dtype=float)

    rev_h, eps_h, ni_h = hist("revenue"), hist("eps_diluted"), hist("net_income")
    margin_h = (ni_h / rev_h.where(rev_h > 0)).dropna()

    beta = num(tv.get("beta_1_year"))
    beta = beta if np.isfinite(beta) else 0.8
    ke = RISK_FREE + (0.67 * beta + 0.33) * EQUITY_PREMIUM
    leverage = _div(net_debt, ebitda)
    spread = 0.013 if leverage < 3 else 0.02 if leverage < 5 else 0.03
    if not np.isfinite(leverage):
        spread = 0.03
    kd = RISK_FREE + spread
    total_cap = mcap + debt
    wacc = (
        _div(mcap, total_cap) * ke + _div(debt, total_cap) * kd * (1 - TAX)
        if np.isfinite(total_cap) and total_cap > 0
        else np.nan
    )
    after_tax_interest = interest * (1 - TAX) if np.isfinite(interest) else 0.0
    fcff = ocf - da + after_tax_interest if np.isfinite(ocf) and np.isfinite(da) else np.nan
    dcf_eq = dcf_equity(fcff, net_debt, wacc)
    fair_value = (
        price * dcf_eq / mcap
        if np.isfinite(dcf_eq) and dcf_eq > 0 and np.isfinite(mcap) and mcap > 0
        else np.nan
    )
    eps_ttm = tt("eps_diluted")
    eps_fwd = num(tv.get("earnings_per_share_forecast_next_fy")) * fx
    year = px[px["date"] > px["date"].iloc[-1] - pd.Timedelta(days=365)] if len(px) else px
    high52 = float(year["close"].max()) if len(year) else np.nan
    dividends = float(year["dividend"].fillna(0).sum()) if len(year) else np.nan
    target = num(tv.get("price_target_average"))
    return {
        "symbol": symbol,
        "name": company.get("name"),
        "industry": company.get("industry") or "Other",
        "sector": company.get("sector"),
        "country": company.get("country"),
        "currency": currency,
        "price": price,
        "price_date": price_date,
        "market_cap": mcap,
        "total_debt": debt,
        "cash": liquid,
        "short_term_debt": short_debt,
        "long_term_debt": long_debt,
        "cash_to_short_term_debt": _div(liquid, short_debt)
        if short_debt and short_debt > 0
        else (np.inf if np.isfinite(liquid) else np.nan),
        "cash_plus_ocf_to_short_term_debt": _div(liquid + max(ocf, 0.0), short_debt)
        if short_debt and short_debt > 0 and np.isfinite(ocf)
        else (np.inf if np.isfinite(liquid) else np.nan),
        "cash_to_long_term_debt": _div(liquid, long_debt)
        if long_debt and long_debt > 0
        else (np.inf if np.isfinite(liquid) else np.nan),
        "net_debt": net_debt,
        "net_debt_to_ebitda": leverage,
        "ebitda_to_interest": _div(ebitda, interest),
        "debt_to_equity": _div(debt, equity),
        **_growth_stats(rev_h, "revenue"),
        **_growth_stats(eps_h, "eps"),
        **_margin_stats(margin_h),
        **_growth_stats(hist("cash"), "cash"),
        **_growth_stats(hist("operating_cf"), "ocf"),
        "revenue_cagr_3y": _cagr(rev_h),
        "ebitda_cagr_3y": _cagr(hist("ebitda")),
        "eps_cagr_3y": _cagr(eps_h),
        "revenue_growth_yoy": quarter_growth(f, symbol, "revenue"),
        "earnings_growth_yoy": quarter_growth(f, symbol, "net_income"),
        "operating_cf": ocf,
        "capex": capex,
        "free_cf": fcf,
        "fcf_yield": _div(fcf, mcap),
        "revenue": revenue,
        "ebitda": ebitda,
        "net_income": net_income,
        "net_margin": _div(net_income, revenue),
        "eps_ttm": eps_ttm,
        "eps_fwd": eps_fwd,
        "pe_ttm": price / eps_ttm if eps_ttm > 0 else np.nan,
        "pe_fwd": price / eps_fwd if eps_fwd > 0 else np.nan,
        "ev_to_ebitda": _div(mcap + net_debt, ebitda),
        "price_to_sales": _div(mcap, revenue),
        "price_to_book": _div(mcap, equity) if equity > 0 else np.nan,
        "dividend_yield": _div(dividends, price),
        "vs_52w_high": _div(price, high52) - 1 if np.isfinite(high52) else np.nan,
        "analyst_upside": _div(target, price) - 1 if np.isfinite(target) else np.nan,
        "analyst_view": analyst_view(tv.get("recommendation_mark")),
        "beta": beta,
        "wacc": wacc,
        "fcff_before_growth": fcff,
        "dcf_method": "standard: (OCF - D&A) at 2.5% growth",
        "dcf_fair_value": fair_value,
        "price_vs_fair_value": _div(price, fair_value) - 1 if np.isfinite(fair_value) else np.nan,
        "data_flag": ""
        if currency == "USD"
        else f"Reports in {currency}, converted to USD; check against filings",
    }


def rows(data, symbols: Iterable[str]) -> pd.DataFrame:
    """One row per stock (index: symbol) with the absolute values, ratios, growth and
    standard DCF, from the database. Stocks the database doesn't have
    get a row with only `error`."""
    symbols = sorted({s.upper() for s in symbols})
    comp = companies(data, symbols)
    fx_all = fx_rates(data)
    fx = {s: fx_all.get(reporting_currency(comp.loc[s]), np.nan) for s in comp.index}
    t = ttm(data, comp.index, fx)
    f = fundamentals(data, comp.index, fx, first_year=pd.Timestamp.today().year - 8)
    px = prices(data, comp.index, (pd.Timestamp.today() - pd.Timedelta(days=380)).strftime("%F"))
    out = []
    for s in symbols:
        if s not in comp.index:
            out.append({"symbol": s, "error": "not in the database"})
            continue
        y = yearly(f, s) if not f.empty else pd.DataFrame()
        p = px[px["symbol"] == s] if not px.empty else px
        tr = t.loc[s] if s in t.index else None
        out.append(stock_row(s, comp.loc[s], tr, y, f, p, fx.get(s, 1.0)))
    return pd.DataFrame(out).set_index("symbol")


def statements(data, symbols: Iterable[str], first_year: int = 2014) -> dict[str, dict]:
    """Per stock, its statements as tables (rows = period ends, oldest first; columns = core
    items, US dollars): "annual" (fiscal-year flows, the balance sheet at the year end) and
    "quarterly" (quarterly flows, the balance sheet at each quarter end), each with free_cf
    (operating cash flow + capex) added."""
    symbols = sorted({s.upper() for s in symbols})
    comp = companies(data, symbols)
    fx_all = fx_rates(data)
    fx = {s: fx_all.get(reporting_currency(comp.loc[s]), np.nan) for s in comp.index}
    f = fundamentals(data, comp.index, fx, first_year=first_year)
    out = {}
    for s in comp.index:
        g = f[f["symbol"] == s] if not f.empty else f
        annual = yearly(f, s) if not f.empty else pd.DataFrame()
        q = g[(g["period_type"] == "Q") & g["item"].isin(FLOWS)] if len(g) else g
        i = g[(g["period_type"] == "I") & g["item"].isin(INSTANTS)] if len(g) else g
        both = pd.concat([q, i]) if len(g) else g
        quarterly = (
            both.assign(period_end=pd.to_datetime(both["period_end"]))
            .pivot_table(index="period_end", columns="item", values="value", aggfunc="last")
            .sort_index()
            if len(both)
            else pd.DataFrame()
        )
        for t in (annual, quarterly):
            for item in FLOWS + INSTANTS:
                if item not in t:
                    t[item] = np.nan
            t["free_cf"] = t["operating_cf"] + t["capex"]
        out[s] = {"annual": annual, "quarterly": quarterly}
    return out


HISTORY_COLUMNS = {  # history column -> core item (money in $bn, per share in $)
    "revenue": "revenue",
    "ebitda": "ebitda",
    "net_income": "net_income",
    "eps": "eps_diluted",
    "total_debt": "total_debt",
    "short_term_debt": "short_term_debt",
    "long_term_debt": "long_term_debt",
    "cash": "cash",
    "operating_cf": "operating_cf",
    "capex": "capex",
}


def history(data, symbols: Iterable[str], first_year: int = 2016) -> pd.DataFrame:
    """Every fiscal year on record, long format (symbol, fiscal_year_end, column, value,
    source): money in $bn, EPS on today's share basis, plus
    net debt, free cash flow, the DCF base, the year-end price and (US-dollar filers) the
    market value."""
    symbols = sorted({s.upper() for s in symbols})
    comp = companies(data, symbols)
    if comp.empty:
        return pd.DataFrame(columns=["symbol", "fiscal_year_end", "column", "value", "source"])
    fx_all = fx_rates(data)
    fx = {s: fx_all.get(reporting_currency(comp.loc[s]), np.nan) for s in comp.index}
    f = fundamentals(data, comp.index, fx, first_year=first_year)
    if f.empty:
        return pd.DataFrame(columns=["symbol", "fiscal_year_end", "column", "value", "source"])
    px = prices(data, comp.index, f"{first_year - 1}-01-01")
    out = []
    for s in comp.index:
        y = yearly(f, s)
        if y.empty:
            continue
        src = f[(f["symbol"] == s) & (f["period_type"].isin(["FY", "I"]))]
        src = src.assign(end=pd.to_datetime(src["period_end"]))
        p = px[px["symbol"] == s].set_index("date")["close"] if not px.empty else pd.Series()
        for end, r in y.iterrows():
            if end.year < first_year:
                continue

            def add(column, value, source, end=end, s=s):
                if np.isfinite(num(value)):
                    out.append([s, end.date().isoformat(), column, float(value), source])

            def source_of(item, end=end, src=src):
                m = src[(src["item"] == item) & ((src["end"] - end).abs() < pd.Timedelta(days=20))]
                return m["source"].iloc[-1] if len(m) else ""

            for column, item in HISTORY_COLUMNS.items():
                scale = 1 if item in PER_SHARE else 1e9
                add(column, num(r.get(item)) / scale, source_of(item))
            debt, cash = num(r.get("total_debt")) / 1e9, num(r.get("cash")) / 1e9
            add("net_debt", debt - cash, "derived")
            ocf, capex = num(r.get("operating_cf")) / 1e9, num(r.get("capex")) / 1e9
            add("free_cf", ocf + capex, "derived")
            da, interest = num(r.get("d_and_a")) / 1e9, abs(num(r.get("interest_expense"))) / 1e9
            interest = interest if np.isfinite(interest) else 0.0
            add("fcff_before_growth", ocf - da + interest * (1 - TAX), "derived")
            before = p[p.index <= end]
            if len(before):
                price = float(before.iloc[-1])
                add("price", price, "price")
                shares = num(r.get("shares_outstanding"))
                if reporting_currency(comp.loc[s]) == "USD":
                    add("market_cap", price * shares / 1e9, "price x shares")
    return pd.DataFrame(out, columns=["symbol", "fiscal_year_end", "column", "value", "source"])


Q_SCREENER_RUN = """
SELECT u.run_date, r.stage, r.symbol, r.sector, r.category, r.status, r.rank_in_sector,
       r.close, r.cheap_price, r.detail_json
FROM out_screener_result r JOIN out_screener_run u ON u.run_id = r.run_id
WHERE u.run_id = (SELECT run_id FROM out_screener_run ORDER BY run_date DESC, run_id DESC
                  LIMIT 1)"""
TEXT_COLUMNS = {"symbol", "sector", "category", "status", "run_date"}


def screener_run(data) -> tuple[str | None, pd.DataFrame, pd.DataFrame]:
    """The newest market screener run: (run date, Stage 1 rows, Stage 2 top), each indexed
    by TradingView symbol with every column of detail_json."""
    res = data.sql(Q_SCREENER_RUN)
    if res.empty:
        return None, pd.DataFrame(), pd.DataFrame()
    detail = pd.DataFrame([json.loads(x) if x else {} for x in res["detail_json"]])
    detail = detail[[c for c in detail.columns if c not in res.columns]]
    res = pd.concat([res.drop(columns="detail_json").reset_index(drop=True), detail], axis=1)
    for c in res.columns:
        if c not in TEXT_COLUMNS and res[c].dtype == object:
            converted = pd.to_numeric(res[c], errors="coerce")
            if converted.notna().sum() == res[c].notna().sum():
                res[c] = converted
    if "tv_symbol" not in res:
        res["tv_symbol"] = res["symbol"]
    res = res.set_index("tv_symbol")
    run_date = str(res["run_date"].iloc[0])[:10]
    return run_date, res[res["stage"] == 1].copy(), res[res["stage"] == 2].copy()


def sector_symbols(data, sector: str, index_only: bool = False) -> list[str]:
    """The companies of a sector (TradingView's sector names, e.g. "Utilities")."""
    sql = "SELECT c.symbol FROM core_company c"
    if index_only:
        sql += " JOIN core_index_member m ON m.company_id = c.company_id AND m.end_date IS NULL"
    sql += f" WHERE c.sector = '{sector.replace(chr(39), '')}' ORDER BY c.symbol"
    return data.sql(sql)["symbol"].tolist()


def row_columns() -> list[str]:
    """The columns of rows() (without a database: a row built from nothing)."""
    empty_f = pd.DataFrame(columns=["symbol", "item", "period_type", "period_end", "value"])
    empty_px = pd.DataFrame(columns=["symbol", "date", "close", "dividend"])
    row = stock_row("X", pd.Series({"name": "X", "tv": {}}), None, pd.DataFrame(), empty_f,
                    empty_px, 1.0)  # fmt: skip
    return [c for c in row if c != "symbol"]


HISTORY_NAMES = [*HISTORY_COLUMNS, "net_debt", "free_cf", "fcff_before_growth", "price",
                 "market_cap"]  # fmt: skip
