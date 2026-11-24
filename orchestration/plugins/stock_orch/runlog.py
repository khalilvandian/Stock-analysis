"""The run log, the checks and the alert, as Airflow calls them (issue #30).

Each function opens its own short connection to the stock database (STOCK_PIPELINE_DB_URL,
or a target of config/database.toml) and closes it, so the scheduler holds no connection
between tasks: the server allows only 50, shared with the jobs and the web API.
"""

from __future__ import annotations

import datetime as dt

import httpx
from airflow.sdk.exceptions import AirflowFailException

from stock_analysis import pipeline as p


def started_at(run_key: str) -> dt.datetime:
    with p.connect() as conn:
        return p.run_row(conn, run_key)["started_at"]


def record(run_key: str, step: str, result: p.Result) -> None:
    with p.connect() as conn:
        p.log_step(conn, run_key, step, result, p.utcnow())


def begin(run_key: str, pipeline: str) -> str:
    with p.connect() as conn:
        run_id = p.start(conn, run_key, pipeline, p.utcnow(), p.load_config())
        p.log_step(conn, run_key, "start", p.Result(p.DONE, f"Run {run_id} started"), p.utcnow())
    return f"Run {run_id} started"


def check(run_key: str, step: str, name: str) -> str:
    """Run one check by name, record it, and fail the task (no retry) when it fails."""
    cfg, now = p.load_config(), p.utcnow()
    with p.connect() as conn:
        started = p.run_row(conn, run_key)["started_at"]
        result = {
            "ingest": lambda: p.check_ingest(conn, started, cfg),
            "build": lambda: p.check_build(conn, started),
            "nightly": lambda: p.check_nightly(conn, started),
            "prices": lambda: p.check_prices(conn, now, cfg),
            "quotes": lambda: p.check_quotes(conn, started),
        }[name]()
        p.log_step(conn, run_key, step, result, now)
    if result.code != p.DONE:
        raise AirflowFailException(result.message)
    return result.message


def set_status(run_key: str, step: str, status: str, message: str, closing: bool = False) -> str:
    """`closing`: the DAG's `finish` task, which runs only when every other task succeeded,
    so it may turn a failed run (rerun in Airflow) ok."""
    with p.connect() as conn:
        p.set_status(conn, run_key, status, p.utcnow(), closing=closing)
        p.log_step(conn, run_key, step, p.Result(p.DONE, message), p.utcnow())
    return message


def publish_site(run_key: str, step: str) -> str:
    with httpx.Client() as client:
        result = p.publish_site(p.load_config(), client)
    record(run_key, step, result)
    if result.code != p.DONE:
        raise AirflowFailException(result.message)
    return result.message


def on_failure(context) -> None:
    """Mark the run failed, log the step and email the alert. Never raises: a callback that
    fails must not hide the failure it reports, so each part is tried on its own."""
    ti = context["ti"]
    run_key = context["dag_run"].run_id
    error = context.get("exception")
    message = f"{type(error).__name__}: {error}" if error else "failed"
    notes = []
    try:
        with p.connect() as conn:
            p.set_status(conn, run_key, "failed", p.utcnow())
            p.log_step(conn, run_key, ti.task_id, p.Result(p.FAILED, message), p.utcnow())
    except Exception as exc:  # noqa: BLE001
        notes.append(f"(could not write the run log: {exc})")
    body = f"DAG {ti.dag_id}, run {run_key}\nStep {ti.task_id} failed:\n\n{message}\n"
    url = getattr(ti, "log_url", None)
    if url:
        body += f"\nLog: {url}\n"
    body += "\n".join(notes)
    try:
        with httpx.Client() as client:
            sent = p.alert(f"Stock pipeline FAILED: {ti.task_id}", body, p.load_config(), client)
        if not sent:
            print("No alert email: the Brevo settings are missing")
    except Exception as exc:  # noqa: BLE001
        print(f"The alert email failed: {exc}")
