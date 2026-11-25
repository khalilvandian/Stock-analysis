from pathlib import Path

import numpy as np
import pandas as pd

from stock_analysis import nightly
from stock_analysis.report import render


def _dates(rows: list[tuple[str, float | None]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in rows]).tz_localize("America/New_York")
    return pd.DataFrame({"EPS Estimate": 1.0, "Reported EPS": [e for _, e in rows]}, index=idx)


def test_quarterly_eps_drops_duplicates_and_applies_overrides():
    d = _dates(
        [
            ("2026-01-20", 1.0),
            ("2026-01-20", 1.0),  # same report listed twice
            ("2026-04-16", 9.0),  # one-off, overridden below
            ("2026-07-16", 1.2),
            ("2026-10-20", 1.3),
            ("2027-01-19", None),  # future report
        ]
    )
    q = nightly.quarterly_eps(d, [{"reported": "2026-04-16", "eps": 1.1}])
    assert list(q.round(2)) == [1.0, 1.1, 1.2, 1.3]
    assert nightly.trailing_eps(q).iloc[-1] == 4.6


def test_trailing_eps_needs_four_consecutive_quarters():
    q = pd.Series(
        [1.0, 1.0, 1.0, 1.0],
        index=pd.to_datetime(["2020-01-20", "2020-04-20", "2022-07-20", "2022-10-20"]),
    )
    assert nightly.trailing_eps(q).empty


def test_yearly_pe_uses_eps_at_the_q4_report_and_average_price():
    days = pd.bdate_range("2024-01-01", "2026-06-30")
    prices = pd.Series(100.0, index=days)
    ttm = pd.Series(
        [4.0, 5.0], index=pd.to_datetime(["2025-02-10", "2026-02-10"])
    )  # FY2024 and FY2025 EPS
    y = nightly.yearly_pe(prices, ttm)
    assert y.loc[2024, "pe"] == 25.0
    assert y.loc[2025, "pe"] == 20.0


def test_formatting():
    assert render.times(np.nan) == "–"
    assert render.pct(-0.0712) == "-7.1%"


def test_site_lists_every_dated_pdf(tmp_path, monkeypatch):
    import importlib.util  # analysis/site.py shares its name with the stdlib site module

    spec = importlib.util.spec_from_file_location(
        "analyses_site", Path(__file__).resolve().parent.parent / "analysis/site.py"
    )
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)

    analyses = tmp_path / "analyses"
    (analyses / "BSX").mkdir(parents=True)
    (analyses / "market").mkdir()
    (analyses / "BSX/README.md").write_text(
        "# Boston Scientific Corporation (BSX): dated analyses\n"
    )
    (analyses / "OLD").mkdir()  # analysed before, since removed from the watch list

    def run(symbol, run_at, file, price, verdict):
        return {"symbol": symbol, "run_at": run_at, "file": file, "price": price,
                "eps_adj_ttm": 3.2, "pe_adj": 14.0, "pe_median_10y": 25.2, "target_pe": 13,
                "entry_price": 41.7, "to_entry": -0.07, "verdict": verdict}  # fmt: skip

    runs = [  # out_watchlist_run keeps the times in UTC
        run("BSX", "2026-10-26T20:00:00", "2026-10-26_2100.pdf", 44, "Old."),
        run("BSX", "2026-10-27T20:00:00", "2026-10-27_2100.pdf", 45, "Cheap."),
        run("OLD", "2026-10-20T19:00:00", "2026-10-20_2100.pdf", 10, "Gone."),
    ]

    def query(sql):
        if "user_watchlist" in sql:
            return [{"symbol": "BSX"}]
        return [dict(r) for r in runs] if "out_watchlist_run" in sql else []

    monkeypatch.setattr(site, "db", lambda: query)
    for p in ("BSX/2026-10-26_2100.pdf", "BSX/2026-10-27_2100.pdf", "market/2026-10-27_2100.pdf"):
        (analyses / p).write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(site, "ANALYSES", analyses)
    out = site.build(tmp_path / "_site")
    index, bsx = (out / "index.html").read_text(), (out / "BSX.html").read_text()
    assert (out / "BSX/2026-10-26_2100.pdf").exists() and (
        out / "market/2026-10-27_2100.pdf"
    ).exists()
    # the watch list page: active stocks in the sidebar, each with its latest summary
    assert 'href="#BSX"' in index and 'id="BSX"' in index and 'href="BSX.html"' in index
    assert "Previously watched" in index and 'href="OLD.html"' in index and 'id="OLD"' not in index
    # the stock page: the report viewer can switch to every earlier analysis
    assert 'value="BSX/2026-10-26_2100.pdf"' in bsx and 'id="previous"' in bsx
    assert bsx.index("2026-10-27 21:00 CET") < bsx.index("2026-10-26 21:00 CET")  # newest first
    assert "Boston Scientific Corporation" in bsx and 'href="market.html"' in bsx  # the menu


def test_site_has_grouped_menus_and_the_pipeline_page(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "analyses_site_menu", Path(__file__).resolve().parent.parent / "analysis/site.py"
    )
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    monkeypatch.setattr(site, "db", lambda: None)  # no database: the pages still build
    monkeypatch.setattr(site, "ANALYSES", tmp_path / "analyses")
    (tmp_path / "analyses").mkdir()
    out = site.build(tmp_path / "_site")
    page = (out / "pipeline.html").read_text(encoding="utf-8")
    # every group is on every page; the current page and its group are marked
    for group in ("Analyses", "Markets", "Project"):
        assert f"<summary>{group}</summary>" in page
    assert 'href="pipeline.html" class=on aria-current=page' in page
    assert "<details class=on><summary>Project</summary>" in page
    # the diagram comes from docs/pipeline.html, without the notes on maintaining it
    assert "Stock Analysis Pipeline" in page and "<svg" in page
    assert 'id="maintain"' not in page and ".pipeline .box" in page


def test_first_sentence():
    assert render.first_sentence("**Cheap. Buy below $10.**") == "Cheap."
