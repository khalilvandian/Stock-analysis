"""stock_quotes: the latest price of every company, every hour on weekdays (issue #30).

    start ─► quotes ─► check_quotes ─► finish

- quotes: a run of the Container Apps Job `stock-quotes` (`db quotes`), which has no
  schedule of its own.
- check_quotes: the run stored its quotes, or found the same prices as the last run (the
  market is closed), but didn't fail.

Each run is a row in ops_pipeline_run (pipeline stock_quotes); a failure emails the alert.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.sdk import dag, task
from airflow.timetables.trigger import CronTriggerTimetable
from stock_orch import runlog
from stock_orch.azure_jobs import ContainerAppJobOperator

KEY = "{{ run_id }}"


@dag(
    dag_id="stock_quotes",
    description="Hourly quotes on weekdays",
    schedule=CronTriggerTimetable("5 * * * 1-5", timezone="UTC"),
    start_date=datetime(2026, 11, 19),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=50),
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=2),
        "on_failure_callback": runlog.on_failure,
    },
    tags=["stock", "issue-30"],
    doc_md=__doc__,
)
def stock_quotes():
    @task
    def start(key: str) -> str:
        return runlog.begin(key, "stock_quotes")

    @task(retries=0)
    def check_quotes(key: str) -> str:
        return runlog.check(key, "check_quotes", "quotes")

    @task
    def finish(key: str) -> str:
        return runlog.set_status(key, "finish", "ok", "Quotes run finished ok")

    quotes = ContainerAppJobOperator(
        task_id="quotes",
        job="stock-quotes",
        args=["quotes"],
        run_key=KEY,
        execution_timeout=timedelta(minutes=20),
        poll_seconds=15,
    )
    start(KEY) >> quotes >> check_quotes(KEY) >> finish(KEY)


stock_quotes()
