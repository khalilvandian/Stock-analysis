"""stock_nightly: the weekday night after the US close (issue #30, docs/ORCHESTRATION.md).

Airflow runs every piece as a task; the Azure jobs have no schedule of their own. Each heavy
step is its own run of the job `stock-ingest`, so a failure reruns only that step.

    start → fetch → check_fetch → build → check_build, then in parallel:
        quality                                         ─┐
        coverage ─────────────────────┐                  ├→ finish
        nightly → check_nightly ──────┴→ publish_site    ─┤
        check_prices → mark_ready → wait_for_evening     ─┘

- fetch: `db ingest --no-build --no-site`: the sources into the raw layer (ops_run).
- build: `db build`: the core layer from what changed (core_build).
- quality: `db check`: the database's own checks; a FAIL fails the task.
- coverage: `db coverage`: the day's coverage snapshot, shown on the site's Data page.
- nightly: `db nightly`: the screener, the watch list's numbers and the market numbers, which
  the Claude session reads.
- check_*: SQL on what the step stored (stock_analysis.pipeline), recorded in
  ops_pipeline_step; a failed check fails at once (no retry).
- mark_ready: the marker the Claude session can read (python -m stock_analysis.pipeline marker).
- wait_for_evening: the Claude session (its own schedule, 00:00 Italy time) committed
  "Watch list analyses ..." and the site published it; waited for in the triggerer.
- publish_site: the Pages workflow, once the coverage and the nightly numbers are stored.

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
JOB = "stock-ingest"  # one image, one job: each step is a run with its own command

DEFAULTS = {
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "on_failure_callback": runlog.on_failure,
}


def job_step(task_id: str, args: list[str], hours: float, retries: int = 1):
    return ContainerAppJobOperator(
        task_id=task_id,
        job=JOB,
        args=args,
        run_key=KEY,
        execution_timeout=timedelta(hours=hours),
        retries=retries,
    )


@dag(
    dag_id="stock_nightly",
    description="Weekday night: fetch, build, quality, coverage, nightly analyses, the session",
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
    def check_fetch(key: str) -> str:
        return runlog.check(key, "check_fetch", "ingest")

    @task(retries=0)
    def check_build(key: str) -> str:
        return runlog.check(key, "check_build", "build")

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
        return runlog.set_status(key, "finish", "ok", "Run finished ok", closing=True)

    fetch = job_step("fetch", ["ingest", "--no-build", "--no-site"], hours=3)
    build = job_step("build", ["build"], hours=1.5)
    quality = job_step("quality", ["check"], hours=0.5)
    coverage = job_step("coverage", ["coverage"], hours=0.5)
    nightly = job_step("nightly", ["nightly"], hours=1)
    evening = WaitForEveningOperator(task_id="wait_for_evening", run_key=KEY, retries=0)

    built = check_build(KEY)
    site = publish_site(KEY)
    done = finish(KEY)

    start(KEY) >> fetch >> check_fetch(KEY) >> build >> built
    built >> [quality, coverage, nightly]
    nightly >> check_nightly(KEY) >> site
    coverage >> site
    built >> check_prices(KEY) >> mark_ready(KEY) >> evening
    [quality, site, evening] >> done


stock_nightly()
