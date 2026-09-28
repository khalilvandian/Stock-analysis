"""Screen every US-listed utility and compute a standard set of metrics.

Pulls the Yahoo Finance utilities screen (US exchanges), keeps common stock,
fetches each company's statements, converts reported figures to USD, and
computes debt, growth, cash flow, earnings, valuation, price and a standard
enterprise DCF for every company. Writes data/sector/utilities.csv and
data/sector/utilities.json.

Usage: uv run python analysis/sector.py
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from yfinance import EquityQuery as Q

OUT = Path("data/sector")
RISK_FREE = 0.0518
EQUITY_PREMIUM = 0.05
TAX = 0.21
TERMINAL_GROWTH = 0.025
EXCHANGES = ["NMS", "NYQ", "ASE", "NGM", "NCM"]
# Guidance-based enterprise DCF (analysis/dcf_firm.py) replaces the standard one here
GUIDED = {"CEG", "VST", "NRG", "TLN"}
NOT_COMMON = re.compile(r"-P|W$|^(DUKU|PPLC|SOMN|AHD)$")


def universe() -> list[dict]:
    q = Q(
        "and",
        [
            Q("eq", ["sector", "Utilities"]),
            Q("eq", ["region", "us"]),
            Q("is-in", ["exchange", *EXCHANGES]),
        ],
    )
    quotes, offset = [], 0
    while True:
        page = yf.screen(q, offset=offset, size=250, sortField="intradaymarketcap", sortAsc=False)
        quotes += page.get("quotes", [])
        if len(page.get("quotes", [])) < 250:
            break
        offset += 250
    return [
        x
        for x in quotes
        if x.get("quoteType") == "EQUITY"
        and (x.get("marketCap") or 0) > 0
        and not NOT_COMMON.search(x["symbol"])
    ]


_fx: dict[str, float] = {"USD": 1.0}


def fx_to_usd(currency: str | None) -> float:
    currency = (currency or "USD").upper()
    if currency not in _fx:
        hist = yf.Ticker(f"{currency}USD=X").history(period="5d")
        _fx[currency] = float(hist["Close"].iloc[-1]) if not hist.empty else np.nan
    return _fx[currency]


def _get(df: pd.DataFrame, *names: str) -> pd.Series:
    """First matching line item, oldest period first."""
    for n in names:
        if df is not None and not df.empty and n in df.index:
            return df.loc[n].sort_index().astype(float)
    return pd.Series(dtype=float)


def _ttm(q: pd.DataFrame, a: pd.DataFrame, *names: str) -> float:
    s = _get(q, *names).dropna()
    if len(s) >= 4:
        return s.iloc[-4:].sum()
    s = _get(a, *names).dropna()
    return s.iloc[-1] if len(s) else np.nan


def _latest(q: pd.DataFrame, a: pd.DataFrame, *names: str) -> float:
    for df in (q, a):
        s = _get(df, *names).dropna()
        if len(s):
            return s.iloc[-1]
    return np.nan


def _cagr(s: pd.Series) -> float:
    s = s.dropna()
    s = s[s > 0]
    if len(s) < 2:
        return np.nan
    years = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1 if years > 0.5 else np.nan


def _yearly_growth(s: pd.Series) -> pd.Series:
    """Year-over-year growth for each fiscal year; undefined when the prior year is <= 0."""
    s = s.dropna()
    prev = s.shift(1)
    g = (s - prev) / prev
    return g[prev > 0].dropna()


def _growth_stats(s: pd.Series, prefix: str) -> dict:
    g = _yearly_growth(s)
    return {
        f"{prefix}_growth_avg": g.mean() if len(g) else np.nan,
        f"{prefix}_growth_median": g.median() if len(g) else np.nan,
        f"{prefix}_growth_years": len(g),
        f"{prefix}_growth_years_positive": int((g > 0).sum()),
        f"{prefix}_growth_by_year": "; ".join(f"{d.year}: {v:+.1%}" for d, v in g.items()),
    }


def _margin_stats(m: pd.Series) -> dict:
    """Net margin by fiscal year and its year-over-year change in percentage points."""
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


def _div(a: float, b: float) -> float:
    return a / b if b and np.isfinite(a) and np.isfinite(b) and b != 0 else np.nan


def dcf_equity(fcff: float, net_debt: float, wacc: float) -> float:
    """Standard enterprise DCF on cash flow before growth investment.

    FCFF grows at TERMINAL_GROWTH (inflation) forever: value = FCFF x (1 + g) / (WACC - g),
    minus net debt. Growth projects are assumed to earn roughly their cost of capital,
    so they are left out of both the cash flow and the growth rate.
    """
    if not (np.isfinite(fcff) and fcff > 0 and np.isfinite(wacc)) or wacc <= TERMINAL_GROWTH + 0.01:
        return np.nan
    return fcff * (1 + TERMINAL_GROWTH) / (wacc - TERMINAL_GROWTH) - net_debt


def apply_guided_dcf(df: pd.DataFrame) -> pd.DataFrame:
    """Use the guidance-based enterprise DCF (base case) for the modelled producers."""
    import sys

    sys.path.insert(0, str(Path(__file__).parent))
    from dcf import COMPANIES
    from dcf_firm import inputs, value

    for c in COMPANIES:
        if c.symbol in GUIDED and c.symbol in df.index:
            x = inputs(c)
            fair = value(c, 0.04)["per_share"]
            df.loc[c.symbol, "dcf_fair_value"] = fair
            df.loc[c.symbol, "wacc"] = x["wacc"]
            df.loc[c.symbol, "fcff_before_growth"] = x["base"]
            df.loc[c.symbol, "dcf_method"] = "guided FCF before growth, 4% growth"
            df.loc[c.symbol, "price_vs_fair_value"] = df.loc[c.symbol, "price"] / fair - 1
    return df


def analyse(quote: dict) -> dict:
    sym = quote["symbol"]
    t = yf.Ticker(sym)
    for attempt in range(3):
        try:
            info = t.info
            iq, ia = t.quarterly_income_stmt, t.income_stmt
            bq, ba = t.quarterly_balance_sheet, t.balance_sheet
            cq, ca = t.quarterly_cashflow, t.cashflow
            break
        except Exception:  # noqa: BLE001 - rate limits and transient errors
            time.sleep(2 * (attempt + 1))
    else:
        return {"symbol": sym, "name": quote.get("shortName"), "error": "fetch failed"}

    fx = fx_to_usd(info.get("financialCurrency"))
    bn = lambda v: v * fx / 1e9 if np.isfinite(v) else np.nan  # noqa: E731

    price = (
        info.get("currentPrice")
        or info.get("regularMarketPrice")
        or quote.get("regularMarketPrice")
    )
    mcap = (info.get("marketCap") or quote.get("marketCap") or np.nan) / 1e9

    revenue = bn(_ttm(iq, ia, "Total Revenue", "Operating Revenue"))
    net_income = bn(_ttm(iq, ia, "Net Income", "Net Income Common Stockholders"))
    ebitda = bn(_ttm(iq, ia, "EBITDA", "Normalized EBITDA"))
    interest = bn(_ttm(iq, ia, "Interest Expense", "Interest Expense Non Operating"))
    ocf = bn(_ttm(cq, ca, "Operating Cash Flow"))
    capex = bn(_ttm(cq, ca, "Capital Expenditure"))
    fcf = ocf + capex if np.isfinite(ocf) and np.isfinite(capex) else np.nan
    da = bn(_ttm(cq, ca, "Depreciation And Amortization", "Depreciation Amortization Depletion"))
    debt = bn(_latest(bq, ba, "Total Debt"))
    cash = bn(
        _latest(
            bq, ba, "Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"
        )
    )
    equity_book = bn(_latest(bq, ba, "Stockholders Equity", "Common Stock Equity"))
    # cash including short-term investments, and debt split by maturity
    liquid = bn(
        _latest(
            bq, ba, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"
        )
    )
    short_debt = bn(_latest(bq, ba, "Current Debt And Capital Lease Obligation", "Current Debt"))
    long_debt = bn(_latest(bq, ba, "Long Term Debt And Capital Lease Obligation", "Long Term Debt"))
    total_known = bn(_latest(bq, ba, "Total Debt"))
    if not np.isfinite(short_debt) and np.isfinite(long_debt) and np.isfinite(total_known):
        short_debt = max(total_known - long_debt, 0.0)
    if not np.isfinite(long_debt) and np.isfinite(short_debt) and np.isfinite(total_known):
        long_debt = max(total_known - short_debt, 0.0)
    if not np.isfinite(total_known) or total_known == 0:
        short_debt = 0.0 if not np.isfinite(short_debt) else short_debt
        long_debt = 0.0 if not np.isfinite(long_debt) else long_debt
    debt = 0.0 if not np.isfinite(debt) else debt
    cash = 0.0 if not np.isfinite(cash) else cash
    net_debt = debt - cash

    rev_hist = _get(ia, "Total Revenue", "Operating Revenue")
    ebitda_hist = _get(ia, "EBITDA", "Normalized EBITDA")
    eps_hist = _get(ia, "Diluted EPS", "Basic EPS")
    ni_hist = _get(ia, "Net Income", "Net Income Common Stockholders")
    margin_hist = (ni_hist / rev_hist.where(rev_hist > 0)).dropna()
    cash_hist = _get(
        ba, "Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"
    )
    ocf_hist = _get(ca, "Operating Cash Flow")

    beta = info.get("beta")
    beta = beta if isinstance(beta, int | float) and np.isfinite(beta) else 0.8
    ke = RISK_FREE + (0.67 * beta + 0.33) * EQUITY_PREMIUM
    leverage = _div(net_debt, ebitda)
    spread = (
        0.013
        if np.isfinite(leverage) and leverage < 3
        else 0.02
        if np.isfinite(leverage) and leverage < 5
        else 0.03
    )
    kd = RISK_FREE + spread
    total_cap = mcap + debt
    wacc = (
        _div(mcap, total_cap) * ke + _div(debt, total_cap) * kd * (1 - TAX)
        if total_cap > 0
        else np.nan
    )
    after_tax_interest = abs(interest) * (1 - TAX) if np.isfinite(interest) else 0.0
    # maintenance capex approximated by depreciation
    fcff = ocf - da + after_tax_interest if np.isfinite(ocf) and np.isfinite(da) else np.nan
    dcf_eq = dcf_equity(fcff, net_debt, wacc)
    fair_value = (
        price * dcf_eq / mcap if np.isfinite(dcf_eq) and dcf_eq > 0 and mcap > 0 else np.nan
    )

    target = info.get("targetMeanPrice")
    high52 = info.get("fiftyTwoWeekHigh")
    div_yield = info.get("dividendYield")
    return {
        "symbol": sym,
        "name": info.get("longName") or quote.get("shortName"),
        "industry": (info.get("industry") or "Other").replace("Utilities - ", ""),
        "country": info.get("country"),
        "currency": info.get("financialCurrency"),
        "price": price,
        "market_cap": mcap,
        # debt
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
        "ebitda_to_interest": _div(ebitda, abs(interest) if np.isfinite(interest) else np.nan),
        "debt_to_equity": _div(debt, equity_book),
        # growth
        **_growth_stats(rev_hist, "revenue"),
        **_growth_stats(eps_hist, "eps"),
        **_margin_stats(margin_hist),
        **_growth_stats(cash_hist, "cash"),
        **_growth_stats(ocf_hist, "ocf"),
        "revenue_cagr_3y": _cagr(rev_hist.iloc[-4:]),
        "ebitda_cagr_3y": _cagr(ebitda_hist.iloc[-4:]),
        "eps_cagr_3y": _cagr(eps_hist.iloc[-4:]),
        "revenue_growth_yoy": info.get("revenueGrowth"),
        "earnings_growth_yoy": info.get("earningsGrowth"),
        # cash flow
        "operating_cf": ocf,
        "capex": capex,
        "free_cf": fcf,
        "fcf_yield": _div(fcf, mcap),
        # earnings
        "revenue": revenue,
        "ebitda": ebitda,
        "net_income": net_income,
        "net_margin": _div(net_income, revenue),
        "eps_ttm": info.get("trailingEps"),
        "eps_fwd": info.get("forwardEps"),
        # valuation
        "pe_ttm": info.get("trailingPE"),
        "pe_fwd": info.get("forwardPE"),
        "ev_to_ebitda": _div(mcap + net_debt, ebitda),
        "price_to_sales": _div(mcap, revenue),
        "price_to_book": info.get("priceToBook"),
        "dividend_yield": div_yield / 100 if isinstance(div_yield, int | float) else np.nan,
        # price
        "vs_52w_high": _div(price, high52) - 1 if high52 else np.nan,
        "analyst_upside": _div(target, price) - 1 if target else np.nan,
        "analyst_view": info.get("recommendationKey"),
        "beta": beta,
        # standard DCF
        "wacc": wacc,
        "fcff_before_growth": fcff,
        "dcf_method": "standard: (OCF - D&A) at 2.5% growth",
        "dcf_fair_value": fair_value,
        "price_vs_fair_value": _div(price, fair_value) - 1 if np.isfinite(fair_value) else np.nan,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    quotes = universe()
    print(f"{len(quotes)} companies")
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows = list(pool.map(analyse, quotes))
    df = pd.DataFrame(rows).drop_duplicates(subset="name", keep="first").set_index("symbol")
    df["data_flag"] = np.where(
        df["currency"].fillna("USD") != "USD",
        "Reports in " + df["currency"].fillna("?") + ", converted to USD; check against filings",
        "",
    )
    df = apply_guided_dcf(df)
    df.to_csv(OUT / "utilities.csv")
    meta = {
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "Yahoo Finance screener (sector=Utilities, US exchanges)",
        "count": len(df),
        "failed": df.index[df.get("error", pd.Series(dtype=object)).notna()].tolist()
        if "error" in df
        else [],
        "fx_to_usd": _fx,
    }
    (OUT / "_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"saved {len(df)} rows, failed: {meta['failed']}")


if __name__ == "__main__":
    main()
