"""stock_nightly: the weekday night after the US close (issue #30, docs/ORCHESTRATION.md).

Airflow runs every piece as a task; the Azure jobs have no schedule of their own.

    start ─► ingest ─► check_ingest ─┬─► check_prices ─► mark_ready ─► wait_for_evening ──┐
                                     └─► nightly ─► check_nightly ─► publish_site ────────┴─► finish

- ingest: a run of the Container Apps Job `stock-ingest` (`db ingest --no-nightly
  --no-site`): fetch, build, coverage snapshot.
- nightly: another run of the same job (`db nightly`): the screener, the watch list's
  numbers and the market numbers, which the Claude session reads.
- check_*: SQL on what the run stored (stock_analysis.pipeline), recorded in
  ops_pipeline_step; a failed check fails at once (no retry).
- mark_ready: the marker the Claude session can read (python -m stock_analysis.pipeline marker).
- wait_for_evening: the Claude session (its own schedule, 00:00 Italy time) committed
  "Watch list analyses ..." and the site published it; waited for in the triggerer.
- publish_site: the Pages workflow, so the site shows the night's screener and coverage.

A failure (a job run that failed after its retries, a failed check, a wait that ran out)
marks the run failed and emails the alert address.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.sdk import dag, task
from airflow.timetables.trigger import CronTriggerTimetable
from stock_orch import runlog
from stock_orch.azure_jobs import ContainerAppJobOperator
from stock_orch.github import WaitForEveningOperator

KEY = "{{ run_id }}"  # Airflow's run id: the run log's run_key

DEFAULTS = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "on_failure_callback": runlog.on_failure,
}


@dag(
    dag_id="stock_nightly",
    description="Weekday night: ingest, nightly analyses, checks, ready marker, the session",
    schedule=CronTriggerTimetable("30 22 * * 1-5", timezone="UTC"),
    start_date=datetime(2026, 11, 19),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=10),
    default_args=DEFAULTS,
    tags=["stock", "issue-30"],
    doc_md=__doc__,
)
def stock_nightly():
    @task
    def start(key: str) -> str:
        return runlog.begin(key, "stock_nightly")

    @task(retries=0)
    def check_ingest(key: str) -> str:
        return runlog.check(key, "check_ingest", "ingest")

    @task(retries=0)
    def check_prices(key: str) -> str:
        return runlog.check(key, "check_prices", "prices")

    @task(retries=0)
    def check_nightly(key: str) -> str:
        return runlog.check(key, "check_nightly", "nightly")

    @task
    def mark_ready(key: str) -> str:
        return runlog.set_status(key, "mark_ready", "ready", "Data ready for the session")

    @task
    def publish_site(key: str) -> str:
        return runlog.publish_site(key, "publish_site")

    @task
    def finish(key: str) -> str:
        return runlog.set_status(key, "finish", "ok", "Run finished ok")

    ingest = ContainerAppJobOperator(
        task_id="ingest",
        job="stock-ingest",
        args=["ingest", "--no-nightly", "--no-site"],
        execution_timeout=timedelta(hours=3, minutes=30),
        retries=1,
    )
    nightly = ContainerAppJobOperator(
        task_id="nightly",
        job="stock-ingest",
        args=["nightly"],
        execution_timeout=timedelta(hours=1),
        retries=1,
    )
    evening = WaitForEveningOperator(task_id="wait_for_evening", run_key=KEY, retries=0)
    done = finish(KEY)
    checked = check_ingest(KEY)

    start(KEY) >> ingest >> checked
    checked >> check_prices(KEY) >> mark_ready(KEY) >> evening >> done
    checked >> nightly >> check_nightly(KEY) >> publish_site(KEY) >> done


stock_nightly()
