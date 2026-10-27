import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import watchlist  # noqa: E402


def _dates(rows: list[tuple[str, float | None]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in rows]).tz_localize("America/New_York")
    return pd.DataFrame({"EPS Estimate": 1.0, "Reported EPS": [e for _, e in rows]}, index=idx)


def test_config_has_what_each_stock_needs():
    cfg = watchlist.load_watchlist()
    assert cfg["stock"], "the watch list is empty"
    for s in cfg["stock"]:
        assert s["symbol"].isupper() and s["peers"] and s["target_pe"] > 0


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
    q = watchlist.quarterly_eps(d, [{"reported": "2026-04-16", "eps": 1.1}])
    assert list(q.round(2)) == [1.0, 1.1, 1.2, 1.3]
    assert watchlist.trailing_eps(q).iloc[-1] == 4.6


def test_trailing_eps_needs_four_consecutive_quarters():
    q = pd.Series(
        [1.0, 1.0, 1.0, 1.0],
        index=pd.to_datetime(["2020-01-20", "2020-04-20", "2022-07-20", "2022-10-20"]),
    )
    assert watchlist.trailing_eps(q).empty


def test_yearly_pe_uses_eps_at_the_q4_report_and_average_price():
    days = pd.bdate_range("2024-01-01", "2026-06-30")
    prices = pd.Series(100.0, index=days)
    ttm = pd.Series(
        [4.0, 5.0], index=pd.to_datetime(["2025-02-10", "2026-02-10"])
    )  # FY2024 and FY2025 EPS
    y = watchlist.yearly_pe(prices, ttm)
    assert y.loc[2024, "pe"] == 25.0
    assert y.loc[2025, "pe"] == 20.0


def test_split_adjust_rescales_pre_split_eps_and_shares():
    hist = pd.DataFrame(
        {
            "symbol": "X",
            "fiscal_year_end": pd.to_datetime(["2024-12-31"] * 2 + ["2026-12-31"] * 2),
            "column": ["_shares", "eps", "_shares", "eps"],
            "value": [40.0, 100.0, 1000.0, 4.0],
        }
    )
    splits = pd.Series([25.0], index=pd.to_datetime(["2025-06-01"]).tz_localize("UTC"))
    out = watchlist.split_adjust(hist, splits, shares_now=1000.0)
    assert list(out["value"]) == [1000.0, 4.0, 1000.0, 4.0]


def test_notes_sections_and_first_sentence(tmp_path, monkeypatch):
    monkeypatch.setattr(watchlist, "OUT", tmp_path)
    (tmp_path / "X").mkdir()
    (tmp_path / "X/notes.md").write_text(
        "# X\n\nUpdated: 2026-10-27\n\n## Verdict\n\n**Cheap. Buy below $10.**\n\n## Risks\n\n- a\n"
    )
    updated, notes = watchlist.read_notes("X")
    assert updated == "2026-10-27"
    assert notes["Risks"] == "- a"
    assert watchlist.first_sentence(notes["Verdict"]) == "Cheap."


def test_new_pdf_never_overwrites(tmp_path):
    first = watchlist.new_pdf(tmp_path, "2026-10-27_2100")
    first.write_bytes(b"x")
    assert watchlist.new_pdf(tmp_path, "2026-10-27_2100").name == "2026-10-27_2100-2.pdf"


def test_formatting():
    assert watchlist.times(np.nan) == "–"
    assert watchlist.pct(-0.0712) == "-7.1%"


def test_email_attaches_every_pdf_and_sends_once_through_brevo(tmp_path, monkeypatch):
    import json

    import httpx
    import pytest
    import respx
    import send_email

    (tmp_path / "analyses/BSX").mkdir(parents=True)
    (tmp_path / "analyses/BSX/2026-10-27_2100.pdf").write_bytes(b"%PDF-1.4")
    (tmp_path / "email.html").write_text("<p>hi</p>")
    monkeypatch.setattr(send_email, "ROOT", tmp_path)
    run = {"subject": "S", "html": "email.html", "files": ["analyses/BSX/2026-10-27_2100.pdf"]}
    msg = send_email.build_message(
        run, "a@example.com, b@example.com", "Bot <bot@example.com>", test=True
    )
    assert msg["subject"] == "[Test] S"
    with respx.mock:
        route = respx.post(send_email.API).mock(
            return_value=httpx.Response(201, json={"messageId": "<m1>"})
        )
        assert send_email.send(msg, "k")["id"] == "<m1>"
        assert len(route.calls) == 1
        req = route.calls[0].request
    body = json.loads(req.content)
    assert req.headers["api-key"] == "k"
    assert body["sender"] == {"email": "bot@example.com", "name": "Bot"}
    assert body["to"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]
    assert body["attachment"] == [{"name": "BSX_2026-10-27_2100.pdf", "content": "JVBERi0xLjQ="}]
    with pytest.raises(SystemExit):
        send_email.recipients(",".join(f"{i}@example.com" for i in range(6)))


def test_links_go_to_the_pages_site_on_main(monkeypatch):
    pdf = watchlist.OUT / "BSX/2026-10-27_2100.pdf"
    monkeypatch.setenv("WATCHLIST_BRANCH", "main")
    assert watchlist.link(pdf) == f"{watchlist.PAGES_URL}/BSX/2026-10-27_2100.pdf"
    assert watchlist.link(watchlist.OUT / "README.md") == f"{watchlist.PAGES_URL}/"
    monkeypatch.setenv("WATCHLIST_BRANCH", "work")
    assert watchlist.link(pdf).endswith("/blob/work/analyses/BSX/2026-10-27_2100.pdf")


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
    (analyses / "BSX/runs.csv").write_text(
        "run,file,price,eps_adj_ttm,pe_adj,pe_median_10y,target_pe,entry_price,to_entry,verdict\n"
        "2026-10-26 21:00 CET,2026-10-26_2100.pdf,44,3.2,13.8,25.2,13,41.7,-0.05,Old.\n"
        "2026-10-27 21:00 CET,2026-10-27_2100.pdf,45,3.2,14.0,25.2,13,41.7,-0.07,Cheap.\n"
    )
    (analyses / "OLD").mkdir()  # analysed before, since removed from the watch list
    (analyses / "OLD/runs.csv").write_text(
        "run,file,price,eps_adj_ttm,pe_adj,pe_median_10y,target_pe,entry_price,to_entry,verdict\n"
        "2026-10-20 21:00 CEST,2026-10-20_2100.pdf,10,1,10,12,9,9,-0.1,Gone.\n"
    )
    for p in ("BSX/2026-10-26_2100.pdf", "BSX/2026-10-27_2100.pdf", "market/2026-10-27_2100.pdf"):
        (analyses / p).write_bytes(b"%PDF-1.4")
    (tmp_path / "watchlist.toml").write_text('[[stock]]\nsymbol = "BSX"\n')
    monkeypatch.setattr(site, "ANALYSES", analyses)
    monkeypatch.setattr(site, "CONFIG", tmp_path / "watchlist.toml")
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
