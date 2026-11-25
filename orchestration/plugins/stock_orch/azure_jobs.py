"""Start an Azure Container Apps Job run from Airflow and wait for it (issue #30).

The jobs (stock-ingest, stock-quotes) have no schedule of their own: Airflow starts each run
through Azure Resource Manager's REST API, with the arguments of the task (`db ingest`,
`db nightly`, `db quotes`), then hands the wait to the triggerer, which polls the run's
status every `poll_seconds` without holding a worker slot.

    POST   .../jobs/{job}/start                  a run, with this task's container arguments
    GET    .../jobs/{job}/executions/{name}      its status: Running, Succeeded, Failed, ...
    GET    .../jobs/{job}/executions             the job's runs, to find one already started

An unanswered call says nothing about the run, so no single call fails a task:
- a status call that fails is asked again at the next poll, until the task's own time limit;
  a refusal (no permission, say) fails it only after REFUSALS polls in a row;
- a start that fails is tried again for about ten minutes. Azure may have started the run
  without its answer arriving, so each new try first looks for it and waits for that one;
- a retry of the task waits for a run with the same arguments that is still going, instead
  of starting a second one.

Credentials: AZURE_ARM_TOKEN if set (local development: `az account get-access-token`),
else azure.identity's DefaultAzureCredential, which on the VM is its managed identity
(allowed to start only these jobs). AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP say where.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import httpx
from airflow.sdk import BaseOperator
from airflow.triggers.base import BaseTrigger, TriggerEvent

ARM = "https://management.azure.com"
API_VERSION = "2024-03-01"
DONE_OK = {"Succeeded"}
DONE_BAD = {"Failed", "Stopped", "Degraded"}
START_WAITS = (15, 30, 60, 120, 180, 180)  # seconds before each new try of a start
REFUSALS = 10  # refused status calls in a row before the wait gives up

log = logging.getLogger(__name__)


class AzureUnavailable(Exception):
    """No usable answer from Azure's control service: worth asking again."""


def ask(client: httpx.Client, method: str, url: str, token: str, **kwargs) -> dict:
    """One call. AzureUnavailable for what passes by itself (no answer, too many requests, a
    server error, an unreadable answer); httpx.HTTPStatusError for a refusal."""
    try:
        r = client.request(
            method, url, headers={"Authorization": f"Bearer {token}"}, timeout=60, **kwargs
        )
    except httpx.TransportError as exc:
        raise AzureUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if r.status_code in (408, 429) or r.status_code >= 500:
        raise AzureUnavailable(f"HTTP {r.status_code}: {r.text[:200]}")
    r.raise_for_status()
    try:
        return r.json()
    except ValueError as exc:
        raise AzureUnavailable(f"Unreadable answer (HTTP {r.status_code})") from exc


def arm_token() -> str:
    if os.environ.get("AZURE_ARM_TOKEN"):
        return os.environ["AZURE_ARM_TOKEN"]
    from azure.core.exceptions import AzureError
    from azure.identity import DefaultAzureCredential

    try:
        return DefaultAzureCredential().get_token(f"{ARM}/.default").token
    except AzureError as exc:  # the identity service can be unreachable for a moment too
        raise AzureUnavailable(f"No Azure token: {exc}") from exc


def job_url(job: str, suffix: str = "") -> str:
    sub = os.environ["AZURE_SUBSCRIPTION_ID"]
    rg = os.environ.get("AZURE_RESOURCE_GROUP", "stock-rg")
    return (
        f"{ARM}/subscriptions/{sub}/resourceGroups/{rg}/providers/Microsoft.App/jobs/{job}"
        f"{suffix}?api-version={API_VERSION}"
    )


def start_run(job: str, args: list[str], client: httpx.Client, token: str) -> str:
    """Start one run of `job` with these container arguments; returns the run's name.
    The start request replaces the job's container settings for this run, so they are read
    from the job first and only the arguments change (the image, environment variables and
    secrets stay the job's)."""
    body = ask(client, "GET", job_url(job), token)
    container = dict(body["properties"]["template"]["containers"][0])
    template = {
        k: container[k] for k in ("name", "image", "command", "env", "resources") if k in container
    }
    template["args"] = args
    sent = ask(client, "POST", job_url(job, "/start"), token, json={"containers": [template]})
    return sent["name"]


def list_runs(job: str, args: list[str], client: httpx.Client, token: str) -> dict[str, str]:
    """The job's runs with exactly these arguments: name -> status."""
    found, url = {}, job_url(job, "/executions")
    while url:
        page = ask(client, "GET", url, token)
        for run in page.get("value", []):
            props = run.get("properties", {})
            containers = (props.get("template") or {}).get("containers") or [{}]
            if (containers[0].get("args") or []) == args:
                found[run["name"]] = props.get("status", "Unknown")
        url = page.get("nextLink")
    return found


def start_or_find(
    job: str, args: list[str], client: httpx.Client, reuse: bool = False, sleep=time.sleep
) -> str:
    """Start a run, trying again while Azure doesn't answer; returns the run's name. A run
    that appeared since the first look is ours, started by a call whose answer was lost.
    `reuse` (a retry of the task): a run still going is taken too."""
    before: set[str] | None = None
    for wait in (*START_WAITS, None):
        try:
            token = arm_token()
            runs = list_runs(job, args, client, token)
            if before is None:
                going = [n for n, s in runs.items() if s not in DONE_OK | DONE_BAD]
                if reuse and going:
                    log.info("%s run %s is still going: waiting for it", job, going[0])
                    return going[0]
                before = set(runs)
            new = sorted(set(runs) - before)
            if new:
                log.info("%s run %s had started after all", job, new[0])
                return new[0]
            return start_run(job, args, client, token)
        except AzureUnavailable as exc:
            if wait is None:
                raise
            log.warning("Azure did not answer (%s): trying again in %s s", exc, wait)
            sleep(wait)
    raise AssertionError("unreachable")


def run_status(job: str, name: str, client: httpx.Client, token: str) -> dict:
    props = ask(client, "GET", job_url(job, f"/executions/{name}"), token).get("properties", {})
    return {
        "status": props.get("status", "Unknown"),
        "start": props.get("startTime"),
        "end": props.get("endTime"),
    }


class ContainerAppJobTrigger(BaseTrigger):
    """Polls one job run until it ends; fires once with its final status. A call without an
    answer is repeated at the next poll; the task's time limit ends the wait."""

    def __init__(self, job: str, name: str, poll_seconds: float = 30.0):
        super().__init__()
        self.job, self.name, self.poll_seconds = job, name, poll_seconds

    def serialize(self) -> tuple[str, dict[str, Any]]:
        return (
            "stock_orch.azure_jobs.ContainerAppJobTrigger",
            {"job": self.job, "name": self.name, "poll_seconds": self.poll_seconds},
        )

    async def run(self):
        refused = 0
        while True:
            try:
                state = await asyncio.to_thread(self._poll)
                refused = 0
            except AzureUnavailable as exc:
                log.warning("Status of %s unknown (%s): asking again", self.name, exc)
                state = {"status": "Unknown"}
            except httpx.HTTPStatusError as exc:  # also a new run Azure doesn't list yet
                refused += 1
                if refused >= REFUSALS:
                    raise
                log.warning("Status of %s refused (%s): asking again", self.name, exc)
                state = {"status": "Unknown"}
            if state["status"] in DONE_OK | DONE_BAD:
                yield TriggerEvent({"job": self.job, "name": self.name, **state})
                return
            await asyncio.sleep(self.poll_seconds)

    def _poll(self) -> dict:
        with httpx.Client() as client:
            return run_status(self.job, self.name, client, arm_token())


class ContainerAppJobOperator(BaseOperator):
    """Run an Azure Container Apps Job once with `args`, deferred while it runs. A failed
    run fails the task (and is retried as a new run, by the task's retries)."""

    template_fields = ("args", "run_key")
    ui_color = "#c9e7ec"

    def __init__(
        self,
        *,
        job: str,
        args: list[str],
        run_key: str | None = None,
        poll_seconds: float = 30.0,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.job, self.args, self.poll_seconds = job, args, poll_seconds
        self.run_key = run_key  # set: the run is recorded in ops_pipeline_step

    def execute(self, context):
        with httpx.Client() as client:
            retry = context["ti"].try_number > 1
            name = start_or_find(self.job, list(self.args), client, reuse=retry)
        self.log.info("Waiting for %s run %s with %s", self.job, name, self.args)
        self.defer(
            trigger=ContainerAppJobTrigger(self.job, name, self.poll_seconds),
            method_name="execute_complete",
            timeout=self.execution_timeout,
        )

    def execute_complete(self, context, event: dict):
        self.log.info("%s run %s ended %s (%s to %s)", event["job"], event["name"],
                      event["status"], event["start"], event["end"])  # fmt: skip
        if event["status"] not in DONE_OK:
            raise RuntimeError(
                f"{event['job']} run {event['name']} ended {event['status']}: see its logs in "
                "Azure (Container Apps, the job's execution history)"
            )
        if self.run_key:
            from stock_analysis import pipeline as p
            from stock_orch import runlog

            message = f"{event['job']} run {event['name']} succeeded ({' '.join(self.args)})"
            runlog.record(self.run_key, self.task_id, p.Result(p.DONE, message, event))
        return event["name"]
