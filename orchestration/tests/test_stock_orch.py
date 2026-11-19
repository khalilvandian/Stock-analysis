"""The Airflow side of the pipeline (issue #30): the job operator and its trigger, the
evening trigger, and the DAGs' structure. Runs in the Airflow image, with Azure and GitHub
mocked by respx (docs/ORCHESTRATION.md, "Checks"):

    docker compose -f orchestration/compose.yaml run --rm --no-deps --entrypoint bash \\
        airflow-scheduler -c "pip install -q pytest respx && \\
        cd /opt/stock/orchestration/plugins && \\
        python -m pytest -q -p no:cacheprovider /opt/stock/orchestration/tests"
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
import respx
from stock_orch import azure_jobs, github

from stock_analysis import pipeline as p

DAGS = Path(__file__).resolve().parent.parent / "dags"
SUB = "00000000-0000-0000-0000-000000000000"
JOB = f"https://management.azure.com/subscriptions/{SUB}/resourceGroups/stock-rg/providers/Microsoft.App/jobs/stock-ingest"


@pytest.fixture(autouse=True)
def azure_env(monkeypatch):
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUB)
    monkeypatch.setenv("AZURE_RESOURCE_GROUP", "stock-rg")
    monkeypatch.setenv("AZURE_ARM_TOKEN", "token")


def job_body() -> dict:
    container = {
        "name": "stock-ingest",
        "image": "ghcr.io/x/stock-ingest:latest",
        "args": ["ingest"],
        "env": [{"name": "STOCK_DB_TARGET", "value": "server-writer"},
                {"name": "PGPASSWORD", "secretRef": "db-password"}],
        "resources": {"cpu": 1.5, "memory": "3Gi"},
    }  # fmt: skip
    return {"properties": {"template": {"containers": [container]}}}


@respx.mock
def test_start_run_keeps_the_job_settings_and_changes_only_the_arguments() -> None:
    respx.get(JOB).mock(return_value=httpx.Response(200, json=job_body()))
    start = respx.post(f"{JOB}/start").mock(
        return_value=httpx.Response(202, json={"name": "stock-ingest-abc", "id": "x"})
    )
    with httpx.Client() as c:
        assert azure_jobs.start_run("stock-ingest", ["build"], c, "token") == "stock-ingest-abc"
    sent = json.loads(start.calls.last.request.content)["containers"][0]
    assert sent["args"] == ["build"]
    assert sent["env"] == job_body()["properties"]["template"]["containers"][0]["env"]
    assert sent["image"].endswith("stock-ingest:latest")
    assert start.calls.last.request.headers["authorization"] == "Bearer token"


@respx.mock
def test_the_trigger_waits_until_the_run_ends() -> None:
    states = iter(["Running", "Running", "Succeeded"])
    respx.get(f"{JOB}/executions/stock-ingest-abc").mock(
        side_effect=lambda request: httpx.Response(
            200, json={"properties": {"status": next(states), "startTime": "s", "endTime": "e"}}
        )
    )
    trigger = azure_jobs.ContainerAppJobTrigger("stock-ingest", "stock-ingest-abc", 0)

    async def first():
        async for event in trigger.run():
            return event.payload

    assert asyncio.run(first())["status"] == "Succeeded"
    assert trigger.serialize()[0] == "stock_orch.azure_jobs.ContainerAppJobTrigger"


def test_a_failed_run_fails_the_task() -> None:
    op = azure_jobs.ContainerAppJobOperator(task_id="build", job="stock-ingest", args=["build"])
    event = {"job": "stock-ingest", "name": "n", "status": "Failed", "start": "s", "end": "e"}
    with pytest.raises(RuntimeError, match="ended Failed"):
        op.execute_complete({}, event)
    assert op.execute_complete({}, {**event, "status": "Succeeded"}) == "n"


def test_the_evening_trigger_polls_until_a_result(monkeypatch) -> None:
    results = iter([p.Result(p.NOT_YET, "waiting"), p.Result(p.DONE, "published", {"c": 1})])
    monkeypatch.setattr(p, "check_evening", lambda *a, **k: next(results))
    trigger = github.EveningTrigger("2026-11-18T22:30:00", 0)

    async def first():
        async for event in trigger.run():
            return event.payload

    assert asyncio.run(first()) == {"code": p.DONE, "message": "published", "detail": {"c": 1}}


def test_the_dags_load_with_the_intended_order() -> None:
    from airflow.dag_processing.dagbag import DagBag

    bag = DagBag(dag_folder=str(DAGS))
    assert not bag.import_errors
    night = bag.dags["stock_nightly"]
    down = {t.task_id: set(t.downstream_task_ids) for t in night.tasks}
    assert down["start"] == {"fetch"}
    assert down["check_build"] == {"quality", "coverage", "nightly", "check_prices"}
    assert down["coverage"] == down["check_nightly"] == {"publish_site"}
    assert {k for k, v in down.items() if "finish" in v} == {
        "quality", "publish_site", "wait_for_evening"
    }  # fmt: skip
    args = {t.task_id: getattr(t, "args", None) for t in night.tasks}
    assert args["fetch"] == ["ingest", "--no-build", "--no-site"]
    assert args["nightly"] == ["nightly"]
    assert night.timetable.summary == "30 22 * * 1-5"
    quotes = bag.dags["stock_quotes"]
    assert [t.task_id for t in quotes.topological_sort()] == [
        "start", "quotes", "check_quotes", "finish"
    ]  # fmt: skip
