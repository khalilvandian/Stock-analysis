"""Export the data of the ticker explorer (issue #20): one JSON file per company in the
database, plus an index, for the explorer pages of the GitHub Pages site (analysis/site.py).

    tickers/index.json        one row per company: snapshot, ratios, screener, next earnings
    tickers/<SYMBOL>.json     profile, absolute values (TTM), ratios, annual and quarterly
                              statements, the ratio history (issue #22), weekly and daily
                              prices, technicals, dividends, earnings, screener verdict,
                              valuations

The database is read in a few bulk queries, by blocks of symbols, so that no query returns
more than the web API's 50,000 rows. Backend: the web API when STOCK_API_URL and STOCK_API_KEY
are set (the Pages workflow), else stock_analysis.data (a PC with the project installed).
Standard library only, so the Pages workflow needs no install step.

Usage:
    python analysis/explore.py [OUT_DIR] [--symbols NVDA,NEE,...]
"""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import statistics
import sys
import tomllib
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROW_LIMIT = 50_000
SYMBOL = re.compile(r"^[A-Z0-9.\-]{1,12}$")

FLOWS = [
    "revenue",
    "operating_income",
    "ebitda",
    "d_and_a",
    "net_income",
    "eps_diluted",
    "eps_continuing",
    "interest_expense",
    "operating_cf",
    "capex",
]
INSTANTS = [
    "cash",
    "short_term_debt",
    "long_term_debt",
    "total_debt",
    "total_assets",
    "total_liabilities",
    "equity",
    "shares_outstanding",
]
FIRST_YEAR = 2014  # SEC company facts start about here
QUARTERS_KEPT = 40
WEEKLY_YEARS = 11
DAILY_DAYS = 400  # enough trading days for the 200-day average and the 52-week range

# --- the queries ----------------------------------------------------------------------

Q_COMPANIES = """
SELECT c.symbol, c.name, c.exchange, c.sector, c.industry, c.currency, c.cik,
       m.start_date AS sp500_since
FROM core_company c
LEFT JOIN core_index_member m ON m.company_id = c.company_id AND m.end_date IS NULL
ORDER BY c.symbol"""

# Per-share values on today's share basis, as in v_annual.
Q_FUNDAMENTALS = f"""
SELECT c.symbol, f.item, f.period_type, f.fiscal_year, f.fiscal_period,
       f.period_end, f.source,
       CASE WHEN f.item IN ('eps_diluted', 'eps_continuing') THEN f.value / f.split_factor
            WHEN f.item = 'shares_outstanding' THEN f.value * f.split_factor
            ELSE f.value END AS value
FROM v_fundamental_latest f
JOIN core_company c ON c.company_id = f.company_id
WHERE c.symbol IN ({{symbols}}) AND f.fiscal_year >= {FIRST_YEAR}"""

Q_TTM = """
SELECT DISTINCT ON (t.company_id, t.item) c.symbol, t.item, t.period_end, t.filed,
       t.basis, t.value_adj AS value
FROM core_fundamental_ttm t
JOIN core_company c ON c.company_id = t.company_id
ORDER BY t.company_id, t.item, t.period_end DESC, t.filed DESC"""

Q_WEEKLY = f"""
SELECT c.symbol, w.date, w.close, w.adj_close
FROM (
    SELECT p.company_id, p.date, p.close, p.adj_close,
           ROW_NUMBER() OVER (PARTITION BY p.company_id, date_trunc('week', p.date)
                              ORDER BY p.date DESC) AS rn
    FROM core_price_daily p
    WHERE p.date >= CURRENT_DATE - INTERVAL '{WEEKLY_YEARS} years'
      AND p.company_id IN (SELECT company_id FROM core_company WHERE symbol IN ({{symbols}}))
) w
JOIN core_company c ON c.company_id = w.company_id
WHERE w.rn = 1
ORDER BY c.symbol, w.date"""

# The last close of each month (as stock_analysis.stocks.Q_MONTHLY), for the yearly average
# price of the ratio history (the same as Stage 2's own-history P/E).
Q_MONTHLY = f"""
SELECT symbol, month, day, close FROM (
    SELECT c.symbol, date_trunc('month', p.date)::date AS month, p.date AS day, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.company_id, date_trunc('month', p.date)
                              ORDER BY p.date DESC) AS rn
    FROM core_price_daily p
    JOIN core_company c ON c.company_id = p.company_id
    WHERE c.symbol IN ({{symbols}}) AND p.date >= DATE '{FIRST_YEAR - 1}-01-01'
) m WHERE rn = 1
ORDER BY symbol, month"""

# Every version of every trailing-twelve-month value (balance sheet: at the quarter end) with
# its filing date, for the monthly ratios: each month-end close against what had been filed
# by that day (as v_daily). On today's share basis.
Q_TTM_HISTORY = f"""
SELECT c.symbol, t.item, t.period_end, t.filed, t.value_adj AS value
FROM core_fundamental_ttm t
JOIN core_company c ON c.company_id = t.company_id
WHERE c.symbol IN ({{symbols}}) AND t.filed >= DATE '{FIRST_YEAR}-01-01'
  AND t.item IN ('revenue', 'eps_diluted', 'eps_continuing', 'operating_cf', 'capex', 'ebitda',
                 'equity', 'cash', 'total_debt', 'shares_outstanding')
ORDER BY c.symbol, t.item, t.filed, t.period_end"""

Q_DAILY = f"""
SELECT c.symbol, p.date, p.close, p.volume
FROM core_price_daily p
JOIN core_company c ON c.company_id = p.company_id
WHERE c.symbol IN ({{symbols}}) AND p.date >= CURRENT_DATE - INTERVAL '{DAILY_DAYS} days'
ORDER BY c.symbol, p.date"""

Q_DIVIDENDS = """
SELECT c.symbol, p.date, p.dividend
FROM core_price_daily p
JOIN core_company c ON c.company_id = p.company_id
WHERE p.dividend > 0
ORDER BY c.symbol, p.date"""

# The latest fetch of each report date.
Q_EARNINGS = """
SELECT DISTINCT ON (symbol, report_date) symbol, report_date, eps_estimate, eps_reported,
       surprise_pct
FROM raw_yahoo_earnings
WHERE report_date >= DATE '2016-01-01'
ORDER BY symbol, report_date, fetch_id DESC"""

Q_SCREENER = """
SELECT u.run_date, r.stage, r.symbol, r.category, r.status, r.rank_in_sector, r.close,
       r.cheap_price, r.detail_json
FROM out_screener_result r
JOIN out_screener_run u ON u.run_id = r.run_id
WHERE u.run_id = (SELECT run_id FROM out_screener_run ORDER BY run_date DESC, run_id DESC
                  LIMIT 1)"""

Q_VALUATIONS = """
SELECT DISTINCT ON (symbol, method) symbol, as_of, method, fair_value, price, source
FROM out_valuation
ORDER BY symbol, method, as_of DESC"""

Q_WATCHLIST = "SELECT symbol FROM user_watchlist ORDER BY position"

# Stage 1 and Stage 2 fields kept for the Screener tab (the rest of detail_json stays out).
STAGE1_KEEP = [
    "rule_set",
    "failed",
    "missing",
    "flags",
    "piotroski_f_score_ttm",
    "altman_z_score_ttm",
    "return_on_equity_fq",
    "price_book_fq",
    "debt_to_equity",
    "interest_cover",
    "net_debt_to_ebitda",
    "cash_to_short_term_debt",
    "revenue_growth_median",
    "eps_growth_median",
    "eps_growth_3y",
    "eps_vs_5y_peak",
    "eps_big_drops_10y",
    "recession_eps_change",
    "dividend_years_10y",
    "dividend_payout_ratio_ttm",
]
STAGE2_KEEP = [
    "cheap_pe",
    "cheap_basis",
    "pe_now",
    "pe_median_10y",
    "pe_low_10y",
    "sector_pe",
    "vs_cheap",
    "cheapness",
    "why",
    "trend",
    "rsi_read",
    "tv_rating",
    "Recommend.All",
    "earnings_per_share_forecast_next_fy",
    "fcf_yield",
    "pe_vs_sector",
    "ev_ebitda_vs_sector",
]


# --- backends -------------------------------------------------------------------------


def api_backend(url: str, key: str):
    def query(sql: str) -> list[dict]:
        req = urllib.request.Request(
            url.rstrip("/") + "/query",
            data=json.dumps({"sql": sql, "limit": ROW_LIMIT}).encode(),
            method="POST",
            headers={"Content-Type": "application/json", "X-API-Key": key},
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            body = json.loads(r.read())
        if body.get("truncated"):
            raise RuntimeError("a query returned more than the API's row limit")
        return [dict(zip(body["columns"], row, strict=True)) for row in body["rows"]]

    return query


def local_backend():
    sys.path.insert(0, str(ROOT / "src"))
    from stock_analysis.data import Data  # needs the project's packages

    data = Data.open()

    def query(sql: str) -> list[dict]:
        df = data.sql(sql, limit=ROW_LIMIT + 1)
        if len(df) > ROW_LIMIT:
            raise RuntimeError("a query returned more than the row limit")
        df = df.astype(object).where(df.notna(), None)
        return df.to_dict("records")

    return query


def backend():
    url, key = os.environ.get("STOCK_API_URL"), os.environ.get("STOCK_API_KEY")
    if url and key:
        return api_backend(url, key)
    return local_backend()


def in_list(symbols: list[str]) -> str:
    bad = [s for s in symbols if not SYMBOL.match(s)]
    if bad:
        raise ValueError(f"not a ticker: {bad[:3]}")
    return ", ".join(f"'{s}'" for s in symbols)


def blocks(symbols: list[str], size: int):
    for i in range(0, len(symbols), size):
        yield symbols[i : i + size]


def fetch(query, symbols: list[str] | None = None) -> dict:
    """Every row the explorer needs, grouped by symbol."""
    companies = query(Q_COMPANIES)
    if symbols:
        wanted = set(symbols)
        companies = [c for c in companies if c["symbol"] in wanted]
    syms = [c["symbol"] for c in companies if SYMBOL.match(c["symbol"] or "")]

    def chunked(sql: str, size: int) -> list[dict]:
        rows = []
        for block in blocks(syms, size):
            rows += query(sql.format(symbols=in_list(block)))
        return rows

    raw = {
        "companies": companies,
        "fundamentals": chunked(Q_FUNDAMENTALS, 40),
        "ttm": query(Q_TTM),
        "weekly": chunked(Q_WEEKLY, 60),
        "monthly": chunked(Q_MONTHLY, 150),
        "ttm_history": chunked(Q_TTM_HISTORY, 30),
        "daily": chunked(Q_DAILY, 120),
        "dividends": query(Q_DIVIDENDS),
        "earnings": query(Q_EARNINGS),
        "screener": query(Q_SCREENER),
        "valuations": query(Q_VALUATIONS),
        "watchlist": query(Q_WATCHLIST),
    }
    return raw


def group(rows: list[dict], key: str = "symbol") -> dict[str, list[dict]]:
    out = defaultdict(list)
    for r in rows:
        out[r[key]].append(r)
    return out


# --- small helpers --------------------------------------------------------------------


def f(v) -> float | None:
    """A finite float, or None."""
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def r6(v) -> float | None:
    """Six significant digits, to keep the files small."""
    x = f(v)
    return None if x is None else float(f"{x:.6g}")


def div(a, b) -> float | None:
    a, b = f(a), f(b)
    if a is None or b is None or b == 0:
        return None
    return a / b


def pos_div(a, b) -> float | None:
    """a / b only when both are positive (a P/E of a loss maker means nothing)."""
    a, b = f(a), f(b)
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return a / b


def add(*xs) -> float | None:
    xs = [f(x) for x in xs]
    return None if any(x is None for x in xs) else sum(xs)


def iso(v) -> str | None:
    return None if v is None else str(v)[:10]


def cagr(first, last, years: float) -> float | None:
    first, last = f(first), f(last)
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return (last / first) ** (1 / years) - 1


def median(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def price_on(weekly: list[list], day: str) -> float | None:
    """The last weekly close on or before the day."""
    best = None
    for d, close, _ in weekly:
        if d <= day:
            best = close
        else:
            break
    return best


# --- statements -----------------------------------------------------------------------


def annual(rows: list[dict]) -> dict:
    """One column per fiscal year: flows from the FY rows, the balance sheet at the Q4 date."""
    years: dict[int, dict] = defaultdict(dict)
    ends: dict[int, str] = {}
    for r in rows:
        fy, item = r["fiscal_year"], r["item"]
        if fy is None:
            continue
        fy = int(fy)
        if r["period_type"] == "FY" and item in FLOWS:
            years[fy][item] = f(r["value"])
            ends[fy] = iso(r["period_end"])
        elif r["period_type"] == "I" and r["fiscal_period"] == "Q4" and item in INSTANTS:
            years[fy][item] = f(r["value"])
            ends.setdefault(fy, iso(r["period_end"]))
    keep = sorted(y for y in years if "revenue" in years[y] or "net_income" in years[y])
    return {
        "years": keep,
        "period_end": [ends.get(y) for y in keep],
        "items": {i: [r6(years[y].get(i)) for y in keep] for i in FLOWS + INSTANTS},
    }


def quarterly(rows: list[dict]) -> dict:
    """One column per quarter. A missing fourth quarter (often only in the 10-K) is the
    fiscal year less the first three quarters, and is listed under `derived`."""
    flows: dict[str, dict] = defaultdict(dict)
    instants: dict[str, dict] = defaultdict(dict)
    label: dict[str, tuple] = {}
    fy_flow: dict[int, dict] = defaultdict(dict)
    fy_end: dict[int, str] = {}
    q_by_year: dict[int, dict] = defaultdict(dict)
    for r in rows:
        end, item, fy, fp = iso(r["period_end"]), r["item"], r["fiscal_year"], r["fiscal_period"]
        if r["period_type"] == "Q" and item in FLOWS:
            flows[end][item] = f(r["value"])
            label[end] = (fy, fp)
            if fy is not None:
                q_by_year[int(fy)].setdefault(fp, {})[item] = f(r["value"])
        elif r["period_type"] == "I" and item in INSTANTS:
            instants[end][item] = f(r["value"])
            label.setdefault(end, (fy, fp))
        elif r["period_type"] == "FY" and item in FLOWS and fy is not None:
            fy_flow[int(fy)][item] = f(r["value"])
            fy_end[int(fy)] = end
    derived = []
    for fy, total in fy_flow.items():
        qs = q_by_year.get(fy, {})
        end = fy_end[fy]
        for item, value in total.items():
            if flows.get(end, {}).get(item) is not None or value is None:
                continue
            parts = [qs.get(p, {}).get(item) for p in ("Q1", "Q2", "Q3")]
            if all(p is not None for p in parts):
                flows[end][item] = value - sum(parts)
                label[end] = (fy, "Q4")
                derived.append([end, item])
    ends = sorted(set(flows) | set(instants))
    ends = [e for e in ends if flows.get(e)][-QUARTERS_KEPT:]
    return {
        "period_end": ends,
        "label": [f"{label[e][1]} FY{label[e][0]}" if label[e][0] else e for e in ends],
        "items": {
            i: [r6((flows if i in FLOWS else instants).get(e, {}).get(i)) for e in ends]
            for i in FLOWS + INSTANTS
        },
        "derived": [d for d in derived if d[0] in ends],
    }


def pe_eps(g: dict) -> float | None:
    """The EPS a P/E is measured on: from continuing operations, without the businesses a
    company sold or spun off (as data providers measure it, #49), else diluted EPS (the same
    figure for a company without discontinued operations)."""
    v = g.get("eps_continuing")
    return v if v is not None else g.get("eps_diluted")


def annual_ratios(a: dict, weekly: list[list]) -> dict:
    """Per fiscal year: free cash flow, net debt, margins, returns, and the P/E at the
    fiscal year end (price that week on today's share basis over that year's EPS)."""
    it = a["items"]
    n = len(a["years"])
    out = defaultdict(list)
    for k in range(n):
        g = {i: it[i][k] for i in it}
        price = price_on(weekly, a["period_end"][k]) if a["period_end"][k] else None
        cap = (
            None
            if price is None or g["shares_outstanding"] is None
            else (price * g["shares_outstanding"])
        )
        fcf = add(g["operating_cf"], g["capex"])
        net_debt = add(g["total_debt"], -(g["cash"] or 0)) if g["total_debt"] is not None else None
        out["price"].append(r6(price))
        out["market_cap"].append(r6(cap))
        out["free_cf"].append(r6(fcf))
        out["net_debt"].append(r6(net_debt))
        out["pe"].append(r6(pos_div(price, pe_eps(g))))
        out["ps"].append(r6(pos_div(cap, g["revenue"])))
        out["pb"].append(r6(pos_div(cap, g["equity"])))
        out["ev_ebitda"].append(r6(pos_div(add(cap, net_debt), g["ebitda"])))
        out["fcf_yield"].append(r6(div(fcf, cap)))
        out["operating_margin"].append(r6(div(g["operating_income"], g["revenue"])))
        out["ebitda_margin"].append(r6(div(g["ebitda"], g["revenue"])))
        out["net_margin"].append(r6(div(g["net_income"], g["revenue"])))
        out["fcf_margin"].append(r6(div(fcf, g["revenue"])))
        out["roe"].append(r6(pos_div(g["net_income"], g["equity"])))
        out["roa"].append(r6(div(g["net_income"], g["total_assets"])))
        out["debt_to_equity"].append(r6(pos_div(g["total_debt"], g["equity"])))
        out["debt_to_assets"].append(r6(div(g["total_debt"], g["total_assets"])))
        out["net_debt_to_ebitda"].append(r6(div(net_debt, g["ebitda"])))
        out["interest_cover"].append(r6(pos_div(g["ebitda"], g["interest_expense"])))
        out["fcf_per_share"].append(r6(div(fcf, g["shares_outstanding"])))
        out["book_per_share"].append(r6(div(g["equity"], g["shares_outstanding"])))
    return dict(out)


def screener_settings() -> dict:
    """The own-history settings of Stage 2 (config/screeners.toml), so the explorer's cheap
    band is the screener's cheap P/E."""
    out = {"cheap_percentile": 0.25, "history_years": 10, "min_history_years": 6}
    try:
        with open(ROOT / "config/screeners.toml", "rb") as fh:
            cfg = tomllib.load(fh)
    except OSError:
        return out
    return {k: cfg.get(k, v) for k, v in out.items()}


SETTINGS = screener_settings()
MIN_MONTHS = 9  # months of closes a fiscal year needs for its average price (as Stage 2)


def average_price(monthly: list[list], end: str | None) -> float | None:
    """The average of the month-end closes over the fiscal year ending on `end`: the months
    starting after `end` less one year, up to `end` (Stage 2's fiscal_pe window)."""
    if not end:
        return None
    start = shift_years(end, -1)
    window = [row[1] for row in monthly if row[1] is not None and start < row[0] <= end]
    return sum(window) / len(window) if len(window) >= MIN_MONTHS else None


def quantile(xs: list[float], q: float) -> float | None:
    """Linear interpolation between the closest ranks (pandas' default)."""
    xs = sorted(xs)
    if not xs:
        return None
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def ratio_history(a: dict, monthly: list[list]) -> dict:
    """Per fiscal year, the valuation multiples at the year's average month-end close (the
    same price as Stage 2's own-history P/E), for the yearly ratio table and the own P/E
    history of the Fair value tab. The charts use the monthly series (monthly_ratios)."""
    it, n = a["items"], len(a["years"])
    series: dict[str, list] = defaultdict(list)
    for k in range(n):
        g = {i: it[i][k] for i in it}
        price = average_price(monthly, a["period_end"][k])
        shares = g["shares_outstanding"]
        cap = price * shares if price is not None and shares is not None else None
        net_debt = add(g["total_debt"], -(g["cash"] or 0)) if g["total_debt"] is not None else None
        series["avg_price"].append(r6(price))
        series["pe"].append(r6(pos_div(price, pe_eps(g))))
        series["ps"].append(r6(pos_div(cap, g["revenue"])))
        series["pb"].append(r6(pos_div(cap, g["equity"])))
        series["ev_ebitda"].append(r6(pos_div(add(cap, net_debt), g["ebitda"])))
        series["fcf_yield"].append(r6(div(add(g["operating_cf"], g["capex"]), cap)))
    return {
        "years": a["years"],
        "series": dict(series),
        "cheap_percentile": SETTINGS["cheap_percentile"],
        "history_years": SETTINGS["history_years"],
        "min_history_years": SETTINGS["min_history_years"],
    }


MONTHLY_ITEMS = [
    "revenue",
    "eps_diluted",
    "eps_continuing",
    "operating_cf",
    "capex",
    "ebitda",
    "equity",
    "cash",
    "total_debt",
    "shares_outstanding",
]
# The charted multiples: P/E (GAAP diluted EPS), price / book, price / sales, price / free
# cash flow (operating cash flow + capex) and EV / EBITDA, each on the trailing twelve months.
MONTHLY_KEYS = ["pe", "pb", "ps", "pfcf", "ev_ebitda"]


def monthly_ratios(monthly: list[list], ttm_rows: list[dict]) -> dict:
    """The MONTHLY_KEYS multiples at every month-end close, against the trailing-twelve-month
    values (and the balance sheet) of the latest period published by that day, in the period's
    latest (corrected) version: a period counts from its first publication (the earnings
    release), with the figures as the company later restated them (Microsoft's 2016-17 under
    the new revenue standard, Pfizer's without the businesses it spun off), as data providers
    show history (#49)."""
    by_item: dict[str, list] = defaultdict(list)
    for r in ttm_rows:
        if r["item"] in MONTHLY_ITEMS and r["filed"] is not None:
            by_item[r["item"]].append((iso(r["filed"]), iso(r["period_end"]), f(r["value"])))
    for item, rows in by_item.items():
        rows.sort()
        first, latest = {}, {}
        for filed, end, value in rows:
            first.setdefault(end, filed)
            latest[end] = value
        by_item[item] = sorted((first[e], e, latest[e]) for e in first)
    pos = dict.fromkeys(MONTHLY_ITEMS, 0)
    best: dict[str, tuple | None] = dict.fromkeys(MONTHLY_ITEMS)
    out: dict[str, list] = defaultdict(list)
    for row in monthly:
        month, close, day = row[0], row[1], row[2] if len(row) > 2 else row[0]
        g = {}
        for item in MONTHLY_ITEMS:
            rows = by_item.get(item, [])
            while pos[item] < len(rows) and rows[pos[item]][0] <= day:
                filed, end, value = rows[pos[item]]
                b = best[item]
                if b is None or (end, filed) >= (b[0], b[1]):
                    best[item] = (end, filed, value)
                pos[item] += 1
            g[item] = best[item][2] if best[item] else None
        shares = g["shares_outstanding"]
        cap = close * shares if close is not None and shares is not None else None
        out["month"].append(month[:7])
        out["close"].append(r6(close))
        out["pe"].append(r6(pos_div(close, pe_eps(g))))
        out["pb"].append(r6(pos_div(cap, g["equity"])))
        out["ps"].append(r6(pos_div(cap, g["revenue"])))
        out["pfcf"].append(r6(pos_div(cap, add(g["operating_cf"], g["capex"]))))
        # enterprise value = market value + total debt - cash
        net_debt = add(g["total_debt"], -(g["cash"] or 0)) if g["total_debt"] is not None else None
        out["ev_ebitda"].append(r6(pos_div(add(cap, net_debt), g["ebitda"])))
    # start at the first month with any multiple
    keys = MONTHLY_KEYS
    first = next(
        (i for i in range(len(out["month"])) if any(out[k][i] is not None for k in keys)),
        len(out["month"]),
    )
    res = {k: v[first:] for k, v in out.items()}
    # the monthly chart's own marks: the same rule over the last `history_years` of months
    span, pct = SETTINGS["history_years"] * 12, SETTINGS["cheap_percentile"]
    need = SETTINGS["min_history_years"] * 12
    bands = {}
    for key in keys:
        vals = [v for v in res[key][-span:] if v is not None and v > 0]
        if not vals:
            continue
        band = {"median": r6(median(vals)), "low": r6(min(vals)), "high": r6(max(vals))}
        band["months"] = len(vals)
        if len(vals) >= need:
            band["cheap"] = r6(quantile(vals, pct))
        bands[key] = band
    res["bands"] = bands
    return res


def growth(a: dict) -> dict:
    """Compound annual growth of revenue, EPS, FCF and shares over 3, 5 and 10 years."""
    out = {}
    years = a["years"]
    fcf = [add(o, c) for o, c in zip(a["items"]["operating_cf"], a["items"]["capex"], strict=True)]
    series = {
        "revenue": a["items"]["revenue"],
        "eps": a["items"]["eps_diluted"],
        "fcf": fcf,
        "shares": a["items"]["shares_outstanding"],
    }
    for name, values in series.items():
        for span in (3, 5, 10):
            if len(years) > span:
                out[f"{name}_{span}y"] = r6(cagr(values[-1 - span], values[-1], span))
    return out


# --- prices ---------------------------------------------------------------------------


def sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's relative strength index."""
    if len(closes) <= n:
        return None
    gains = [max(b - a, 0) for a, b in zip(closes, closes[1:], strict=False)]
    losses = [max(a - b, 0) for a, b in zip(closes, closes[1:], strict=False)]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    for g, l_ in zip(gains[n:], losses[n:], strict=True):
        ag, al = (ag * (n - 1) + g) / n, (al * (n - 1) + l_) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def technicals(daily: list[list], weekly: list[list]) -> dict:
    closes = [c for _, c, _ in daily if c is not None]
    last = closes[-1] if closes else None
    year = [c for d, c, _ in daily if c is not None and d >= iso_days_before(daily, 365)]
    volumes = [v for _, _, v in daily if v]
    out = {
        "sma20": r6(sma(closes, 20)),
        "sma50": r6(sma(closes, 50)),
        "sma200": r6(sma(closes, 200)),
        "rsi14": r6(rsi(closes)),
        "high52": r6(max(year)) if year else None,
        "low52": r6(min(year)) if year else None,
        "volume": volumes[-1] if volumes else None,
        "avg_volume_3m": round(sum(volumes[-63:]) / len(volumes[-63:])) if volumes else None,
    }
    # 12-1 momentum: the return from a year ago to a month ago (weekly closes).
    if len(weekly) >= 53 and weekly[-53][1] and weekly[-5][1]:
        out["momentum_12_1"] = r6(weekly[-5][1] / weekly[-53][1] - 1)
    # Total return (dividends reinvested) from the weekly adjusted close.
    if weekly:
        end_day, _, end_adj = weekly[-1]
        for span in (1, 3, 5, 10):
            start = shift_years(end_day, -span)
            past = [w for w in weekly if w[0] <= start]
            if past and past[-1][2] and end_adj:
                total = end_adj / past[-1][2]
                out[f"return_{span}y"] = r6(total ** (1 / span) - 1 if span > 1 else total - 1)
    out["last"] = r6(last)
    return out


def iso_days_before(daily: list[list], days: int) -> str:
    if not daily:
        return ""
    end = dt.date.fromisoformat(daily[-1][0])
    return (end - dt.timedelta(days=days)).isoformat()


def shift_years(day: str, years: int) -> str:
    d = dt.date.fromisoformat(day)
    try:
        return d.replace(year=d.year + years).isoformat()
    except ValueError:  # 29 February
        return d.replace(year=d.year + years, day=28).isoformat()


# --- dividends, earnings, screener, valuation -----------------------------------------


def dividends(rows: list[dict], asof: str | None, price: float | None, eps_ttm) -> dict:
    paid = [[iso(r["date"]), f(r["dividend"])] for r in rows if f(r["dividend"])]
    if not paid:
        return {}
    by_year: dict[int, float] = defaultdict(float)
    for d, v in paid:
        by_year[int(d[:4])] += v
    end = asof or paid[-1][0]
    start = (dt.date.fromisoformat(end) - dt.timedelta(days=365)).isoformat()
    ttm = sum(v for d, v in paid if start < d <= end)
    years = sorted(by_year)
    this_year = int(end[:4])
    full = [y for y in years if y < this_year]
    streak = 0  # years in a row (up to last year) with a higher total than the year before
    for y in reversed(full):
        if y - 1 in by_year and by_year[y] > by_year[y - 1]:
            streak += 1
        else:
            break
    last_year = [d for d, _ in paid if start < d <= end]
    return {
        "last": paid[-1],
        "per_year_count": len(last_year),  # 4 = quarterly, 12 = monthly
        "per_year": [[y, r6(by_year[y])] for y in years],
        "partial_year": this_year if this_year in by_year else None,
        "recent": paid[-12:],
        "ttm": r6(ttm),
        "yield": r6(div(ttm, price)),
        "payout": r6(pos_div(ttm, eps_ttm)),
        "growth_streak": streak,
        "cagr_5y": r6(cagr(by_year.get(full[-6]), by_year.get(full[-1]), 5))
        if len(full) >= 6
        else None,
    }


def earnings(rows: list[dict], today: str) -> dict:
    hist = [
        [iso(r["report_date"]), r6(r["eps_estimate"]), r6(r["eps_reported"]), r6(r["surprise_pct"])]
        for r in sorted(rows, key=lambda r: iso(r["report_date"]))
    ]
    done = [h for h in hist if h[2] is not None]
    nxt = next((h for h in hist if h[2] is None and h[0] >= today), None)
    beats = [h for h in done[-12:] if h[3] is not None]
    return {
        "history": done[-40:],
        "next": {"date": nxt[0], "eps_estimate": nxt[1]} if nxt else None,
        "beat_rate": r6(sum(1 for h in beats if h[3] > 0) / len(beats)) if beats else None,
    }


def screener(rows: list[dict]) -> dict:
    out = {}
    for r in rows:
        detail = json.loads(r["detail_json"]) if r.get("detail_json") else {}
        keep = STAGE1_KEEP if int(r["stage"]) == 1 else STAGE2_KEEP
        entry = {
            "run_date": iso(r["run_date"]),
            "category": r.get("category"),
            "status": r.get("status"),
            "rank_in_sector": r.get("rank_in_sector"),
            "cheap_price": r6(r.get("cheap_price")),
        }
        for k in keep:
            v = detail.get(k)
            entry[k] = r6(v) if isinstance(v, int | float) and not isinstance(v, bool) else v
        out[f"stage{int(r['stage'])}"] = {k: v for k, v in entry.items() if v not in (None, "")}
    return out


def valuation(snap: dict, ratios_by_year: dict, vals: list[dict], stage2: dict | None) -> dict:
    eps, bvps, price = snap.get("eps_diluted"), snap.get("book_per_share"), snap.get("price")
    graham = None
    if eps and bvps and eps > 0 and bvps > 0:
        graham = math.sqrt(22.5 * eps * bvps)
    pes = [p for p in ratios_by_year.get("pe", [])[-10:] if p is not None]
    pe_med, pe_low = median(pes), (min(pes) if pes else None)
    out = {
        "graham_number": r6(graham),
        "pe_now": r6(pos_div(price, eps)),
        "pe_median_10y": r6(pe_med),
        "pe_low_10y": r6(pe_low),
        "pe_years": len(pes),
        "price_at_median_pe": r6(pe_med * eps) if pe_med and eps and eps > 0 else None,
        "price_at_low_pe": r6(pe_low * eps) if pe_low and eps and eps > 0 else None,
        "dcf": [
            {
                "method": v["method"],
                "as_of": iso(v["as_of"]),
                "fair_value": r6(v["fair_value"]),
                "price": r6(v["price"]),
            }
            for v in vals
        ],
    }
    if stage2:
        out["cheap_pe"] = stage2.get("cheap_pe")
        out["cheap_price"] = stage2.get("cheap_price")
    return out


# --- one ticker -----------------------------------------------------------------------


def snapshot(ttm_rows: list[dict], price: float | None) -> dict:
    """The absolute values now: flows over the trailing twelve months, the balance sheet at
    the latest quarter end, the market value at the latest close."""
    s: dict = {i: None for i in FLOWS + INSTANTS}
    ends = []
    for r in ttm_rows:
        if r["item"] in s:
            s[r["item"]] = f(r["value"])
            ends.append(iso(r["period_end"]))
    s["price"] = f(price)
    shares = s["shares_outstanding"]
    s["market_cap"] = price * shares if price and shares else None
    s["free_cf"] = add(s["operating_cf"], s["capex"])
    s["net_debt"] = add(s["total_debt"], -(s["cash"] or 0)) if s["total_debt"] is not None else None
    s["enterprise_value"] = add(s["market_cap"], s["net_debt"])
    s["book_per_share"] = div(s["equity"], shares)
    s["period_end"] = max(ends) if ends else None
    return s


def ratios(s: dict) -> dict:
    cap, ev = s["market_cap"], s["enterprise_value"]
    return {
        "pe": pos_div(s["price"], pe_eps(s)),
        "ps": pos_div(cap, s["revenue"]),
        "pb": pos_div(cap, s["equity"]),
        "ev_ebitda": pos_div(ev, s["ebitda"]),
        "ev_revenue": pos_div(ev, s["revenue"]),
        "pfcf": pos_div(cap, s["free_cf"]),
        "fcf_yield": div(s["free_cf"], cap),
        "earnings_yield": div(s["net_income"], cap),
        "operating_margin": div(s["operating_income"], s["revenue"]),
        "ebitda_margin": div(s["ebitda"], s["revenue"]),
        "net_margin": div(s["net_income"], s["revenue"]),
        "fcf_margin": div(s["free_cf"], s["revenue"]),
        "roe": pos_div(s["net_income"], s["equity"]),
        "roa": div(s["net_income"], s["total_assets"]),
        "debt_to_equity": pos_div(s["total_debt"], s["equity"]),
        "debt_to_assets": div(s["total_debt"], s["total_assets"]),
        "net_debt_to_ebitda": div(s["net_debt"], s["ebitda"]),
        "interest_cover": pos_div(s["ebitda"], s["interest_expense"]),
        "cash_to_short_term_debt": pos_div(s["cash"], s["short_term_debt"]),
        "capex_to_ocf": div(-(s["capex"] or 0), s["operating_cf"]) if s["capex"] else None,
    }


def ticker(sym: str, g: dict, today: str) -> dict:
    """Everything the explorer page shows for one company."""
    c = g["company"]
    weekly = [[iso(r["date"]), r6(r["close"]), r6(r["adj_close"])] for r in g["weekly"]]
    daily = [[iso(r["date"]), r6(r["close"]), r["volume"]] for r in g["daily"]]
    last = daily[-1] if daily else (weekly[-1] if weekly else None)
    asof, price = (last[0], last[1]) if last else (None, None)
    snap = snapshot(g["ttm"], price)
    monthly = [[iso(r["month"]), r6(r["close"]), iso(r["day"])] for r in g["monthly"]]
    a = annual(g["fundamentals"])
    by_year = annual_ratios(a, weekly)
    hist = ratio_history(a, monthly)
    hist["monthly"] = monthly_ratios(monthly, g["ttm_history"])
    scr = screener(g["screener"])
    data = {
        "symbol": sym,
        "asof": asof,
        "built": today,
        "profile": {
            "name": c.get("name"),
            "sector": c.get("sector"),
            "industry": c.get("industry"),
            "exchange": c.get("exchange"),
            "currency": c.get("currency"),
            "cik": c.get("cik"),
            "sp500_since": iso(c.get("sp500_since")),
            "watchlist": g["watch"],
        },
        "snapshot": {k: (r6(v) if k != "period_end" else v) for k, v in snap.items()},
        "ratios": {k: r6(v) for k, v in ratios(snap).items()},
        "growth": growth(a),
        "annual": a,
        "annual_ratios": by_year,
        "ratio_history": hist,
        "quarterly": quarterly(g["fundamentals"]),
        "prices": {"weekly": weekly, "daily": daily},
        "technicals": technicals(daily, weekly),
        "dividends": dividends(g["dividends"], asof, price, snap["eps_diluted"]),
        "earnings": earnings(g["earnings"], today),
        "screener": scr,
        # the own P/E history on the yearly average price, as the ratio charts and Stage 2
        "valuation": valuation(
            snap, {"pe": hist["series"]["pe"]}, g["valuations"], scr.get("stage2")
        ),
    }
    return data


def index_row(t: dict) -> dict:
    s, r, gr = t["snapshot"], t["ratios"], t["growth"]
    s1 = t["screener"].get("stage1", {})
    s2 = t["screener"].get("stage2", {})
    nxt = t["earnings"].get("next") or {}
    hist = t["earnings"].get("history") or []
    return {
        "symbol": t["symbol"],
        "name": t["profile"]["name"],
        "sector": t["profile"]["sector"],
        "industry": t["profile"]["industry"],
        "watchlist": t["profile"]["watchlist"],
        "asof": t["asof"],
        "price": s["price"],
        "market_cap": s["market_cap"],
        "revenue": s["revenue"],
        "net_income": s["net_income"],
        "free_cf": s["free_cf"],
        "net_debt": s["net_debt"],
        "pe": r["pe"],
        "ps": r["ps"],
        "pb": r["pb"],
        "ev_ebitda": r["ev_ebitda"],
        "fcf_yield": r["fcf_yield"],
        "net_margin": r["net_margin"],
        "roe": r["roe"],
        "net_debt_to_ebitda": r["net_debt_to_ebitda"],
        "div_yield": t["dividends"].get("yield"),
        "revenue_5y": gr.get("revenue_5y"),
        "eps_5y": gr.get("eps_5y"),
        "return_1y": t["technicals"].get("return_1y"),
        "category": s1.get("category"),
        "stage1": s1.get("status"),
        "stage2_rank": s2.get("rank_in_sector"),
        "piotroski": s1.get("piotroski_f_score_ttm"),
        "next_earnings": nxt.get("date"),
        "next_eps_estimate": nxt.get("eps_estimate"),
        "last_surprise": hist[-1][3] if hist else None,
    }


def export(out: Path, query=None, symbols: list[str] | None = None, today: str | None = None):
    """Write tickers/*.json under `out`. Returns the index rows."""
    query = query or backend()
    today = today or dt.date.today().isoformat()
    raw = fetch(query, symbols)
    by = {k: group(v) for k, v in raw.items() if k not in ("companies", "watchlist")}
    watch = {r["symbol"] for r in raw["watchlist"]}
    folder = out / "tickers"
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for c in raw["companies"]:
        sym = c["symbol"]
        if not SYMBOL.match(sym or ""):
            continue
        g = {k: v.get(sym, []) for k, v in by.items()}
        g["company"], g["watch"] = c, sym in watch
        t = ticker(sym, g, today)
        (folder / f"{sym}.json").write_text(
            json.dumps(t, separators=(",", ":"), allow_nan=False), encoding="utf-8"
        )
        index.append(index_row(t))
    asof = max((r["asof"] for r in index if r["asof"]), default=None)
    (folder / "index.json").write_text(
        json.dumps(
            {"built": today, "asof": asof, "tickers": index},
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    return {"built": today, "asof": asof, "tickers": index}


def main(argv: list[str]) -> None:
    args = [a for a in argv if not a.startswith("--")]
    symbols = None
    if "--symbols" in argv:
        symbols = [s.strip().upper() for s in argv[argv.index("--symbols") + 1].split(",")]
        args = [a for a in args if a != argv[argv.index("--symbols") + 1]]
    out = Path(args[0]) if args else ROOT / "_site"
    idx = export(out, symbols=symbols)
    print(f"{len(idx['tickers'])} tickers, data as of {idx['asof']}, in {out / 'tickers'}")


if __name__ == "__main__":
    main(sys.argv[1:])
