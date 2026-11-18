"""The nightly pipeline's checks and run log (issue #30). No network: GitHub and Brevo are
mocked with respx; the database tests use the local test PostgreSQL and skip without it."""

from __future__ import annotations

import datetime as dt
import json
import py_compile
from pathlib import Path

import httpx
import pytest
from test_db import empty_db, pg_url  # noqa: F401  (pg_url is a fixture)

from stock_analysis import pipeline as p
from stock_analysis.db import run

ROOT = Path(__file__).resolve().parent.parent
CFG = p.load_config()
T = dt.datetime


@pytest.fixture()
def fresh(pg_url: str):  # noqa: F811
    db = empty_db(pg_url)
    db.migrate()
    yield db
    db.close()


# ---------------------------------------------------------------- trading days


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


def test_dag_file_compiles() -> None:
    # The full DAG check (imports, order) runs inside the Airflow image: docs/ORCHESTRATION.md
    py_compile.compile(str(ROOT / "orchestration" / "dags" / "stock_nightly.py"), doraise=True)


# ---------------------------------------------------------------- audit (no database)


def test_audit_needs_an_ok_run_for_the_last_trading_day() -> None:
    now = T(2026, 11, 19, 6, 0)  # Thursday morning: the 18th must be done
    ok = {"run_date": "2026-11-18", "status": "ok"}
    assert p.audit([ok], now, CFG).code == p.DONE
    assert p.audit([{**ok, "run_date": "2026-11-17"}], now, CFG).code == p.FAILED
    assert "ready" in p.audit([{**ok, "status": "ready"}], now, CFG).message


def test_marker_tells_the_evening_session_whether_to_start() -> None:
    now = T(2026, 11, 19, 0, 0)  # just after midnight UTC: Wednesday the 18th's data
    row = {"run_date": "2026-11-18", "status": "running"}
    assert p.marker([row], now, CFG).code == p.NOT_YET
    assert p.marker([{**row, "status": "ready"}], now, CFG).code == p.DONE
    assert p.marker([{**row, "status": "failed"}], now, CFG).code == p.FAILED
    assert p.marker([{**row, "run_date": "2026-11-17", "status": "ok"}], now, CFG).code == p.NOT_YET


# ---------------------------------------------------------------- GitHub (respx)

REPO = CFG["evening"]["repo"]
COMMITS = f"https://api.github.com/repos/{REPO}/commits"
RUNS = f"https://api.github.com/repos/{REPO}/actions/workflows/pages.yml/runs"
READY = T(2026, 11, 18, 23, 40)


def commit(message: str, sha: str = "abc1234def") -> dict:
    return {"sha": sha, "commit": {"message": message}}


def test_evening_waits_then_fails_without_the_commit(respx_mock) -> None:
    respx_mock.get(COMMITS).mock(return_value=httpx.Response(200, json=[commit("Other work")]))
    with httpx.Client() as c:
        assert p.check_evening(READY, READY + dt.timedelta(hours=1), CFG, c).code == p.NOT_YET
        late = p.check_evening(READY, READY + dt.timedelta(hours=5), CFG, c)
    assert late.code == p.FAILED and "routine" in late.message


def test_evening_passes_when_pages_published_the_commit(respx_mock) -> None:
    msg = "Evening watch list analyses, 2026-11-18 23:50 CET"
    respx_mock.get(COMMITS).mock(return_value=httpx.Response(200, json=[commit(msg)]))
    route = respx_mock.get(RUNS)
    route.mock(return_value=httpx.Response(200, json={"workflow_runs": []}))
    later = READY + dt.timedelta(hours=1)
    with httpx.Client() as c:
        assert p.check_evening(READY, later, CFG, c).code == p.NOT_YET
        route.mock(
            return_value=httpx.Response(
                200, json={"workflow_runs": [{"status": "completed", "conclusion": "success"}]}
            )
        )
        assert p.check_evening(READY, later, CFG, c).code == p.DONE
        route.mock(
            return_value=httpx.Response(
                200, json={"workflow_runs": [{"status": "completed", "conclusion": "failure"}]}
            )
        )
        assert p.check_evening(READY, later, CFG, c).code == p.FAILED
    assert route.calls.last.request.url.params["head_sha"] == "abc1234def"


# ---------------------------------------------------------------- database


def seed_prices(db, newest: dict[str, str]) -> None:
    with db.begin() as conn:
        for i, (symbol, day) in enumerate(newest.items(), start=1):
            run(conn, "INSERT INTO core_company (company_id, symbol) VALUES (:i, :s)",
                {"i": i, "s": symbol})  # fmt: skip
            run(conn, "INSERT INTO core_index_member VALUES (:i, 'SP:SPX', '2020-01-01', NULL)",
                {"i": i})  # fmt: skip
            for d in ("2026-11-16", day):
                run(conn, "INSERT INTO core_price_daily (company_id, date, close) "
                    "VALUES (:i, :d, 1) ON CONFLICT DO NOTHING", {"i": i, "d": d})  # fmt: skip


def ingest_row(db, started: str, status: str, finished: str | None = None) -> None:
    with db.begin() as conn:
        run(
            conn,
            "INSERT INTO ops_run (started_at, finished_at, mode, status) "
            "VALUES (:s, :f, 'maintain', :st)",
            {"s": started, "f": finished, "st": status},
        )


def test_run_log_start_is_idempotent_and_steps_upsert(fresh) -> None:
    now = T(2026, 11, 18, 22, 35)
    first = p.start(fresh, "scheduled__1", now, CFG)
    assert p.start(fresh, "scheduled__1", now, CFG) == first
    row = p.run_row(fresh, "scheduled__1")
    assert row["status"] == "running" and str(row["run_date"]) == "2026-11-18"
    p.log_step(fresh, "scheduled__1", "wait_for_ingest", p.Result(p.NOT_YET, "waiting"), now)
    p.log_step(fresh, "scheduled__1", "wait_for_ingest", p.Result(p.DONE, "found"), now)
    with fresh.connect() as conn:
        steps = run(conn, "SELECT step, status, detail FROM ops_pipeline_step").fetchall()
    assert [(s, st) for s, st, _ in steps] == [("wait_for_ingest", "ok")]
    assert json.loads(steps[0][2])["message"] == "found"
    p.set_status(fresh, "scheduled__1", "ready", now)
    assert p.run_row(fresh, "scheduled__1")["ready_at"] == now


def test_ingest_waits_passes_and_fails(fresh) -> None:
    dag_start = T(2026, 11, 18, 22, 35)
    soon = dag_start + dt.timedelta(minutes=30)
    ingest_row(fresh, "2026-11-17T22:30:00", "ok", "2026-11-17T22:31:00")  # last night: ignored
    assert p.check_ingest(fresh, dag_start, soon, CFG).code == p.NOT_YET
    late = p.check_ingest(fresh, dag_start, dag_start + dt.timedelta(hours=4), CFG)
    assert late.code == p.FAILED and "not started" in late.message
    ingest_row(fresh, "2026-11-18T22:30:05", "running")
    assert p.check_ingest(fresh, dag_start, soon, CFG).code == p.NOT_YET
    with fresh.begin() as conn:
        run(conn, "UPDATE ops_run SET status = 'partial', finished_at = '2026-11-18T23:10:00' "
            "WHERE started_at = '2026-11-18T22:30:05'")  # fmt: skip
    done = p.check_ingest(fresh, dag_start, soon, CFG)
    assert done.code == p.DONE and done.detail["status"] == "partial"
    with fresh.begin() as conn:
        run(conn, "UPDATE ops_run SET status = 'failed'")
    assert p.check_ingest(fresh, dag_start, soon, CFG).code == p.FAILED


def test_prices_must_reach_the_last_close(fresh) -> None:
    now = T(2026, 11, 18, 22, 50)
    seed_prices(fresh, {f"S{i}": "2026-11-18" for i in range(19)} | {"LATE": "2026-11-17"})
    result = p.check_prices(fresh, now, CFG)
    assert result.code == p.DONE and result.detail["fresh"] == 19  # 95% exactly
    with fresh.begin() as conn:
        run(conn, "DELETE FROM core_price_daily WHERE date = '2026-11-18' AND company_id = 1")
    stale = p.check_prices(fresh, now, CFG)
    assert stale.code == p.FAILED and stale.message.startswith("Prices are stale")


def test_fail_marks_the_run_and_emails_the_alert(fresh, respx_mock, monkeypatch) -> None:
    from stock_analysis.pipeline.__main__ import main

    monkeypatch.setattr("stock_analysis.pipeline.__main__.database", lambda read_only=False: fresh)
    monkeypatch.setattr(fresh, "close", lambda: None)
    for k, v in {"BREVO_API_KEY": "k", "WATCHLIST_EMAIL_FROM": "bot@example.com",
                 "PIPELINE_ALERT_TO": "me@example.com"}.items():  # fmt: skip
        monkeypatch.setenv(k, v)
    brevo = respx_mock.post(p.BREVO).mock(return_value=httpx.Response(201, json={}))
    assert main(["start", "manual__x"]) == p.DONE
    assert main(["fail", "manual__x", "check_prices", "Prices are stale"]) == p.DONE
    assert p.run_row(fresh, "manual__x")["status"] == "failed"
    sent = json.loads(brevo.calls.last.request.content)
    assert sent["subject"] == "Stock pipeline FAILED: check_prices"
    assert sent["to"] == [{"email": "me@example.com"}]
