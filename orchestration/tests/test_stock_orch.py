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


def first_event(trigger) -> dict:
    async def first():
        async for event in trigger.run():
            return event.payload

    return asyncio.run(first())


@respx.mock
def test_unanswered_status_calls_do_not_fail_the_wait() -> None:
    ok = httpx.Response(200, json={"properties": {"status": "Succeeded"}})
    answers = [httpx.ReadTimeout("t")] * 30 + [httpx.Response(503), httpx.Response(404), ok]
    respx.get(f"{JOB}/executions/n").mock(side_effect=answers)
    trigger = azure_jobs.ContainerAppJobTrigger("stock-ingest", "n", 0)
    assert first_event(trigger)["status"] == "Succeeded"


@respx.mock
def test_a_lasting_refusal_fails_the_wait() -> None:
    route = respx.get(f"{JOB}/executions/n").mock(return_value=httpx.Response(403))
    with pytest.raises(httpx.HTTPStatusError):
        first_event(azure_jobs.ContainerAppJobTrigger("stock-ingest", "n", 0))
    assert route.call_count == azure_jobs.REFUSALS


def runs(*found: tuple[str, str, list[str]]) -> httpx.Response:
    value = [
        {"name": n, "properties": {"status": s, "template": {"containers": [{"args": a}]}}}
        for n, s, a in found
    ]
    return httpx.Response(200, json={"value": value})


def started(listed: list, start: list, reuse: bool = False):
    respx.get(JOB).mock(return_value=httpx.Response(200, json=job_body()))
    respx.get(f"{JOB}/executions").mock(side_effect=listed)
    post = respx.post(f"{JOB}/start").mock(side_effect=start)
    with httpx.Client() as c:
        name = azure_jobs.start_or_find("stock-ingest", ["build"], c, reuse, lambda s: None)
    return name, post.call_count


OLD = ("old", "Succeeded", ["build"])
NEW = httpx.Response(202, json={"name": "new"})


@respx.mock
def test_a_start_without_an_answer_is_tried_again() -> None:
    lists = [httpx.ReadTimeout("t"), runs(OLD), runs(OLD)]
    assert started(lists, [httpx.ReadTimeout("t"), NEW]) == ("new", 2)


@respx.mock
def test_a_run_started_by_a_lost_answer_is_not_started_twice() -> None:
    other = ("check1", "Running", ["check"])  # a parallel step's run is not ours
    lists = [runs(OLD), runs(OLD, other, ("lost", "Running", ["build"]))]
    assert started(lists, [httpx.ReadTimeout("t")]) == ("lost", 1)


@respx.mock
def test_a_task_retry_waits_for_the_run_still_going() -> None:
    going = runs(OLD, ("going", "Running", ["build"]))
    assert started([going], [NEW], reuse=True) == ("going", 0)


@respx.mock
def test_a_task_retry_after_a_finished_run_starts_a_new_one() -> None:
    assert started([runs(OLD)], [NEW], reuse=True) == ("new", 1)


@respx.mock
def test_a_start_that_is_never_answered_gives_up() -> None:
    with pytest.raises(azure_jobs.AzureUnavailable):
        started([httpx.ReadTimeout("t")] * 20, [NEW])


@respx.mock
def test_a_refused_start_fails_at_once() -> None:
    with pytest.raises(httpx.HTTPStatusError):
        started([httpx.Response(403)], [NEW])


@respx.mock
def test_execute_looks_for_a_running_job_only_on_a_retry(monkeypatch) -> None:
    from types import SimpleNamespace

    from airflow.sdk.exceptions import TaskDeferred

    seen = []
    monkeypatch.setattr(
        azure_jobs, "start_or_find", lambda j, a, c, reuse: seen.append(reuse) or "n"
    )
    op = azure_jobs.ContainerAppJobOperator(task_id="build", job="stock-ingest", args=["build"])
    for attempt in (1, 2):
        with pytest.raises(TaskDeferred):
            op.execute({"ti": SimpleNamespace(try_number=attempt)})
    assert seen == [False, True]


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


def test_unanswered_github_calls_do_not_fail_the_evening_wait(monkeypatch) -> None:
    few = [httpx.ReadTimeout("t")] * (github.FAILED_CALLS - 1)
    answers = iter([*few, p.Result(p.NOT_YET, "w"), *few, p.Result(p.DONE, "published")])

    def check(*args, **kwargs):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(p, "check_evening", check)
    assert first_event(github.EveningTrigger("2026-11-18T22:30:00", 0))["code"] == p.DONE


def test_a_lasting_github_failure_fails_the_evening_wait(monkeypatch) -> None:
    def check(*args, **kwargs):
        raise httpx.ReadTimeout("t")

    monkeypatch.setattr(p, "check_evening", check)
    event = first_event(github.EveningTrigger("2026-11-18T22:30:00", 0))
    assert event["code"] == p.FAILED and "did not answer 12 times" in event["message"]


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


@respx.mock
def test_the_ui_opens_its_own_database_firewall_rule(monkeypatch) -> None:
    from stock_orch import firewall

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "h")
    respx.get("http://identity.local/token").mock(
        return_value=httpx.Response(200, json={"access_token": "mi-token"})
    )
    respx.get(firewall.IP_SERVICE).mock(return_value=httpx.Response(200, text="20.1.2.3"))
    rule = respx.put(url__regex=r".*/firewallRules/airflow-ui\?api-version=.*").mock(
        return_value=httpx.Response(200, json={})
    )
    with httpx.Client() as c:
        assert firewall.open_rule("airflow-ui", c, sleep=lambda s: None) == "20.1.2.3"
    sent = json.loads(rule.calls.last.request.content)["properties"]
    assert sent == {"startIpAddress": "20.1.2.3", "endIpAddress": "20.1.2.3"}
    assert rule.calls.last.request.headers["authorization"] == "Bearer mi-token"


def test_no_rule_outside_azure(monkeypatch) -> None:
    from stock_orch import firewall

    monkeypatch.delenv("IDENTITY_ENDPOINT", raising=False)
    with httpx.Client() as c:
        assert firewall.open_rule("airflow-ui", c) is None
