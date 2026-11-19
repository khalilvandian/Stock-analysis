"""stock_nightly: the weekday pipeline after the US close (issue #30, docs/ORCHESTRATION.md).

    start ─┬─► wait_for_ingest ─┬─► check_prices ─► mark_ready ─► wait_for_evening ─┐
           │                    └─► check_nightly ─────────────────────────────────┤
           └─► check_quotes ───────────────────────────────────────────────────────┴─► finish

- check_quotes: the hourly quotes job (`stock-quotes`) stored a quote in the last 4 hours.
- wait_for_ingest: the Azure Container Apps Job `stock-ingest` (22:30 UTC) fetched, built,
  took the coverage snapshot and ran the nightly analyses (a finished row in ops_run).
- check_nightly: the nightly analyses (screener, watch-list numbers, market numbers) ran
  without errors. A side branch: it alerts but doesn't hold back the ready marker, because
  the evening session computes what is missing on the spot.
- check_prices: the current S&P 500 members have the last close in core_price_daily.
- mark_ready: ops_pipeline_run.status = 'ready', the marker the evening session can read
  (python -m stock_analysis.pipeline marker).
- wait_for_evening: the scheduled Claude session's "Watch list analyses" commit is on main
  and the Pages workflow published it.

Every step is a row in ops_pipeline_step. A failure (or a sensor that runs out of time)
marks the run failed and emails the alert address through Brevo. The logic lives in
`python -m stock_analysis.pipeline`; this file only orders the steps, so everything here
also runs by hand without Airflow.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta

from airflow.sdk import PokeReturnValue, dag, task
from airflow.timetables.trigger import CronTriggerTimetable

try:
    from airflow.sdk.exceptions import AirflowFailException
except ImportError:  # older layout
    from airflow.exceptions import AirflowFailException

# The project's own interpreter and code (orchestration/Dockerfile): separate from Airflow's,
# because the two pin different SQLAlchemy versions.
PYTHON = os.environ.get("STOCK_PYTHON", "/opt/stock-venv/bin/python")
PROJECT = os.environ.get("STOCK_PROJECT", "/opt/stock")
DONE, NOT_YET, FAILED = 0, 3, 4


def pipeline(*args: str) -> int:
    """Run one pipeline step; its output goes to the task log."""
    env = {**os.environ, "PYTHONPATH": os.path.join(PROJECT, "src")}
    proc = subprocess.run(
        [PYTHON, "-m", "stock_analysis.pipeline", *args],
        cwd=PROJECT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )
    for line in (proc.stdout + proc.stderr).splitlines():
        print(line)
    return proc.returncode


def step(*args: str) -> None:
    code = pipeline(*args)
    if code == FAILED:
        raise AirflowFailException(f"{args[0]} failed (see the log)")
    if code != DONE:
        raise RuntimeError(f"{args[0]} crashed with exit code {code}; it will be retried")


def poke(*args: str) -> PokeReturnValue:
    code = pipeline(*args)
    if code == FAILED:
        raise AirflowFailException(f"{args[0]} failed (see the log)")
    if code not in (DONE, NOT_YET):
        raise RuntimeError(f"{args[0]} crashed with exit code {code}; it will be retried")
    return PokeReturnValue(is_done=code == DONE)


def on_failure(context) -> None:
    """Mark the run failed and send the alert email (a callback never raises)."""
    ti = context["ti"]
    error = context.get("exception")
    message = f"{type(error).__name__}: {error}" if error else "failed"
    try:
        args = ["fail", context["dag_run"].run_id, ti.task_id, message]
        url = getattr(ti, "log_url", None)
        pipeline(*args, *(["--log-url", url] if url else []))
    except Exception as exc:  # noqa: BLE001
        print(f"The failure callback itself failed: {exc}")


DEFAULTS = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "on_failure_callback": on_failure,
}


@dag(
    dag_id="stock_nightly",
    description="Weekday pipeline after the US close: ingest, prices, ready marker, evening run",
    schedule=CronTriggerTimetable("35 22 * * 1-5", timezone="UTC"),
    start_date=datetime(2026, 11, 18),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=10),
    default_args=DEFAULTS,
    tags=["stock", "issue-30"],
    doc_md=__doc__,
)
def stock_nightly():
    @task
    def start(key: str) -> None:
        step("start", key)

    @task.sensor(poke_interval=300, timeout=4 * 3600, mode="reschedule")
    def wait_for_ingest(key: str) -> PokeReturnValue:
        return poke("wait-ingest", key)

    @task
    def check_prices(key: str) -> None:
        step("check-prices", key)

    @task
    def check_nightly(key: str) -> None:
        step("check-nightly", key)

    @task
    def check_quotes(key: str) -> None:
        step("check-quotes", key)

    @task
    def mark_ready(key: str) -> None:
        step("ready", key)

    @task.sensor(poke_interval=600, timeout=5 * 3600, mode="reschedule")
    def wait_for_evening(key: str) -> PokeReturnValue:
        return poke("wait-evening", key)

    @task
    def finish(key: str) -> None:
        step("finish", key)

    key = "{{ run_id }}"  # the dag_run_id: the run log's run_key
    begin, ingest, done = start(key), wait_for_ingest(key), finish(key)
    prices, nightly, quotes = check_prices(key), check_nightly(key), check_quotes(key)
    begin >> ingest >> [prices, nightly]
    prices >> mark_ready(key) >> wait_for_evening(key) >> done
    nightly >> done
    begin >> quotes >> done


stock_nightly()
