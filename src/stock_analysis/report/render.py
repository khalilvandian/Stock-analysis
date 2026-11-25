"""The pages of a run's reports, and their PDFs: one per stock and the watch list summary
(market.py has the market report), and the email's body. Everything comes from the numbers and
analyses passed in; run.py reads them from the database.

A stock's report has three parts, in this order:
  1. Summary: the verdict and key points of Claude's analysis, plus price against entry price.
  2. The numbers: absolute values (latest 12 months and yearly history), ratios, the strict
     and weighted screens against the stock's peers, and the standard DCF.
  3. Analysis: adjusted P/E against the stock's own 10-year history, Claude's EPS corrections
     next to the stored figures, the entry price if the stock has a target, then business,
     risks, news and what to watch.

Adjusted EPS is Yahoo's reported quarterly EPS, on the same basis as analysts' estimates
(excluding amortization and one-offs), split-adjusted, with user_eps_override applied.
"""

from __future__ import annotations

import html
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

import markdown
import numpy as np
import pandas as pd

from .. import absolute, screen, stocks
from ..nightly import YEARS, daily_pe, key_numbers, trailing_eps, yearly_pe

PAGES_URL = "https://khalilvandian.github.io/Stock-analysis"  # built by analysis/site.py


@dataclass
class Analysis:
    """Claude's analysis of one subject (out_analysis)."""

    reviewed: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    corrections: list[dict] = field(default_factory=list)


EMPTY = Analysis()


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


def target_text(v) -> str:
    """'20x', or '–' for a stock without a target."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "–"
    return f"{v:g}x" if np.isfinite(v) and v > 0 else "–"


def price_at(k: dict, multiple: str) -> str:
    """Price at one of the stock's own P/E levels, on trailing adjusted EPS (+ stakes)."""
    pe, eps = k[multiple], k["eps_adj_ttm"]
    if not (np.isfinite(pe) and np.isfinite(eps)) or eps <= 0:
        return "–"
    return money(pe * eps + (k.get("stakes_per_share") or 0.0))


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
    """Inline SVG of daily trailing adjusted P/E with the 10-year median and the target.

    The target line is left out when the stock has no target (target is NaN).
    """
    pe = pe[pe.index >= pe.index.max() - pd.DateOffset(years=YEARS)]
    if pe.empty:
        return ""
    w, h, pad = 700, 220, 36
    points = pe.resample("2W").last().dropna()  # every two weeks keeps the PDF light
    # cap the axis so years of near-zero earnings (e.g. 2020) don't flatten the rest
    top = min(float(np.nanpercentile(points, 99)) * 1.1, median * 2.5)
    has_target = bool(np.isfinite(target))
    top = max(top, median * 1.3, float(points.iloc[-1]) * 1.2)
    if has_target:
        top = max(top, target * 1.3)
    t0, t1 = points.index[0].value, points.index[-1].value

    def x(ts: pd.Timestamp) -> float:
        return pad + (ts.value - t0) / (t1 - t0) * (w - 2 * pad)

    def y(v: float) -> float:
        return h - pad - min(v, top) / top * (h - 2 * pad)

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in points.items())
    grid = []
    step = next(st for st in (5, 10, 20, 50, 100) if top / st <= 8)
    for v in range(0, int(top) + 1, step):
        grid.append(
            f'<line x1="{pad}" x2="{w - pad}" y1="{y(v):.1f}" y2="{y(v):.1f}" class="grid"/>'
            f'<text x="{pad - 6}" y="{y(v) + 4:.1f}" class="ax" text-anchor="end">{v}x</text>'
        )
    for yr in range(points.index[0].year + 1, points.index[-1].year + 1):
        ts = pd.Timestamp(f"{yr}-01-01")
        grid.append(f'<text x="{x(ts):.1f}" y="{h - pad + 16}" class="ax">{yr}</text>')
    last = points.iloc[-1]
    target_line = (
        f'<line x1="{pad}" x2="{w - pad}" y1="{y(target):.1f}" y2="{y(target):.1f}" class="tgt"/>'
        f'<text x="{w - pad}" y="{y(target) + 13:.1f}" class="lab tgtl" text-anchor="end">'
        f"target {target:g}x</text>"
        if has_target
        else ""
    )
    return f"""<svg viewBox="0 0 {w} {h}" class="chart" xmlns="http://www.w3.org/2000/svg">
{"".join(grid)}
<line x1="{pad}" x2="{w - pad}" y1="{y(median):.1f}" y2="{y(median):.1f}" class="med"/>
<text x="{w - pad}" y="{y(median) - 5:.1f}" class="lab" text-anchor="end">
10-yr median {median:.0f}x</text>
{target_line}
<polyline points="{pts}" class="line"/>
<circle cx="{x(points.index[-1]):.1f}" cy="{y(last):.1f}" r="4" class="dot"/>
</svg>"""


CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font-family: "Liberation Sans", Helvetica, Arial, sans-serif; font-size: 9.5pt;
       color: #1b1f24; line-height: 1.4; }
ul { list-style-type: square; }
code { font-family: "Liberation Mono", Courier, monospace; }
h1 { font-size: 17pt; margin: 0 0 2px; }
h2 { font-size: 13pt; margin: 18px 0 6px; border-bottom: 2px solid #1b1f24; padding-bottom: 2px; }
h3 { font-size: 10.5pt; margin: 12px 0 4px; }
.sub { color: #57606a; margin-bottom: 10px; }
.verdict { font-size: 11pt; font-weight: bold; background: #f3f5f8; padding: 8px 10px;
           border-left: 4px solid #2f6feb; margin: 8px 0; }
.key { display: flex; gap: 8px; margin: 8px 0; }
.key div { flex: 1; background: #f6f8fa; padding: 6px 8px; }
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
        _, weighted = screen.run_screens(peers)
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
        ["Growth forever", pct(stocks.TERMINAL_GROWTH, False)],
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


def with_corrections(d: dict, corrections: list[dict]) -> dict:
    """The stock's numbers with Claude's EPS corrections in place of the stored quarters
    (only for the report: nothing stored changes). Dates that match no quarter are ignored."""
    q = d["quarters"].copy()
    for c in corrections:
        day = pd.Timestamp(c["reported"]).normalize()
        if day in q.index:
            q[day] = float(c["eps"])
    return {**d, "quarters": q, "ttm": trailing_eps(q)}


def corrections_html(d: dict, k: dict, a: Analysis) -> str:
    """Claude's EPS corrections: each one, and the figures stored and corrected side by side."""
    if not a.corrections:
        return ""
    quarters = d["quarters"]
    items = []
    for c in sorted(a.corrections, key=lambda c: c["reported"]):
        day = pd.Timestamp(c["reported"]).normalize()
        stored = money(quarters[day]) if day in quarters.index else "no quarter on that date"
        items.append(
            [
                html.escape(c["reported"]),
                stored,
                money(c["eps"]),
                html.escape(c["reason"]),
                inline_source(c["source"]),
            ]
        )
    f = key_numbers(with_corrections(d, a.corrections))
    rows = [
        ["Adjusted EPS, 12 months", money(k["eps_adj_ttm"]), money(f["eps_adj_ttm"])],
        ["Adjusted P/E", times(k["pe_adj"]), times(f["pe_adj"])],
        ["10-year median P/E", times(k["pe_median_10y"]), times(f["pe_median_10y"])],
    ]
    if np.isfinite(k["target_pe"]):
        rows.append(["Entry price", money(k["entry_price"]), money(f["entry_price"])])
    return (
        "<h3>Claude's EPS corrections</h3>"
        + table(["Reported", "Stored EPS", "Corrected", "Reason", "Source"], items)
        + table(["", "As stored", "With the corrections"], rows)
        + "<p class='note'>The corrections are part of this analysis only. Every other figure "
        "in the report, and the stored data, is as stored.</p>"
    )


def inline_source(source: str) -> str:
    """A source as text, or as a link when it is an address."""
    text = html.escape(source)
    return f'<a href="{text}">link</a>' if re.fullmatch(r"https?://\S+", source) else text


def render(d: dict, k: dict, run_label: str, a: Analysis) -> str:
    stock, row = d["stock"], d["row"]
    sym = stock["symbol"]
    name = row.get("name") or sym
    updated, notes = a.reviewed, a.sections
    verdict = notes.get("Verdict", "_No verdict written yet._")
    latest, yearly = absolute_tables(d)

    def note(section: str) -> str:
        return md(notes[section]) if section in notes else "<p class='note'>Not written yet.</p>"

    has_target = bool(np.isfinite(k["target_pe"]))
    gap = k["to_entry"]
    gap_text = (
        f"{abs(gap):.0%} {'below' if gap < 0 else 'above'} today's price"
        if np.isfinite(gap)
        else "–"
    )
    stakes_text = (
        f" plus {money(k['stakes_per_share'])} a share of equity stakes (kept out of the P/E)"
        if k.get("stakes_per_share")
        else ""
    )
    nxt = (
        f"Next report {k['next_report']} (EPS estimate {money(k['next_estimate'])}); "
        f"if met, the entry price becomes {money(k['entry_after_next'])}."
        if k["next_report"] and has_target
        else ""
    )
    entry_box = (
        f"<div><span>Entry at {k['target_pe']:g}x</span><b>{money(k['entry_price'])}</b>"
        f"<span>{gap_text}</span></div>"
        if has_target
        else "<div><span>Entry price</span><b>no target</b></div>"
    )
    entry_section = (
        f"""<p>At {k["target_pe"]:g}x trailing adjusted EPS of
{money(k["eps_adj_ttm"])}{stakes_text}, the entry price is
<b>{money(k["entry_price"])}</b>, {gap_text}. The 10-year range of yearly P/E is
{times(k["pe_low_10y"])} to {times(k["pe_high_10y"])} (years of collapsed earnings, such as 2020,
show very high P/Es). {nxt}</p>
<p class="note">Target: {html.escape(stock.get("target_note") or "")}</p>"""
        if has_target
        else f"""<p>No target is set for this stock, so there is no entry price. For reference,
the price at the yearly P/E of its own history: {price_at(k, "pe_low_10y")} at the 10-year low
({times(k["pe_low_10y"])}), {price_at(k, "pe_median_5y")} at the 5-year median
({times(k["pe_median_5y"])}) and {price_at(k, "pe_median_10y")} at the 10-year median
({times(k["pe_median_10y"])}), on trailing adjusted EPS of {money(k["eps_adj_ttm"])}.</p>
{f'<p class="note">{html.escape(stock["target_note"])}</p>' if stock.get("target_note") else ""}"""
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
 {entry_box}
</div>
<h3>Today</h3>
{note("Today")}
{note("Summary")}

<h2 class="page">2. The numbers</h2>
<h3>Absolute values, latest 12 months</h3>
{latest}
<h3>Absolute values by year (SEC filings; Yahoo where SEC has no figure; from the database)</h3>
{yearly}
{screens_html(d)}
<h3>DCF</h3>
{dcf_html(row)}

<h2 class="page">3. Analysis</h2>
<h3>Adjusted P/E against its own 10-year history</h3>
{pe_history_html(d, k)}
{corrections_html(d, k, a)}
<h3>Entry price</h3>
{entry_section}
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
<li>Prices are the database's latest close (the ingest runs after the US close), not
live quotes. Yahoo data is unofficial; capex can include acquisitions or stakes, so check
SEC capex.</li>
<li>The peer group is hand-picked, so the weighted scores depend on it.</li>
<li>Claude's notes are written for each run from the day's news, linked in News; the build
stops if a section was not reviewed for the run.</li>
</ul>
</body></html>"""


def render_summary(
    results: list[tuple[dict, dict]], run_label: str, analyses: dict[str, Analysis]
) -> str:
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
                target_text(k["target_pe"]),
                money(k["entry_price"]),
                pct(k["to_entry"]),
                k["next_report"] or "–",
            ]
        )
        gap = k["to_entry"]
        if not np.isfinite(k["target_pe"]):
            where = f"adjusted P/E {times(k['pe_adj'])}, no target set"
        elif np.isfinite(gap) and gap >= 0:
            where = "at or below its entry price"
        else:
            where = f"{abs(gap):.0%} above its entry price of {money(k['entry_price'])}"
        lines.append(f"<li><b>{sym}</b> {money(k['price'])}: {where}.</li>")
        notes = analyses.get(sym, EMPTY).sections
        parts.append(
            f"<h3>{html.escape(d['row'].get('name') or sym)} ({sym})</h3>"
            f"<div class='verdict'>{md(notes.get('Verdict', 'No verdict written yet.'))}</div>"
            f"{md(notes.get('Summary', ''))}"
        )
    a = analyses.get("summaries", EMPTY)
    updated, notes = a.reviewed, a.sections
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
<p class="note">Entry price = target multiple x trailing 12-month adjusted EPS, for stocks
with a target. A negative "entry vs price" means the entry price is below today's price.</p>

<h2>3. Analysis</h2>
{md(notes.get("Analysis", ""))}
{"".join(parts)}
<p class="note">Each stock's full analysis is in its own PDF from the same run.</p>
</body></html>"""


# --- PDF ---


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
        src.write_text(page, encoding="utf-8")
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
    "price",
    "eps_adj_ttm",
    "pe_adj",
    "pe_median_10y",
    "target_pe",
    "entry_price",
    "to_entry",
    "stakes_per_share",
]


def local_label(run_at: str, tz: ZoneInfo) -> str:
    """A run time stored in UTC as it reads in the watch list's time zone."""
    t = pd.Timestamp(run_at).tz_localize("UTC").tz_convert(tz)
    return t.strftime("%Y-%m-%d %H:%M ") + t.tzname()


def first_sentence(text: str) -> str:
    plain = re.sub(r"[*_`]", "", text).strip()
    return re.split(r"(?<=[.!?])\s", plain, maxsplit=1)[0] if plain else ""


# --- the email ---


def email_html(
    run_label: str,
    files: list[str],
    results: list[tuple[dict, dict]],
    analyses: dict[str, Analysis],
    market: dict | None = None,
    failed: list[str] | None = None,
) -> str:
    """Email body: what failed (if anything), the high-level summary, then the PDFs."""
    parts = [f"<h2>Watch list analyses, {html.escape(run_label)}</h2>"]
    if failed:
        parts.append("<p><b>Not built tonight:</b></p><ul>")
        parts += [f"<li>{html.escape(f)}</li>" for f in failed]
        parts.append("</ul>")
    if market:
        r = market
        notes = analyses.get("market", EMPTY).sections
        parts += [
            "<h3>Market</h3>",
            md(notes.get("Verdict", "")),
            f"<p>S&amp;P 500 {r['sp500']:,.0f} ({pct(r['sp500_day'])} today), VIX "
            f"{r['vix']:.1f}, {r['above_200d']:.0%} of S&amp;P 500 stocks above their "
            f"200-day average.</p>",
        ]
        if r.get("screener_listed") is not None:
            parts.append(
                f"<p>Market screener: {int(r['screener_passed'])} of "
                f"{int(r['screener_screened'])} S&amp;P 500 companies have good financial "
                f"statements; {int(r['screener_listed'])} are cheap or close to cheap (top 3 per "
                f"sector, in the market report). Cheapest: "
                f"{html.escape(str(r['stocks_to_look_at']))}.</p>"
            )
        else:
            parts.append(f"<p>Stocks to look at: {html.escape(str(r['stocks_to_look_at']))}.</p>")
    notes = analyses.get("summaries", EMPTY).sections
    parts += ["<h3>Watch list</h3>", md(notes.get("Verdict", "")), "<ul>"]
    for d, k in results:
        sym = d["stock"]["symbol"]
        verdict = first_sentence(analyses.get(sym, EMPTY).sections.get("Verdict", ""))
        parts.append(
            f"<li><b>{sym}</b> {money(k['price'])}, adjusted P/E {times(k['pe_adj'])} "
            f"(10-yr median {times(k['pe_median_10y'])}); "
            + (
                f"entry {money(k['entry_price'])} at {k['target_pe']:g}x, "
                f"{pct(k['to_entry'])} from today's price. "
                if np.isfinite(k["target_pe"])
                else "no target set. "
            )
            + f"{html.escape(verdict)}</li>"
        )
    parts += ["</ul>", "<h3>The PDFs (attached, and online here)</h3>", "<ul>"]
    names = {"market": "Market report", "summaries": "Watch list summary"}
    for f in files:
        folder, name = f.split("/")
        title = names.get(folder, f"{folder} analysis")
        parts.append(f'<li><a href="{PAGES_URL}/{f}">{title}</a> ({name})</li>')
    parts += [
        "</ul>",
        f'<p>Every dated analysis: <a href="{PAGES_URL}/">analyses</a>.</p>',
    ]
    return "\n".join(parts)
