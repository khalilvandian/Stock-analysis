"""The market report's page, in the same three parts as every report.

  - Market: main indices, rates, oil, gold, the dollar and bitcoin; the 11 S&P 500 sectors;
    breadth (share of S&P 500 stocks above their 200-day average, near 52-week highs/lows).
  - Stocks to look at: the market screener's top 3 cheap or close-to-cheap stocks per
    sector (stock_analysis.screener, docs/SCREENER.md).
  - Claude's analysis: what happened, why, what it means, the names, what to watch, sources.

The numbers are computed on the server after each night's ingest (stock_analysis.nightly:
the instruments of config/market.toml, breadth of the S&P 500 members, the screener's top).
"""

from __future__ import annotations

import html
import tomllib

import numpy as np
import pandas as pd

from ..db import ROOT
from ..nightly import plain
from . import render as w

MARKET_CONFIG = ROOT / "config/market.toml"

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
    a: w.Analysis,
) -> str:
    updated, notes = a.reviewed, a.sections
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
<h3>What happened</h3>
{note("What happened")}
<h3>Why it happened</h3>
{note("Why it happened")}
<h3>What it means for a long-term investor</h3>
{note("What it means")}
<h3>The stocks to look at</h3>
{note("Stocks to look at")}
<h3>What to watch</h3>
{note("What to watch")}
<h3>Sources</h3>
{note("Sources")}
</body></html>"""


def page(n: dict, run_label: str, a: w.Analysis) -> str:
    """The report's page from nightly's market numbers and Claude's analysis."""
    if "^GSPC" not in n["markets"].index or n["markets"]["last"].isna().all():
        raise RuntimeError("no market prices in the database yet (core_market_daily)")
    return render(
        n["markets"], n["sectors"], n["breadth"], n["top"], n["screener"], run_label,
        n["price_date"], a,
    )  # fmt: skip


def run_row(n: dict, run_at: str, file: str) -> dict:
    """The run's row in out_market_run."""
    m, top, info = n["markets"], n["top"], n["screener"]
    return {
        "run_at": run_at,
        "file": file,
        "sp500": plain(m.loc["^GSPC", "last"]),
        "sp500_day": plain(m.loc["^GSPC", "day"]),
        "vix": plain(m.loc["^VIX", "last"]),
        "above_200d": plain(n["breadth"]["above_200d"]),
        "stocks_to_look_at": " ".join(top["name"].head(TOP)) if len(top) else "",
        "screener_date": info.get("date") or None,
        "screener_passed": info.get("passed", 0),
        "screener_screened": info.get("screened", 0),
        "screener_listed": info.get("listed", 0),
    }
