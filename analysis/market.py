"""A short whole-market report, saved as a dated PDF next to the watch list analyses.

Same template as every report: 1. Summary, 2. The numbers, 3. Analysis.
  - Market: main indices, rates, oil, gold, the dollar and bitcoin; the 11 S&P 500 sectors;
    breadth (share of S&P 500 stocks above their 200-day average, near 52-week highs/lows).
  - Stocks to look at: the panic-sell screen. S&P 500 stocks at least 25% below their
    52-week high whose adjusted earnings are still growing, ranked by how cheap their
    adjusted P/E is against their own 10-year (and 5-year) median.
  - Claude's view (summary, what is driving the market, comments on the names) comes from
    analyses/market/notes.md.

The S&P 500 list is config/market_universe.csv (from Wikipedia; refresh it occasionally).

Writes analyses/market/<YYYY-MM-DD_HHMM>.pdf and analyses/market/runs.csv.

Usage:
    uv run python analysis/market.py             # build the PDF
    uv run python analysis/market.py --numbers   # print the numbers only
"""

from __future__ import annotations

import argparse
import html
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watchlist as w  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "config/market_universe.csv"
OUT = w.OUT / "market"

INDICES = {
    "^GSPC": "S&P 500",
    "^IXIC": "Nasdaq Composite",
    "^DJI": "Dow Jones",
    "^RUT": "Russell 2000",
    "^STOXX50E": "Euro Stoxx 50",
    "FTSEMIB.MI": "FTSE MIB (Italy)",
    "^VIX": "VIX (fear index)",
    "^TNX": "US 10-year yield",
    "CL=F": "Oil (WTI)",
    "GC=F": "Gold",
    "EURUSD=X": "Euro in dollars",
    "BTC-USD": "Bitcoin",
}
SECTORS = {
    "XLK": "Technology",
    "XLC": "Communication",
    "XLY": "Consumer discretionary",
    "XLP": "Consumer staples",
    "XLF": "Financials",
    "XLV": "Health care",
    "XLI": "Industrials",
    "XLE": "Energy",
    "XLB": "Materials",
    "XLRE": "Real estate",
    "XLU": "Utilities",
}
DRAWDOWN = -0.25  # at least 25% below the 52-week high
TOP = 10


def closes(symbols: list[str], period: str) -> pd.DataFrame:
    px = yf.download(symbols, period=period, auto_adjust=False, progress=False, threads=True)[
        "Close"
    ]
    px.index = pd.to_datetime(px.index).tz_localize(None).normalize()
    return px.dropna(how="all")


def moves(px: pd.DataFrame) -> pd.DataFrame:
    """Level, 1-day, 1-month and year-to-date change, and distance from the 52-week high."""
    last = px.ffill().iloc[-1]
    year = px[px.index >= px.index[-1] - pd.DateOffset(years=1)]
    ytd = px[px.index.year == px.index[-1].year]
    month = px[px.index >= px.index[-1] - pd.DateOffset(months=1)]
    return pd.DataFrame(
        {
            "last": last,
            "day": last / px.ffill().iloc[-2] - 1,
            "month": last / month.bfill().iloc[0] - 1,
            "ytd": last / ytd.bfill().iloc[0] - 1,
            "from_high": last / year.max() - 1,
        }
    )


def breadth(px: pd.DataFrame) -> dict:
    p = px.ffill()
    last = p.iloc[-1]
    ma200 = p.tail(200).mean()
    year = p.tail(252)
    return {
        "above_200d": float((last > ma200).mean()),
        "near_high": int((last >= year.max() * 0.98).sum()),
        "near_low": int((last <= year.min() * 1.02).sum()),
        "count": int(last.notna().sum()),
    }


def own_history(symbol: str, now: pd.Timestamp) -> dict | None:
    """Adjusted P/E now against the stock's own yearly P/E history (as in watchlist.py)."""
    try:
        t = yf.Ticker(symbol)
        q = w.quarterly_eps(t.get_earnings_dates(limit=60))
        start = (now - pd.DateOffset(years=w.YEARS + 1)).strftime("%Y-%m-%d")
        prices = t.history(start=start, auto_adjust=False)["Close"]
    except Exception:  # noqa: BLE001 - one bad symbol shouldn't stop the report
        return None
    if prices.empty or len(q) < 8:
        return None
    prices.index = prices.index.tz_localize(None).normalize()
    ttm = w.trailing_eps(q)
    if len(ttm) < 5 or ttm.iloc[-1] <= 0:
        return None
    yearly = w.yearly_pe(prices, ttm)
    if len(yearly) < 6:  # too short a history to call it cheap against its own
        return None
    eps, eps_year_ago = float(ttm.iloc[-1]), float(ttm.iloc[-5])
    pe = float(prices.iloc[-1]) / eps
    med10 = float(yearly["pe"].median())
    med5 = float(yearly["pe"].tail(5).median())
    return {
        "symbol": symbol,
        "eps_adj_ttm": eps,
        "eps_growth": eps / eps_year_ago - 1 if eps_year_ago > 0 else np.nan,
        "pe_adj": pe,
        "pe_median_10y": med10,
        "pe_median_5y": med5,
        "pe_low_10y": float(yearly["pe"].min()),
        # against the lower of the two medians, so a stock's early hyper-growth years
        # don't make it look cheap
        "vs_median": pe / min(med10, med5) - 1,
    }


def screen_stocks(stocks: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    hit = stocks[stocks["from_high"] <= DRAWDOWN]
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [r for r in pool.map(lambda s: own_history(s, now), hit.index) if r]
    if not rows:
        return pd.DataFrame()
    h = pd.DataFrame(rows).set_index("symbol").join(hit)
    # earnings still growing: fear rather than falling profits
    h = h[h["eps_growth"] > 0]
    # a P/E under 5x is almost always a data problem (e.g. EPS not split-adjusted)
    h = h[h["pe_adj"] >= 5]
    return h.sort_values("vs_median")


def pct(v: float) -> str:
    return w.pct(v)


def level(sym: str, v: float) -> str:
    if not np.isfinite(v):
        return "–"
    if sym == "^TNX":
        return f"{v:.2f}%"
    if sym == "EURUSD=X":
        return f"{v:.4f}"
    return f"{v:,.2f}"


def render(
    m: pd.DataFrame, sec: pd.DataFrame, b: dict, top: pd.DataFrame, run_label: str, price_date: str
) -> str:
    updated, notes = w.read_notes("market")

    def note(section: str) -> str:
        if section in notes:
            return w.md(notes[section])
        return "<p class='note'>Not written yet.</p>"

    spx, vix = m.loc["^GSPC"], m.loc["^VIX"]
    idx_rows = [
        [
            html.escape(INDICES[s]),
            level(s, r["last"]),
            pct(r["day"]),
            pct(r["month"]),
            pct(r["ytd"]),
            pct(r["from_high"]),
        ]
        for s, r in m.iterrows()
    ]
    sec_rows = [
        [
            html.escape(SECTORS[s]),
            pct(r["day"]),
            pct(r["month"]),
            pct(r["ytd"]),
            pct(r["from_high"]),
        ]
        for s, r in sec.sort_values("ytd", ascending=False).iterrows()
    ]
    top_rows = [
        [
            f"<b>{s}</b> {html.escape(str(r['name']))}",
            html.escape(str(r["sector"])),
            w.money(r["last"]),
            pct(r["from_high"]),
            w.times(r["pe_adj"]),
            w.times(r["pe_median_5y"]),
            w.times(r["pe_median_10y"]),
            pct(r["eps_growth"]),
        ]
        for s, r in top.head(TOP).iterrows()
    ]
    names = ", ".join(top.head(TOP).index)
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{w.CSS}</style></head><body>
<h1>Market report</h1>
<div class="sub">{run_label}. Latest prices on {price_date}. Claude's notes updated
{html.escape(updated or "never")}.</div>

<h2>1. Summary</h2>
<div class="verdict">{note("Verdict")}</div>
<div class="key">
 <div><span>S&amp;P 500</span><b>{level("^GSPC", spx["last"])}</b>
  <span>{pct(spx["day"])} today, {pct(spx["from_high"])} from high</span></div>
 <div><span>VIX</span><b>{vix["last"]:.1f}</b><span>{pct(vix["day"])} today</span></div>
 <div><span>Above 200-day average</span><b>{b["above_200d"]:.0%}</b>
  <span>of S&amp;P 500 stocks</span></div>
 <div><span>Near 52-week high / low</span><b>{b["near_high"]} / {b["near_low"]}</b>
  <span>of {b["count"]}</span></div>
</div>
{note("Summary")}
<p><b>Stocks to look at:</b> {names or "none passed the screen today"}.</p>

<h2>2. The numbers</h2>
<h3>Markets</h3>
{w.table(["", "Level", "Day", "1 month", "This year", "From 52-wk high"], idx_rows)}
<h3>S&amp;P 500 sectors (sector ETFs), best this year first</h3>
{w.table(["Sector", "Day", "1 month", "This year", "From 52-wk high"], sec_rows)}
<h3>Stocks to look at: sold off, earnings still growing, cheap against their own history</h3>
{
        w.table(
            [
                "Stock",
                "Sector",
                "Price",
                "From 52-wk high",
                "Adjusted P/E",
                "5-yr median",
                "10-yr median",
                "EPS growth, 1 yr",
            ],
            top_rows,
        )
    }
<p class="note">S&amp;P 500 stocks at least {abs(DRAWDOWN):.0%} below their 52-week high
({int(top.shape[0])} of them with growing adjusted EPS), ranked by adjusted P/E against the lower
of their 5- and 10-year median yearly P/E. Stocks with under six years of history or a P/E
below 5x (usually a data problem) are left out. Adjusted EPS is Yahoo's reported quarterly EPS,
as in the watch list analyses. One-offs inside it are not corrected here, so check each name
before acting.</p>

<h2>3. Analysis</h2>
<h3>What is driving the market</h3>
{note("What is driving the market")}
<h3>The stocks to look at</h3>
{note("Stocks to look at")}
<h3>What to watch</h3>
{note("What to watch")}
<p class="note">Reproduce: <code>uv run python analysis/market.py</code></p>
</body></html>"""


def build(local: datetime, numbers: bool = False) -> Path | None:
    """Fetch, print the numbers and (unless numbers) write the dated PDF; returns its path."""
    now = pd.Timestamp(local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None))
    m = moves(closes(list(INDICES), "2y")).reindex(list(INDICES))
    sec = moves(closes(list(SECTORS), "2y"))
    universe = pd.read_csv(UNIVERSE).set_index("symbol")
    px = closes(universe.index.tolist(), "2y")
    b = breadth(px)
    stocks = moves(px).join(universe)
    top = screen_stocks(stocks, now)
    price_date = px.index[-1].date().isoformat()

    spx = m.loc["^GSPC"]
    print(
        f"Market: S&P 500 {spx['last']:,.0f} ({pct(spx['day'])} today, {pct(spx['ytd'])} this "
        f"year), VIX {m.loc['^VIX', 'last']:.1f}, {b['above_200d']:.0%} above 200-day; "
        f"stocks to look at: {' '.join(top.head(TOP).index) or 'none'}"
    )
    if numbers:
        print(m.round(4).to_string())
        cols = ["name", "last", "from_high", "pe_adj", "pe_median_5y", "pe_median_10y"]
        print(top[cols + ["eps_growth"]].head(TOP).round(3).to_string() if len(top) else "")
        return None

    stamp = local.strftime("%Y-%m-%d_%H%M")
    run_label = local.strftime("%Y-%m-%d %H:%M ") + local.tzname()
    pdf = w.new_pdf(OUT, stamp)
    w.to_pdf(render(m, sec, b, top, run_label, price_date), pdf)
    runs = OUT / "runs.csv"
    row = pd.DataFrame(
        [
            {
                "run": run_label,
                "file": pdf.name,
                "sp500": spx["last"],
                "sp500_day": spx["day"],
                "vix": m.loc["^VIX", "last"],
                "above_200d": b["above_200d"],
                "stocks_to_look_at": " ".join(top.head(TOP).index),
            }
        ]
    )
    if runs.exists():
        row = pd.concat([pd.read_csv(runs), row], ignore_index=True)
    row.to_csv(runs, index=False, float_format="%.4f")
    return pdf


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--numbers", action="store_true", help="print the numbers, write nothing")
    args = ap.parse_args()
    local = datetime.now(ZoneInfo(w.load_watchlist()["timezone"]))
    pdf = build(local, args.numbers)
    if pdf:
        print(f"Wrote {pdf.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
