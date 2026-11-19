"""Build the public website of the watch list analyses (GitHub Pages).

Pages: an overview (market strip and one card per stock), one page per stock (verdict,
key numbers, Claude's notes, every dated PDF), the market reports, the market screener's
latest top 3 per sector, the watch list summaries, the data coverage and the pipeline
diagram (docs/pipeline.html), with grouped menus on every page. The PDFs and notes are
files in analyses/; the recorded runs (out_watchlist_run, out_market_run), the screener
run, the coverage and the explorer's data come from the database: through the web API
when STOCK_API_URL and STOCK_API_KEY are set (the Pages workflow), else stock_analysis.data
on a PC. The PDFs are copied next to the pages, so a link opens the report in the browser.
The evening run commits to `main`; the Pages workflow (.github/workflows/pages.yml) then
runs this and publishes `_site/` at https://khalilvandian.github.io/Stock-analysis/.

Standard library only, so the workflow needs no install step.

Usage:
    python analysis/site.py [OUT_DIR]
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import tomllib
from functools import cache
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
ANALYSES = ROOT / "analyses"
CONFIG = ROOT / "config/watchlist.toml"
SITE = ROOT / "_site"
PIPELINE = ROOT / "docs/pipeline.html"  # the hand-drawn pipeline diagram
# The menus: (group, [(page, label)]). A page is <page>.html; "index" is the home page.
MENU = [
    ("Analyses", [("index", "Watch list"), ("summaries", "Summaries")]),
    (
        "Explore",
        [
            ("tickers", "All tickers"),
            ("ticker", "Ticker explorer"),
            ("sectors", "Sector valuations"),
            ("calendar", "Earnings calendar"),
        ],
    ),
    ("Markets", [("market", "Market reports"), ("screener", "Screener")]),
    ("Project", [("pipeline", "Pipeline"), ("coverage", "Data coverage")]),
]
EXPLORER_JS = ROOT / "analysis/explorer.js"  # the ticker page's script
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
nav { display: flex; gap: 4px; margin-left: auto; }
nav details { position: relative; }
nav summary { list-style: none; cursor: pointer; color: #b8c2d3; padding: 8px 12px;
  border-radius: 8px; white-space: nowrap; font-size: .94em; user-select: none;
  display: flex; align-items: center; gap: 6px; }
nav summary::-webkit-details-marker { display: none; }
nav summary::after { content: ""; width: 6px; height: 6px; margin-top: -3px;
  border-right: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor;
  transform: rotate(45deg); opacity: .7; }
nav details[open] summary::after { transform: rotate(-135deg); margin-top: 3px; }
nav summary:hover, nav details[open] summary { background: rgba(255, 255, 255, .08); color: #fff; }
nav summary:focus-visible, nav .dd a:focus-visible { outline: 2px solid #7aa2ff;
  outline-offset: 1px; }
nav details.on summary { color: #fff; box-shadow: inset 0 -2px 0 #7aa2ff;
  border-radius: 8px 8px 2px 2px; }
nav .dd { position: absolute; right: 0; top: calc(100% + 6px); min-width: 190px; padding: 6px;
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  box-shadow: 0 8px 24px rgba(16, 24, 40, .18); display: flex; flex-direction: column; gap: 2px; }
nav .dd a { color: var(--text); padding: 8px 12px; border-radius: 7px; white-space: nowrap; }
nav .dd a:hover { background: var(--bg); text-decoration: none; }
nav .dd a.on { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
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
th.n { text-align: right; }
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
.meter { height: 8px; border-radius: 4px; background: var(--line); overflow: hidden;
  min-width: 80px; }
.meter i { display: block; height: 100%; border-radius: 4px; background: var(--brand); }
.heat { border-collapse: separate; border-spacing: 2px; font-size: .78em; }
.heat th, .heat td { padding: 3px 5px; border: 0; }
.heat th.v { writing-mode: vertical-rl; transform: rotate(180deg); height: 120px;
  text-transform: none; letter-spacing: 0; font-size: .95em; vertical-align: bottom; }
.heat td.c { width: 26px; min-width: 26px; border-radius: 3px; text-align: center;
  font-variant-numeric: tabular-nums; }
.heat td.na { background: transparent; color: var(--muted); }
.heat td.h0 { background: color-mix(in srgb, var(--brand) 6%, var(--card)); }
.heat td.h1 { background: color-mix(in srgb, var(--brand) 28%, var(--card)); }
.heat td.h2 { background: color-mix(in srgb, var(--brand) 50%, var(--card)); }
.heat td.h3 { background: color-mix(in srgb, var(--brand) 72%, var(--card)); }
.heat td.h4 { background: var(--brand); }
.heat tr.hide { display: none; }
.tools { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin: 0 0 12px; }
.tools input[type=search] { font: inherit; padding: 7px 10px; border-radius: 8px;
  min-width: 220px; border: 1px solid var(--line); background: var(--card); color: var(--text); }
.trend svg { width: 100%; height: auto; display: block; }
.trend text { fill: var(--muted); font-size: 11px; }
footer { color: var(--muted); font-size: .85em; text-align: center; padding: 24px 16px; }
form.find input { font: inherit; font-size: .9em; width: 120px; padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid rgba(255, 255, 255, .18); background: rgba(255, 255, 255, .06); color: #fff; }
form.find input::placeholder { color: #b8c2d3; }
.na, .muted { color: var(--muted); font-weight: 400; }
.xhead { display: flex; justify-content: space-between; align-items: flex-start; gap: 16px;
  flex-wrap: wrap; }
.xhead .sub { margin-bottom: 12px; }
.xprice { text-align: right; } .xprice b { font-size: 1.8em; font-variant-numeric: tabular-nums; }
.xprice small { display: block; color: var(--muted); }
.chg { margin-left: 8px; font-weight: 600; font-variant-numeric: tabular-nums; }
.chg.up { color: var(--good); } .chg.down { color: var(--warn); }
table.fin th.grp { text-transform: uppercase; font-size: .75em; letter-spacing: .4px;
  color: var(--muted); padding-top: 14px; }
.tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); margin: 8px 0 8px;
  overflow-x: auto; }
.tabs button, .seg button { font: inherit; cursor: pointer; background: none; border: 0;
  color: var(--muted); padding: 10px 14px; white-space: nowrap; }
.tabs button.on { color: var(--brand); box-shadow: inset 0 -2px 0 var(--brand); font-weight: 600; }
.tabs button:hover, .seg button:hover { color: var(--text); }
.seg { display: inline-flex; gap: 2px; padding: 3px; border-radius: 9px; background: var(--card);
  border: 1px solid var(--line); margin: 14px 0 0; }
.seg button { padding: 5px 12px; border-radius: 7px; font-size: .9em; }
.seg button.on { background: var(--brand-soft); color: var(--brand); font-weight: 600; }
.tile em { display: block; font-style: normal; color: var(--muted); font-size: .78em;
  margin-top: 2px; }
.xpanel { padding: 14px 16px; margin-bottom: 14px; }
.xpanel h3 { margin: 0 0 8px; font-size: .95em; }
.xpanel h3:empty { display: none; }
.xpanel .seg { margin: 0 0 8px; }
.note { color: var(--muted); font-size: .85em; margin: 8px 0 0; }
.empty { color: var(--muted); }
.charts { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr));
  margin-top: 14px; }
.charts .xpanel { margin: 0; }
.chart svg { width: 100%; height: auto; display: block; }
.chart text { fill: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; }
.chart .grid { stroke: var(--line); stroke-width: 1; }
.chart .base { stroke: var(--muted); stroke-width: 1; opacity: .6; }
.chart .bar { fill: var(--brand); }
.chart .bar.neg { fill: var(--muted); }
.chart .line { fill: none; stroke: var(--brand); stroke-width: 2; stroke-linejoin: round; }
.chart .cross { stroke: var(--muted); stroke-dasharray: 3 3; }
.chart .dotm { fill: var(--brand); stroke: var(--card); stroke-width: 2; }
.chart .hit { fill: transparent; }
.chart rect.hit:hover { fill: color-mix(in srgb, var(--brand) 7%, transparent); }
.tip { position: fixed; z-index: 20; pointer-events: none; background: var(--card);
  color: var(--text);
  border: 1px solid var(--line); border-radius: 8px; padding: 6px 10px; font-size: .85em;
  box-shadow: 0 6px 18px rgba(16, 24, 40, .18); font-variant-numeric: tabular-nums; }
table.fin th[scope=row] { text-transform: none; letter-spacing: 0; font-size: .95em;
  color: var(--text);
  font-weight: 500; position: sticky; left: 0; background: var(--card); white-space: nowrap; }
table.fin td, table.fin th { padding: 7px 10px; }
table.sort th { cursor: pointer; user-select: none; white-space: nowrap; }
table.sort th[aria-sort=ascending]::after { content: " \\25B2"; }
table.sort th[aria-sort=descending]::after { content: " \\25BC"; }
.tools select, .tools label { font: inherit; }
.tools select { padding: 7px 10px; border-radius: 8px; border: 1px solid var(--line);
  background: var(--card); color: var(--text); }
tr.hide { display: none; }
/* a wide table scrolls inside its card instead of widening the page */
.cols > *, .charts > *, .strip > *, #explorer, #tab, .xpanel { min-width: 0; }
@media (max-width: 860px) {
  .split { grid-template-columns: 1fr; gap: 12px; }
  aside.side { position: static; }
  .side .list { flex-direction: row; overflow-x: auto; }
  .side a.it { flex: none; background: var(--card); border-color: var(--line); }
  .panel .kv { grid-template-columns: repeat(2, 1fr); }
  .viewer iframe { height: 70vh; }
}
@media (max-width: 640px) {
  .bar .in { gap: 8px; } .brand { font-size: .95em; } h1 { font-size: 1.5em; }
  nav summary { padding: 8px 8px; font-size: .9em; }
  form.find { display: none; }
  .xprice { text-align: left; }
}
"""


# --- reading the analyses folder ----------------------------------------------------


@cache
def db():
    """The database query function (analysis/explore.py's backends); None if unreachable."""
    sys.path.insert(0, str(ROOT / "analysis"))
    import explore

    try:
        return explore.backend()
    except Exception as exc:  # the site still builds, with what the files give
        print(f"database: not reachable ({exc}); pages that need it say so")
        return None


def query(sql: str) -> list[dict]:
    q = db()
    if q is None:
        return []
    try:
        return q(sql)
    except Exception as exc:  # one failed query leaves its page empty
        print(f"database: query failed ({exc})")
        return []


def timezone() -> ZoneInfo:
    if CONFIG.exists():
        return ZoneInfo(tomllib.loads(CONFIG.read_text()).get("timezone", "Europe/Rome"))
    return ZoneInfo("Europe/Rome")


def run_label(run_at: str) -> str:
    """A run time stored in UTC, as it reads in the watch list's time zone."""
    t = dt.datetime.fromisoformat(str(run_at)[:19]).replace(tzinfo=dt.UTC)
    t = t.astimezone(timezone())
    return t.strftime("%Y-%m-%d %H:%M ") + t.tzname()


@cache
def all_runs() -> dict[str, list[dict]]:
    """Every recorded run by folder (the stock's symbol, or "market"), newest first; each
    with `run`, its time as a label in the watch list's time zone."""
    out: dict[str, list[dict]] = {}
    rows = [(r["symbol"], r) for r in query("SELECT * FROM out_watchlist_run")]
    rows += [("market", r) for r in query("SELECT * FROM out_market_run")]
    for folder, r in rows:
        out.setdefault(folder, []).append({**r, "run": run_label(r["run_at"])})
    for runs in out.values():
        runs.sort(key=lambda r: str(r["run_at"]), reverse=True)
    return out


def read_runs(folder: Path) -> list[dict]:
    """The folder's recorded runs, newest first (empty if there are none)."""
    return all_runs().get(folder.name, [])


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
    """Stock folders with recorded runs, most recently analysed first."""
    found = [
        f
        for f in ANALYSES.iterdir()
        if f.is_dir() and f.name not in ("market", "summaries") and read_runs(f)
    ]
    return sorted(found, key=lambda f: str(read_runs(f)[0]["run_at"]), reverse=True)


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


def menu_groups(menu) -> list[tuple[str, list[tuple[str, str]]]]:
    """The menu as groups; a flat [(page, label)] list (older callers) is one group."""
    if menu and isinstance(menu[0][1], list):
        return menu
    return [("Pages", list(menu))]


# Opens one menu at a time; Escape or a click elsewhere closes it.
MENU_JS = """<script>
const menus = [...document.querySelectorAll("nav details")];
menus.forEach(d => d.addEventListener("toggle", () => {
  if (d.open) menus.forEach(o => { if (o !== d) o.open = false; });
}));
document.addEventListener("click", e => {
  if (!e.target.closest("nav")) menus.forEach(d => d.open = false);
});
document.addEventListener("keydown", e => {
  if (e.key !== "Escape") return;
  menus.filter(d => d.open).forEach(d => { d.open = false; d.querySelector("summary").focus(); });
});
</script>"""


def layout(title_: str, active: str, body: str, menu, head: str = "") -> str:
    groups = []
    for group, pages in menu_groups(menu):
        here = any(key == active for key, _ in pages)
        links = "".join(
            f'<a href="{"./" if key == "index" else key + ".html"}"'
            f"{' class=on aria-current=page' if key == active else ''}>{esc(label)}</a>"
            for key, label in pages
        )
        groups.append(
            f"<details{' class=on' if here else ''}><summary>{esc(group)}</summary>"
            f'<div class="dd">{links}</div></details>'
        )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{esc(title_)}</title>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700"
        "&display=swap' rel='stylesheet'>"
        f"<style>{CSS}</style>{head}</head><body>"
        "<header class='bar'><div class='in'><a class='brand' href='./'>Stock "
        "<span>analysis</span></a><form class='find' action='ticker.html' role='search'>"
        "<input name='s' placeholder='Find a ticker' aria-label='Find a ticker' "
        "autocomplete='off'></form>"
        f"<nav aria-label='Site'>{''.join(groups)}</nav></div></header>"
        f"<main>{body}</main>"
        "<footer>Analysed every evening at 21:00 Italy time. Every run is kept as a dated "
        f"PDF. Not investment advice.</footer>{MENU_JS}</body></html>"
    )


def pipeline_page(menu, source: Path | None = None) -> str:
    """The pipeline diagram, taken from docs/pipeline.html as it is: its styles are scoped
    under .pipeline, so only its body rule and the maintenance notes are left out."""
    text = (source or PIPELINE).read_text(encoding="utf-8")
    fonts = "".join(re.findall(r"<link [^>]*fonts\.googleapis[^>]*>", text))
    css = re.search(r"<style>(.*?)</style>", text, re.S).group(1)
    css = re.sub(r"^body \{[^}]*\}\n", "", css, flags=re.M)
    body = text.split("</style>", 1)[1]
    body = re.sub(r'<section id="maintain">.*?</section>', "", body, flags=re.S)
    return layout("Pipeline", "pipeline", body, menu, head=f"{fonts}<style>{css}</style>")


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
    latest = max((read_runs(f)[0]["run"] for f in now), default="")  # labels sort by time
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


SCREENER_RUN = """
SELECT u.run_date, r.stage, r.symbol, r.sector, r.category, r.status, r.rank_in_sector,
       r.close, r.cheap_price, r.detail_json
FROM out_screener_result r JOIN out_screener_run u ON u.run_id = r.run_id
WHERE u.run_id = (SELECT run_id FROM out_screener_run ORDER BY run_date DESC, run_id DESC
                  LIMIT 1)"""


def screener_rows() -> tuple[str, list[dict], list[dict]]:
    """The newest screener run: (date, Stage 1 rows, Stage 2 top), detail_json merged in."""
    rows = []
    for r in query(SCREENER_RUN):
        detail = json.loads(r.pop("detail_json") or "{}")
        rows.append({**detail, **r})
    run_date = str(rows[0]["run_date"])[:10] if rows else "never"
    return (
        run_date,
        [r for r in rows if int(r["stage"]) == 1],
        [r for r in rows if int(r["stage"]) == 2],
    )


def text(v) -> str:
    return "" if v is None else str(v)


def screener_page(menu) -> str:
    """The market screener's latest top 3 cheap or close-to-cheap stocks per sector."""
    run_date, stage1, top = screener_rows()
    passed = [r for r in stage1 if r.get("status") == "pass"]
    body = [
        "<h1>Market screener</h1>",
        f'<p class="sub">Run {esc(run_date)} on the S&amp;P 500. '
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
        sectors.setdefault(text(r["sector"]), []).append(r)
    body.append(
        "<h2>Top 3 per sector</h2><div class='card wrap'><table><tr><th>Sector</th>"
        "<th>Stock</th><th>Lynch category</th><th>Price</th><th>P/E now</th>"
        "<th>Cheap P/E</th><th>Cheap price</th><th>Price vs cheap</th><th></th>"
        "<th>Trend</th></tr>"
    )
    for sector in sorted(sectors):
        rows = sorted(sectors[sector], key=lambda r: int(float(r["rank_in_sector"] or 0)))
        for i, r in enumerate(rows):
            cell = f"<td rowspan={len(rows)}><b>{esc(sector)}</b></td>" if i == 0 else ""
            body.append(
                f'<tr>{cell}<td title="{esc(text(r.get("why")))}">'
                f"<b>{esc(text(r.get('name') or r['symbol']))}</b> "
                f"{esc(text(r.get('description')))}</td>"
                f"<td>{esc(text(r.get('category')).replace('_', ' '))}</td>"
                f"<td class='n'>{num(r.get('close'), '{:,.2f}')}</td>"
                f"<td class='n'>{num(r.get('pe_now'), '{:.1f}x')}</td>"
                f"<td class='n'>{num(r.get('cheap_multiple'), '{:.1f}x')} "
                f"<small>{esc(text(r.get('cheap_basis')))}</small></td>"
                f"<td class='n'>{num(r.get('cheap_price'), '{:,.2f}')}</td>"
                f"<td class='n'>{num(r.get('vs_cheap'), '{:+.1%}')}</td>"
                f"<td>{esc(text(r.get('cheapness')))}</td><td>{esc(text(r.get('trend')))}</td></tr>"
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


# --- the data coverage page (issue #18) --------------------------------------------


def coverage_detail() -> dict | None:
    """The newest coverage snapshot (out_coverage_snapshot), or nothing."""
    rows = query(
        "SELECT detail_json FROM out_coverage_snapshot ORDER BY snapshot_date DESC LIMIT 1"
    )
    return json.loads(rows[0]["detail_json"]) if rows else None


def share(a_, b_) -> float:
    return a_ / b_ if b_ else 0.0


def meter(x: float) -> str:
    return f'<div class="meter"><i style="width:{max(0.0, min(1.0, x)) * 100:.1f}%"></i></div>'


def heat_cell(x) -> str:
    """One cell of the company x item heatmap: one hue in five steps, darker = more years."""
    if x is None:
        return '<td class="c na" title="does not apply">·</td>'
    step = 4 if x >= 1 else int(x * 4)  # 0-24%, 25-49%, 50-74%, 75-99%, all
    return f'<td class="c h{step}" title="{x:.0%} of the fiscal years"></td>'


def trend_svg(trend: list[dict]) -> str:
    """Share of the required values present, per snapshot day (one series, so no legend)."""
    pts = [(t["date"], share(t["cells_present"], t["cells_required"])) for t in trend]
    if len(pts) < 2:
        return "<p class='sub'>The trend line appears after the second daily snapshot.</p>"
    w, h, left, bottom = 720, 180, 36, 22

    def y_of(v: float) -> float:
        return 10 + (1 - v) * (h - bottom - 10)

    xs = [left + i * (w - left - 10) / (len(pts) - 1) for i in range(len(pts))]
    ys = [y_of(v) for _, v in pts]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys, strict=True))
    area = f"{xs[0]:.1f},{h - bottom} {line} {xs[-1]:.1f},{h - bottom}"
    grid = "".join(
        f'<line x1="{left}" x2="{w - 10}" y1="{y_of(g):.1f}" y2="{y_of(g):.1f}" '
        f'stroke="var(--line)" stroke-width="1"/>'
        f'<text x="{left - 6}" y="{y_of(g) + 4:.1f}" text-anchor="end">{g:.0%}</text>'
        for g in (0, 0.5, 1)
    )
    dots = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--brand)" stroke="var(--card)" '
        f'stroke-width="2"><title>{esc(d)}: {v:.1%}</title></circle>'
        for (d, v), x, y in zip(pts, xs, ys, strict=True)
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Share of the required values '
        f'present, per day">{grid}<polygon points="{area}" fill="var(--brand-soft)"/>'
        f'<polyline points="{line}" fill="none" stroke="var(--brand)" stroke-width="2"/>{dots}'
        f'<text x="{left}" y="{h - 4}">{esc(pts[0][0])}</text>'
        f'<text x="{w - 10}" y="{h - 4}" text-anchor="end">{esc(pts[-1][0])}</text></svg>'
    )


def table(head: list[str], rows: str) -> str:
    th = "".join(f"<th>{esc(x)}</th>" for x in head)
    return f"<div class='card wrap'><table><tr>{th}</tr>{rows}</table></div>"


def share_rows(entries: list[tuple[str, int, int]]) -> str:
    return "".join(
        f"<tr><td>{label}</td><td class='n'>{have:,} / {need:,}</td>"
        f"<td class='n'>{share(have, need):.0%}</td>"
        f"<td style='width:40%'>{meter(share(have, need))}</td></tr>"
        for label, have, need in entries
    )


def coverage_page(menu, d: dict | None = None) -> str:
    d = d if d is not None else coverage_detail()
    if not d:
        body = (
            "<h1>Data coverage</h1><p class='sub'>No coverage snapshot yet. It appears after "
            "the first run of the ingest job (python -m stock_analysis.db ingest).</p>"
        )
        return layout("Data coverage", "coverage", body, menu)
    t, p = d["totals"], d["pipeline"]
    n = t["companies"]
    if d.get("mode") == "maintain":
        mode_badge = '<span class="badge good">Maintenance: complete, kept current</span>'
    else:
        mode_badge = '<span class="badge warn">Backfill: still filling the database</span>'
    if p.get("runs_to_finish"):
        finish = f"about {p['runs_to_finish']} more runs"
    else:
        finish = "every task fetched" if not p.get("never_fetched") else "not known yet"
    tiles = [
        ("Companies covered", f"{t['companies_covered']} / {n}", "every required value in"),
        ("Required values", f"{share(t['cells_present'], t['cells_required']):.1%}",
         f"{t['cells_present']:,} of {t['cells_required']:,}"),
        ("Fiscal-year values", f"{share(t['annual_present'], t['annual_required']):.0%}",
         f"{t['annual_present']:,} of {t['annual_required']:,}"),
        ("Quarterly values", f"{share(t['quarterly_present'], t['quarterly_required']):.0%}",
         f"{t['quarterly_present']:,} of {t['quarterly_required']:,}"),
        ("Price history", f"{t['prices_ok']} / {n}", "complete and current"),
        ("Reported EPS", f"{t['earnings_ok']} / {n}", "the last 8 reports"),
        ("Still to fetch", f"{p.get('never_fetched', 0):,} tasks", finish),
    ]  # fmt: skip
    body = [
        "<h1>Data coverage</h1>",
        '<p class="sub">How much of the required data for the S&amp;P 500 '
        f"({n} companies) is in the database, and how good it is. Snapshot of "
        f"{esc(d['as_of'])}. {mode_badge}</p>",
        '<div class="strip">'
        + "".join(
            f'<div class="card tile"><small>{esc(x)}</small><b>{esc(y)}</b>'
            f"<small>{esc(z)}</small></div>"
            for x, y, z in tiles
        )
        + "</div>",
        "<h2>Required values present, per day</h2>"
        "<div class='card trend' style='padding:14px 16px'>"
        + trend_svg(d.get("trend", []))
        + "</div>",
    ]
    items = share_rows(
        [
            (
                esc(i["label"]) + (" <small>(optional)</small>" if i["optional"] else ""),
                i["present"],
                i["required"],
            )
            for i in d["items"]
        ]  # fmt: skip
    )
    years = share_rows([(f"FY{y['fiscal_year']}", y["present"], y["required"]) for y in d["years"]])
    body.append(
        "<div class='cols'><div><h2>By item (fiscal years)</h2>"
        + table(["Item", "Present", "Share", ""], items)
        + "</div><div><h2>By fiscal year</h2>"
        + table(["Year", "Present", "Share", ""], years)
        + "</div></div>"
    )
    sectors = share_rows(
        [
            (
                f"{esc(s['sector'])} <small>{s['covered']} of {s['companies']} covered</small>",
                s["present"],
                s["required"],
            )
            for s in sorted(d["sectors"], key=lambda s: -s["companies"])
        ]  # fmt: skip
    )
    f = d["freshness"]
    fresh = (
        f"<tr><td>Newest price</td><td class='n'>{esc(f.get('newest_price') or '–')}</td></tr>"
        f"<tr><td>Companies with incomplete or stale prices</td>"
        f"<td class='n'>{f['prices_stale']}</td></tr>"
        f"<tr><td>Newest SEC filing loaded</td>"
        f"<td class='n'>{esc(f.get('newest_filing') or '–')}</td></tr>"
        f"<tr><td>Companies with no SEC filing in 120 days</td>"
        f"<td class='n'>{f['no_filing_120_days']}</td></tr>"
    )
    total_src = sum(x["values"] for x in d["sources"]) or 1
    sources = "".join(
        f"<tr><td>{esc(x['source'])}</td><td class='n'>{x['values']:,}</td>"
        f"<td class='n'>{x['values'] / total_src:.0%}</td></tr>"
        for x in d["sources"]
    )
    quality = (
        "".join(
            f"<tr><td>{esc(q['check_name'].replace('_', ' '))}</td><td>{esc(q['severity'])}</td>"
            f"<td class='n'>{q['count']:,}</td></tr>"
            for q in d["quality"]
        )
        or "<tr><td colspan=3>No issues in the last build.</td></tr>"
    )
    body.append(
        "<div class='cols'><div><h2>By sector</h2>"
        + table(["Sector", "Values", "Share", ""], sectors)
        + "</div><div><h2>Freshness</h2>"
        + table(["", ""], fresh)
        + "<h2>Where the fiscal-year values come from</h2>"
        + table(["Source", "Values", "Share"], sources)
        + "<h2>Quality checks (last build)</h2>"
        + table(["Check", "Severity", "Count"], quality)
        + "</div></div>"
    )
    src = "".join(
        f"<tr><td>{esc(k.replace('_', ' '))}</td><td class='n'>{v.get('tasks', 0)}</td>"
        f"<td class='n'>{v.get('ok', 0) + v.get('empty', 0)}</td>"
        f"<td class='n'>{v.get('pending', 0)}</td><td class='n'>{v.get('error', 0)}</td></tr>"
        for k, v in sorted(p["sources"].items())
    )
    runs = "".join(
        f"<tr><td class='d'>{esc(str(r['started_at'])[:16].replace('T', ' '))}</td>"
        f"<td>{esc(r['mode'])}</td><td>{esc(r['status'])}</td>"
        f"<td class='n'>{r['requests']:,}</td><td class='n'>{r['tasks_ok']:,}</td>"
        f"<td class='n'>{r['tasks_failed']:,}</td><td class='n'>{r['rows_stored']:,}</td>"
        f"<td>{esc('; '.join(f'{g}: {why}' for g, why in r['stopped'].items()))}</td></tr>"
        for r in p["runs"][:10]
    )
    body.append(
        "<h2>The ingest job</h2><div class='cols'>"
        + table(["Source", "Tasks", "Fetched", "Waiting", "Failed"], src)
        + table(
            ["Run (UTC)", "Mode", "Result", "Requests", "Done", "Failed", "Rows", "Stopped by"],
            runs,
        )
        + "</div>"
    )
    order = d.get("item_order", [i["item"] for i in d["items"]])
    labels = {i["item"]: i["label"] for i in d["items"]}
    head = "".join(f"<th class='v'>{esc(labels.get(i, i))}</th>" for i in order)
    lines = []
    for c in sorted(d["companies"], key=lambda c: (c["share"], c["symbol"])):
        if c["covered"]:
            flag = '<span class="dot good" title="covered"></span>'
        else:
            flag = '<span class="dot warn" title="not covered yet"></span>'
        more = c["missing_count"] - len(c["missing"])
        missing = ", ".join(c["missing"]) + (f" and {more} more" if more > 0 else "")
        tags = esc(f"{c['symbol']} {c['name'] or ''} {c['sector'] or ''}")
        price_tip = f"{c['prices']['share']:.0%} of trading days, last {c['prices']['last']}"
        lines.append(
            f"<tr data-s='{tags}' data-ok='{int(c['covered'])}'><td>{flag}</td>"
            f"<td><b>{esc(c['symbol'])}</b></td><td class='n'>{c['share']:.0%}</td>"
            f"<td class='n' title='{esc(price_tip)}'>{'✓' if c['prices']['ok'] else '✗'}</td>"
            f"<td class='n'>{c['quarterly']['present']}/{c['quarterly']['required']}</td>"
            f"<td class='n'>{c['earnings']['present']}/{c['earnings']['required']}</td>"
            + "".join(heat_cell(x) for x in c["item_shares"])
            + f"<td class='n' title='{esc(missing)}'>{c['missing_count']}</td></tr>"
        )
    script = (
        "<script>(function(){var q=document.getElementById('q'),g=document.getElementById("
        "'gaps');function f(){var s=q.value.toLowerCase();document.querySelectorAll("
        "'tr[data-s]').forEach(function(r){var hit=r.dataset.s.toLowerCase().indexOf(s)>=0&&"
        "(!g.checked||r.dataset.ok==='0');r.classList.toggle('hide',!hit);});}"
        "q.addEventListener('input',f);g.addEventListener('change',f);})();</script>"
    )
    body.append(
        "<h2>Every company</h2><p class='sub'>Each cell is the share of the company's fiscal "
        "years that have the value (darker is more, the darkest is every year; · = does not "
        "apply to the business). "
        "Prices ✓ = complete and current. Quarters and EPS = present / required. Hover the "
        "last cell of a row for what is missing.</p><div class='tools'><input type='search' "
        "id='q' placeholder='Filter by symbol, name or sector' aria-label='Filter companies'>"
        "<label><input type='checkbox' id='gaps'> Only companies not covered</label></div>"
        "<div class='card wrap'><table class='heat'><tr><th></th><th>Symbol</th><th>All</th>"
        f"<th>Prices</th><th>Quarters</th><th>EPS</th>{head}<th>Missing</th></tr>"
        + "".join(lines)
        + "</table></div>"
        + script
        + "<p class='sub'>What counts as required: config/coverage.toml. How it is measured: "
        "docs/COVERAGE.md in the repository.</p>"
    )
    return layout("Data coverage", "coverage", "\n".join(body), menu)


# --- the ticker explorer (issue #20) --------------------------------------------------


def explore_index(out: Path) -> dict | None:
    """Export the explorer's data into out/tickers (analysis/explore.py) and return its
    index, from the database (the web API in the Pages workflow, stock_analysis.data on a
    PC). STOCK_EXPLORE=off skips it (the explorer pages then say there is no data)."""
    if os.environ.get("STOCK_EXPLORE") == "off" or db() is None:
        return None
    sys.path.insert(0, str(ROOT / "analysis"))
    import explore

    try:
        return explore.export(out, query=db())
    except Exception as exc:  # the rest of the site still builds
        print(f"explorer: export failed ({exc}); the explorer pages say there is no data")
        return None


def fmt_money(v) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    s, x = ("−" if x < 0 else ""), abs(x)
    for unit, d in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if x >= unit:
            return f"{s}${x / unit:.{2 if d == 'T' else 1 if x < 1e11 else 0}f}{d}"
    return f"{s}${x:,.0f}"


def fmt(v, pattern: str) -> str:
    try:
        return pattern.format(float(v))
    except (TypeError, ValueError):
        return "—"


def median_of(xs) -> float | None:
    v = sorted(float(x) for x in xs if isinstance(x, int | float))
    if not v:
        return None
    m = len(v) // 2
    return v[m] if len(v) % 2 else (v[m - 1] + v[m]) / 2


def no_explore_data(title_: str, active: str, menu) -> str:
    return layout(
        title_,
        active,
        f"<h1>{esc(title_)}</h1><p class='sub'>No explorer data in this build. The Pages "
        "workflow exports it from the database every day; locally, build with the database "
        "reachable (stock_analysis.data) or <code>STOCK_API_URL</code> and "
        "<code>STOCK_API_KEY</code> set.</p>",
        menu,
    )


def ticker_link(sym: str) -> str:
    return f'<a href="ticker.html?s={esc(sym)}"><b>{esc(sym)}</b></a>'


# Sortable, filterable tables: click a header to sort by its data-v values.
SORT_JS = """<script>
document.querySelectorAll("table.sort").forEach(t => {
  const body = t.tBodies[0];
  t.querySelectorAll("th").forEach((th, col) => th.addEventListener("click", () => {
    const dir = th.getAttribute("aria-sort") === "descending" ? 1 : -1;
    t.querySelectorAll("th").forEach(h => h.removeAttribute("aria-sort"));
    th.setAttribute("aria-sort", dir === 1 ? "ascending" : "descending");
    const key = r => { const c = r.cells[col]; const v = c.dataset.v ?? c.textContent.trim();
      const n = parseFloat(v); return v === "" ? null : (isNaN(n) ? v.toLowerCase() : n); };
    [...body.rows].sort((a, b) => { const x = key(a), y = key(b);
      if (x === null) return 1; if (y === null) return -1;
      return (x < y ? -1 : x > y ? 1 : 0) * dir; }).forEach(r => body.appendChild(r));
  }));
});
const q = document.getElementById("q"), sec = document.getElementById("sector"),
  pass = document.getElementById("pass"), count = document.getElementById("count");
function filter() {
  const s = (q?.value || "").toLowerCase(); let n = 0;
  document.querySelectorAll("table.sort tbody tr").forEach(r => {
    const show = (!s || r.dataset.k.includes(s))
      && (!sec || !sec.value || r.dataset.s === sec.value)
      && (!pass || !pass.checked || r.dataset.p === "pass");
    r.classList.toggle("hide", !show); n += show;
  });
  if (count) count.textContent = n;
}
[q, sec, pass].forEach(e => e && e.addEventListener("input", filter));
</script>"""


def ticker_page(menu) -> str:
    body = (
        '<div id="explorer"><p class="sub">Loading…</p></div>'
        "<noscript><p>The ticker explorer needs JavaScript.</p></noscript>"
        '<script src="explorer.js" defer></script>'
    )
    return layout("Ticker explorer", "ticker", body, menu)


def tickers_page(menu, idx: dict | None) -> str:
    if not idx:
        return no_explore_data("All tickers", "tickers", menu)
    rows = sorted(idx["tickers"], key=lambda r: -(r.get("market_cap") or 0))
    sectors = sorted({r["sector"] for r in rows if r.get("sector")})
    cols = [
        ("Price", "price", "${:,.2f}"),
        ("Market value", "market_cap", None),
        ("Revenue", "revenue", None),
        ("Net income", "net_income", None),
        ("FCF", "free_cf", None),
        ("Net debt", "net_debt", None),
        ("P/E", "pe", "{:.1f}x"),
        ("EV/EBITDA", "ev_ebitda", "{:.1f}x"),
        ("FCF yield", "fcf_yield", "{:.1%}"),
        ("Div. yield", "div_yield", "{:.1%}"),
        ("Net margin", "net_margin", "{:.1%}"),
        ("ROE", "roe", "{:.1%}"),
        ("Revenue 5y", "revenue_5y", "{:+.1%}"),
        ("Return 1y", "return_1y", "{:+.1%}"),
    ]
    head = (
        "<th>Ticker</th><th>Company</th><th>Sector</th>"
        + "".join(f"<th class='n'>{esc(c[0])}</th>" for c in cols)
        + "<th>Lynch category</th><th>Stage 1</th>"
    )
    trs = []
    for r in rows:
        key = f"{r['symbol']} {r.get('name') or ''} {r.get('industry') or ''}".lower()
        cells = "".join(
            f"<td class='n' data-v=\"{'' if r.get(k) is None else r[k]}\">"
            f"{fmt_money(r.get(k)) if p is None else fmt(r.get(k), p)}</td>"
            for _, k, p in cols
        )
        cat = (r.get("category") or "").replace("_", " ")
        trs.append(
            f'<tr data-k="{esc(key)}" data-s="{esc(r.get("sector") or "")}" '
            f'data-p="{esc(r.get("stage1") or "")}"><td>{ticker_link(r["symbol"])}</td>'
            f"<td>{esc(r.get('name') or '')}</td><td>{esc(r.get('sector') or '')}</td>{cells}"
            f"<td>{esc(cat)}</td><td>{esc(r.get('stage1') or '')}</td></tr>"
        )
    body = (
        "<h1>All tickers</h1>"
        f"<p class='sub'><span id='count'>{len(rows)}</span> companies in the database, data "
        f"as of {esc(idx.get('asof') or '—')}. Absolute values over the last twelve months; "
        "click a column to sort, a ticker to explore it.</p>"
        "<div class='tools'><input type='search' id='q' placeholder='Ticker, name or industry'"
        " aria-label='Search'><select id='sector' aria-label='Sector'><option value=''>"
        "Every sector</option>"
        + "".join(f"<option>{esc(s)}</option>" for s in sectors)
        + "</select><label><input type='checkbox' id='pass'> Stage 1 pass only</label></div>"
        f"<div class='card wrap'><table class='sort'><thead><tr>{head}</tr></thead><tbody>"
        + "".join(trs)
        + "</tbody></table></div>"
        + SORT_JS
    )
    return layout("All tickers", "tickers", body, menu)


SECTOR_COLS = [
    ("P/E", "pe", "{:.1f}x"),
    ("P/S", "ps", "{:.1f}x"),
    ("P/B", "pb", "{:.1f}x"),
    ("EV/EBITDA", "ev_ebitda", "{:.1f}x"),
    ("FCF yield", "fcf_yield", "{:.1%}"),
    ("Div. yield", "div_yield", "{:.1%}"),
    ("Net margin", "net_margin", "{:.1%}"),
    ("ROE", "roe", "{:.1%}"),
    ("Net debt/EBITDA", "net_debt_to_ebitda", "{:.1f}x"),
    ("Revenue 5y", "revenue_5y", "{:+.1%}"),
    ("EPS 5y", "eps_5y", "{:+.1%}"),
    ("Return 1y", "return_1y", "{:+.1%}"),
]


def sectors_page(menu, idx: dict | None) -> str:
    if not idx:
        return no_explore_data("Sector valuations", "sectors", menu)
    by: dict[str, list[dict]] = {}
    for r in idx["tickers"]:
        by.setdefault(r.get("sector") or "Not classified", []).append(r)
    every = idx["tickers"]
    head = "<th>Sector</th><th class='n'>Companies</th><th class='n'>Market value</th>" + "".join(
        f"<th class='n'>{esc(c[0])}</th>" for c in SECTOR_COLS
    )

    def line(name: str, rows: list[dict], link: bool) -> str:
        cap = sum(r.get("market_cap") or 0 for r in rows)
        cells = ""
        for _, k, p in SECTOR_COLS:
            m = median_of(r.get(k) for r in rows)
            cells += f"<td class='n' data-v=\"{'' if m is None else m}\">{fmt(m, p)}</td>"
        label = f'<a href="#{esc(slug(name))}">{esc(name)}</a>' if link else f"<b>{esc(name)}</b>"
        return (
            f"<tr><td>{label}</td><td class='n'>{len(rows)}</td>"
            f"<td class='n' data-v='{cap}'>{fmt_money(cap)}</td>{cells}</tr>"
        )

    body = [
        "<h1>Sector valuations</h1>",
        f"<p class='sub'>Medians per TradingView sector, data as of "
        f"{esc(idx.get('asof') or '—')}. P/E, P/B and EV/EBITDA only count positive "
        "earnings, equity and EBITDA. Each sector lists its companies below, cheapest P/E "
        "first.</p>",
        f"<div class='card wrap'><table class='sort'><thead><tr>{head}</tr></thead><tbody>",
        *[line(s, by[s], True) for s in sorted(by)],
        "</tbody><tfoot>" + line("All companies", every, False) + "</tfoot></table></div>",
    ]
    for s in sorted(by):
        rows = sorted(by[s], key=lambda r: (r.get("pe") is None, r.get("pe") or 0))
        body.append(
            f"<h2 id='{esc(slug(s))}'>{esc(s)}</h2><div class='card wrap'><table><tr>"
            "<th>Ticker</th><th>Company</th><th class='n'>Market value</th>"
            + "".join(f"<th class='n'>{esc(c[0])}</th>" for c in SECTOR_COLS[:8])
            + "</tr>"
            + "".join(
                f"<tr><td>{ticker_link(r['symbol'])}</td><td>{esc(r.get('name') or '')}</td>"
                f"<td class='n'>{fmt_money(r.get('market_cap'))}</td>"
                + "".join(f"<td class='n'>{fmt(r.get(k), p)}</td>" for _, k, p in SECTOR_COLS[:8])
                + "</tr>"
                for r in rows
            )
            + "</table></div>"
        )
    return layout("Sector valuations", "sectors", "\n".join(body) + SORT_JS, menu)


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def calendar_page(menu, idx: dict | None, weeks: int = 8) -> str:
    if not idx:
        return no_explore_data("Earnings calendar", "calendar", menu)
    import datetime as dt

    start = dt.date.fromisoformat(idx.get("built") or dt.date.today().isoformat())
    end = (start + dt.timedelta(weeks=weeks)).isoformat()
    rows = sorted(
        (r for r in idx["tickers"] if r.get("next_earnings") and r["next_earnings"] <= end),
        key=lambda r: (r["next_earnings"], -(r.get("market_cap") or 0)),
    )
    body = [
        "<h1>Earnings calendar</h1>",
        f"<p class='sub'>The next {weeks} weeks of quarterly reports: {len(rows)} companies. "
        "EPS estimate = the analysts' consensus for that quarter; last surprise = reported "
        "EPS against the estimate a quarter earlier. Source: Yahoo, rebuilt "
        f"{esc(idx.get('built') or '—')}.</p>",
    ]
    day = None
    for r in rows:
        if r["next_earnings"] != day:
            if day:
                body.append("</table></div>")
            day = r["next_earnings"]
            label = dt.date.fromisoformat(day).strftime("%A %d %B %Y")
            body.append(
                f"<h2>{esc(label)}</h2><div class='card wrap'><table><tr><th>Ticker</th>"
                "<th>Company</th><th>Sector</th><th>Market value</th><th>EPS estimate</th>"
                "<th>Last surprise</th><th>P/E</th></tr>"
            )
        last = r.get("last_surprise")
        surprise = None if last is None else last / 100
        body.append(
            f"<tr><td>{ticker_link(r['symbol'])}</td><td>{esc(r.get('name') or '')}</td>"
            f"<td>{esc(r.get('sector') or '')}</td>"
            f"<td class='n'>{fmt_money(r.get('market_cap'))}</td>"
            f"<td class='n'>{fmt(r.get('next_eps_estimate'), '${:,.2f}')}</td>"
            f"<td class='n'>{fmt(surprise, '{:+.1%}')}</td>"
            f"<td class='n'>{fmt(r.get('pe'), '{:.1f}x')}</td></tr>"
        )
    if day:
        body.append("</table></div>")
    else:
        body.append("<p class='empty'>No reports in the coming weeks.</p>")
    return layout("Earnings calendar", "calendar", "\n".join(body), menu)


def build(out: Path = SITE) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    idx = explore_index(out)
    shutil.copy2(EXPLORER_JS, out / "explorer.js")
    for pdf in ANALYSES.glob("*/*.pdf"):
        dst = out / pdf.parent.name / pdf.name
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(pdf, dst)
    menu = MENU
    (out / "index.html").write_text(overview(menu))
    for f in stocks():
        (out / f"{f.name}.html").write_text(stock_page(f, menu))
    (out / "market.html").write_text(market_page(menu))
    (out / "screener.html").write_text(screener_page(menu))
    (out / "summaries.html").write_text(summaries_page(menu))
    (out / "coverage.html").write_text(coverage_page(menu), encoding="utf-8")
    (out / "pipeline.html").write_text(pipeline_page(menu), encoding="utf-8")
    (out / "ticker.html").write_text(ticker_page(menu), encoding="utf-8")
    (out / "tickers.html").write_text(tickers_page(menu, idx), encoding="utf-8")
    (out / "sectors.html").write_text(sectors_page(menu, idx), encoding="utf-8")
    (out / "calendar.html").write_text(calendar_page(menu, idx), encoding="utf-8")
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE))
