"""A short whole-market report, saved as a dated PDF next to the watch list analyses.

Same template as every report: 1. Summary, 2. The numbers, 3. Analysis.
  - Market: main indices, rates, oil, gold, the dollar and bitcoin; the 11 S&P 500 sectors;
    breadth (share of S&P 500 stocks above their 200-day average, near 52-week highs/lows).
  - Stocks to look at: the market screener's top 3 cheap or close-to-cheap stocks per
    sector (analysis/screener.py, report 13): Stage 1 keeps companies with good financial
    statements for their Lynch category, Stage 2 ranks the survivors by price against
    their own cheap price. Read from data/screener/top.csv; the evening run refreshes it
    first (analysis/watchlist.py).
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
import tomllib
from datetime import date, datetime
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
SCREENER = ROOT / "data/screener"  # written by analysis/screener.py
SCREENER_CONFIG = ROOT / "config/screeners.toml"
TOP = 10  # names in the summary line (the cheapest first)


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


def load_screener() -> tuple[pd.DataFrame, dict]:
    """The market screener's latest top per sector (data/screener/top.csv), cheapest first,
    and Stage 1's counts. The evening run refreshes both just before this report."""
    top_path, stage1_path = SCREENER / "top.csv", SCREENER / "stage1.csv"
    if not top_path.exists() or not stage1_path.exists():
        return pd.DataFrame(), {}
    top = pd.read_csv(top_path).sort_values("vs_cheap")
    s1 = pd.read_csv(stage1_path)
    dated = sorted(p.stem for p in SCREENER.glob("????-??-??.csv"))
    info = {
        "date": dated[-1] if dated else "",
        "screened": len(s1),
        "passed": int((s1["status"] == "pass").sum()),
        "listed": len(top),
        "sectors": int(top["sector"].nunique()) if len(top) else 0,
        "stale": bool(dated) and dated[-1] != date.today().isoformat(),
    }
    with SCREENER_CONFIG.open("rb") as f:
        cfg = tomllib.load(f)
    info |= {"top_n": cfg["top_per_sector"], "close": cfg["close_to_cheap"]}
    return top, info


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
    m: pd.DataFrame,
    sec: pd.DataFrame,
    b: dict,
    top: pd.DataFrame,
    info: dict,
    run_label: str,
    price_date: str,
) -> str:
    updated, notes = w.read_notes("market")
    top_n, close = info.get("top_n", 3), info.get("close", 0.15)

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
    top_rows = []
    for _, r in top.sort_values(["sector", "rank_in_sector"]).iterrows():
        cur = "$" if r["currency"] == "USD" else f"{r['currency']} "
        top_rows.append(
            [
                f"<b>{html.escape(str(r['name']))}</b> {html.escape(str(r['description']))}",
                html.escape(str(r["sector"])),
                html.escape(str(r["category"]).replace("_", " ")),
                w.money(r["close"], cur),
                w.times(r["pe_now"]),
                f"{w.times(r['cheap_multiple'])} ({html.escape(str(r['cheap_basis']))})",
                w.money(r["cheap_price"], cur),
                pct(r["vs_cheap"]),
                html.escape(str(r["cheapness"])),
                html.escape(str(r["trend"]) if pd.notna(r["trend"]) else ""),
            ]
        )
    names = ", ".join(top["name"].head(TOP)) if len(top) else ""
    stale = (
        f" <b>The screener's data is from {html.escape(info['date'])}</b>, not today: its run"
        " failed tonight, so these are the last good results."
        if info.get("stale")
        else ""
    )
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
<p><b>Stocks to look at</b> (the screener's cheapest first): {
        names or "none passed the screen today"
    }.</p>

<h2>2. The numbers</h2>
<h3>Markets</h3>
{w.table(["", "Level", "Day", "1 month", "This year", "From 52-wk high"], idx_rows)}
<h3>S&amp;P 500 sectors (sector ETFs), best this year first</h3>
{w.table(["Sector", "Day", "1 month", "This year", "From 52-wk high"], sec_rows)}
<h3>Stocks to look at: the market screener's top {top_n} per sector</h3>
<p>{info.get("passed", 0)} of {info.get("screened", 0)} S&amp;P 500 companies pass Stage 1
(good financial statements for their Peter Lynch category); {info.get("listed", 0)} of them
are cheap or close to cheap, the top {top_n} in each of {info.get("sectors", 0)} sectors.{stale}</p>
{
        w.table(
            [
                "Stock",
                "Sector",
                "Lynch category",
                "Price",
                "P/E now",
                "Cheap P/E",
                "Cheap price",
                "Price vs cheap",
                "Cheap or close",
                "Trend",
            ],
            top_rows,
        )
    }
<p class="note">Stage 1 sorts each company into one of Lynch's six categories and keeps those
that pass every financial-statement rule for their category (banks, insurers and REITs by their
own rules). Stage 2 sets each survivor's cheap price: EPS times the lower of the bottom quarter
of its own yearly P/E over 10 years (6 years at least) and its sector's median P/E. EPS is
Yahoo's adjusted EPS for the closest names in each sector, diluted EPS otherwise. "Cheap" is
at or below that price; "close" is within {close:.0%} above it. Trend is timing only, not a
rule. Details and every rule's source: report 13 and docs/SCREENER.md. Check each name before
acting.</p>

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
    m = moves(closes(list(INDICES), "2y")).reindex(list(INDICES))
    sec = moves(closes(list(SECTORS), "2y"))
    universe = pd.read_csv(UNIVERSE).set_index("symbol")
    px = closes(universe.index.tolist(), "2y")
    b = breadth(px)
    top, info = load_screener()
    price_date = px.index[-1].date().isoformat()

    spx = m.loc["^GSPC"]
    print(
        f"Market: S&P 500 {spx['last']:,.0f} ({pct(spx['day'])} today, {pct(spx['ytd'])} this "
        f"year), VIX {m.loc['^VIX', 'last']:.1f}, {b['above_200d']:.0%} above 200-day; "
        f"stocks to look at: {' '.join(top['name'].head(TOP)) if len(top) else 'none'}"
    )
    if numbers:
        print(m.round(4).to_string())
        cols = ["name", "sector", "category", "close", "pe_now", "cheap_price", "vs_cheap"]
        print(top[cols].round(3).to_string(index=False) if len(top) else "")
        return None

    stamp = local.strftime("%Y-%m-%d_%H%M")
    run_label = local.strftime("%Y-%m-%d %H:%M ") + local.tzname()
    pdf = w.new_pdf(OUT, stamp)
    w.to_pdf(render(m, sec, b, top, info, run_label, price_date), pdf)
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
                "stocks_to_look_at": " ".join(top["name"].head(TOP)) if len(top) else "",
                "screener_date": info.get("date", ""),
                "screener_passed": info.get("passed", 0),
                "screener_screened": info.get("screened", 0),
                "screener_listed": info.get("listed", 0),
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
