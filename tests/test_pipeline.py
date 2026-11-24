"""The nightly pipeline's run log and checks (issue #30). No network: GitHub and Brevo are
mocked with respx; the database tests use the local test PostgreSQL and skip without it.
The Airflow side (operators, triggers, DAGs) is tested in the Airflow image:
orchestration/tests (docs/ORCHESTRATION.md)."""

from __future__ import annotations

import ast
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import psycopg
import pytest
from test_db import PASSWORD_ENV, empty_db, pg_url  # noqa: F401  (pg_url is a fixture)

from stock_analysis import pipeline as p

ROOT = Path(__file__).resolve().parent.parent
CFG = p.load_config()
T = dt.datetime
STARTED = T(2026, 11, 18, 22, 30)
# The audit tests use dates around go-live, so most of them leave live_from out.
ANY_DAY = {**CFG, "audit": {k: v for k, v in CFG["audit"].items() if k != "live_from"}}


@pytest.fixture()
def conn(pg_url: str):  # noqa: F811
    db = empty_db(pg_url)
    db.migrate()
    db.close()
    with psycopg.connect(pg_url, password=os.environ.get(PASSWORD_ENV), autocommit=True) as c:
        yield c


def sql(c, statement: str, params: dict | None = None) -> None:
    p.rows(c, statement, params)


# ---------------------------------------------------------------- no database


def test_last_close_after_and_before_the_close() -> None:
    assert p.last_close(T(2026, 11, 18, 22, 35), CFG) == dt.date(2026, 11, 18)
    assert p.last_close(T(2026, 11, 18, 15, 0), CFG) == dt.date(2026, 11, 17)


def test_last_close_skips_weekends_and_holidays() -> None:
    assert p.last_close(T(2026, 11, 22, 23, 0), CFG) == dt.date(2026, 11, 20)  # Sunday
    assert p.last_close(T(2026, 11, 26, 23, 0), CFG) == dt.date(2026, 11, 25)  # Thanksgiving
    assert p.last_close(T(2026, 11, 30, 3, 0), CFG) == dt.date(2026, 11, 27)  # Monday morning


def test_holidays_cover_this_year_and_next_from_december() -> None:
    today = dt.date.today()
    years = {d.year for d in p.holidays(CFG)}
    assert today.year in years, "add this year's NYSE holidays to config/pipeline.toml"
    if today.month == 12:
        assert today.year + 1 in years, "add next year's NYSE holidays to config/pipeline.toml"


def test_the_module_imports_without_the_heavy_dependencies() -> None:
    # Airflow imports it in its own interpreter (no pandas, no SQLAlchemy 2.1)
    code = (
        "import sys; import stock_analysis.pipeline; "
        "bad = [m for m in ('pandas', 'sqlalchemy', 'stock_analysis.db') if m in sys.modules]; "
        "assert not bad, bad"
    )
    subprocess.run([sys.executable, "-c", code], check=True, cwd=ROOT)


def test_orchestration_files_parse() -> None:
    # The Airflow side runs in the Airflow image (orchestration/tests); here: valid Python
    for path in (ROOT / "orchestration").rglob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_audit_needs_an_ok_run_for_the_last_trading_day() -> None:
    now = T(2026, 11, 19, 7, 0)
    ok = {"run_date": "2026-11-18", "status": "ok"}
    assert p.audit([ok], now, ANY_DAY).code == p.DONE
    assert p.audit([{**ok, "run_date": "2026-11-17"}], now, ANY_DAY).code == p.FAILED
    assert "ready" in p.audit([{**ok, "status": "ready"}], now, ANY_DAY).message


def test_audit_waits_until_the_night_should_be_over() -> None:
    running = {"run_date": "2026-11-18", "status": "running"}
    friday_ok = {"run_date": "2026-11-17", "status": "ok"}
    # 01:00 Thursday: Wednesday's run may still be going, so Tuesday's is the one checked
    assert p.audit([running, friday_ok], T(2026, 11, 19, 1, 0), CFG).code == p.DONE
    assert p.audit([running, friday_ok], T(2026, 11, 19, 7, 0), CFG).code == p.FAILED


def test_audit_skips_the_days_before_go_live() -> None:
    now = T(2026, 11, 20, 1, 0)  # Friday 01:00: Wednesday the 18th is the day checked
    assert p.audit([], now, CFG).code == p.DONE  # live_from is Thursday the 19th
    later = {**CFG, "audit": {**CFG["audit"], "live_from": dt.date(2026, 11, 18)}}
    assert p.audit([], now, later).code == p.FAILED  # after go-live, no run is never silent


def test_quotes_audit_on_weekdays_only() -> None:
    now = T(2026, 11, 18, 15, 20)  # Wednesday
    fresh = {"status": "ok", "started_at": T(2026, 11, 18, 14, 5)}
    old = {"status": "ok", "started_at": T(2026, 11, 18, 11, 5)}
    assert p.audit_quotes([fresh], now, CFG).code == p.DONE
    assert p.audit_quotes([old, {**fresh, "status": "failed"}], now, CFG).code == p.FAILED
    assert p.audit_quotes([], T(2026, 11, 21, 15, 0), CFG).code == p.DONE  # Saturday


def test_marker_tells_the_session_whether_the_data_is_ready() -> None:
    now = T(2026, 11, 19, 0, 0)
    row = {"run_date": "2026-11-18", "status": "running"}
    assert p.marker([row], now, CFG).code == p.NOT_YET
    assert p.marker([{**row, "status": "ready"}], now, CFG).code == p.DONE
    assert p.marker([{**row, "status": "failed"}], now, CFG).code == p.FAILED


# ---------------------------------------------------------------- GitHub and Brevo (respx)

REPO = CFG["evening"]["repo"]
COMMITS = f"https://api.github.com/repos/{REPO}/commits"
RUNS = f"https://api.github.com/repos/{REPO}/actions/workflows/pages.yml/runs"
DISPATCH = f"https://api.github.com/repos/{REPO}/actions/workflows/pages.yml/dispatches"


def commit(message: str, sha: str = "abc1234def", date: str = "2026-11-18T23:10:00Z") -> dict:
    return {"sha": sha, "commit": {"message": message, "committer": {"date": date}}}


def pages_runs(own: list[dict], later: list[dict]):
    """The Pages runs API: `own` for the commit's runs (head_sha), `later` for the successful
    runs on main since it (created)."""

    def answer(request: httpx.Request) -> httpx.Response:
        runs = own if "head_sha" in request.url.params else later
        return httpx.Response(200, json={"workflow_runs": runs})

    return answer


def test_evening_waits_then_fails_without_the_commit(respx_mock) -> None:
    respx_mock.get(COMMITS).mock(return_value=httpx.Response(200, json=[commit("Other work")]))
    with httpx.Client() as c:
        assert p.check_evening(STARTED, STARTED + dt.timedelta(hours=1), CFG, c).code == p.NOT_YET
        late = p.check_evening(STARTED, STARTED + dt.timedelta(hours=6), CFG, c)
    assert late.code == p.FAILED and "routine" in late.message


def test_evening_passes_when_pages_published_the_commit(respx_mock) -> None:
    msg = "Watch list analyses, 2026-11-19 00:20 CET"
    respx_mock.get(COMMITS).mock(return_value=httpx.Response(200, json=[commit(msg)]))
    route = respx_mock.get(RUNS)
    route.mock(side_effect=pages_runs([], []))
    later = STARTED + dt.timedelta(hours=1)
    with httpx.Client() as c:
        assert p.check_evening(STARTED, later, CFG, c).code == p.NOT_YET
        route.mock(side_effect=pages_runs([{"status": "completed", "conclusion": "success"}], []))
        assert p.check_evening(STARTED, later, CFG, c).code == p.DONE
        assert route.calls.last.request.url.params["head_sha"] == "abc1234def"
        route.mock(side_effect=pages_runs([{"status": "completed", "conclusion": "failure"}], []))
        assert p.check_evening(STARTED, later, CFG, c).code == p.FAILED


def test_evening_takes_the_nights_commit_and_a_later_publish(respx_mock) -> None:
    # A rerun days later: main has that night's session commit and a newer one; the night's
    # own Pages run failed, a later run on main published the site.
    newer = commit("Watch list analyses, 2026-11-22", "newer99", "2026-11-21T23:05:00Z")
    night = commit("Watch list analyses, 2026-11-19", "night11", "2026-11-18T23:10:00Z")
    respx_mock.get(COMMITS).mock(return_value=httpx.Response(200, json=[newer, night]))
    failed = [{"status": "completed", "conclusion": "failure"}]
    route = respx_mock.get(RUNS)
    route.mock(side_effect=pages_runs(failed, [{"head_sha": "after55", "conclusion": "success"}]))
    rerun = STARTED + dt.timedelta(days=4)
    with httpx.Client() as c:
        result = p.check_evening(STARTED, rerun, CFG, c)
    assert result.code == p.DONE and result.detail["commit"] == "night11"
    assert "after55" in result.message
    since = route.calls.last.request.url.params
    assert since["created"] == ">=2026-11-18T23:10:00Z" and since["status"] == "success"


def test_publish_site_needs_the_token_and_dispatches(respx_mock, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN", raising=False)
    with httpx.Client() as c:
        assert p.publish_site(CFG, c).code == p.FAILED
        monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "t")
        route = respx_mock.post(DISPATCH).mock(return_value=httpx.Response(204))
        assert p.publish_site(CFG, c).code == p.DONE
    assert route.calls.last.request.headers["authorization"] == "Bearer t"


def test_alert_splits_the_sender(respx_mock, monkeypatch) -> None:
    for k, v in {"BREVO_API_KEY": "k", "WATCHLIST_EMAIL_FROM": "Stock analysis <bot@example.com>",
                 "PIPELINE_ALERT_TO": "me@example.com"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    brevo = respx_mock.post(p.BREVO).mock(return_value=httpx.Response(201, json={}))
    with httpx.Client() as c:
        assert p.alert("Stock pipeline FAILED: x", "body", CFG, c)
    sent = json.loads(brevo.calls.last.request.content)
    assert sent["sender"]["email"] == "bot@example.com"
    assert sent["to"] == [{"email": "me@example.com"}]


# ---------------------------------------------------------------- database


def test_run_log_start_steps_and_status(conn) -> None:
    now = T(2026, 11, 18, 22, 30)
    first = p.start(conn, "scheduled__1", "stock_nightly", now, CFG)
    assert p.start(conn, "scheduled__1", "stock_nightly", now, CFG) == first
    row = p.run_row(conn, "scheduled__1")
    assert row["status"] == "running" and str(row["run_date"]) == "2026-11-18"
    p.log_step(conn, "scheduled__1", "ingest", p.Result(p.NOT_YET, "waiting"), now)
    p.log_step(conn, "scheduled__1", "ingest", p.Result(p.DONE, "found"), now)
    steps = p.rows(conn, "SELECT step, status, detail FROM ops_pipeline_step")
    assert [(s["step"], s["status"]) for s in steps] == [("ingest", "ok")]
    assert json.loads(steps[0]["detail"])["message"] == "found"
    p.set_status(conn, "scheduled__1", "ready", now)
    assert p.run_row(conn, "scheduled__1")["ready_at"] == now
    p.set_status(conn, "scheduled__1", "failed", now)
    p.set_status(conn, "scheduled__1", "ok", now)  # a failure isn't hidden by a later step
    assert p.run_row(conn, "scheduled__1")["status"] == "failed"
    with pytest.raises(LookupError):
        p.run_row(conn, "nope")


def ingest_row(c, started: str, status: str) -> None:
    sql(c, "INSERT INTO ops_run (started_at, finished_at, mode, status) "
        "VALUES (%(s)s, %(s)s, 'maintain', %(st)s)", {"s": started, "st": status})  # fmt: skip


def test_ingest_check(conn) -> None:
    assert p.check_ingest(conn, STARTED, CFG).code == p.FAILED  # no run
    ingest_row(conn, "2026-11-17T22:30:00", "ok")  # last night's: ignored
    assert p.check_ingest(conn, STARTED, CFG).code == p.FAILED
    ingest_row(conn, "2026-11-18T22:30:05", "partial")
    ok = p.check_ingest(conn, STARTED, CFG)
    assert ok.code == p.DONE and ok.detail["status"] == "partial"
    ingest_row(conn, "2026-11-18T22:31:00", "failed")  # the newest run counts
    assert "failed" in p.check_ingest(conn, STARTED, CFG).message


def test_build_check(conn) -> None:
    assert p.check_build(conn, STARTED).code == p.FAILED  # no build
    sql(conn, "INSERT INTO core_build (started_at, status, summary) VALUES "
        "('2026-11-18T22:40:00', 'failed', '{\"error\": \"boom\"}')")  # fmt: skip
    failed = p.check_build(conn, STARTED)
    assert failed.code == p.FAILED and "boom" in failed.message
    sql(conn, "INSERT INTO core_build (started_at, status, summary) VALUES "
        "('2026-11-18T22:50:00', 'ok', '{}')")  # fmt: skip
    assert p.check_build(conn, STARTED).code == p.DONE


def test_nightly_check_reads_what_was_stored(conn) -> None:
    for i, sym in enumerate(("NEE", "NFLX")):
        sql(conn, "INSERT INTO user_watchlist (symbol, position) VALUES (%(s)s, %(i)s)",
            {"s": sym, "i": i})  # fmt: skip
    failed = p.check_nightly(conn, STARTED)
    assert failed.code == p.FAILED and "no screener run" in failed.message
    at = "2026-11-18T23:00:00"
    sql(conn, "INSERT INTO out_screener_run (run_date, universe, created_at) "
        "VALUES ('2026-11-18', 'SP:SPX', %(t)s)", {"t": at})  # fmt: skip
    sql(conn, "INSERT INTO out_market_numbers (as_of, computed_at, payload_json) "
        "VALUES ('2026-11-18', %(t)s, '{}')", {"t": at})  # fmt: skip
    sql(conn, "INSERT INTO out_stock_numbers (symbol, as_of, computed_at, stock_key, "
        "payload_json) VALUES ('NEE', '2026-11-18', %(t)s, '{}', '{}')", {"t": at})  # fmt: skip
    missing = p.check_nightly(conn, STARTED)
    assert missing.code == p.FAILED and missing.detail["stocks_missing"] == ["NFLX"]
    sql(conn, "INSERT INTO out_stock_numbers (symbol, as_of, computed_at, stock_key, "
        "payload_json) VALUES ('NFLX', '2026-11-18', %(t)s, '{}', '{}')", {"t": at})  # fmt: skip
    assert p.check_nightly(conn, STARTED).code == p.DONE


def test_prices_must_reach_the_last_close(conn) -> None:
    now = T(2026, 11, 18, 22, 50)
    for i in range(1, 21):
        sql(conn, "INSERT INTO core_company (company_id, symbol) VALUES (%(i)s, %(s)s)",
            {"i": i, "s": f"S{i}"})  # fmt: skip
        sql(conn, "INSERT INTO core_index_member VALUES (%(i)s, 'SP:SPX', '2020-01-01', NULL)",
            {"i": i})  # fmt: skip
        day = "2026-11-17" if i == 20 else "2026-11-18"
        sql(conn, "INSERT INTO core_price_daily (company_id, date, close) VALUES (%(i)s, %(d)s, 1)",
            {"i": i, "d": day})  # fmt: skip
    result = p.check_prices(conn, now, CFG)
    assert result.code == p.DONE and result.detail["fresh"] == 19  # 95% exactly
    sql(conn, "DELETE FROM core_price_daily WHERE company_id = 1")
    assert p.check_prices(conn, now, CFG).message.startswith("Prices are stale")


def quote_fetch(c, at: str, status: str, sha: str | None, error: str | None = None) -> None:
    sql(c, "INSERT INTO raw_fetch (source, request_key, fetched_at, loaded_at, status, "
        "rows_stored, payload_sha256, error) VALUES ('tradingview_quotes', 'all', %(t)s, %(t)s, "
        "%(st)s, 500, %(h)s, %(e)s)", {"t": at, "st": status, "h": sha, "e": error})  # fmt: skip


def test_quotes_check_reads_the_run_just_started(conn) -> None:
    started = T(2026, 11, 18, 15, 5)
    quote_fetch(conn, "2026-11-18T14:05:30", "error", None, "old error")  # before: ignored
    assert p.check_quotes(conn, started).code == p.DONE  # same prices: nothing stored
    quote_fetch(conn, "2026-11-18T15:05:40", "ok", "a")
    assert "500 rows" in p.check_quotes(conn, started).message
    quote_fetch(conn, "2026-11-18T15:06:10", "error", None, "HTTP 503")
    failed = p.check_quotes(conn, started)
    assert failed.code == p.FAILED and "HTTP 503" in failed.message
