"""python -m stock_analysis.pipeline: the steps of the nightly pipeline (see __init__.py)."""

from __future__ import annotations

import argparse
import os
import sys

import httpx

from . import (
    DONE,
    FAILED,
    Result,
    alert,
    audit,
    check_evening,
    check_ingest,
    check_prices,
    load_config,
    log_step,
    marker,
    run_row,
    set_status,
    start,
    utcnow,
)


def database(read_only: bool = False):
    from ..db import Database

    # STOCK_PIPELINE_TARGET picks the database (server-writer in production); unset, the
    # usual order applies (DATABASE_URL, STOCK_DB_TARGET, `selected`).
    return Database.open(os.environ.get("STOCK_PIPELINE_TARGET") or None, read_only=read_only)


def report(db, key: str, step: str, result: Result) -> int:
    log_step(db, key, step, result, utcnow())
    print(result.message)
    return result.code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m stock_analysis.pipeline", description=__doc__)
    ap.add_argument(
        "command",
        choices=[
            "start", "wait-ingest", "check-prices", "ready", "wait-evening", "finish", "fail",
            "marker", "audit",
        ],
    )  # fmt: skip
    ap.add_argument("run_key", nargs="?", help="the Airflow dag_run_id")
    ap.add_argument("step", nargs="?", help="fail: the step that failed")
    ap.add_argument("message", nargs="?", help="fail: what happened")
    ap.add_argument("--log-url", help="fail: the Airflow log of the failed step")
    args = ap.parse_args(argv)
    cfg = load_config()
    now = utcnow()

    if args.command in ("marker", "audit"):  # read-only; through the web API in the cloud
        from ..data import Data

        rows = Data.open().sql(
            "SELECT run_key, run_date, status, started_at, finished_at FROM ops_pipeline_run "
            f"WHERE pipeline = '{cfg['pipeline']}' ORDER BY run_id DESC LIMIT 20"
        )
        check = marker if args.command == "marker" else audit
        result = check(rows.to_dict("records"), now, cfg)
        print(result.message)
        return result.code

    if not args.run_key:
        ap.error(f"{args.command} needs RUN_KEY")
    key = args.run_key
    db = database()
    try:
        if args.command == "start":
            run_id = start(db, key, now, cfg)
            return report(db, key, "start", Result(DONE, f"Pipeline run {run_id} started"))
        if args.command == "wait-ingest":
            started = run_row(db, key)["started_at"]
            return report(db, key, "wait_for_ingest", check_ingest(db, started, now, cfg))
        if args.command == "check-prices":
            return report(db, key, "check_prices", check_prices(db, now, cfg))
        if args.command == "ready":
            set_status(db, key, "ready", now)
            return report(db, key, "mark_ready", Result(DONE, "Data ready for the evening session"))
        if args.command == "wait-evening":
            ready_at = run_row(db, key)["ready_at"] or now
            with httpx.Client() as client:
                result = check_evening(ready_at, now, cfg, client)
            return report(db, key, "wait_for_evening", result)
        if args.command == "finish":
            set_status(db, key, "ok", now)
            return report(db, key, "finish", Result(DONE, "Pipeline run finished ok"))
        # fail: the DAG's failure callback
        step, message = args.step or "?", args.message or "failed"
        try:  # the run's row may not exist (start itself failed): the email still goes
            set_status(db, key, "failed", now)
            log_step(db, key, step, Result(FAILED, message), now)
        except Exception as exc:  # noqa: BLE001
            message += f" (could not write the run log: {exc})"
        body = f"Run {key}\nStep {step} failed:\n\n{message}\n"
        if args.log_url:
            body += f"\nLog: {args.log_url}\n"
        with httpx.Client() as client:
            sent = alert(f"Stock pipeline FAILED: {step}", body, cfg, client)
        print(message + ("" if sent else " (no alert email: Brevo settings missing)"))
        return DONE
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
