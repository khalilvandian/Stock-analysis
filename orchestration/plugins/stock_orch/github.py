"""Wait in the triggerer for the Claude session's commit on main and its published site
(issue #30). The check itself is stock_analysis.pipeline.check_evening; the trigger calls it
every `poll_seconds` until it passes or fails (it fails by itself after `wait_hours` in
config/pipeline.toml)."""

from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import httpx
from airflow.sdk import BaseOperator
from airflow.sdk.exceptions import AirflowFailException
from airflow.triggers.base import BaseTrigger, TriggerEvent

from stock_analysis import pipeline as p


class EveningTrigger(BaseTrigger):
    def __init__(self, started: str, poll_seconds: float = 600.0):
        super().__init__()
        self.started, self.poll_seconds = started, poll_seconds

    def serialize(self) -> tuple[str, dict[str, Any]]:
        return (
            "stock_orch.github.EveningTrigger",
            {"started": self.started, "poll_seconds": self.poll_seconds},
        )

    async def run(self):
        while True:
            result = await asyncio.to_thread(self._check)
            if result.code != p.NOT_YET:
                yield TriggerEvent(
                    {"code": result.code, "message": result.message, "detail": result.detail}
                )
                return
            await asyncio.sleep(self.poll_seconds)

    def _check(self) -> p.Result:
        with httpx.Client() as client:
            return p.check_evening(
                dt.datetime.fromisoformat(self.started), p.utcnow(), p.load_config(), client
            )


class WaitForEveningOperator(BaseOperator):
    """Deferred until the Claude session's commit is published, or the wait ran out."""

    template_fields = ("run_key",)

    def __init__(self, *, run_key: str, poll_seconds: float = 600.0, **kwargs):
        super().__init__(**kwargs)
        self.run_key, self.poll_seconds = run_key, poll_seconds

    def execute(self, context):
        from stock_orch import runlog

        started = runlog.started_at(self.run_key)
        self.defer(
            trigger=EveningTrigger(p.stamp(started), self.poll_seconds),
            method_name="execute_complete",
        )

    def execute_complete(self, context, event: dict):
        from stock_orch import runlog

        result = p.Result(event["code"], event["message"], event.get("detail") or {})
        runlog.record(self.run_key, self.task_id, result)
        if result.code != p.DONE:
            raise AirflowFailException(result.message)
        return result.message
