"""Analyse every stock on the watch list and save each analysis as a dated PDF.

For each stock in config/watchlist.toml the PDF has three parts, in this order:
  1. Summary: the verdict and key points from analyses/<SYMBOL>/notes.md, plus price
     against the entry price.
  2. The numbers: absolute values (latest 12 months and SEC yearly history), ratios, the
     strict and weighted screens against the stock's peers, and the standard DCF.
  3. Analysis: adjusted P/E against the stock's own 10-year history, the entry price at the
     target multiple, then business, risks, news and what to watch from notes.md.

Adjusted EPS is Yahoo's reported quarterly EPS, which is on the same basis as analysts'
estimates (excluding amortization and one-offs). It is split-adjusted and goes back
decades, so the own-history P/E needs no hand-kept table. One-offs Yahoo still includes
can be corrected with eps_override in the config.

Each run writes analyses/<SYMBOL>/<YYYY-MM-DD_HHMM>.pdf, adds a line to
analyses/<SYMBOL>/runs.csv and rebuilds the dated lists analyses/<SYMBOL>/README.md and
analyses/README.md. Earlier PDFs are never overwritten.

Usage:
    uv run python analysis/watchlist.py              # market report + every stock + summary
    uv run python analysis/watchlist.py BSX NFLX     # selected stocks
    uv run python analysis/watchlist.py --numbers    # print the key numbers, no PDF
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
import numpy as np
import pandas as pd
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent))
import absolute  # noqa: E402
import history  # noqa: E402
import peer_screen  # noqa: E402
import screen  # noqa: E402
import sector  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/watchlist.toml"
OUT = ROOT / "analyses"
YEARS = 10


# --- configuration -------------------------------------------------------------------


def load_watchlist(path: Path = CONFIG) -> dict:
    with path.open("rb") as f:
        cfg = tomllib.load(f)
    cfg.setdefault("timezone", "Europe/Rome")
    for s in cfg["stock"]:
        s["symbol"] = s["symbol"].upper()
        s.setdefault("peers", [])
        s.setdefault("eps_override", [])
    return cfg


# --- adjusted EPS and P/E history ----------------------------------------------------


def quarterly_eps(dates: pd.DataFrame, overrides: list[dict] | None = None) -> pd.Series:
    """Reported (adjusted) EPS by report date, one value per quarter, oldest first.

    `dates` is yfinance's get_earnings_dates() frame. Duplicate rows for the same report are
    dropped; overrides replace the EPS of the quarter reported on that date.
    """
    s = dates["Reported EPS"].dropna()
    s.index = pd.to_datetime(s.index, utc=True).tz_convert(None).normalize()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    # two reports within 30 days are the same quarter (a re-dated entry); keep the later one
    keep = ~(pd.Series(s.index, index=s.index).diff(-1).abs() < pd.Timedelta(days=30))
    s = s[keep.values]
    for o in overrides or []:
        day = pd.Timestamp(o["reported"]).normalize()
        if day in s.index:
            s[day] = float(o["eps"])
    return s.astype(float)


def trailing_eps(q: pd.Series) -> pd.Series:
    """Sum of the last four quarters at each report date (only when the four are consecutive)."""
    ttm = q.rolling(4).sum()
    span = pd.Series(q.index, index=q.index).diff(3)
    return ttm[span <= pd.Timedelta(days=400)].dropna()


def daily_pe(prices: pd.Series, ttm: pd.Series) -> pd.Series:
    """Price divided by the trailing adjusted EPS known on each day; blank when EPS <= 0."""
    eps = ttm.reindex(prices.index.union(ttm.index)).ffill().reindex(prices.index)
    return (prices / eps.where(eps > 0)).dropna()


def yearly_pe(prices: pd.Series, ttm: pd.Series, years: int = YEARS) -> pd.DataFrame:
    """Per calendar year: average price, full-year adjusted EPS, P/E on the average price.

    Full-year EPS is the trailing EPS at the first report after the year ends (the Q4 report,
    for calendar-year companies).
    """
    last = prices.index.max().year
    rows = []
    for y in range(last - years, last):
        after = ttm[(ttm.index > f"{y}-12-31") & (ttm.index <= f"{y + 1}-04-30")]
        p = prices[prices.index.year == y]
        if after.empty or p.empty:
            continue
        eps = float(after.iloc[0])
        rows.append(
            {
                "year": y,
                "avg_price": float(p.mean()),
                "eps": eps,
                "pe": float(p.mean()) / eps if eps > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("year") if rows else pd.DataFrame()


def next_report(dates: pd.DataFrame, now: pd.Timestamp) -> tuple[pd.Timestamp | None, float]:
    future = dates[dates["Reported EPS"].isna()].copy()
    future.index = pd.to_datetime(future.index, utc=True).tz_convert(None)
    future = future[future.index >= now].sort_index()
    if future.empty:
        return None, np.nan
    return future.index[0], float(future["EPS Estimate"].iloc[0])


# --- data ----------------------------------------------------------------------------


def fetch_row(symbol: str) -> dict:
    """sector.analyse() with retries: Yahoo sometimes answers without a price."""
    for attempt in range(4):
        row = sector.analyse({"symbol": symbol})
        if row.get("price"):
            return row
        time.sleep(5 * (attempt + 1))
    return row


def split_adjust(hist: pd.DataFrame, splits: pd.Series, shares_now: float) -> pd.DataFrame:
    """Put EPS and share counts filed before a stock split on today's share basis.

    Yahoo prices are split-adjusted, but SEC values keep the share basis of the filing
    they come from. A year's share count is scaled by the splits since its year end when
    that brings it closer to today's share count (share counts rarely move 2x otherwise).
    """
    if hist.empty or splits.empty or not np.isfinite(shares_now) or shares_now <= 0:
        return hist
    splits = splits.copy()
    splits.index = pd.to_datetime(splits.index, utc=True).tz_convert(None)
    h = hist.copy()
    ends = pd.to_datetime(h["fiscal_year_end"])
    for end in ends.unique():
        factor = float(splits[splits.index > end].prod())
        sh = h[(ends == end) & (h["column"] == "_shares")]["value"]
        if factor < 1.5 or sh.empty:
            continue
        if abs(np.log(sh.iloc[0] * factor / shares_now)) < abs(np.log(sh.iloc[0] / shares_now)):
            h.loc[(ends == end) & (h["column"] == "_shares"), "value"] *= factor
            h.loc[(ends == end) & (h["column"] == "eps"), "value"] /= factor
    return h


def sec_years(
    symbol: str, yahoo_rows: list[dict], currency: str | None, shares_now: float
) -> pd.DataFrame:
    """Yearly absolute values: SEC filings first, Yahoo for gaps, year-end prices."""
    history.CACHE.mkdir(parents=True, exist_ok=True)
    cik = history.ticker_ciks().get(symbol.replace("-", "."))
    cached = history.CACHE / f"{symbol}.json"
    stale = not cached.exists() or time.time() - cached.stat().st_mtime > 86400
    facts = history.company_facts(symbol, cik, refresh=stale) if cik else None
    hist = history.sec_history(symbol, facts) if facts else pd.DataFrame()
    hist = history.fill_from_yahoo(hist, pd.DataFrame(yahoo_rows), symbol)
    hist = split_adjust(hist, yf.Ticker(symbol).splits, shares_now)
    cur = history.reporting_currency(facts) if facts else (currency or "USD")
    hist = history.add_prices(hist, symbol, cur)
    return hist[hist["column"] != "_shares"] if not hist.empty else hist


def gather(stock: dict, rows: dict[str, dict], now: pd.Timestamp) -> dict:
    sym = stock["symbol"]
    t = yf.Ticker(sym)
    dates = t.get_earnings_dates(limit=100)
    start = now - pd.DateOffset(years=YEARS + 1)
    prices = t.history(start=start.strftime("%Y-%m-%d"), auto_adjust=False)["Close"]
    prices.index = prices.index.tz_localize(None).normalize()
    q = quarterly_eps(dates, stock["eps_override"])
    ttm = trailing_eps(q)
    row = rows[sym]
    yahoo_rows = row.get("_history", [])
    peers = pd.DataFrame([rows[s] for s in [sym, *stock["peers"]] if s in rows])
    peers = peers.drop(columns="_history", errors="ignore").set_index("symbol")
    peers["data_flag"] = ""
    nxt, nxt_est = next_report(dates, now)
    return {
        "stock": stock,
        "row": row,
        "prices": prices,
        "quarters": q,
        "ttm": ttm,
        "years": sec_years(
            sym,
            yahoo_rows,
            row.get("currency"),
            sector._div(row.get("market_cap") or np.nan, row.get("price") or np.nan) * 1e9,
        ),
        "peers": peers,
        "next_report": nxt,
        "next_estimate": nxt_est,
    }


def key_numbers(d: dict) -> dict:
    """The few numbers that go in the summary, the dated list and the evening message."""
    stock, row, prices, ttm = d["stock"], d["row"], d["prices"], d["ttm"]
    price = float(row.get("price") or prices.iloc[-1])
    eps = float(ttm.iloc[-1]) if not ttm.empty else np.nan
    yearly = yearly_pe(prices, ttm)
    median = float(yearly["pe"].median()) if not yearly.empty else np.nan
    entry = stock["target_pe"] * eps if eps > 0 else np.nan
    q = d["quarters"]
    eps_next = (
        eps - float(q.iloc[-4]) + d["next_estimate"]
        if len(q) >= 4 and np.isfinite(d["next_estimate"])
        else np.nan
    )
    return {
        "price": price,
        "price_date": prices.index[-1].date().isoformat(),
        "eps_adj_ttm": eps,
        "pe_adj": price / eps if eps > 0 else np.nan,
        "pe_median_10y": median,
        "pe_median_5y": float(yearly["pe"].tail(5).median()) if not yearly.empty else np.nan,
        "pe_low_10y": float(yearly["pe"].min()) if not yearly.empty else np.nan,
        "pe_high_10y": float(yearly["pe"].max()) if not yearly.empty else np.nan,
        "target_pe": stock["target_pe"],
        "entry_price": entry,
        "to_entry": entry / price - 1 if np.isfinite(entry) else np.nan,
        "next_report": d["next_report"].date().isoformat() if d["next_report"] is not None else "",
        "next_estimate": d["next_estimate"],
        "entry_after_next": stock["target_pe"] * eps_next if eps_next > 0 else np.nan,
    }


# --- notes (Claude's own analysis, kept as Markdown) ---------------------------------

NOTE_SECTIONS = ["Verdict", "Summary", "Business", "Risks", "News", "What to watch"]


def read_notes(symbol: str) -> tuple[str, dict[str, str]]:
    """analyses/<SYMBOL>/notes.md split into its '## ' sections; returns (updated, sections)."""
    path = OUT / symbol / "notes.md"
    if not path.exists():
        return "", {}
    text = path.read_text()
    m = re.search(r"^Updated:\s*(.+)$", text, re.M)
    parts = re.split(r"^## +(.+)$", text, flags=re.M)
    sections = {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return (m.group(1).strip() if m else ""), sections


# --- HTML ----------------------------------------------------------------------------


def money(v: float, unit: str = "$") -> str:
    if v is None or not np.isfinite(v):
        return "–"
    return absolute.fmt(v, unit)


def pct(v: float, signed: bool = True) -> str:
    if v is None or not np.isfinite(v):
        return "–"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def times(v: float) -> str:
    return f"{v:.1f}x" if v is not None and np.isfinite(v) else "–"


def table(header: list[str], rows: list[list[str]], bold_row: int | None = None) -> str:
    th = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = []
    for i, r in enumerate(rows):
        cls = ' class="hl"' if i == bold_row else ""
        body.append(f"<tr{cls}>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>")
    return f"<table><thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def md(text: str) -> str:
    return markdown.markdown(text, extensions=["tables"])


def pe_chart(pe: pd.Series, median: float, target: float) -> str:
    """Inline SVG of daily trailing adjusted P/E with the 10-year median and the target."""
    pe = pe[pe.index >= pe.index.max() - pd.DateOffset(years=YEARS)]
    if pe.empty:
        return ""
    w, h, pad = 700, 220, 36
    weekly = pe.resample("W").last().dropna()
    # cap the axis so years of near-zero earnings (e.g. 2020) don't flatten the rest
    top = min(float(np.nanpercentile(weekly, 99)) * 1.1, median * 2.5)
    top = max(top, median * 1.3, target * 1.3, float(weekly.iloc[-1]) * 1.2)
    t0, t1 = weekly.index[0].value, weekly.index[-1].value

    def x(ts: pd.Timestamp) -> float:
        return pad + (ts.value - t0) / (t1 - t0) * (w - 2 * pad)

    def y(v: float) -> float:
        return h - pad - min(v, top) / top * (h - 2 * pad)

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in weekly.items())
    grid = []
    step = next(st for st in (5, 10, 20, 50, 100) if top / st <= 8)
    for v in range(0, int(top) + 1, step):
        grid.append(
            f'<line x1="{pad}" x2="{w - pad}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
            f'<text x="{pad - 6}" y="{y(v) + 4:.1f}" class="ax" text-anchor="end">{v}x</text>'
        )
    for yr in range(weekly.index[0].year + 1, weekly.index[-1].year + 1):
        ts = pd.Timestamp(f"{yr}-01-01")
        grid.append(f'<text x="{x(ts):.1f}" y="{h - pad + 16}" class="ax">{yr}</text>')
    last = weekly.iloc[-1]
    return f"""<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">
{"".join(grid)}
<line x1="{pad}" x2="{w - pad}" y1="{y(median):.1f}" y2="{y(median):.1f}" class="med"/>
<text x="{w - pad}" y="{y(median) - 5:.1f}" class="lab" text-anchor="end">
10-yr median {median:.0f}x</text>
<line x1="{pad}" x2="{w - pad}" y1="{y(target):.1f}" y2="{y(target):.1f}" class="tgt"/>
<text x="{w - pad}" y="{y(target) + 13:.1f}" class="lab tgtl" text-anchor="end">
target {target:g}x</text>
<polyline points="{pts}" class="line"/>
<circle cx="{x(weekly.index[-1]):.1f}" cy="{y(last):.1f}" r="4" class="dot"/>
</svg>"""


CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "DejaVu Sans", Helvetica, Arial, sans-serif; font-size: 9.5pt;
       color: #1b1f24; line-height: 1.4; }
h1 { font-size: 17pt; margin: 0 0 2px; }
h2 { font-size: 13pt; margin: 18px 0 6px; border-bottom: 2px solid #1b1f24; padding-bottom: 2px; }
h3 { font-size: 10.5pt; margin: 12px 0 4px; }
.sub { color: #57606a; margin-bottom: 10px; }
.verdict { font-size: 11pt; font-weight: bold; background: #f3f5f8; padding: 8px 10px;
           border-left: 4px solid #2f6feb; margin: 8px 0; }
.key { display: flex; gap: 8px; margin: 8px 0; }
.key div { flex: 1; background: #f6f8fa; padding: 6px 8px; border-radius: 4px; }
.key b { display: block; font-size: 12pt; }
.key span { color: #57606a; font-size: 8pt; }
table { border-collapse: collapse; width: 100%; margin: 4px 0 8px; font-size: 8.5pt; }
th, td { border-bottom: 1px solid #d0d7de; padding: 3px 5px; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { background: #f6f8fa; }
tr.hl td { font-weight: bold; background: #eef4ff; }
.wide td, .wide th { font-size: 7.5pt; padding: 2px 3px; }
.note { color: #57606a; font-size: 8.5pt; }
.pass { color: #1a7f37; } .fail { color: #cf222e; }
.chart { width: 100%; height: auto; }
.chart .grid { stroke: #e5e8eb; } .chart .ax { font-size: 9px; fill: #57606a; }
.chart .line { fill: none; stroke: #2f6feb; stroke-width: 1.6; }
.chart .med { stroke: #57606a; stroke-dasharray: 4 3; }
.chart .tgt { stroke: #1a7f37; stroke-dasharray: 4 3; }
.chart .lab { font-size: 9px; fill: #57606a; } .chart .tgtl { fill: #1a7f37; }
.chart .dot { fill: #cf222e; }
.page { page-break-before: always; }
tr, .verdict, .key, svg { break-inside: avoid; }
h2, h3 { break-after: avoid; }
"""


def absolute_tables(d: dict) -> tuple[str, str]:
    row, hist = d["row"], d["years"]
    latest_rows, group_cols, group = [], absolute.columns(absolute.load_config()), None
    for v in group_cols:
        if v["group"] != group:
            group = v["group"]
            latest_rows.append([f"<b>{html.escape(group)}</b>", ""])
        latest_rows.append([html.escape(v["label"]), money(row.get(v["column"]), v["unit"])])
    latest = table(["Value", d["stock"]["symbol"]], latest_rows)

    if hist.empty:
        return latest, "<p class='note'>No yearly history found.</p>"
    h = hist.copy()
    h["year"] = pd.to_datetime(h["fiscal_year_end"]).dt.year
    wide = h.pivot_table(index="column", columns="year", values="value", aggfunc="last")
    years = sorted(wide.columns)[-YEARS:]
    rows = []
    for v in group_cols:
        key = v.get("history", v["column"])
        if not key or key not in wide.index:
            continue
        vals = [money(wide.loc[key].get(y, np.nan), v["unit"]) for y in years]
        rows.append([v["label"], *vals, money(row.get(v["column"]), v["unit"])])
    yearly = table(["Value", *[f"FY{y}" for y in years], "Latest 12m"], rows)
    return latest, f'<div class="wide">{yearly}</div>'


def screens_html(d: dict) -> str:
    sym, peers, row = d["stock"]["symbol"], d["peers"], d["row"]
    r = pd.DataFrame([row]).drop(columns="_history", errors="ignore").set_index("symbol")
    r["data_flag"] = ""
    rules = []
    for name, rule in screen.MUST_HAVE.items():
        ok = bool(rule(r).fillna(False).iloc[0])
        rules.append(
            [
                html.escape(name),
                f'<span class="{"pass" if ok else "fail"}">{"Pass" if ok else "Fail"}</span>',
            ]
        )
    strict_ok = all("Pass" in x[1] for x in rules)

    med = peers[["pe_ttm", "ev_to_ebitda"]].median()
    ratios = [
        ["Net debt / EBITDA", times(row.get("net_debt_to_ebitda")), "≤ 4.5x"],
        ["EBITDA / interest", times(row.get("ebitda_to_interest")), "≥ 4x"],
        ["Cash / short-term debt", times(row.get("cash_to_short_term_debt")), "≥ 1x"],
        ["Cash / long-term debt", pct(row.get("cash_to_long_term_debt"), False), "≥ 5%"],
        [
            "Revenue growth, average / median year",
            f"{pct(row.get('revenue_growth_avg'), False)} / "
            f"{pct(row.get('revenue_growth_median'), False)}",
            "> 0",
        ],
        [
            "EPS growth (GAAP), average / median year",
            f"{pct(row.get('eps_growth_avg'), False)} / {pct(row.get('eps_growth_median'), False)}",
            "> 0",
        ],
        ["Net margin, 12 months", pct(row.get("net_margin"), False), ""],
        ["P/E, trailing GAAP", times(row.get("pe_ttm")), f"peer median {times(med['pe_ttm'])}"],
        ["P/E, forward", times(row.get("pe_fwd")), ""],
        [
            "EV / EBITDA",
            times(row.get("ev_to_ebitda")),
            f"peer median {times(med['ev_to_ebitda'])}",
        ],
        ["Free cash flow yield", pct(row.get("fcf_yield"), False), ""],
        ["Price vs standard DCF fair value", pct(row.get("price_vs_fair_value")), "< 0 is cheap"],
    ]
    out = [
        "<h3>Ratios</h3>",
        table(["Measure", sym, "Rule or peer median"], ratios),
        f"<h3>Strict screen: {'passes' if strict_ok else 'fails'}</h3>",
        table(["Must-have", sym], rules),
    ]
    try:
        _, weighted = peer_screen.run_screens(peers)
    except Exception as e:  # noqa: BLE001
        weighted = pd.DataFrame()
        out.append(f"<p class='note'>Weighted screen failed: {html.escape(str(e))}</p>")
    if not weighted.empty:
        rows, hl = [], None
        for i, (s, w) in enumerate(weighted.iterrows()):
            if s == sym:
                hl = i
            rows.append(
                [
                    f"{int(w['rank'])}. {s}",
                    f"{w['total_score']:.1f}",
                    f"{w['debt_score']:.1f}",
                    f"{w['quality_score']:.1f}",
                    f"{w['cheap_score']:.1f}",
                ]
            )
        title = (
            f"ranks {int(weighted.loc[sym, 'rank'])} of {len(weighted)}"
            if sym in weighted.index
            else "not ranked (fails the base or growth rules)"
        )
        out += [
            f"<h3>Weighted screen against peers: {sym} {title}</h3>",
            table(
                ["Company", "Total", "Debt (50%)", "Profit and cash (25%)", "Cheapness (25%)"],
                rows,
                hl,
            ),
            f"<p class='note'>Peers: {', '.join(d['stock']['peers'])}. Growth required. "
            "Scores are percentiles within the peers that pass the base rules.</p>",
        ]
    return "".join(out)


def dcf_html(row: dict) -> str:
    fcff, wacc, nd = row.get("fcff_before_growth"), row.get("wacc"), row.get("net_debt")
    ev = (row.get("market_cap") or np.nan) + (nd or 0)
    ok = all(map(np.isfinite, [ev, wacc, fcff]))
    implied = (ev * wacc - fcff) / (ev + fcff) if ok else np.nan
    rows = [
        ["Cash flow before growth (OCF − D&A + after-tax interest)", money(fcff, "$bn")],
        ["WACC (CAPM)", pct(wacc, False)],
        ["Growth forever", pct(sector.TERMINAL_GROWTH, False)],
        ["Fair value per share", money(row.get("dcf_fair_value"))],
        ["Price vs fair value", pct(row.get("price_vs_fair_value"))],
        ["Growth forever implied by today's price", pct(implied, False)],
    ]
    return table(["Standard DCF", ""], rows)


def pe_history_html(d: dict, k: dict) -> str:
    yearly = yearly_pe(d["prices"], d["ttm"])
    pe = daily_pe(d["prices"], d["ttm"])
    rows = [["Now (12m)", money(k["price"]), money(k["eps_adj_ttm"]), times(k["pe_adj"])]]
    for y, r in yearly.sort_index(ascending=False).iterrows():
        rows.append([str(y), money(r["avg_price"]), money(r["eps"]), times(r["pe"])])
    q = d["quarters"].tail(4)
    quarters = ", ".join(f"{i:%b %Y} {money(v)}" for i, v in q.items())
    fixes = "".join(
        f" The {o['reported']} quarter uses {money(o['eps'])}: {html.escape(o.get('reason', ''))}"
        for o in d["stock"]["eps_override"]
    )
    return (
        pe_chart(pe, k["pe_median_10y"], k["target_pe"])
        + table(["Year", "Average price", "Adjusted EPS", "P/E"], rows, 0)
        + f"<p>Median of the yearly P/E: {times(k['pe_median_10y'])} over 10 years, "
        f"{times(k['pe_median_5y'])} over the last 5.</p>"
        + f"<p class='note'>Adjusted EPS: Yahoo's reported quarterly EPS (the basis analysts "
        f"use, without amortization and one-offs), split-adjusted. Last four quarters, by "
        f"report date: {quarters}. Full-year EPS is the trailing figure at the Q4 report; "
        f"P/E uses the year's average price. The chart shows the daily price over the "
        f"trailing adjusted EPS known that day.{fixes}</p>"
    )


def render(d: dict, k: dict, run_label: str) -> str:
    stock, row = d["stock"], d["row"]
    sym = stock["symbol"]
    name = row.get("name") or sym
    updated, notes = read_notes(sym)
    verdict = notes.get("Verdict", "_No verdict written yet: add one to notes.md._")
    latest, yearly = absolute_tables(d)

    def note(section: str) -> str:
        return md(notes[section]) if section in notes else "<p class='note'>Not written yet.</p>"

    gap = k["to_entry"]
    gap_text = (
        f"{abs(gap):.0%} {'below' if gap < 0 else 'above'} today's price"
        if np.isfinite(gap)
        else "–"
    )
    nxt = (
        f"Next report {k['next_report']} (EPS estimate {money(k['next_estimate'])}); "
        f"if met, the entry price becomes {money(k['entry_after_next'])}."
        if k["next_report"]
        else ""
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h1>{html.escape(name)} ({sym})</h1>
<div class="sub">Watch list analysis, {run_label}. Latest prices on {k["price_date"]}.
Claude's notes updated {html.escape(updated or "never")}.</div>

<h2>1. Summary</h2>
<div class="verdict">{md(verdict)}</div>
<div class="key">
 <div><span>Price</span><b>{money(k["price"])}</b></div>
 <div><span>Adjusted P/E, 12m</span><b>{times(k["pe_adj"])}</b></div>
 <div><span>10-year median P/E</span><b>{times(k["pe_median_10y"])}</b></div>
 <div><span>Entry at {k["target_pe"]:g}x</span><b>{money(k["entry_price"])}</b>
  <span>{gap_text}</span></div>
</div>
{note("Summary")}

<h2 class="page">2. The numbers</h2>
<h3>Absolute values, latest 12 months</h3>
{latest}
<h3>Absolute values by year (SEC filings; Yahoo where SEC has no figure)</h3>
{yearly}
{screens_html(d)}
<h3>DCF</h3>
{dcf_html(row)}

<h2 class="page">3. Analysis</h2>
<h3>Adjusted P/E against its own 10-year history</h3>
{pe_history_html(d, k)}
<h3>Entry price</h3>
<p>At {k["target_pe"]:g}x trailing adjusted EPS of {money(k["eps_adj_ttm"])}, the entry price is
<b>{money(k["entry_price"])}</b>, {gap_text}. The 10-year range of yearly P/E is
{times(k["pe_low_10y"])} to {times(k["pe_high_10y"])} (years of collapsed earnings, such as 2020,
show very high P/Es). {nxt}</p>
<p class="note">Target: {html.escape(stock.get("target_note", ""))}</p>
<h3>Business</h3>
{note("Business")}
<h3>Risks</h3>
{note("Risks")}
<h3>News</h3>
{note("News")}
<h3>What to watch</h3>
{note("What to watch")}

<h3>Caveats</h3>
<ul class="note">
<li>Yahoo data is unofficial; capex can include acquisitions or stakes, so check SEC capex.</li>
<li>The peer group is hand-picked, so the weighted scores depend on it.</li>
<li>Claude's notes are dated above and may be older than the numbers.</li>
</ul>
<p class="note">Reproduce: <code>uv run python analysis/watchlist.py {sym}</code></p>
</body></html>"""


def render_summary(results: list[tuple[dict, dict]], run_label: str) -> str:
    """One PDF summarising every stock analysed in this run, in the same three parts."""
    rows, lines, parts = [], [], []
    for d, k in results:
        sym = d["stock"]["symbol"]
        rows.append(
            [
                f"<b>{sym}</b>",
                money(k["price"]),
                times(k["pe_adj"]),
                times(k["pe_median_10y"]),
                f"{k['target_pe']:g}x",
                money(k["entry_price"]),
                pct(k["to_entry"]),
                k["next_report"] or "–",
            ]
        )
        gap = k["to_entry"]
        where = (
            "at or below its entry price"
            if np.isfinite(gap) and gap >= 0
            else f"{abs(gap):.0%} above its entry price of {money(k['entry_price'])}"
        )
        lines.append(f"<li><b>{sym}</b> {money(k['price'])}: {where}.</li>")
        _, notes = read_notes(sym)
        parts.append(
            f"<h3>{html.escape(d['row'].get('name') or sym)} ({sym})</h3>"
            f"<div class='verdict'>{md(notes.get('Verdict', 'No verdict written yet.'))}</div>"
            f"{md(notes.get('Summary', ''))}"
        )
    updated, notes = read_notes("summaries")
    verdict = notes.get("Verdict", "")
    head = table(
        [
            "Stock",
            "Price",
            "Adjusted P/E",
            "10-yr median",
            "Target",
            "Entry price",
            "Entry vs price",
            "Next report",
        ],
        rows,
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>
<h1>Watch list summary</h1>
<div class="sub">{run_label}. Claude's notes updated {html.escape(updated or "never")}.</div>

<h2>1. Summary</h2>
{f'<div class="verdict">{md(verdict)}</div>' if verdict else ""}
<ul>{"".join(lines)}</ul>

<h2>2. The numbers</h2>
{head}
<p class="note">Entry price = target multiple x trailing 12-month adjusted EPS. A negative
"entry vs price" means the entry price is below today's price.</p>

<h2>3. Analysis</h2>
{md(notes.get("Analysis", ""))}
{"".join(parts)}
<p class="note">Each stock's full analysis is in its own PDF from the same run.</p>
</body></html>"""


# --- PDF and the dated lists ---------------------------------------------------------


def chrome() -> str:
    found = os.environ.get("CHROME_PATH") or next(
        (str(p) for p in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux*/chrome"))),
        None,
    )
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = found or shutil.which(name)
    if not found:
        raise RuntimeError("No Chrome or Chromium found; set CHROME_PATH")
    return found


def to_pdf(page: str, pdf: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "page.html"
        src.write_text(page)
        subprocess.run(
            [
                chrome(),
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--no-pdf-header-footer",  # a custom --user-data-dir makes it hang
                f"--print-to-pdf={pdf}",
                src.as_uri(),
            ],
            check=True,
            capture_output=True,
            timeout=120,
        )
    if not pdf.exists() or pdf.stat().st_size == 0:
        raise RuntimeError(f"Chrome did not write {pdf}")


RUN_COLUMNS = [
    "run",
    "file",
    "price",
    "eps_adj_ttm",
    "pe_adj",
    "pe_median_10y",
    "target_pe",
    "entry_price",
    "to_entry",
    "verdict",
]


def first_sentence(text: str) -> str:
    plain = re.sub(r"[*_`]", "", text).strip()
    return re.split(r"(?<=[.!?])\s", plain, maxsplit=1)[0] if plain else ""


def record_run(sym: str, run: str, file: str, k: dict) -> pd.DataFrame:
    path = OUT / sym / "runs.csv"
    _, notes = read_notes(sym)
    new = {c: k.get(c) for c in RUN_COLUMNS} | {
        "run": run,
        "file": file,
        "verdict": first_sentence(notes.get("Verdict", "")),
    }
    runs = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=RUN_COLUMNS)
    runs = pd.concat([runs, pd.DataFrame([new])], ignore_index=True)
    runs.to_csv(path, index=False, float_format="%.4f")
    return runs


def stock_index(sym: str, name: str, runs: pd.DataFrame) -> str:
    lines = [
        f"# {name} ({sym}): dated analyses",
        "",
        "Every analysis of this stock, newest first. Each PDF has the summary, the numbers, "
        "and Claude's analysis. Claude's current notes are in [notes.md](notes.md).",
        "",
        "| Date and time | Price | Adjusted P/E | 10-yr median | Entry price | vs price "
        "| Verdict | PDF |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, r in runs.iloc[::-1].iterrows():
        lines.append(
            f"| {r['run']} | {money(r['price'])} | {times(r['pe_adj'])} "
            f"| {times(r['pe_median_10y'])} | {money(r['entry_price'])} "
            f"| {pct(r['to_entry'])} | {r['verdict'] if isinstance(r['verdict'], str) else ''} "
            f"| [{r['file']}]({r['file']}) |"
        )
    return "\n".join(lines) + "\n"


def overview(cfg: dict) -> str:
    lines = [
        "# Watch list analyses",
        "",
        "Each stock on the watch list ([config/watchlist.toml](../config/watchlist.toml)) is "
        "analysed every evening and saved as a dated PDF in its own folder. Nothing is "
        "overwritten: every run, including several in one day, stays in the stock's dated "
        "list. Each run also writes one summary PDF of all the stocks to "
        "[summaries/](summaries/). Built by `uv run python analysis/watchlist.py`.",
        "",
        "| Stock | Latest analysis | Price | Adjusted P/E | 10-yr median | Target | "
        "Entry price | vs price | All analyses |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    on_list = [s["symbol"] for s in cfg["stock"]]
    skip = set(on_list) | {"market"}
    others = sorted(p.parent.name for p in OUT.glob("*/runs.csv") if p.parent.name not in skip)
    for sym in on_list + others:
        path = OUT / sym / "runs.csv"
        if not path.exists():
            lines.append(f"| {sym} | none yet | | | | | | | |")
            continue
        r = pd.read_csv(path).iloc[-1]
        tag = "" if sym in on_list else " (off the list)"
        lines.append(
            f"| {sym}{tag} | [{r['run']}]({sym}/{r['file']}) | {money(r['price'])} "
            f"| {times(r['pe_adj'])} | {times(r['pe_median_10y'])} | {r['target_pe']:g}x "
            f"| {money(r['entry_price'])} | {pct(r['to_entry'])} | [list]({sym}/README.md) |"
        )
    lines.append("")
    for folder, title in (("market", "Market report"), ("summaries", "Watch list summary")):
        pdfs = sorted((OUT / folder).glob("*.pdf"), reverse=True)
        links = ", ".join(f"[{p.stem}]({folder}/{p.name})" for p in pdfs)
        lines.append(f"**{title}**, newest first: {links or 'none yet'}")
        lines.append("")
    return "\n".join(lines)


# --- main ----------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("symbols", nargs="*", help="only these stocks (default: the whole list)")
    ap.add_argument("--numbers", action="store_true", help="print key numbers, write nothing")
    ap.add_argument("--no-market", action="store_true", help="skip the market report")
    args = ap.parse_args()

    cfg = load_watchlist()
    stocks = [s for s in cfg["stock"] if not args.symbols or s["symbol"] in args.symbols]
    if not stocks:
        raise SystemExit(f"Not on the watch list: {args.symbols}")
    tz = ZoneInfo(cfg["timezone"])
    local = datetime.now(tz)
    now = pd.Timestamp(local.astimezone(ZoneInfo("UTC")).replace(tzinfo=None))

    symbols = sorted({x for s in stocks for x in [s["symbol"], *s["peers"]]})
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = dict(zip(symbols, pool.map(fetch_row, symbols), strict=True))

    stamp = local.strftime("%Y-%m-%d_%H%M")
    run_label = local.strftime("%Y-%m-%d %H:%M ") + local.tzname()
    results, written = [], []
    if not args.numbers and not args.no_market and not args.symbols:
        import market  # the whole-market report goes with the full evening run

        written.append(market.build(local))
    for stock in stocks:
        sym = stock["symbol"]
        d = gather(stock, rows, now)
        k = key_numbers(d)
        print(
            f"{sym}: price {money(k['price'])}, adjusted EPS {money(k['eps_adj_ttm'])}, "
            f"P/E {times(k['pe_adj'])} vs 10-yr median {times(k['pe_median_10y'])}, "
            f"entry {money(k['entry_price'])} at {k['target_pe']:g}x ({pct(k['to_entry'])}), "
            f"next report {k['next_report'] or '–'}"
        )
        if args.numbers:
            continue
        results.append((d, k))
        pdf = new_pdf(OUT / sym, stamp)
        to_pdf(render(d, k, run_label), pdf)
        runs = record_run(sym, run_label, pdf.name, k)
        (OUT / sym / "README.md").write_text(stock_index(sym, d["row"].get("name") or sym, runs))
        written.append(pdf)
    if args.numbers:
        return
    pdf = new_pdf(OUT / "summaries", stamp)
    to_pdf(render_summary(results, run_label), pdf)
    written.append(pdf)
    (OUT / "README.md").write_text(overview(cfg))
    print("\nWrote:")
    for p in written:
        print(f"  {p.relative_to(ROOT)}")
    EMAIL.parent.mkdir(parents=True, exist_ok=True)
    EMAIL.write_text(email_html(run_label, written, results))
    print(f"\nEmail subject: Watch list analyses, {run_label}")
    print(f"Email body (HTML): {EMAIL.relative_to(ROOT)}")
    LAST_RUN.write_text(
        json.dumps(
            {
                "subject": f"Watch list analyses, {run_label}",
                "html": str(EMAIL.relative_to(ROOT)),
                "files": [str(p.relative_to(ROOT)) for p in written],
            },
            indent=2,
        )
    )


# --- the evening email ---------------------------------------------------------------

REPO_URL = "https://github.com/khalilvandian/Stock-analysis/blob"
EMAIL = ROOT / ".cache/watchlist/email.html"
LAST_RUN = ROOT / ".cache/watchlist/last_run.json"  # read by analysis/send_email.py


def link(path: Path) -> str:
    """GitHub page for a file on the branch the run is pushed to (shows PDFs in the browser)."""
    branch = os.environ.get("WATCHLIST_BRANCH", "main")
    return f"{REPO_URL}/{branch}/{path.relative_to(ROOT).as_posix()}"


def email_html(run_label: str, written: list[Path], results: list[tuple[dict, dict]]) -> str:
    """Email body: the high-level summary first, then the PDFs (attached, and linked)."""
    parts = [f"<h2>Watch list analyses, {html.escape(run_label)}</h2>"]
    market_runs = OUT / "market/runs.csv"
    if any(p.parent.name == "market" for p in written) and market_runs.exists():
        r = pd.read_csv(market_runs).iloc[-1]
        _, notes = read_notes("market")
        parts += [
            "<h3>Market</h3>",
            md(notes.get("Verdict", "")),
            f"<p>S&amp;P 500 {r['sp500']:,.0f} ({pct(r['sp500_day'])} today), VIX "
            f"{r['vix']:.1f}, {r['above_200d']:.0%} of S&amp;P 500 stocks above their "
            f"200-day average. Stocks to look at: {html.escape(str(r['stocks_to_look_at']))}.</p>",
        ]
    _, notes = read_notes("summaries")
    parts += ["<h3>Watch list</h3>", md(notes.get("Verdict", "")), "<ul>"]
    for d, k in results:
        sym = d["stock"]["symbol"]
        verdict = first_sentence(read_notes(sym)[1].get("Verdict", ""))
        parts.append(
            f"<li><b>{sym}</b> {money(k['price'])}, adjusted P/E {times(k['pe_adj'])} "
            f"(10-yr median {times(k['pe_median_10y'])}); entry {money(k['entry_price'])} at "
            f"{k['target_pe']:g}x, {pct(k['to_entry'])} from today's price. "
            f"{html.escape(verdict)}</li>"
        )
    parts += ["</ul>", "<h3>The PDFs (attached, and online here)</h3>", "<ul>"]
    names = {"market": "Market report", "summaries": "Watch list summary"}
    for p in written:
        title = names.get(p.parent.name, f"{p.parent.name} analysis")
        parts.append(f'<li><a href="{link(p)}">{title}</a> ({p.name})</li>')
    parts += [
        "</ul>",
        f'<p>Every dated analysis: <a href="{link(OUT / "README.md")}">analyses</a>.</p>',
    ]
    return "\n".join(parts)


def new_pdf(folder: Path, stamp: str) -> Path:
    """A dated PDF path that never overwrites an earlier run."""
    folder.mkdir(parents=True, exist_ok=True)
    pdf, n = folder / f"{stamp}.pdf", 1
    while pdf.exists():
        n += 1
        pdf = folder / f"{stamp}-{n}.pdf"
    return pdf


if __name__ == "__main__":
    main()
