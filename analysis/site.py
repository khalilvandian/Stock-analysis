"""Build the public website of the watch list analyses (GitHub Pages).

Pages: an overview (market strip and one card per stock), one page per stock (verdict,
key numbers, Claude's notes, every dated PDF), the market reports and the watch list
summaries, with a menu on every page. The PDFs are copied next to the pages, so a link
opens the report in the browser. The evening run commits to `main`; the Pages workflow
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANALYSES = ROOT / "analyses"
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
.strip { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
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
footer { color: var(--muted); font-size: .85em; text-align: center; padding: 24px 16px; }
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


def stock_card(f: Path) -> str:
    r = read_runs(f)[0]
    verdict = first_sentence(r.get("verdict", "") or notes(f).get("Verdict", ""))
    return (
        f'<a class="card stock" href="{f.name}.html">'
        f'<div class="top"><div><div class="sym">{esc(f.name)}</div>'
        f'<div class="name">{esc(company(f))}</div></div>'
        f'<div class="price">{num(r["price"], "${:,.2f}")}</div></div>'
        f"{badge(r['to_entry'])}"
        f'<div class="kv">'
        f"<div><small>Adjusted P/E</small><b>{num(r['pe_adj'], '{:.1f}x')}</b></div>"
        f"<div><small>10y median</small><b>{num(r['pe_median_10y'], '{:.1f}x')}</b></div>"
        f"<div><small>Entry ({num(r['target_pe'], '{:g}x')})</small>"
        f"<b>{num(r['entry_price'], '${:,.2f}')}</b></div></div>"
        f'<p class="verdict">{esc(verdict)}</p></a>'
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
        f'<div class="card tile" style="grid-column: span 2"><small>Stocks to look at</small>'
        f'<b style="font-size:1em">{look}</b></div>'
    )
    return f'<div class="strip">{out}</div>'


def overview(menu) -> str:
    market = ANALYSES / "market"
    summaries = ANALYSES / "summaries"
    runs = [read_runs(f)[0]["run"] for f in stocks()]
    latest = max(runs) if runs else ""
    body = [
        "<h1>Watch list</h1>",
        f'<p class="sub">Last analysed {esc(latest)}. Each card opens the stock\'s page '
        "with its notes and every dated report.</p>",
    ]
    buttons = []
    if summaries.exists() and pdfs(summaries):
        buttons.append(
            a(f"summaries/{pdfs(summaries)[0]}", "Latest watch list summary (PDF)", "btn")
        )
    if market.exists() and pdfs(market):
        buttons.append(a(f"market/{pdfs(market)[0]}", "Latest market report (PDF)", "btn ghost"))
    if buttons:
        body.append(f'<div class="row">{"".join(buttons)}</div>')
    body.append('<div class="grid">' + "".join(stock_card(f) for f in stocks()) + "</div>")
    mruns = read_runs(market)
    if mruns:
        verdict = first_sentence(notes(market).get("Verdict", ""))
        body += [
            "<h2>Market <a href='market.html' style='font-size:.75em;font-weight:500'>"
            "all market reports →</a></h2>",
            market_strip(mruns[0]),
        ]
        if verdict:
            body.append(
                f'<div class="card callout" style="margin-top:16px"><p>{esc(verdict)}</p></div>'
            )
    return layout("Watch list analyses", "index", "\n".join(body), menu)


def stock_page(f: Path, menu) -> str:
    runs = read_runs(f)
    r = runs[0]
    n = notes(f)
    tiles = [
        ("Price", num(r["price"], "${:,.2f}")),
        ("Adjusted P/E", num(r["pe_adj"], "{:.1f}x")),
        ("10-yr median P/E", num(r["pe_median_10y"], "{:.1f}x")),
        ("Target P/E", num(r["target_pe"], "{:g}x")),
        ("Entry price", num(r["entry_price"], "${:,.2f}")),
        ("Price vs entry", num(-float(r["to_entry"]) if r["to_entry"] else None, "{:+.1%}")),
    ]
    body = [
        f"<h1>{esc(company(f))} <span style='color:var(--muted);font-weight:500'>"
        f"{esc(f.name)}</span></h1>",
        f'<p class="sub">Latest analysis {esc(r["run"])} {badge(r["to_entry"])}</p>',
    ]
    if n.get("Verdict"):
        body.append(f'<div class="card callout">{md(n["Verdict"])}</div>')
    body.append(
        '<div class="row">'
        + a(f"{f.name}/{r['file']}", "Open the latest report (PDF)", "btn")
        + a("#history", f"All {len(runs)} dated reports", "btn ghost")
        + "</div>"
    )
    body.append(
        '<div class="strip">'
        + "".join(
            f'<div class="card tile"><small>{esc(k)}</small><b>{v}</b></div>' for k, v in tiles
        )
        + "</div>"
    )
    cols = [k for k in ("Summary", "What to watch", "Risks", "News") if n.get(k)]
    if cols:
        body.append("<h2>Claude's notes</h2><div class='cols'>")
        body += [f'<div class="card notes"><h3>{esc(k)}</h3>{md(n[k])}</div>' for k in cols]
        body.append("</div>")
    if n.get("Business"):
        body.append(f'<h2>Business</h2><div class="card notes">{md(n["Business"])}</div>')
    body.append(
        "<h2 id='history'>Every dated report</h2><div class='card wrap'><table>"
        "<tr><th>Date and time</th><th>Price</th><th>Adj. P/E</th><th>Entry price</th>"
        "<th>Price vs entry</th><th>Verdict</th></tr>"
    )
    for x in runs:
        body.append(
            f"<tr><td class='d'>{a(f.name + '/' + x['file'], x['run'])}</td>"
            f"<td class='n'>{num(x['price'], '${:,.2f}')}</td>"
            f"<td class='n'>{num(x['pe_adj'], '{:.1f}x')}</td>"
            f"<td class='n'>{num(x['entry_price'], '${:,.2f}')}</td>"
            f"<td class='n'>{num(-float(x['to_entry']) if x['to_entry'] else None, '{:+.1%}')}</td>"
            f"<td>{esc(x.get('verdict', ''))}</td></tr>"
        )
    body.append("</table></div>")
    return layout(f"{f.name}: {company(f)}", f.name, "\n".join(body), menu)


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
    menu = [("index", "Overview")] + [(f.name, f.name) for f in stocks()]
    menu += [("market", "Market"), ("summaries", "Summaries")]
    (out / "index.html").write_text(overview(menu))
    for f in stocks():
        (out / f"{f.name}.html").write_text(stock_page(f, menu))
    (out / "market.html").write_text(market_page(menu))
    (out / "summaries.html").write_text(summaries_page(menu))
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE))
