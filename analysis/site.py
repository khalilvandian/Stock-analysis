"""Build the public website of the watch list analyses (GitHub Pages).

Pages: an overview (market strip and one card per stock), one page per stock (verdict,
key numbers, Claude's notes, every dated PDF), the market reports, the market screener's
latest top 3 per sector (data/screener/) and the watch list summaries, with a menu on
every page. The PDFs are copied next to the pages, so a link opens the report in the
browser. The evening run commits to `main`; the Pages workflow
(.github/workflows/pages.yml) then runs this and publishes `_site/` at
https://khalilvandian.github.io/Stock-analysis/.

Standard library only, so the workflow needs no install step.

Usage:
    python analysis/site.py [OUT_DIR]
"""

from __future__ import annotations

import csv
import html
import re
import shutil
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYSES = ROOT / "analyses"
CONFIG = ROOT / "config/watchlist.toml"
SCREENER = ROOT / "data/screener"  # written by analysis/screener.py
SITE = ROOT / "_site"
URL = "https://khalilvandian.github.io/Stock-analysis/"

CSS = """
:root {
  --bg: #f6f7f9; --card: #ffffff; --text: #16181d; --muted: #5d6573; --line: #e3e6eb;
  --brand: #1f4fd1; --brand-soft: #e8eefc; --good: #137a3f; --good-soft: #e3f4ea;
  --warn: #9a5b00; --warn-soft: #fdf1dc; --bar: #0f172a; --bar-text: #e8ecf3;
  --shadow: 0 1px 2px rgba(16, 24, 40, .06), 0 1px 3px rgba(16, 24, 40, .08);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --card: #161b22; --text: #e6edf3; --muted: #8d96a0; --line: #2a313c;
    --brand: #6ea0ff; --brand-soft: #1b2740; --good: #4cc27a; --good-soft: #13291d;
    --warn: #e0a548; --warn-soft: #2e2413; --bar: #010409; --bar-text: #e6edf3;
    --shadow: none;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text); line-height: 1.5;
  font-family: Inter, -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
a { color: var(--brand); text-decoration: none; }
a:hover { text-decoration: underline; }
header.bar { background: var(--bar); color: var(--bar-text); position: sticky; top: 0; z-index: 5; }
.bar .in { max-width: 1100px; margin: 0 auto; padding: 0 16px; display: flex;
  align-items: center; gap: 24px; height: 56px; }
.brand { font-weight: 700; color: var(--bar-text); white-space: nowrap; letter-spacing: .2px; }
.brand span { color: #7aa2ff; }
nav { display: flex; gap: 4px; overflow-x: auto; scrollbar-width: none; }
nav a { color: #b8c2d3; padding: 8px 12px; border-radius: 8px; white-space: nowrap;
  font-size: .94em; }
nav a:hover { background: rgba(255, 255, 255, .08); color: #fff; text-decoration: none; }
nav a.on { background: rgba(122, 162, 255, .18); color: #fff; }
main { max-width: 1100px; margin: 0 auto; padding: 28px 16px 64px; }
h1 { font-size: 1.9em; margin: 0 0 4px; letter-spacing: -.3px; }
h2 { font-size: 1.2em; margin: 36px 0 12px; }
.sub { color: var(--muted); margin: 0 0 24px; }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 12px;
  box-shadow: var(--shadow); }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.stock { padding: 18px 20px; display: flex; flex-direction: column; gap: 12px; color: var(--text); }
.stock:hover { border-color: var(--brand); text-decoration: none; }
.stock .top { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.sym { font-size: 1.35em; font-weight: 700; }
.name { color: var(--muted); font-size: .9em; }
.price { font-size: 1.35em; font-weight: 600; font-variant-numeric: tabular-nums; }
.verdict { color: var(--muted); font-size: .93em; margin: 0; }
.kv { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.kv div { background: var(--bg); border-radius: 8px; padding: 8px 10px; }
.kv b { display: block; font-size: 1.05em; font-variant-numeric: tabular-nums; }
.kv small { color: var(--muted); font-size: .78em; }
.badge { display: inline-block; align-self: flex-start; font-size: .8em; font-weight: 600;
  padding: 3px 10px; border-radius: 999px; background: var(--brand-soft); color: var(--brand);
  white-space: nowrap; }
.badge.good { background: var(--good-soft); color: var(--good); }
.badge.warn { background: var(--warn-soft); color: var(--warn); }
.strip { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
.tile { padding: 14px 16px; }
.tile small { color: var(--muted); display: block; font-size: .8em; }
.tile b { font-size: 1.3em; font-variant-numeric: tabular-nums; }
.callout { padding: 16px 20px; border-left: 4px solid var(--brand); }
.callout p { margin: 0; }
.btn { display: inline-block; background: var(--brand); color: #fff; padding: 9px 16px;
  border-radius: 8px; font-weight: 600; font-size: .95em; }
.btn:hover { text-decoration: none; opacity: .92; }
.btn.ghost { background: transparent; color: var(--brand); border: 1px solid var(--line); }
.row { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin: 16px 0; }
.cols { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.notes { padding: 4px 20px 12px; }
.notes h3 { font-size: 1em; margin: 16px 0 6px; }
.notes ul { padding-left: 18px; margin: 6px 0; }
.notes p, .notes li { font-size: .95em; }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .92em; }
th, td { padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left;
  vertical-align: top; }
th { color: var(--muted); font-weight: 600; font-size: .85em; text-transform: uppercase;
  letter-spacing: .4px; }
tr:last-child td { border-bottom: 0; }
td.d { white-space: nowrap; }
td.n { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.split { display: grid; grid-template-columns: 230px 1fr; gap: 28px; align-items: start; }
aside.side { position: sticky; top: 76px; }
.split > * { min-width: 0; }
.side h4 { font-size: .75em; text-transform: uppercase; letter-spacing: .5px; color: var(--muted);
  margin: 0 0 8px 4px; }
.side .list { display: flex; flex-direction: column; gap: 4px; margin-bottom: 22px; }
.side a.it { display: flex; justify-content: space-between; align-items: center; gap: 8px;
  padding: 9px 12px; border-radius: 10px; color: var(--text); border: 1px solid transparent; }
.side a.it:hover { background: var(--card); border-color: var(--line); text-decoration: none; }
.side a.it.on { background: var(--card); border-color: var(--brand); }
.side a.it b { font-size: 1em; }
.side a.it small { color: var(--muted); font-variant-numeric: tabular-nums; }
.side a.it.old { color: var(--muted); }
.dot { width: 8px; height: 8px; border-radius: 50%; background: var(--line); flex: none; }
.dot.good { background: var(--good); } .dot.warn { background: var(--warn); }
.panel { padding: 20px 22px; margin-bottom: 18px; scroll-margin-top: 76px; }
.panel .top { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;
  flex-wrap: wrap; }
.panel h2 { margin: 0; font-size: 1.3em; }
.panel .lead { margin: 12px 0; font-weight: 600; }
.panel ul { padding-left: 18px; margin: 8px 0 0; }
.panel .kv { grid-template-columns: repeat(4, 1fr); margin-top: 12px; }
.viewer { padding: 0; overflow: hidden; }
.viewer .head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  padding: 12px 16px; border-bottom: 1px solid var(--line); }
.viewer select { font: inherit; padding: 7px 10px; border-radius: 8px;
  border: 1px solid var(--line); background: var(--bg); color: var(--text); }
.viewer iframe { width: 100%; height: 80vh; border: 0; display: block; background: #fff; }
footer { color: var(--muted); font-size: .85em; text-align: center; padding: 24px 16px; }
@media (max-width: 860px) {
  .split { grid-template-columns: 1fr; gap: 12px; }
  aside.side { position: static; }
  .side .list { flex-direction: row; overflow-x: auto; }
  .side a.it { flex: none; background: var(--card); border-color: var(--line); }
  .panel .kv { grid-template-columns: repeat(2, 1fr); }
  .viewer iframe { height: 70vh; }
}
@media (max-width: 640px) {
  .bar .in { gap: 12px; } .brand { font-size: .95em; } h1 { font-size: 1.5em; }
}
"""


# --- reading the analyses folder ----------------------------------------------------


def read_runs(folder: Path) -> list[dict]:
    """The folder's runs.csv, newest first (empty if there is none)."""
    path = folder / "runs.csv"
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(reversed(list(csv.DictReader(f))))


def pdfs(folder: Path) -> list[str]:
    """The folder's dated PDFs, newest first."""
    return sorted((p.name for p in folder.glob("*.pdf")), reverse=True)


def title(folder: Path) -> str:
    """Company name from the folder's README heading, e.g. 'Boston Scientific Corporation (BSX)'."""
    readme = folder / "README.md"
    if readme.exists():
        m = re.match(r"#\s*(.+?):", readme.read_text().splitlines()[0])
        if m:
            return m.group(1)
    return folder.name


def company(folder: Path) -> str:
    """'Boston Scientific Corporation (BSX)' -> 'Boston Scientific Corporation'."""
    return re.sub(r"\s*\([^)]*\)$", "", title(folder))


def notes(folder: Path) -> dict[str, str]:
    """Sections of Claude's notes.md, by heading."""
    path = folder / "notes.md"
    if not path.exists():
        return {}
    out, name = {}, None
    for line in path.read_text().splitlines():
        if line.startswith("## "):
            name = line[3:].strip()
            out[name] = []
        elif name:
            out[name].append(line)
    return {k: "\n".join(v).strip() for k, v in out.items()}


def stocks() -> list[Path]:
    """Stock folders (they have runs.csv with a price), most recently analysed first."""
    found = [
        f
        for f in ANALYSES.iterdir()
        if f.is_dir() and f.name not in ("market", "summaries") and read_runs(f)
    ]
    return sorted(found, key=lambda f: read_runs(f)[0]["run"], reverse=True)


def active() -> list[str]:
    """Symbols on the watch list now, in config order."""
    if not CONFIG.exists():
        return []
    return [x["symbol"] for x in tomllib.loads(CONFIG.read_text()).get("stock", [])]


def watched() -> tuple[list[Path], list[Path]]:
    """(stocks on the watch list now, stocks analysed before but since removed)."""
    have = {f.name: f for f in stocks()}
    now = [have[s] for s in active() if s in have]
    return now, [f for f in have.values() if f not in now]


# --- formatting -------------------------------------------------------------------


def num(v, fmt: str) -> str:
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return "–"


def stamp(name: str) -> str:
    """'2026-10-27_1657.pdf' -> '2026-10-27 16:57'."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})", name)
    return f"{m.group(1)} {m.group(2)}:{m.group(3)}" if m else name


def esc(s) -> str:
    return html.escape(str(s))


def a(href: str, text: str, cls: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<a href="{esc(href)}"{c}>{esc(text)}</a>'


def inline(text: str) -> str:
    """Escape, then **bold**."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))


def md(text: str) -> str:
    """The small part of Markdown the notes use: paragraphs, bullet lists and bold."""
    out, items, para = [], [], []

    def close():
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()
        if items:
            out.append("<ul>" + "".join(f"<li>{inline(i)}</li>" for i in items) + "</ul>")
            items.clear()

    for line in text.splitlines():
        s = line.strip()
        if s.startswith("- "):
            if para:
                close()
            items.append(s[2:])
        elif not s:
            close()
        else:
            if items:
                close()
            para.append(s)
    close()
    return "\n".join(out)


def first_sentence(text: str) -> str:
    plain = re.sub(r"\*\*", "", text).strip()
    m = re.match(r"(.+?[.!?])(\s|$)", plain)
    return m.group(1) if m else plain


def badge(to_entry) -> str:
    """How far the price is from the entry price."""
    try:
        d = float(to_entry)
    except (TypeError, ValueError):
        return ""
    if d >= 0:
        return '<span class="badge good">At or below entry price</span>'
    if d > -0.10:
        return f'<span class="badge warn">{-d:.0%} above entry</span>'
    return f'<span class="badge">{-d:.0%} above entry</span>'


# --- pages ------------------------------------------------------------------------


def layout(title_: str, active: str, body: str, menu: list[tuple[str, str]]) -> str:
    links = "".join(
        f'<a href="{href}"{" class=on" if key == active else ""}>{esc(label)}</a>'
        for key, label, href in [(k, label, f"{k}.html") for k, label in menu]
    ).replace('href="index.html"', 'href="./"')
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title_)}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700"
        "&display=swap' rel='stylesheet'>"
        f"<style>{CSS}</style></head><body>"
        "<header class='bar'><div class='in'><a class='brand' href='./'>Watch list "
        f"<span>analyses</span></a><nav>{links}</nav></div></header>"
        f"<main>{body}</main>"
        "<footer>Analysed every evening at 21:00 Italy time. Every run is kept as a dated "
        "PDF. Not investment advice.</footer></body></html>"
    )


def market_strip(r: dict) -> str:
    tiles = [
        ("S&P 500", num(r.get("sp500"), "{:,.0f}"), num(r.get("sp500_day"), "{:+.1%} today")),
        ("VIX", num(r.get("vix"), "{:.1f}"), "fear gauge"),
        ("Above 200-day", num(r.get("above_200d"), "{:.0%}"), "of S&P 500 stocks"),
    ]
    out = "".join(
        f'<div class="card tile"><small>{esc(k)}</small><b>{v}</b><small>{esc(note)}</small></div>'
        for k, v, note in tiles
    )
    look = esc(r.get("stocks_to_look_at", ""))
    out += (
        f'<a class="card tile" style="grid-column: span 2" href="screener.html">'
        f"<small>Stocks to look at (screener, cheapest first)</small>"
        f'<b style="font-size:1em">{look}</b></a>'
    )
    return f'<div class="strip">{out}</div>'


def tone(to_entry) -> str:
    try:
        d = float(to_entry)
    except (TypeError, ValueError):
        return ""
    return "good" if d >= 0 else "warn" if d > -0.10 else ""


def sidebar(current: str, on_index: bool = False) -> str:
    """Stocks on the watch list, then the ones analysed before. On the watch list page the
    links jump to each stock's summary; elsewhere they open the stock's page."""
    now, former = watched()
    out = ['<aside class="side"><h4>On the watch list</h4><div class="list">']
    for f in now:
        r = read_runs(f)[0]
        href = f"#{f.name}" if on_index else f"{f.name}.html"
        on = " on" if f.name == current else ""
        out.append(
            f'<a class="it{on}" href="{href}"><span style="display:flex;gap:8px;'
            f'align-items:center"><span class="dot {tone(r["to_entry"])}"></span>'
            f"<b>{esc(f.name)}</b></span><small>{num(r['price'], '${:,.2f}')}</small></a>"
        )
    out.append("</div>")
    if former:
        out.append('<h4>Previously watched</h4><div class="list">')
        for f in former:
            on = " on" if f.name == current else ""
            out.append(
                f'<a class="it old{on}" href="{f.name}.html"><b>{esc(f.name)}</b>'
                f"<small>{len(read_runs(f))} analyses</small></a>"
            )
        out.append("</div>")
    out.append("</aside>")
    return "".join(out)


def summary_panel(f: Path) -> str:
    """The latest analysis of one stock, in short."""
    r, n, runs = read_runs(f)[0], notes(f), read_runs(f)
    verdict = n.get("Verdict", "") or r.get("verdict", "")
    bullets = md(n["Summary"]) if n.get("Summary") else ""
    return (
        f'<section class="card panel" id="{f.name}">'
        f'<div class="top"><div><h2>{esc(f.name)} <span style="color:var(--muted);'
        f'font-weight:500;font-size:.75em">{esc(company(f))}</span></h2>'
        f'<small style="color:var(--muted)">Latest analysis {esc(r["run"])}</small></div>'
        f'<div style="text-align:right"><div class="price">{num(r["price"], "${:,.2f}")}</div>'
        f"{badge(r['to_entry'])}</div></div>"
        f'<p class="lead">{inline(verdict.strip())}</p>'
        f"{bullets}"
        '<div class="kv">'
        f"<div><small>Adjusted P/E</small><b>{num(r['pe_adj'], '{:.1f}x')}</b></div>"
        f"<div><small>10y median</small><b>{num(r['pe_median_10y'], '{:.1f}x')}</b></div>"
        f"<div><small>Target P/E</small><b>{num(r['target_pe'], '{:g}x')}</b></div>"
        f"<div><small>Entry price</small><b>{num(r['entry_price'], '${:,.2f}')}</b></div></div>"
        '<div class="row" style="margin-bottom:0">'
        + a(f"{f.name}.html", "Full report", "btn")
        + a(f"{f.name}/{r['file']}", "PDF", "btn ghost")
        + a(f"{f.name}.html#previous", f"Previous analyses ({len(runs) - 1})", "btn ghost")
        + "</div></section>"
    )


def overview(menu) -> str:
    market = ANALYSES / "market"
    summaries = ANALYSES / "summaries"
    now, _ = watched()
    latest = max((read_runs(f)[0]["run"] for f in now), default="")
    main = [
        "<h1>Watch list</h1>",
        f'<p class="sub">{len(now)} stocks, last analysed {esc(latest)}. Each summary below is '
        "the latest analysis; open the full report for the numbers and every earlier "
        "analysis.</p>",
    ]
    buttons = []
    if summaries.exists() and pdfs(summaries):
        buttons.append(
            a(f"summaries/{pdfs(summaries)[0]}", "Watch list summary (PDF)", "btn ghost")
        )
    if market.exists() and pdfs(market):
        buttons.append(a("market.html", "Today's market", "btn ghost"))
    if buttons:
        main.append(f'<div class="row" style="margin-top:0">{"".join(buttons)}</div>')
    main += [summary_panel(f) for f in now]
    body = f'<div class="split">{sidebar("", on_index=True)}<div>{"".join(main)}</div></div>'
    return layout("Watch list", "index", body, menu)


def stock_page(f: Path, menu) -> str:
    runs = read_runs(f)
    r = runs[0]
    n = notes(f)
    now, _ = watched()
    tiles = [
        ("Price", num(r["price"], "${:,.2f}")),
        ("Adjusted P/E", num(r["pe_adj"], "{:.1f}x")),
        ("10-yr median P/E", num(r["pe_median_10y"], "{:.1f}x")),
        ("Target P/E", num(r["target_pe"], "{:g}x")),
        ("Entry price", num(r["entry_price"], "${:,.2f}")),
        ("Price vs entry", num(-float(r["to_entry"]) if r["to_entry"] else None, "{:+.1%}")),
    ]
    status = "" if f in now else " · no longer on the watch list"
    main = [
        f"<h1>{esc(company(f))} <span style='color:var(--muted);font-weight:500'>"
        f"{esc(f.name)}</span></h1>",
        f'<p class="sub">Latest analysis {esc(r["run"])}{status} {badge(r["to_entry"])}</p>',
    ]
    if n.get("Verdict"):
        main.append(f'<div class="card callout">{md(n["Verdict"])}</div>')
    main.append(
        '<div class="strip" style="margin-top:16px">'
        + "".join(
            f'<div class="card tile"><small>{esc(k)}</small><b>{v}</b></div>' for k, v in tiles
        )
        + "</div>"
    )
    options = "".join(
        f'<option value="{esc(f.name + "/" + x["file"])}">{esc(x["run"])}'
        f"{' (latest)' if i == 0 else ''}</option>"
        for i, x in enumerate(runs)
    )
    first = f"{f.name}/{r['file']}"
    main.append(
        "<h2>Full report</h2>"
        '<div class="card viewer"><div class="head">'
        f'<label for="pick">Analysis of</label><select id="pick">{options}</select>'
        f'<a id="open" class="btn ghost" href="{esc(first)}" target="_blank">Open PDF</a>'
        f'</div><iframe id="pdf" src="{esc(first)}" title="Report"></iframe></div>'
        "<script>const p=document.getElementById('pick'),o=document.getElementById('open'),"
        "v=document.getElementById('pdf');p.addEventListener('change',()=>{v.src=p.value;"
        "o.href=p.value;});</script>"
    )
    cols = [k for k in ("Summary", "What to watch", "Risks", "News") if n.get(k)]
    if cols:
        main.append("<h2>Claude's notes</h2><div class='cols'>")
        main += [f'<div class="card notes"><h3>{esc(k)}</h3>{md(n[k])}</div>' for k in cols]
        main.append("</div>")
    if n.get("Business"):
        main.append(f'<h2>Business</h2><div class="card notes">{md(n["Business"])}</div>')
    main.append(
        '<h2 id="previous">Previous analyses</h2><div class="card wrap"><table>'
        "<tr><th>Date and time</th><th>Price</th><th>Adj. P/E</th><th>Entry price</th>"
        "<th>Price vs entry</th><th>Verdict</th></tr>"
    )
    for x in runs:
        main.append(
            f"<tr><td class='d'>{a(f.name + '/' + x['file'], x['run'])}</td>"
            f"<td class='n'>{num(x['price'], '${:,.2f}')}</td>"
            f"<td class='n'>{num(x['pe_adj'], '{:.1f}x')}</td>"
            f"<td class='n'>{num(x['entry_price'], '${:,.2f}')}</td>"
            f"<td class='n'>{num(-float(x['to_entry']) if x['to_entry'] else None, '{:+.1%}')}"
            "</td>"
            f"<td>{esc(x.get('verdict', ''))}</td></tr>"
        )
    main.append("</table></div>")
    body = f'<div class="split">{sidebar(f.name)}<div>{"".join(main)}</div></div>'
    return layout(f"{f.name}: {company(f)}", "index", body, menu)


def market_page(menu) -> str:
    folder = ANALYSES / "market"
    runs, n = read_runs(folder), notes(folder)
    body = [
        "<h1>Market</h1>",
        '<p class="sub">A short report on the whole market each evening.</p>',
    ]
    if runs:
        body.append(market_strip(runs[0]))
    if n.get("Verdict"):
        body.append(f'<div class="card callout" style="margin-top:16px">{md(n["Verdict"])}</div>')
    cols = [k for k in ("Summary", "Stocks to look at", "What to watch") if n.get(k)]
    if cols:
        body.append("<h2>Claude's notes</h2><div class='cols'>")
        body += [f'<div class="card notes"><h3>{esc(k)}</h3>{md(n[k])}</div>' for k in cols]
        body.append("</div>")
    body.append(
        "<h2>Every dated report</h2><div class='card wrap'><table><tr><th>Date and time</th>"
        "<th>S&amp;P 500</th><th>Day</th><th>VIX</th><th>Above 200-day</th>"
        "<th>Stocks to look at</th></tr>"
    )
    for x in runs:
        body.append(
            f"<tr><td class='d'>{a('market/' + x['file'], x['run'])}</td>"
            f"<td class='n'>{num(x.get('sp500'), '{:,.0f}')}</td>"
            f"<td class='n'>{num(x.get('sp500_day'), '{:+.1%}')}</td>"
            f"<td class='n'>{num(x.get('vix'), '{:.1f}')}</td>"
            f"<td class='n'>{num(x.get('above_200d'), '{:.0%}')}</td>"
            f"<td>{esc(x.get('stocks_to_look_at', ''))}</td></tr>"
        )
    body.append("</table></div>")
    return layout("Market reports", "market", "\n".join(body), menu)


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def screener_page(menu) -> str:
    """The market screener's latest top 3 cheap or close-to-cheap stocks per sector."""
    top, stage1 = read_csv(SCREENER / "top.csv"), read_csv(SCREENER / "stage1.csv")
    dated = sorted(p.stem for p in SCREENER.glob("????-??-??.csv"))
    passed = [r for r in stage1 if r.get("status") == "pass"]
    body = [
        "<h1>Market screener</h1>",
        f'<p class="sub">Run {esc(dated[-1] if dated else "never")} on the S&amp;P 500. '
        f"Stage 1: {len(passed)} of {len(stage1)} companies have good financial statements "
        "for their Peter Lynch category. Stage 2: of those, the top 3 per sector that are "
        f"cheap or close to cheap against their own history ({len(top)} stocks). Refreshed "
        "every evening before the market report.</p>",
    ]
    cats: dict[str, list[int]] = {}
    for r in stage1:
        c = cats.setdefault(r.get("category") or "not classified", [0, 0])
        c[0] += 1
        c[1] += r.get("status") == "pass"
    body.append(
        '<div class="strip">'
        + "".join(
            f'<div class="card tile"><small>{esc(k.replace("_", " "))}</small>'
            f"<b>{v[1]} / {v[0]}</b><small>pass</small></div>"
            for k, v in sorted(cats.items(), key=lambda kv: -kv[1][0])
        )
        + "</div>"
    )
    sectors: dict[str, list[dict]] = {}
    for r in top:
        sectors.setdefault(r["sector"], []).append(r)
    body.append(
        "<h2>Top 3 per sector</h2><div class='card wrap'><table><tr><th>Sector</th>"
        "<th>Stock</th><th>Lynch category</th><th>Price</th><th>P/E now</th>"
        "<th>Cheap P/E</th><th>Cheap price</th><th>Price vs cheap</th><th></th>"
        "<th>Trend</th></tr>"
    )
    for sector in sorted(sectors):
        rows = sorted(sectors[sector], key=lambda r: int(float(r["rank_in_sector"])))
        for i, r in enumerate(rows):
            cell = f"<td rowspan={len(rows)}><b>{esc(sector)}</b></td>" if i == 0 else ""
            body.append(
                f'<tr>{cell}<td title="{esc(r["why"])}"><b>{esc(r["name"])}</b> '
                f"{esc(r['description'])}</td>"
                f"<td>{esc(r['category'].replace('_', ' '))}</td>"
                f"<td class='n'>{num(r['close'], '{:,.2f}')}</td>"
                f"<td class='n'>{num(r['pe_now'], '{:.1f}x')}</td>"
                f"<td class='n'>{num(r['cheap_multiple'], '{:.1f}x')} "
                f"<small>{esc(r['cheap_basis'])}</small></td>"
                f"<td class='n'>{num(r['cheap_price'], '{:,.2f}')}</td>"
                f"<td class='n'>{num(r['vs_cheap'], '{:+.1%}')}</td>"
                f"<td>{esc(r['cheapness'])}</td><td>{esc(r['trend'])}</td></tr>"
            )
    body.append(
        "</table></div><p class='sub'>Cheap price = EPS (Yahoo's adjusted EPS for the closest "
        "names) times the lower of the bottom quarter of the stock's own yearly P/E over 10 "
        'years and its sector\'s median P/E. "Cheap" is at or below it, "close" within '
        "15% above. Trend is timing only. "
        'Hover a stock for the reason it is listed. "Not classified" = too little EPS history '
        "for a Lynch category; those don't pass. Every rule and its source: report 13 and "
        "docs/SCREENER.md in the repository.</p>"
    )
    return layout("Market screener", "screener", "\n".join(body), menu)


def summaries_page(menu) -> str:
    folder = ANALYSES / "summaries"
    n = notes(folder)
    body = [
        "<h1>Watch list summaries</h1>",
        '<p class="sub">One PDF per evening comparing every stock on the watch list.</p>',
    ]
    if n.get("Verdict"):
        body.append(f'<div class="card callout">{md(n["Verdict"])}</div>')
    rows = "".join(
        f"<tr><td>{a('summaries/' + p, stamp(p))}</td><td>{a('summaries/' + p, 'PDF')}</td></tr>"
        for p in (pdfs(folder) if folder.exists() else [])
    )
    body.append(
        "<h2>Every dated summary</h2><div class='card wrap'><table>"
        f"<tr><th>Date and time</th><th>Report</th></tr>{rows}</table></div>"
    )
    return layout("Watch list summaries", "summaries", "\n".join(body), menu)


def build(out: Path = SITE) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for pdf in ANALYSES.glob("*/*.pdf"):
        dst = out / pdf.parent.name / pdf.name
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(pdf, dst)
    menu = [
        ("index", "Watch list"),
        ("market", "Market"),
        ("screener", "Screener"),
        ("summaries", "Summaries"),
    ]
    (out / "index.html").write_text(overview(menu))
    for f in stocks():
        (out / f"{f.name}.html").write_text(stock_page(f, menu))
    (out / "market.html").write_text(market_page(menu))
    (out / "screener.html").write_text(screener_page(menu))
    (out / "summaries.html").write_text(summaries_page(menu))
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE))
