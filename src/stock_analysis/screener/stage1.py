"""Stage 1 of the market screener: good financial statements.

Finds the companies worth owning, before any thought of price. Settings in
config/screeners.toml; every rule, threshold and source is explained in docs/SCREENER.md
and the methods doc.

  1. Universe: the members of `[universe] index` (the S&P 500), from the newest TradingView
     snapshot the ingest job stored in the database (current figures, 20 years of yearly
     EPS, revenue, EBITDA and dividends; v_tv_latest). Market values converted to US
     dollars at the ECB rates in the database.
  2. Gap filling: debt, cash, EBITDA and interest figures TradingView leaves blank are
     filled from the database's core values (SEC filings, Yahoo for gaps) where it has
     them. Each filled value is named in `filled`.
  3. Peter Lynch's category (One Up on Wall Street, ch. 7): turnaround, cyclical, asset
     play, fast grower, stalwart or slow grower, from the EPS history, industry and
     balance sheet.
  4. Rules: banks, insurers and REITs get rules for their kind of business; every other
     company gets the rules of its Lynch category (utilities without the Altman score).
     A stock must pass every rule. Missing data = "incomplete", not a pass.

Nothing is downloaded and nothing is written here: stock_analysis.screener.run runs both stages
and saves the run in the database (out_screener_run, out_screener_result).

Usage: uv run python -m stock_analysis.screener.stage1      # print Stage 1's counts
"""

from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from .. import stocks, tradingview
from .common import ABSOLUTE, load_config, to_usd

# The TradingView fields the screener reads (stored by the ingest with every snapshot).
COLUMNS = tradingview.SCREENER_FIELDS
# Columns of raw_tv_constituent under the screener's (TradingView's) names
TV_RENAME = {"symbol": "name", "name": "description", "market_cap": "market_cap_basic"}
MARKET, REGION = "america", "US"  # the ingest's TradingView market


# --- configuration -------------------------------------------------------------------


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


def fetch_universe(cfg: dict, data) -> pd.DataFrame:
    """The index members of the newest TradingView snapshot in the database, one row per
    TradingView symbol with the screener's fields."""
    universe = cfg.get("universe", {})
    index = universe.get("index", "")
    if not index:
        raise RuntimeError(
            "The screener's universe is the ingest's: set [universe] index to the index of "
            "config/ingest.toml (the database has no snapshot of whole markets)."
        )
    raw = data.sql(
        "SELECT tv_symbol, symbol, name, exchange, sector, industry, country, currency, "
        f"market_cap, fetched_at, extra_json FROM v_tv_latest WHERE request_key = '{index}'"
    )
    if raw.empty:
        raise RuntimeError(f"No TradingView snapshot of {index} in the database yet")
    extra = pd.DataFrame([json.loads(x) if x else {} for x in raw["extra_json"]])
    d = raw.drop(columns=["extra_json", "fetched_at"]).rename(columns=TV_RENAME)
    extra = extra[[c for c in extra.columns if c not in d.columns]]
    d = pd.concat([d.reset_index(drop=True), extra.reset_index(drop=True)], axis=1)
    missing = [c for c in COLUMNS if c not in d.columns and c != "indexes"]
    if missing:
        raise RuntimeError(
            f"The TradingView snapshot of {raw['fetched_at'].max()} lacks {missing[:5]}: the "
            "ingest stores them from its next run (tradingview source)"
        )
    d["market"], d["region"] = MARKET, REGION
    d.attrs["snapshot"] = str(raw["fetched_at"].max())
    return d.set_index("tv_symbol")


def in_index(indexes: pd.Series, proname: str) -> pd.Series:
    """True where TradingView lists the stock in the index (e.g. "SP:SPX", the S&P 500)."""
    return indexes.map(
        lambda v: isinstance(v, list) and any(i.get("proname") == proname for i in v)
    )


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


GROWTH_HISTORY = (("total_revenue_fy_h", "revenue"), ("earnings_per_share_diluted_fy_h", "eps"))


def growth_stats(history: pd.Series, years: int) -> tuple[pd.Series, pd.Series]:
    """Average and median yearly growth over `years` years (blank under 3 changes)."""
    g = history.map(lambda v: yearly_growth(v, years))
    avg = g.map(lambda x: float(np.mean(x)) if len(x) >= 3 else np.nan).astype(float)
    med = g.map(lambda x: float(np.median(x)) if len(x) >= 3 else np.nan).astype(float)
    return avg, med


def prepare(raw: pd.DataFrame, cfg: dict, fx: dict[str, float]) -> pd.DataFrame:
    """Convert to US dollars, derive ratios and pick each company's screener."""
    d = raw.copy()
    d["symbol"] = d["name"]  # the database's symbol (TradingView's ticker)
    d["fx_fund"] = d["fundamental_currency_code"].map(fx)  # USD per unit of statements
    d["fx_price"] = d["currency"].map(fx)  # USD per unit of price
    d = d[d["fx_fund"].notna() & d["fx_price"].notna()].copy()
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
    for col, key in GROWTH_HISTORY:
        d[f"{key}_growth_avg"], d[f"{key}_growth_median"] = growth_stats(d[col], years)
        d[f"{key}_growth_years"] = d[col].map(lambda v: len(yearly_growth(v, years)))
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
    d["ebitda_avg_10y"] = avg_ebitda
    d["net_debt_to_avg_ebitda"] = (d["net_debt_fq"] / avg_ebitda).where(avg_ebitda > 0)
    d["net_cash_to_cap"] = -d["net_debt_fq"] / d["market_cap_basic"]
    d["debt_to_equity"] = d["debt_to_equity_fq"]
    total = d["total_debt_fq"]
    d["cash_to_total_debt"] = np.where(total == 0, np.inf, d["cash_n_short_term_invest_fq"] / total)
    d.loc[total.isna() | d["cash_n_short_term_invest_fq"].isna(), "cash_to_total_debt"] = np.nan


CATEGORIES = ["turnaround", "cyclical", "asset_play", "fast_grower", "stalwart", "slow_grower"]


def lynch_category(d: pd.DataFrame, lynch: dict) -> pd.Series:
    """Peter Lynch's six categories (One Up on Wall Street, ch. 7), tested in order.

    0. "no_profit": no profit in any of the last 5 fiscal years. Not one of Lynch's
       categories; he skipped such companies ("avoid long shots"), so Stage 1 fails them.
    1. cyclical by industry (autos, airlines, steel, chemicals, oil...)
    2. turnaround: profitable in the last 5 years but losing money now, or EPS (both 12
       months and the latest fiscal year) less than half its 5-year peak
    3. cyclical by history: EPS fell sharply in several of the last 10 years, and the
       company isn't a fast grower
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
        ((d["price_book_fq"] > 0) & (d["price_book_fq"] < lynch["asset_price_to_book"]))
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


# --- step 2: fill gaps from the database ---------------------------------------------

GAP_FIELDS = {  # TradingView field -> core item
    "short_term_debt_fq": "short_term_debt",
    "long_term_debt_fq": "long_term_debt",
    "cash_n_short_term_invest_fq": "cash",
    "ebitda_ttm": "ebitda",
    "total_debt_fq": "total_debt",
}


def fill_gaps(d: pd.DataFrame, data) -> pd.DataFrame:
    """Fill debt, cash, EBITDA and interest cover from the database's core values (the
    latest twelve months) for stocks whose screener needs them."""
    debt_types = d["type"].isin(["general", "utilities", "reits"])
    need = d[list(GAP_FIELDS)].isna().any(axis=1) | (
        d["interest_cover"].isna() & ~d["net_cash"].fillna(False)
    )
    todo = d[debt_types & need & d["symbol"].notna()]
    got = stocks.ttm(data, todo["symbol"].unique()) if len(todo) else pd.DataFrame()
    for idx, row in todo.iterrows():
        if row["symbol"] not in got.index:
            continue
        y = got.loc[row["symbol"]]
        fx = row["fx_fund"]  # core values are in US dollars, TradingView's in its own currency
        for f, item in GAP_FIELDS.items():
            if pd.isna(row[f]) and pd.notna(y.get(item)):
                d.loc[idx, f] = float(y[item]) / fx
                d.loc[idx, "filled"] += f"{f} (database); "
        interest = y.get("interest_expense")
        if pd.isna(row["interest_cover"]) and pd.notna(interest) and interest:
            ebitda = d.loc[idx, "ebitda_ttm"]
            if pd.notna(ebitda):
                d.loc[idx, "ebitda_interst_cover_ttm"] = ebitda / (abs(float(interest)) / fx)
                d.loc[idx, "filled"] += "interest cover (database); "
    if "net_debt_fq" in d:
        gap = d["net_debt_fq"].isna() & d["total_debt_fq"].notna()
        gap &= d["cash_n_short_term_invest_fq"].notna()
        d.loc[gap, "net_debt_fq"] = (
            d.loc[gap, "total_debt_fq"] - d.loc[gap, "cash_n_short_term_invest_fq"]
        )
        d.loc[gap, "filled"] += "net debt (total debt minus cash); "
    # the database may have filled total and long-term debt but not short-term debt
    derive_short_term_debt(d)
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
        for col, key in GROWTH_HISTORY:
            # over the rule's own number of years when the history lists are at hand
            if col in d:
                avg, med = growth_stats(d[col], int(value))
            else:
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
        s = d["debt_to_equity"].where(d["debt_to_equity"] >= 0)
        r = cmp(s, s <= value)
        # TradingView leaves debt/equity blank when equity is negative, mostly from years
        # of buybacks (Booking, McDonald's). There the ratio means nothing: judge the debt
        # against EBITDA instead, at S&P's "modest" level (2x)
        if "total_equity_fq" in d:
            equity = d["total_equity_fq"]
            negative = (equity < 0) | (equity.isna() & d["price_book_fq"].isna())
        else:
            negative = d["price_book_fq"].isna()
        neg = s.isna() & negative & (d["total_debt_fq"] > 0)
        nd = d["net_debt_to_ebitda"]
        r[neg] = cmp(nd, nd <= NEGATIVE_EQUITY_MAX_NET_DEBT_TO_EBITDA)[neg]
        if "ebitda_ttm" in d:  # negative equity and no EBITDA to carry the debt
            r[neg & (d["ebitda_ttm"] <= 0)] = False
        r[net_cash] = True
        return r
    if name == "min_eps_growth_3y":
        s = d["eps_growth_3y"]
        return cmp(s, s >= value)
    if name == "max_net_debt_to_avg_ebitda":
        s = d["net_debt_to_avg_ebitda"]
        r = cmp(s, s <= value)
        if "ebitda_avg_10y" in d:  # no EBITDA on average over the cycle: fails, as above
            r[(d["ebitda_avg_10y"] <= 0) & ~net_cash] = False
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
    "cash_to_total_debt",
    "net_cash_to_cap",
    "interest_cover",
    "debt_to_equity",
    "price_book_fq",
    "return_on_equity_fq",
    "revenue_growth_median",
    "eps_growth_median",
    "eps_growth_3y",
    "eps_vs_5y_peak",
    "loss_now",
    "no_profit_5y",
    "eps_big_drops_10y",
    "eps_avg_10y",
    "recession_eps_change",
    "dividend_years_10y",
    "dividend_payout_ratio_ttm",
    "piotroski_f_score_ttm",
    "altman_z_score_ttm",
]


def run(cfg: dict, data=None) -> pd.DataFrame:
    data = data or stocks.default_data()
    d = prepare(fetch_universe(cfg, data), cfg, stocks.fx_rates(data))
    d = fill_gaps(d, data)
    return apply_screeners(d, cfg)


def counts(d: pd.DataFrame, by: str) -> pd.DataFrame:
    """Companies screened and passed, per `by` (sector or category) and region."""
    g = d.groupby([by, "region"])["status"]
    out = pd.DataFrame({"screened": g.size(), "passed": g.apply(lambda s: (s == "pass").sum())})
    return out.unstack("region", fill_value=0)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    d = run(load_config())
    pd.set_option("display.width", 250)
    print("Stage 1: good financial statements")
    print(counts(d, "category").to_string())
    print()
    print(counts(d, "sector").to_string())
    print(f"\n{(d['status'] == 'pass').sum()} of {len(d)} pass (nothing saved)")


if __name__ == "__main__":
    main()
