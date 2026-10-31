"""The growth screener: growing revenue, growing profit, high margin, historically low P/E.

A separate screener from the two-stage market screener (analysis/screener.py), for testing
an idea (Babak, 2026-10-31). Settings in `[growth]` of config/screeners.toml; rules and
results in report 15.

  1. Universe: the same as the market screener (`[universe]`, the S&P 500 for now), from
     TradingView: current figures and 20 years of yearly revenue, net income and EPS.
  2. Filter (Babak: "first filter with the growth ... and then, based on what's left,
     apply the P/E"), over the last `years` (5) fiscal years:
       - revenue: compound growth above 0, up in at least 4 of the 5 years
       - net income: compound growth above 0, up in at least 3 of the 5 years, a profit in
         all 6 years
       - diluted EPS: compound growth above 0
       - net margin (12 months) above its sector's average (10% in sectors of under 5)
       - still growing: 12-month revenue and net income not below the latest fiscal year
     Missing data = "incomplete", not a pass. The price plays no part in this step.
  3. Ranking, only of what step 2 left: today's P/E against the stock's own P/E history
     (yearly P/E over up to 10 fiscal years: average monthly price over the year / that
     year's diluted EPS, the same
     history as Stage 2, without yearly P/Es above `max_history_pe`). Lowest first.
     Stocks with fewer than `min_history_years` years of P/E history are listed after the
     ranked ones. Flags (not rules) mark a likely one-off gain and lumpy profit.
  4. Backtest (--backtest): the same rules on each past fiscal year's figures, bought at
     the end of April the year after (when every annual report is out), and the price
     return of the top names against all screened stocks and the S&P 500.

Writes data/screener/growth.csv (every company: measures, status, failed rules, P/E
against its own history, rank) and with --backtest data/screener/growth_backtest.csv.

Usage:
    uv run python analysis/growth_screen.py              # today's list
    uv run python analysis/growth_screen.py --backtest   # and the test on past years
    uv run python analysis/growth_screen.py --all        # every US and European company
                                                         # above $1bn instead of [universe]
"""

from __future__ import annotations

import argparse
import copy
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from stock_analysis import ecb

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage1  # noqa: E402
import stage2  # noqa: E402
from screen_common import ABSOLUTE, OUT, load_config  # noqa: E402

HISTORY = [
    "fiscal_period_fy_h",
    "total_revenue_fy_h",
    "net_income_fy_h",
    "earnings_per_share_diluted_fy_h",
]
# Price history long enough for 10 years of P/E before the earliest backtest year
PRICE_YEARS = 19
INDEX_SYMBOL = "^GSPC"


# --- growth measures -----------------------------------------------------------------


def window(values, n: int) -> list[float] | None:
    """The newest n+1 entries of a newest-first list; None if any is missing."""
    if not isinstance(values, list | tuple) or len(values) < n + 1:
        return None
    v = values[: n + 1]
    if any(x is None or (isinstance(x, float) and np.isnan(x)) for x in v):
        return None
    return [float(x) for x in v]


def cagr(values, n: int) -> float:
    """Compound yearly growth from n years back to the latest; blank unless both > 0."""
    v = window(values, n)
    if v is None or v[0] <= 0 or v[n] <= 0:
        return np.nan
    return (v[0] / v[n]) ** (1 / n) - 1


def up_years(values, n: int) -> float:
    """In how many of the last n years the figure rose; blank if a year is missing."""
    v = window(values, n)
    if v is None:
        return np.nan
    return float(sum(1 for new, old in zip(v, v[1:], strict=False) if new > old))


def positive_years(values, n: int) -> float:
    v = window(values, n)
    return np.nan if v is None else float(sum(1 for x in v if x > 0))


def as_of_year(d: pd.DataFrame, year: int) -> pd.DataFrame:
    """The yearly history lists cut so that fiscal year `year` is the latest.

    Rows that have no fiscal year `year` get empty lists (and so "incomplete").
    """
    d = d.copy()
    cut = []
    for years in d["fiscal_period_fy_h"]:
        ys = [int(y) if y is not None else None for y in years] if isinstance(years, list) else []
        cut.append(ys.index(year) if year in ys else None)
    for col in HISTORY:
        d[col] = [
            list(v[k:]) if k is not None and isinstance(v, list) else []
            for v, k in zip(d[col], cut, strict=False)
        ]
    d["years_back"] = cut
    return d


def growth_measures(d: pd.DataFrame, n: int) -> None:
    rev, ni, eps = (
        d["total_revenue_fy_h"],
        d["net_income_fy_h"],
        d["earnings_per_share_diluted_fy_h"],
    )
    d["revenue_cagr"] = rev.map(lambda v: cagr(v, n))
    d["revenue_up_years"] = rev.map(lambda v: up_years(v, n))
    d["net_income_cagr"] = ni.map(lambda v: cagr(v, n))
    d["net_income_up_years"] = ni.map(lambda v: up_years(v, n))
    d["net_income_positive_years"] = ni.map(lambda v: positive_years(v, n))
    d["eps_cagr"] = eps.map(lambda v: cagr(v, n))
    d["eps_cagr_3y"] = eps.map(lambda v: cagr(v, 3))
    first = lambda v, i: window(v, n)[i] if window(v, n) else np.nan  # noqa: E731
    rev0, revn = rev.map(lambda v: first(v, 0)), rev.map(lambda v: first(v, n))
    ni0, nin = ni.map(lambda v: first(v, 0)), ni.map(lambda v: first(v, n))
    d["net_margin_fy"] = (ni0 / rev0).where(rev0 > 0)
    d["net_margin_fy_start"] = (nin / revn).where(revn > 0)
    d["net_margin_change"] = d["net_margin_fy"] - d["net_margin_fy_start"]
    d["revenue_fy"], d["net_income_fy"] = rev0, ni0


def flags(d: pd.DataFrame, n: int, ttm: bool = True) -> None:
    """Warnings that don't fail a stock but change how far its P/E can be trusted.

    - 12-month net income more than 1.5x the latest fiscal year: often a one-off gain
      (a sale, a tax credit), which makes the P/E look lower than it is.
    - Net income fell more than 30% in one of the last n years: profit is lumpy (property
      sales at REITs, investment gains), so growth rates rest on the end points.
    """
    out = pd.Series("", index=d.index)
    if ttm:
        jump = d["net_income_ttm"] / d["net_income_fy"]
        out[(d["net_income_fy"] > 0) & (jump > 1.5)] += "12m profit 1.5x+ latest year (one-off?); "

    def big_drop(v) -> bool:
        x = window(v, n)
        return bool(x) and any(
            old > 0 and new / old - 1 < -0.30 for new, old in zip(x, x[1:], strict=False)
        )

    out[d["net_income_fy_h"].map(big_drop)] += "net income fell 30%+ in a year; "
    d["flags"] = out


def sector_margin(d: pd.DataFrame, min_size: int, stat: str = "mean") -> pd.Series:
    """Each company's sector average ("mean") or "median" net margin, blank for sectors
    with too few companies."""
    g = d.groupby("sector")["net_margin"]
    return g.transform(stat).where(g.transform("count") >= min_size)


# --- rules ---------------------------------------------------------------------------


def apply_rules(d: pd.DataFrame, g: dict, ttm: bool = True) -> None:
    """Status (pass / fail / incomplete) and the failed and missing rules.

    `ttm` = today's screen: margin on 12-month figures and the still-growing check. The
    backtest uses the fiscal-year margin and skips the still-growing check.
    """
    n = g["years"]
    d["net_margin"] = (
        (d["net_income_ttm"] / d["total_revenue_ttm"]).where(d["total_revenue_ttm"] > 0)
        if ttm
        else d["net_margin_fy"]
    )
    stat = g.get("sector_margin", "mean")
    if stat:
        d["sector_net_margin"] = sector_margin(d, g["min_sector_size"], stat)
        margin_floor = d["sector_net_margin"].fillna(g["min_net_margin"])
    else:
        d["sector_net_margin"] = np.nan
        margin_floor = pd.Series(g["min_net_margin"], index=d.index)
    d["margin_floor"] = margin_floor
    # A loss at either end leaves a compound rate blank: a fail, not missing data. Data is
    # missing only when a year of the history is.
    eps_have = d["earnings_per_share_diluted_fy_h"].map(lambda v: window(v, n) is not None)
    eps_have = eps_have.where(eps_have, np.nan)
    rules = {
        "revenue growth": (d["revenue_cagr"] > g["min_revenue_cagr"], d["revenue_up_years"]),
        "revenue up years": (
            d["revenue_up_years"] >= g["min_revenue_up_years"],
            d["revenue_up_years"],
        ),
        "net income growth": (
            d["net_income_cagr"] > g["min_net_income_cagr"],
            d["net_income_up_years"],
        ),
        "net income up years": (
            d["net_income_up_years"] >= g["min_net_income_up_years"],
            d["net_income_up_years"],
        ),
        "profit every year": (d["net_income_positive_years"] == n + 1, d["net_income_up_years"]),
        "EPS growth": (d["eps_cagr"] > g["min_eps_cagr"], eps_have),
        "net margin": (d["net_margin"] > margin_floor, d["net_margin"]),
    }
    if ttm and g.get("still_growing"):
        rules["still growing"] = (
            (d["total_revenue_ttm"] >= d["revenue_fy"])
            & (d["net_income_ttm"] >= d["net_income_fy"]),
            d["total_revenue_ttm"] + d["net_income_ttm"] + d["revenue_fy"] + d["net_income_fy"],
        )
    failed = pd.Series("", index=d.index)
    missing = pd.Series("", index=d.index)
    for name, (ok, have) in rules.items():
        have = have.notna()
        failed[have & ~ok.fillna(False).astype(bool)] += name + "; "
        missing[~have] += name + "; "
    d["failed"], d["missing"] = failed, missing
    d["status"] = np.where(failed != "", "fail", np.where(missing != "", "incomplete", "pass"))


# --- P/E against the stock's own history ---------------------------------------------


def own_pe(
    d: pd.DataFrame,
    rows: pd.Index,
    prices: pd.DataFrame,
    cfg: dict,
    entry: pd.Timestamp | None = None,
) -> None:
    """P/E now against the stock's own yearly P/E history, for the listed rows.

    Today's screen (entry None): P/E = price / 12-month diluted EPS. Backtest: P/E = the
    price at `entry` / the latest fiscal year's EPS, and only years before `entry` count.
    """
    n, need = cfg["history_years"], cfg["min_history_years"]
    cap = cfg["growth"].get("max_history_pe", np.inf)
    for c in ("pe_now", "pe_median", "pe_low", "pe_years", "pe_vs_median", "pe_percentile"):
        d[c] = np.nan
    for idx in rows:
        r = d.loc[idx]
        sym, years_h = r["yahoo"], r["fiscal_period_fy_h"]
        eps_h = r["earnings_per_share_diluted_fy_h"]
        if sym not in prices.columns or not eps_h:
            continue
        fy_end = pd.to_datetime(r["fiscal_period_end_fy"], unit="s", errors="coerce")
        if pd.isna(fy_end):
            continue
        px = prices[sym].dropna() * r["fx_price"] / r["fx_fund"]
        if entry is not None:
            fy_end -= pd.DateOffset(years=int(r.get("years_back") or 0))
            px = px[px.index <= entry]
            if px.empty or eps_h[0] is None or eps_h[0] <= 0:
                continue
            pe_now = float(px.iloc[-1]) / eps_h[0]
        else:
            if not r["eps"] > 0:
                continue
            pe_now = r["price_fund"] / r["eps"]
        h = stage2.fiscal_pe(px, eps_h, years_h, fy_end, n)["pe"].dropna()
        h = h[(h > 0) & (h <= cap)]
        d.loc[idx, ["pe_now", "pe_years"]] = [pe_now, len(h)]
        if len(h):
            med = float(h.median())
            d.loc[idx, ["pe_median", "pe_low", "pe_vs_median", "pe_percentile"]] = [
                med,
                float(h.min()),
                pe_now / med - 1,
                float((h < pe_now).mean()),
            ]
    d["pe_history_ok"] = d["pe_years"] >= need


def rank(d: pd.DataFrame) -> pd.DataFrame:
    """Passing stocks, lowest P/E against own history first; short histories last."""
    p = d[d["status"] == "pass"].copy()
    p["_short"] = ~p["pe_history_ok"].fillna(False).astype(bool)
    p = p.sort_values(["_short", "pe_vs_median"], na_position="last").drop(columns="_short")
    p["rank"] = range(1, len(p) + 1)
    return p


# --- run -----------------------------------------------------------------------------


def universe(cfg: dict, every: bool = False, refresh: bool = False) -> pd.DataFrame:
    if every:
        cfg = copy.deepcopy(cfg)
        cfg["universe"] = {"index": "", "regions": []}
    today = date.today().isoformat()
    return stage1.prepare(stage1.fetch_universe(cfg, today, refresh), cfg, ecb.usd_per_unit())


def screen_today(d: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    g = cfg["growth"]
    d = d.copy()
    growth_measures(d, g["years"])
    apply_rules(d, g, ttm=True)
    flags(d, g["years"])
    passed = d.index[d["status"] == "pass"]
    syms = d.loc[passed, "yahoo"].dropna().tolist()
    prices = stage2.monthly_prices(syms, date.today().isoformat(), PRICE_YEARS, "prices_long")
    own_pe(d, passed, prices, cfg)
    return d, rank(d)


def backtest(
    d: pd.DataFrame, cfg: dict, years: list[int], top: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Screen each past fiscal year, buy the top names at the end of April after it.

    Returns (each pick with its returns, a summary per year). Price returns in the
    trading currency (no dividends), 1 year after entry and to today. Benchmarks: the
    average of every screened stock with a price at entry, and the S&P 500 index.
    """
    g = cfg["growth"]
    syms = [*d["yahoo"].dropna().tolist(), INDEX_SYMBOL]
    prices = stage2.monthly_prices(syms, date.today().isoformat(), PRICE_YEARS, "prices_long")
    # Yahoo's monthly rows are dated the first of the month and close at its end
    last = prices.index.max()
    picks, summary = [], []
    for year in years:
        entry = pd.Timestamp(year + 1, 4, 1)
        exit_1y = pd.Timestamp(year + 2, 4, 1)
        h = as_of_year(d, year)
        growth_measures(h, g["years"])
        apply_rules(h, g, ttm=False)
        passed = h.index[h["status"] == "pass"]
        own_pe(h, passed, prices, cfg, entry=entry)
        ranked = rank(h)
        ranked = ranked[ranked["pe_history_ok"].fillna(False).astype(bool)]

        def ret(sym: str, end: pd.Timestamp, entry: pd.Timestamp = entry) -> float:
            if sym not in prices.columns or end > last:
                return np.nan
            s = prices[sym]
            a, b = s.get(entry, np.nan), s.get(end, np.nan)
            return b / a - 1 if a and a > 0 else np.nan

        def avg(symbols, end, ret=ret) -> float:
            return float(np.nanmean([ret(s, end) for s in symbols])) if len(symbols) else np.nan

        every = [s for s in h["yahoo"].dropna() if pd.notna(ret(s, last))]
        chosen = ranked.head(top)
        for idx, r in chosen.iterrows():
            picks.append(
                {
                    "fiscal_year": year,
                    "entry": f"{year + 1}-04-30",
                    "tv_symbol": idx,
                    "description": r["description"],
                    "sector": r["sector"],
                    "rank": r["rank"],
                    "revenue_cagr": r["revenue_cagr"],
                    "net_income_cagr": r["net_income_cagr"],
                    "eps_cagr": r["eps_cagr"],
                    "net_margin": r["net_margin"],
                    "pe_now": r["pe_now"],
                    "pe_median": r["pe_median"],
                    "pe_vs_median": r["pe_vs_median"],
                    "return_1y": ret(r["yahoo"], exit_1y),
                    "return_to_date": ret(r["yahoo"], last),
                }
            )
        summary.append(
            {
                "fiscal_year": year,
                "entry": f"{year + 1}-04-30",
                "passed": len(passed),
                "ranked": len(ranked),
                "picks": len(chosen),
                "picks_1y": avg(chosen["yahoo"].dropna().tolist(), exit_1y),
                "all_passed_1y": avg(h.loc[passed, "yahoo"].dropna().tolist(), exit_1y),
                "universe_1y": avg(every, exit_1y),
                "sp500_1y": ret(INDEX_SYMBOL, exit_1y),
                "picks_to_date": avg(chosen["yahoo"].dropna().tolist(), last),
                "all_passed_to_date": avg(h.loc[passed, "yahoo"].dropna().tolist(), last),
                "universe_to_date": avg(every, last),
                "sp500_to_date": ret(INDEX_SYMBOL, last),
            }
        )
    return pd.DataFrame(picks), pd.DataFrame(summary)


GROWTH = [
    "revenue_cagr",
    "revenue_up_years",
    "net_income_cagr",
    "net_income_up_years",
    "eps_cagr",
    "eps_cagr_3y",
    "net_margin",
    "sector_net_margin",
    "net_margin_change",
]
PE = ["pe_now", "pe_median", "pe_low", "pe_years", "pe_vs_median", "pe_percentile"]
SAVE = [
    "description",
    "region",
    "sector",
    "industry",
    "type",
    "status",
    "failed",
    "missing",
    "rank",
    "flags",
    *ABSOLUTE,
    *GROWTH,
    *PE,
]


def save(d: pd.DataFrame, ranked: pd.DataFrame) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    out = d.copy()
    out["rank"] = ranked["rank"]
    out = out.sort_values(["rank", "status", "cap_usd_bn"], ascending=[True, False, False])
    path = OUT / "growth.csv"
    out[SAVE].round(4).to_csv(path)
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backtest", action="store_true", help="also test on past fiscal years")
    ap.add_argument("--all", action="store_true", help="every US and European company > $1bn")
    ap.add_argument("--refresh", action="store_true", help="download again, ignore today's cache")
    args = ap.parse_args()
    cfg = load_config()
    g = cfg["growth"]
    base = universe(cfg, every=args.all, refresh=args.refresh)
    d, ranked = screen_today(base, cfg)
    path = save(d, ranked)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(f"Growth screener: {len(d)} companies")
    print(f"Step 1, filter on growth and margin (no P/E): {len(ranked)} pass")
    fails = d["failed"].str.split("; ").explode().loc[lambda s: s != ""].value_counts()
    print("Failed rules (a company can fail several):")
    print(fails.to_string())
    show = ranked.head(g["top"])
    print("\nAbsolute values ($bn, price and EPS in trading / statement currency)")
    print(show[["description", *ABSOLUTE]].round(2).to_string())
    print(f"\nStep 2, P/E against own history on the {len(ranked)} survivors (lowest first)")
    print(show[["description", "sector", *GROWTH, *PE]].round(3).to_string())
    flagged = show[show["flags"] != ""]
    if len(flagged):
        print("\nFlags (not rules: check before trusting the P/E)")
        print(flagged[["description", "flags"]].to_string())
    print(f"\nSaved {path.relative_to(stage1.OUT.parent.parent)}")

    if args.backtest:
        latest = int(pd.Series([v[0] for v in base["fiscal_period_fy_h"] if v]).mode()[0])
        years = list(range(latest - 6, latest))
        picks, summary = backtest(base, cfg, years, top=10)
        picks.round(4).to_csv(OUT / "growth_backtest.csv", index=False)
        print("\nBacktest: top 10 per fiscal year, bought at the end of April after it")
        print(summary.round(3).to_string(index=False))
        print("Saved data/screener/growth_backtest.csv")


if __name__ == "__main__":
    main()
