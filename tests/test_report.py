"""A run's reports (stock_analysis.report, issue #60): the store, rendering, the checks, the email
sent once. No network (respx) and no Chrome; the steps run on the test database."""

import base64
import json
import os
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
import respx
from sqlalchemy import text
from test_db import HEADINGS, con, data_dir, fresh, pg_url  # noqa: F401 - fixtures

from stock_analysis import nightly
from stock_analysis.data import DbData
from stock_analysis.report import email, render, validate
from stock_analysis.report import run as report_run
from stock_analysis.report.__main__ import step
from stock_analysis.report.store import BlobStore, FolderStore, check_path, open_store

RUN = "manual__2026-11-25T22:30:00+00:00"
PDF = b"%PDF-1.4 " + b"x" * 6000
NOTES = {s: f"{s} text. More." for s in HEADINGS}


def gathered(sym: str = "AAA", target: float | None = 15.0) -> dict:
    """nightly.gather()'s result for a stock with 48 quarters of EPS 1.0 at a price of 100."""
    q = pd.Series(1.0, index=pd.date_range("2014-02-15", periods=48, freq="91D"))
    row = {"symbol": sym, "name": f"{sym} Inc", "price": 100.0, "market_cap": 10.0,
           "industry": "X", "pe_ttm": 25.0, "ev_to_ebitda": 12.0}  # fmt: skip
    from stock_analysis import stocks

    row = {c: np.nan for c in stocks.row_columns()} | row
    peers = pd.DataFrame([row]).set_index("symbol")
    return {
        "stock": {"symbol": sym, "peers": ["BBB"], "target_pe": target, "target_note": "note",
                  "stakes_per_share": 0.0, "eps_override": []},
        "row": row,
        "prices": pd.Series(100.0, index=pd.bdate_range("2015-01-01", "2026-10-23")),
        "quarters": q,
        "ttm": nightly.trailing_eps(q),
        "years": pd.DataFrame(columns=["symbol", "fiscal_year_end", "column", "value", "source"]),
        "peers": peers,
        "next_report": None,
        "next_estimate": np.nan,
    }  # fmt: skip


# --- the store --------------------------------------------------------------------------


def test_folder_store_and_paths(tmp_path, monkeypatch):
    store = FolderStore(tmp_path)
    store.put("AAA/2026-11-25_2300.pdf", PDF)
    assert store.get("AAA/2026-11-25_2300.pdf") == PDF
    for bad in ("../x.pdf", "AAA/../x.pdf", "/etc/passwd", "AAA", "a/b/c.pdf", "AAA/..pdf"):
        with pytest.raises(ValueError):
            check_path(bad)
    monkeypatch.delenv("STOCK_REPORTS_URL", raising=False)
    monkeypatch.setenv("STOCK_REPORTS_DIR", str(tmp_path / "r"))
    assert open_store().folder == tmp_path / "r"
    monkeypatch.setenv("STOCK_REPORTS_URL", "https://acc.blob.core.windows.net/reports/")
    assert open_store().url == "https://acc.blob.core.windows.net/reports"


@respx.mock
def test_blob_store_signs_in_with_the_identity_and_repeats(monkeypatch):
    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.test/token")
    monkeypatch.setenv("IDENTITY_HEADER", "h")
    token = respx.get("http://identity.test/token").mock(
        return_value=httpx.Response(200, json={"access_token": "t"})
    )
    blob = respx.put("https://acc.test/reports/AAA/x.pdf").mock(
        side_effect=[httpx.ConnectError("no"), httpx.Response(503), httpx.Response(201)]
    )
    BlobStore("https://acc.test/reports").put("AAA/x.pdf", PDF)
    assert token.calls[0].request.url.params["resource"] == "https://storage.azure.com/"
    sent = blob.calls[-1].request
    assert len(blob.calls) == 3 and sent.content == PDF
    assert sent.headers["authorization"] == "Bearer t"
    assert sent.headers["x-ms-blob-type"] == "BlockBlob"
    respx.get("https://acc.test/reports/AAA/no.pdf").mock(return_value=httpx.Response(404))
    with pytest.raises(RuntimeError, match="404"):
        BlobStore("https://acc.test/reports").get("AAA/no.pdf")


def test_blob_store_without_an_identity_says_so(monkeypatch):
    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="managed identity"):
        BlobStore("https://acc.test/reports").put("AAA/x.pdf", PDF)


# --- pages ------------------------------------------------------------------------------


def test_corrections_are_shown_next_to_the_stored_figures_and_change_nothing():
    d = gathered()
    last = d["quarters"].index[-1].date().isoformat()
    fix = {"reported": last, "eps": 2.0, "reason": "tax <gain>", "source": "https://x.test/a"}
    lost = {"reported": "2001-01-01", "eps": 9.0, "reason": "wrong day", "source": "10-Q"}
    k = nightly.key_numbers(d)
    page = render.render(d, k, "now", render.Analysis("2026-11-25", NOTES, [fix, lost]))
    assert "Claude's EPS corrections" in page and "tax &lt;gain&gt;" in page
    assert "$4.00" in page and "$5.00" in page  # the 12 months: stored and corrected
    assert "$60.00" in page and "$75.00" in page  # the entry price: stored and corrected
    assert "no quarter on that date" in page
    assert d["quarters"].iloc[-1] == 1.0 and nightly.key_numbers(d) == pytest.approx(k, nan_ok=True)
    plain = render.render(d, k, "now", render.Analysis("2026-11-25", NOTES))
    assert "Claude's EPS corrections" not in plain
    for section in HEADINGS:
        assert f"{section} text" in plain, section


def test_a_stock_without_a_target_has_no_entry_price_on_its_page():
    d = gathered(target=0.0)
    last = d["quarters"].index[-1].date().isoformat()
    fix = {"reported": last, "eps": 2.0, "reason": "tax", "source": "10-Q"}
    page = render.render(
        d, nightly.key_numbers(d), "now", render.Analysis("2026-11-25", NOTES, [fix])
    )
    assert "No target is set" in page and "Entry at" not in page


# --- the steps on the database ----------------------------------------------------------


@pytest.fixture
def run(con, monkeypatch):  # noqa: F811
    """A submitted run of AAA and the summary, its numbers given and Chrome replaced."""
    with con.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO out_analysis_run (run_key, trading_day, subjects_json, opened_at, "
                "submitted_at, submit_note) VALUES (:k, '2026-11-25', :s, "
                "'2026-11-25T22:40:00', '2026-11-25T23:05:00', 'all <fine>')"
            ),
            {"k": RUN, "s": json.dumps(["AAA", "summaries"])},
        )
        for subject, sections in (("AAA", NOTES), ("summaries", {"Verdict": "v", "Analysis": "a"})):
            conn.execute(
                text(
                    "INSERT INTO out_analysis (run_key, subject, reviewed, sections_json, "
                    "saved_at, saved_by) VALUES (:k, :s, '2026-11-26', :j, "
                    "'2026-11-25T23:00:00', 'claude')"
                ),
                {"k": RUN, "s": subject, "j": json.dumps(sections)},
            )
    monkeypatch.setattr(nightly, "stored_stocks", lambda data, stocks: {"AAA": gathered()})
    monkeypatch.setattr(report_run, "to_pdf_bytes", lambda page: PDF)
    monkeypatch.setattr(validate, "check_screener", lambda *a: [])
    monkeypatch.setattr(validate, "check_rows", lambda *a: [])
    monkeypatch.setattr(validate, "check_history", lambda *a: [])
    return DbData(con, con)


def test_render_stores_the_reports_and_can_be_repeated(run, tmp_path, capsys):
    store = FolderStore(tmp_path)
    for _ in range(2):
        assert step("render", RUN, run, store) == 0
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.pdf"))
    assert files == ["AAA/2026-11-26_0005.pdf", "summaries/2026-11-26_0005.pdf"]  # Italy time
    mine = run.watchlist_runs("AAA")
    mine = mine[mine["file"] == "2026-11-26_0005.pdf"]
    assert len(mine) == 1 and mine.iloc[0]["entry_price"] == 48.0  # 12x, the list's target
    state, _ = report_run.load_run(run, RUN)
    assert state["report"]["files"] == files and state["report"]["failed"] == []
    assert f"{render.PAGES_URL}/AAA/2026-11-26_0005.pdf" in state["report"]["html"]
    assert step("validate", RUN, run, store) == 0
    assert "Result: PASS" in capsys.readouterr().out


def test_render_names_what_failed_and_validation_stops_it(run, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(nightly, "stored_stocks", lambda data, stocks: {})
    monkeypatch.setattr(
        nightly, "compute_stocks", lambda data, todo: ({}, {"AAA": "no prices"}, [])
    )
    with pytest.raises(RuntimeError, match="no prices"):
        step("render", RUN, run, FolderStore(tmp_path))
    monkeypatch.setattr(nightly, "stored_stocks", lambda data, stocks: {"AAA": gathered()})
    store = FolderStore(tmp_path)
    step("render", RUN, run, store)
    store.put("AAA/2026-11-26_0005.pdf", b"not a pdf")
    assert step("validate", RUN, run, store) == 1
    assert "empty or not a PDF" in capsys.readouterr().out


def test_a_failed_data_check_goes_to_the_email_but_does_not_stop_it(run, tmp_path, monkeypatch):
    store = FolderStore(tmp_path)
    step("render", RUN, run, store)
    monkeypatch.setattr(
        validate, "check_screener", lambda *a: [validate._fail("screener run", "none <today>")]
    )
    assert step("validate", RUN, run, store) == 0
    state, _ = report_run.load_run(run, RUN)
    assert state["report"]["checks"] == ["screener run: none <today>"]
    top = email.notices(state["report"])
    assert "none &lt;today&gt;" in top and "all &lt;fine&gt;" in top


def test_only_a_submitted_complete_run_is_rendered(run, con, tmp_path):  # noqa: F811
    store = FolderStore(tmp_path)
    with pytest.raises(RuntimeError, match="No analysis run"):
        step("render", "it's none", run, store)
    with con.begin() as conn:
        conn.execute(text("DELETE FROM out_analysis WHERE subject = 'summaries'"))
    with pytest.raises(RuntimeError, match="No analysis of summaries"):
        step("render", RUN, run, store)
    with con.begin() as conn:
        conn.execute(text("UPDATE out_analysis_run SET submitted_at = NULL"))
    with pytest.raises(RuntimeError, match="not submitted"):
        step("render", RUN, run, store)
    with pytest.raises(RuntimeError, match="not rendered"):
        os.environ.update(BREVO_API_KEY="k", WATCHLIST_EMAIL_FROM="b@x", WATCHLIST_EMAIL_TO="a@x")
        try:
            step("email", RUN, run, store)
        finally:
            for name in ("BREVO_API_KEY", "WATCHLIST_EMAIL_FROM", "WATCHLIST_EMAIL_TO"):
                os.environ.pop(name)


# --- the email --------------------------------------------------------------------------


@pytest.fixture
def mail(run, tmp_path, monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "k")
    monkeypatch.setenv("WATCHLIST_EMAIL_FROM", "Bot <bot@example.com>")
    monkeypatch.setenv("WATCHLIST_EMAIL_TO", "a@example.com, b@example.com")
    store = FolderStore(tmp_path)
    step("render", RUN, run, store)
    return run, store


@respx.mock
def test_email_is_sent_once_with_every_pdf(mail, capsys):
    data, store = mail
    route = respx.post(email.API).mock(return_value=httpx.Response(201, json={"messageId": "m1"}))
    assert step("email", RUN, data, store) == 0
    assert step("email", RUN, data, store) == 0
    assert "emailed already" in capsys.readouterr().out and len(route.calls) == 1
    sent = json.loads(route.calls[0].request.content)
    assert route.calls[0].request.headers["api-key"] == "k"
    assert sent["sender"] == {"email": "bot@example.com", "name": "Bot"}
    assert sent["to"] == [{"email": "a@example.com"}, {"email": "b@example.com"}]
    assert [a["name"] for a in sent["attachment"]] == [
        "AAA_2026-11-26_0005.pdf",
        "summaries_2026-11-26_0005.pdf",
    ]
    assert base64.b64decode(sent["attachment"][0]["content"]) == PDF


@respx.mock
def test_a_refused_email_can_be_sent_again_an_unanswered_one_is_not(mail, con):  # noqa: F811
    data, store = mail
    route = respx.post(email.API).mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(email.Refused, match="401"):
        step("email", RUN, data, store)
    route.mock(side_effect=httpx.ReadTimeout("no answer"))
    with pytest.raises(httpx.ReadTimeout):
        step("email", RUN, data, store)
    route.mock(return_value=httpx.Response(201, json={"messageId": "m"}))
    step("email", RUN, data, store)
    assert len(route.calls) == 2  # it may have gone out: not a third time


def test_email_needs_its_settings(mail, monkeypatch):
    monkeypatch.delenv("BREVO_API_KEY")
    with pytest.raises(RuntimeError, match="BREVO_API_KEY"):
        step("email", RUN, *mail)


@pytest.mark.parametrize(
    "path, name",
    [
        ("BSX/2026-10-27_2100.pdf", "BSX_2026-10-27_2100.pdf"),
        ("market/2026-10-27_2100.pdf", "market_2026-10-27_2100.pdf"),
    ],
)
def test_attachment_names_keep_the_folder(path, name):
    assert email.attachment_name(path) == name


def test_recipients_limits_and_blanks():
    assert email.recipients(" a@x.com , b@y.com ,") == ["a@x.com", "b@y.com"]
    five = ",".join(f"{i}@x.com" for i in range(5))
    assert len(email.recipients(five)) == email.MAX_RECIPIENTS
    for bad in ("", " , ,", five + ",5@x.com"):
        with pytest.raises(ValueError):
            email.recipients(bad)


def test_report_steps_run_where_the_package_is():
    assert (Path(report_run.__file__).parent / "__main__.py").exists()
