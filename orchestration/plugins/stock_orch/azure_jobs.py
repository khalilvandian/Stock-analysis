"""Start an Azure Container Apps Job run from Airflow and wait for it (issue #30).

The jobs (stock-ingest, stock-quotes) have no schedule of their own: Airflow starts each run
through Azure Resource Manager's REST API, with the arguments of the task (`db ingest`,
`db nightly`, `db quotes`), then hands the wait to the triggerer, which polls the run's
status every `poll_seconds` without holding a worker slot.

    POST   .../jobs/{job}/start                  a run, with this task's container arguments
    GET    .../jobs/{job}/executions/{name}      its status: Running, Succeeded, Failed, ...

Credentials: AZURE_ARM_TOKEN if set (local development: `az account get-access-token`),
else azure.identity's DefaultAzureCredential, which on the VM is its managed identity
(allowed to start only these jobs). AZURE_SUBSCRIPTION_ID and AZURE_RESOURCE_GROUP say where.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
from airflow.sdk import BaseOperator
from airflow.triggers.base import BaseTrigger, TriggerEvent

ARM = "https://management.azure.com"
API_VERSION = "2024-03-01"
DONE_OK = {"Succeeded"}
DONE_BAD = {"Failed", "Stopped", "Degraded"}


def arm_token() -> str:
    if os.environ.get("AZURE_ARM_TOKEN"):
        return os.environ["AZURE_ARM_TOKEN"]
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential().get_token(f"{ARM}/.default").token


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
    headers = {"Authorization": f"Bearer {token}"}
    r = client.get(job_url(job), headers=headers, timeout=30)
    r.raise_for_status()
    container = dict(r.json()["properties"]["template"]["containers"][0])
    template = {
        k: container[k] for k in ("name", "image", "command", "env", "resources") if k in container
    }
    template["args"] = args
    r = client.post(
        job_url(job, "/start"), headers=headers, json={"containers": [template]}, timeout=60
    )
    r.raise_for_status()
    return r.json()["name"]


def run_status(job: str, name: str, client: httpx.Client, token: str) -> dict:
    r = client.get(
        job_url(job, f"/executions/{name}"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    props = r.json().get("properties", {})
    return {
        "status": props.get("status", "Unknown"),
        "start": props.get("startTime"),
        "end": props.get("endTime"),
    }


class ContainerAppJobTrigger(BaseTrigger):
    """Polls one job run until it ends; fires once with its final status."""

    def __init__(self, job: str, name: str, poll_seconds: float = 30.0):
        super().__init__()
        self.job, self.name, self.poll_seconds = job, name, poll_seconds

    def serialize(self) -> tuple[str, dict[str, Any]]:
        return (
            "stock_orch.azure_jobs.ContainerAppJobTrigger",
            {"job": self.job, "name": self.name, "poll_seconds": self.poll_seconds},
        )

    async def run(self):
        while True:
            state = await asyncio.to_thread(self._poll)
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
            name = start_run(self.job, list(self.args), client, arm_token())
        self.log.info("Started %s run %s with %s", self.job, name, self.args)
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
