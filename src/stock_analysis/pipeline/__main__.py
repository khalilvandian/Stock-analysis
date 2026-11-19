"""python -m stock_analysis.pipeline: the pipeline's checks and run log by hand.

Airflow calls the same functions directly (orchestration/plugins/stock_orch/); this command
is for trying a step outside Airflow, and for the morning audit and the evening session's
marker, which read the log through the web API.

    start RUN_KEY [--pipeline NAME]    a row in ops_pipeline_run
    check-ingest RUN_KEY               the ingest run since the run's start
    check-nightly RUN_KEY              what the nightly analyses stored since then
    check-prices RUN_KEY               the members have the last close
    check-quotes RUN_KEY               the quotes run since then didn't fail
    ready RUN_KEY / finish RUN_KEY     status ready / ok
    wait-evening RUN_KEY               the Claude session's commit and the site (exit 3: not yet)
    publish-site                       start the Pages workflow
    fail RUN_KEY STEP MESSAGE          status failed, and the alert email
    marker                             exit 0 when the last trading day's data is ready
    audit                              exit 4 when the last trading day has no ok run

Exit codes: 0 done, 3 not yet, 4 failed.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from . import (
    DONE,
    FAILED,
    ROOT,
    Result,
    alert,
    audit,
    check_evening,
    check_ingest,
    check_nightly,
    check_prices,
    check_quotes,
    connect,
    load_config,
    log_step,
    marker,
    publish_site,
    run_row,
    set_status,
    start,
    utcnow,
)

COMMANDS = [
    "start", "check-ingest", "check-nightly", "check-prices", "check-quotes", "ready",
    "finish", "wait-evening", "publish-site", "fail", "marker", "audit",
]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(prog="python -m stock_analysis.pipeline", description=__doc__)
    ap.add_argument("command", choices=COMMANDS)
    ap.add_argument("run_key", nargs="?", help="the Airflow run id")
    ap.add_argument("step", nargs="?", help="fail: the step that failed")
    ap.add_argument("message", nargs="?", help="fail: what happened")
    ap.add_argument("--pipeline", default=None, help="start: the DAG (default from the config)")
    ap.add_argument("--target", help="a target in config/database.toml")
    args = ap.parse_args(argv)
    cfg = load_config()
    now = utcnow()

    if args.command in ("marker", "audit"):  # read-only; through the web API in the cloud
        from ..data import Data

        found = Data.open().sql(
            "SELECT run_key, run_date, status FROM ops_pipeline_run "
            f"WHERE pipeline = '{cfg['pipeline']}' ORDER BY run_id DESC LIMIT 20"
        )
        check = marker if args.command == "marker" else audit
        result = check(found.to_dict("records"), now, cfg)
        print(result.message)
        return result.code
    if args.command == "publish-site":
        with httpx.Client() as client:
            result = publish_site(cfg, client)
        print(result.message)
        return result.code

    if not args.run_key:
        ap.error(f"{args.command} needs RUN_KEY")
    key = args.run_key
    with connect(args.target) as conn:
        if args.command == "start":
            run_id = start(conn, key, args.pipeline or cfg["pipeline"], now, cfg)
            result = Result(DONE, f"Pipeline run {run_id} started")
        elif args.command == "fail":
            step, message = args.step or "?", args.message or "failed"
            set_status(conn, key, "failed", now)
            log_step(conn, key, step, Result(FAILED, message), now)
            with httpx.Client() as client:
                sent = alert(f"Stock pipeline FAILED: {step}", f"Run {key}\n\n{message}", cfg,
                             client)  # fmt: skip
            print(message + ("" if sent else " (no alert email: Brevo settings missing)"))
            return DONE
        else:
            started = run_row(conn, key)["started_at"]
            step, result = {
                "check-ingest": lambda: ("check_ingest", check_ingest(conn, started, cfg)),
                "check-nightly": lambda: ("check_nightly", check_nightly(conn, started)),
                "check-prices": lambda: ("check_prices", check_prices(conn, now, cfg)),
                "check-quotes": lambda: ("check_quotes", check_quotes(conn, started)),
                "ready": lambda: ("mark_ready", Result(DONE, "Data ready")),
                "finish": lambda: ("finish", Result(DONE, "Pipeline run finished ok")),
                "wait-evening": lambda: ("wait_for_evening", evening(started, now, cfg)),
            }[args.command]()
            if args.command in ("ready", "finish"):
                set_status(conn, key, "ready" if args.command == "ready" else "ok", now)
            log_step(conn, key, step, result, now)
        if args.command == "start":
            log_step(conn, key, "start", result, now)
    print(result.message)
    return result.code


def evening(started, now, cfg) -> Result:
    with httpx.Client() as client:
        return check_evening(started, now, cfg, client)


if __name__ == "__main__":
    sys.exit(main())
