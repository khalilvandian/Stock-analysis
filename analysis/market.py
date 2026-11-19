"""A short whole-market report, saved as a dated PDF next to the watch list analyses.

Same template as every report: 1. Summary, 2. The numbers, 3. Analysis.
  - Market: main indices, rates, oil, gold, the dollar and bitcoin; the 11 S&P 500 sectors;
    breadth (share of S&P 500 stocks above their 200-day average, near 52-week highs/lows).
  - Stocks to look at: the market screener's top 3 cheap or close-to-cheap stocks per
    sector (stock_analysis.screener, docs/SCREENER.md): Stage 1 keeps companies with good financial
    statements for their Lynch category, Stage 2 ranks the survivors by price against
    their own cheap price. Read from the database's latest screener run; the evening run
    refreshes it first (analysis/watchlist.py).
  - Claude's view (summary, what is driving the market, comments on the names) comes from
    analyses/market/notes.md.

The numbers are computed on the server after each ingest (stock_analysis.nightly:
the instruments of config/market.toml, breadth of the S&P 500 members, the screener's top)
and read here; if none were stored since the last build, they are computed on the spot.

Writes analyses/market/<YYYY-MM-DD_HHMM>.pdf and records the run in out_market_run.

Usage:
    uv run python analysis/market.py             # build the PDF
    uv run python analysis/market.py --numbers   # print the numbers only
"""

from __future__ import annotations

import argparse
import html
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from stock_analysis import nightly, stocks

sys.path.insert(0, str(Path(__file__).resolve().parent))
import watchlist as w  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MARKET_CONFIG = ROOT / "config/market.toml"
OUT = w.OUT / "market"

_instruments = tomllib.loads(MARKET_CONFIG.read_text(encoding="utf-8"))
INDICES: dict[str, str] = _instruments["markets"]
SECTORS: dict[str, str] = _instruments["sectors"]
SCREENER_CONFIG = ROOT / "config/screeners.toml"
TOP = 10  # names in the summary line (the cheapest first)


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
rule. Details and every rule's source: docs/SCREENER.md. Check each name before
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


def build(local: datetime, numbers: bool = False, data=None) -> Path | None:
    """Read, print the numbers and (unless numbers) write the dated PDF; returns its path."""
    data = data or stocks.default_data()
    n = nightly.stored_market(data)  # computed on the server after the ingest
    if n is None:
        print("Market numbers: none stored since the last build; computing them now")
        n = nightly.market_numbers(data)
    m, sec, b, top, info = n["markets"], n["sectors"], n["breadth"], n["top"], n["screener"]
    price_date = n["price_date"]
    if "^GSPC" not in m.index or m["last"].isna().all():
        raise RuntimeError("no market prices in the database yet (core_market_daily)")

    spx = m.loc["^GSPC"]
    print(
        f"Market: S&P 500 {spx['last']:,.0f} ({pct(spx['day'])} today, {pct(spx['ytd'])} this "
        f"year), VIX {m.loc['^VIX', 'last']:.1f}, {b['above_200d']:.0%} above 200-day; "
        f"stocks to look at: {' '.join(top['name'].head(TOP)) if len(top) else 'none'}"
    )
    if numbers:
        print(m.round(4).to_string())
        cols = ["name", "sector", "category", "close", "pe_now", "cheap_price", "vs_cheap"]
        print(
            top[[c for c in cols if c in top]].round(3).to_string(index=False) if len(top) else ""
        )
        return None

    stamp = local.strftime("%Y-%m-%d_%H%M")
    run_label = local.strftime("%Y-%m-%d %H:%M ") + local.tzname()
    pdf = w.new_pdf(OUT, stamp)
    w.to_pdf(render(m, sec, b, top, info, run_label, price_date), pdf)
    data.save_market_run(
        {
            "run_at": local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
            "file": pdf.name,
            "sp500": w.plain(spx["last"]),
            "sp500_day": w.plain(spx["day"]),
            "vix": w.plain(m.loc["^VIX", "last"]),
            "above_200d": w.plain(b["above_200d"]),
            "stocks_to_look_at": " ".join(top["name"].head(TOP)) if len(top) else "",
            "screener_date": info.get("date") or None,
            "screener_passed": info.get("passed", 0),
            "screener_screened": info.get("screened", 0),
            "screener_listed": info.get("listed", 0),
        }
    )
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
