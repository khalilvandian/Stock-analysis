"""Build the public web page of the watch list analyses (GitHub Pages).

One page lists every stock's latest numbers and all its dated PDFs, newest first, plus
the market reports and watch list summaries. The PDFs are copied next to it, so a link
opens the report in the browser. The evening run commits the PDFs to `main`; the Pages
workflow (.github/workflows/pages.yml) then runs this and publishes `_site/` at
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
body { font-family: Helvetica, Arial, sans-serif; color: #1a1a1a; background: #fff;
  max-width: 980px; margin: 0 auto; padding: 16px; line-height: 1.45; }
h1 { font-size: 1.6em; margin-bottom: 0.2em; }
h2 { font-size: 1.25em; margin-top: 1.8em; border-bottom: 1px solid #ddd; }
p.note { color: #555; margin-top: 0; }
.wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 0.92em; }
th, td { padding: 6px 8px; border-bottom: 1px solid #e5e5e5; text-align: left; }
th { background: #f4f4f4; }
td.n { text-align: right; white-space: nowrap; }
a { color: #0b5cad; }
@media (prefers-color-scheme: dark) {
  body { color: #e6e6e6; background: #141414; }
  th { background: #222; } th, td { border-color: #333; }
  p.note { color: #aaa; } a { color: #7fb6ff; } h2 { border-color: #333; }
}
"""


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


def num(v: str, fmt: str) -> str:
    try:
        return fmt.format(float(v))
    except (TypeError, ValueError):
        return "–"


def stamp(name: str) -> str:
    """'2026-10-27_1657.pdf' -> '2026-10-27 16:57'."""
    m = re.match(r"(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})", name)
    return f"{m.group(1)} {m.group(2)}:{m.group(3)}" if m else name


def a(href: str, text: str) -> str:
    return f'<a href="{html.escape(href)}">{html.escape(text)}</a>'


def stocks() -> list[Path]:
    """Stock folders (they have runs.csv with a price), most recently analysed first."""
    found = [
        f
        for f in ANALYSES.iterdir()
        if f.is_dir() and f.name not in ("market", "summaries") and read_runs(f)
    ]
    return sorted(found, key=lambda f: read_runs(f)[0]["run"], reverse=True)


def page() -> str:
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>Watch list analyses</title><style>{CSS}</style></head><body>",
        "<h1>Watch list analyses</h1>",
        "<p class='note'>Every stock on the watch list is analysed each evening at 21:00 "
        "Italy time. Every run is kept as a dated PDF: summary first, then the numbers, "
        "then Claude's analysis.</p>",
    ]
    rows = []
    for f in stocks():
        r = read_runs(f)[0]
        rows.append(
            "<tr>"
            f"<td>{a(f'#{f.name}', f.name)}</td>"
            f"<td>{a(f.name + '/' + r['file'], r['run'])}</td>"
            f"<td class='n'>{num(r['price'], '${:,.2f}')}</td>"
            f"<td class='n'>{num(r['pe_adj'], '{:.1f}x')}</td>"
            f"<td class='n'>{num(r['pe_median_10y'], '{:.1f}x')}</td>"
            f"<td class='n'>{num(r['target_pe'], '{:g}x')}</td>"
            f"<td class='n'>{num(r['entry_price'], '${:,.2f}')}</td>"
            f"<td class='n'>{num(r['to_entry'], '{:+.1%}')}</td>"
            "</tr>"
        )
    parts += [
        "<h2>Latest</h2><div class='wrap'><table><tr><th>Stock</th><th>Latest analysis</th>"
        "<th>Price</th><th>Adjusted P/E</th><th>10-yr median</th><th>Target</th>"
        "<th>Entry price</th><th>vs price</th></tr>",
        *rows,
        "</table></div>",
    ]
    for folder, heading in (
        (ANALYSES / "summaries", "Watch list summary"),
        (ANALYSES / "market", "Market report"),
    ):
        if folder.exists() and pdfs(folder):
            links = ", ".join(a(f"{folder.name}/{p}", stamp(p)) for p in pdfs(folder))
            parts.append(f"<h2>{heading}</h2><p>Newest first: {links}</p>")
    for f in stocks():
        parts.append(
            f"<h2 id='{f.name}'>{html.escape(title(f))}</h2><div class='wrap'><table>"
            "<tr><th>Date and time</th><th>Price</th><th>Adjusted P/E</th>"
            "<th>Entry price</th><th>vs price</th><th>Verdict</th></tr>"
        )
        for r in read_runs(f):
            parts.append(
                f"<tr><td>{a(f.name + '/' + r['file'], r['run'])}</td>"
                f"<td class='n'>{num(r['price'], '${:,.2f}')}</td>"
                f"<td class='n'>{num(r['pe_adj'], '{:.1f}x')}</td>"
                f"<td class='n'>{num(r['entry_price'], '${:,.2f}')}</td>"
                f"<td class='n'>{num(r['to_entry'], '{:+.1%}')}</td>"
                f"<td>{html.escape(r.get('verdict', ''))}</td></tr>"
            )
        parts.append("</table></div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def build(out: Path = SITE) -> Path:
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for pdf in ANALYSES.glob("*/*.pdf"):
        dst = out / pdf.parent.name / pdf.name
        dst.parent.mkdir(exist_ok=True)
        shutil.copy2(pdf, dst)
    (out / "index.html").write_text(page())
    (out / ".nojekyll").write_text("")
    return out


if __name__ == "__main__":
    print(build(Path(sys.argv[1]) if len(sys.argv) > 1 else SITE))
