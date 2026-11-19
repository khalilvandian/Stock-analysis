"""The nightly pipeline's checks and run log (issue #30, docs/ORCHESTRATION.md).

The Airflow DAG `stock_nightly` (orchestration/dags/) calls these through the command line,
so the logic is plain Python, tested without Airflow, and usable by hand:

    python -m stock_analysis.pipeline start RUN_KEY          a row in ops_pipeline_run
    python -m stock_analysis.pipeline wait-ingest RUN_KEY    exit 3 until tonight's ingest ran
    python -m stock_analysis.pipeline check-prices RUN_KEY   the prices reached the last close
    python -m stock_analysis.pipeline check-nightly RUN_KEY  the nightly analyses ran clean
    python -m stock_analysis.pipeline check-quotes RUN_KEY   the hourly quotes job is storing
    python -m stock_analysis.pipeline ready RUN_KEY          the marker the evening session reads
    python -m stock_analysis.pipeline wait-evening RUN_KEY   exit 3 until the commit and the site
    python -m stock_analysis.pipeline finish RUN_KEY         status ok
    python -m stock_analysis.pipeline fail RUN_KEY STEP MSG  status failed, and an email
    python -m stock_analysis.pipeline marker                 exit 0 when the data is ready
    python -m stock_analysis.pipeline audit                  exit 4: last weekday has no ok run

Exit codes: 0 done, 3 not yet (an Airflow sensor pokes again), 4 failed (a check found a
real problem: no retry). Anything else is a crash (a network or database error), which
Airflow retries.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import tomllib
from dataclasses import dataclass, field
from email.utils import parseaddr
from pathlib import Path

import httpx

from ..db import ROOT, Database, run, scalar

CONFIG = ROOT / "config" / "pipeline.toml"
BREVO = "https://api.brevo.com/v3/smtp/email"
DONE, NOT_YET, FAILED = 0, 3, 4


def load_config(path: Path = CONFIG) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None, microsecond=0)


def stamp(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


@dataclass
class Result:
    """What a check found: `code` is DONE, FAILED or NOT_YET; `detail` goes in the log."""

    code: int
    message: str
    detail: dict = field(default_factory=dict)


# ---------------------------------------------------------------- trading days


def holidays(cfg: dict) -> set[dt.date]:
    return {dt.date.fromisoformat(d) for d in cfg["nyse"]["holidays"]}


def is_trading_day(day: dt.date, cfg: dict) -> bool:
    return day.weekday() < 5 and day not in holidays(cfg)


def last_close(now: dt.datetime, cfg: dict) -> dt.date:
    """The newest US trading day whose close has passed at `now` (UTC)."""
    hh, mm = (int(x) for x in cfg["prices"]["close_utc"].split(":"))
    day = now.date()
    if now.time() < dt.time(hh, mm):
        day -= dt.timedelta(days=1)
    while not is_trading_day(day, cfg):
        day -= dt.timedelta(days=1)
    return day


# ---------------------------------------------------------------- run log


def start(db: Database, run_key: str, now: dt.datetime, cfg: dict) -> int:
    """The run's row (made once; a retried start keeps it)."""
    with db.begin() as conn:
        run(
            conn,
            "INSERT INTO ops_pipeline_run (pipeline, run_key, run_date, started_at, status, host) "
            "VALUES (:p, :k, :d, :t, 'running', :h) ON CONFLICT (run_key) DO NOTHING",
            {
                "p": cfg["pipeline"],
                "k": run_key,
                "d": last_close(now, cfg),
                "t": stamp(now),
                "h": socket.gethostname(),
            },
        )
        sql = "SELECT run_id FROM ops_pipeline_run WHERE run_key = :k"
        return scalar(conn, sql, {"k": run_key})


def run_row(db: Database, run_key: str) -> dict:
    with db.connect() as conn:
        row = (
            run(conn, "SELECT * FROM ops_pipeline_run WHERE run_key = :k", {"k": run_key})
            .mappings()
            .first()
        )
    if row is None:
        raise SystemExit(f"No pipeline run {run_key!r}: run `start` first")
    return dict(row)


def log_step(db: Database, run_key: str, step: str, result: Result, now: dt.datetime) -> None:
    status = {DONE: "ok", FAILED: "failed", NOT_YET: "waiting"}[result.code]
    detail = json.dumps({"message": result.message, **result.detail}, default=str)
    with db.begin() as conn:
        run(
            conn,
            "INSERT INTO ops_pipeline_step (run_id, step, status, at, detail) "
            "SELECT run_id, :s, :st, :t, :d FROM ops_pipeline_run WHERE run_key = :k "
            "ON CONFLICT (run_id, step) DO UPDATE SET status = :st, at = :t, detail = :d",
            {"k": run_key, "s": step, "st": status, "t": stamp(now), "d": detail},
        )


def set_status(db: Database, run_key: str, status: str, now: dt.datetime) -> None:
    """A failed run stays failed: a side check (nightly analyses, quotes) can fail while the
    main chain goes on to `ready`."""
    column = {"ready": "ready_at", "ok": "finished_at", "failed": "finished_at"}[status]
    keep = "" if status == "failed" else " AND status <> 'failed'"
    with db.begin() as conn:
        run(
            conn,
            f"UPDATE ops_pipeline_run SET status = :s, {column} = :t WHERE run_key = :k{keep}",
            {"s": status, "t": stamp(now), "k": run_key},
        )


# ---------------------------------------------------------------- checks


def check_ingest(db: Database, started: dt.datetime, now: dt.datetime, cfg: dict) -> Result:
    """Tonight's ingest run (the Azure job): a row in ops_run that started near the DAG's
    start and has finished. `failed` fails; `partial` passes with a note, because the price
    check that follows is the real test."""
    since = started - dt.timedelta(minutes=cfg["ingest"]["started_within_minutes"])
    with db.connect() as conn:
        row = (
            run(
                conn,
                "SELECT run_id, started_at, finished_at, mode, status, requests, tasks_ok, "
                "tasks_failed, rows_stored, build_id FROM ops_run WHERE started_at >= :t "
                "ORDER BY run_id DESC LIMIT 1",
                {"t": stamp(since)},
            )
            .mappings()
            .first()
        )
    waited = (now - started).total_seconds() / 3600
    if row is None or row["status"] == "running":
        if waited >= cfg["ingest"]["wait_hours"]:
            what = "is still running" if row else f"has not started since {stamp(since)}"
            return Result(FAILED, f"The ingest run {what} after {waited:.1f} hours", {})
        return Result(NOT_YET, "Waiting for tonight's ingest run", {})
    detail = {k: (stamp(v) if isinstance(v, dt.datetime) else v) for k, v in row.items()}
    if row["status"] in ("failed", "skipped"):
        return Result(FAILED, f"The ingest run {row['run_id']} ended {row['status']}", detail)
    return Result(
        DONE,
        f"Ingest run {row['run_id']} ({row['mode']}) {row['status']}: "
        f"{row['requests']} requests, {row['rows_stored']} rows stored",
        detail,
    )


def check_nightly(db: Database, started: dt.datetime, cfg: dict) -> Result:
    """The nightly analyses the ingest job runs after its build (stock_analysis.nightly): the
    screener, each watch-list stock's numbers and the market numbers. Errors are in the
    run's summary; the evening session computes what is missing on the spot, so this alerts
    without holding back the ready marker."""
    since = started - dt.timedelta(minutes=cfg["ingest"]["started_within_minutes"])
    with db.connect() as conn:
        row = (
            run(
                conn,
                "SELECT run_id, summary FROM ops_run WHERE started_at >= :t "
                "AND status <> 'running' ORDER BY run_id DESC LIMIT 1",
                {"t": stamp(since)},
            )
            .mappings()
            .first()
        )
    if row is None:
        return Result(FAILED, "No finished ingest run to read the nightly analyses from", {})
    summary = json.loads(row["summary"] or "{}")
    nightly = summary.get("nightly")
    problems = []
    if "nightly_error" in summary:
        problems.append(f"nightly analyses: {summary['nightly_error']}")
    elif nightly is None:
        problems.append("the nightly analyses did not run (no build, or nightly = false)")
    else:
        for key in ("screener_error", "market_error"):
            if key in nightly:
                problems.append(f"{key.split('_')[0]}: {nightly[key]}")
        failed = (nightly.get("stocks") or {}).get("failed") or {}
        if failed:
            problems.append(f"stocks not computed: {', '.join(sorted(failed))}")
    detail = {"run_id": row["run_id"], "nightly": nightly, "problems": problems}
    if problems:
        return Result(FAILED, f"Ingest run {row['run_id']}: " + "; ".join(problems), detail)
    stocks = len((nightly.get("stocks") or {}).get("computed") or [])
    screened = (nightly.get("screener") or {}).get("screened")
    return Result(
        DONE,
        f"Nightly analyses of run {row['run_id']}: screener {screened} stocks, "
        f"{stocks} watch-list stocks, market numbers stored",
        detail,
    )


def check_quotes(db: Database, now: dt.datetime, cfg: dict) -> Result:
    """The hourly quotes job (stock-quotes): a successful fetch within `max_age_hours` on a
    trading day. A run with the same prices as the last stores nothing, so the newest stored
    fetch is the last time a price moved; around the US close it is at most an hour old."""
    q = cfg["quotes"]
    if not is_trading_day(now.date(), cfg):
        return Result(DONE, "Not a trading day: the quotes are not checked", {})
    with db.connect() as conn:
        rows = (
            run(
                conn,
                "SELECT status, fetched_at, rows_stored, error FROM raw_fetch "
                "WHERE source = :s AND request_key = 'all' ORDER BY fetch_id DESC LIMIT 5",
                {"s": q["source"]},
            )
            .mappings()
            .all()
        )
    ok = [r for r in rows if r["status"] == "ok"]
    newest = ok[0]["fetched_at"] if ok else None
    errors = [
        r["error"] for r in rows if r["status"] == "error" and (not ok or r["fetched_at"] > newest)
    ]
    detail = {"newest_ok": stamp(newest) if newest else None, "errors_since": errors[:3]}
    if newest is None:
        return Result(FAILED, "The quotes job has never stored a quote", detail)
    age = (now - newest).total_seconds() / 3600
    if age > q["max_age_hours"]:
        why = f" (last error: {errors[0]})" if errors else ""
        return Result(FAILED, f"No new quotes for {age:.1f} hours{why}", detail)
    return Result(DONE, f"Quotes stored {age:.1f} hours ago", detail)


def check_prices(db: Database, now: dt.datetime, cfg: dict) -> Result:
    """Enough of the current S&P 500 members have a price for the last close."""
    expected = last_close(now, cfg)
    with db.connect() as conn:
        row = (
            run(
                conn,
                "WITH m AS (SELECT DISTINCT company_id FROM core_index_member "
                "WHERE index_code = 'SP:SPX' AND end_date IS NULL), "
                "p AS (SELECT m.company_id, MAX(d.date) AS newest FROM m "
                "LEFT JOIN core_price_daily d ON d.company_id = m.company_id "
                "GROUP BY m.company_id) "
                "SELECT COUNT(*) AS members, COUNT(*) FILTER (WHERE newest >= :d) AS fresh, "
                "MAX(newest) AS newest FROM p",
                {"d": expected},
            )
            .mappings()
            .first()
        )
    members, fresh = row["members"] or 0, row["fresh"] or 0
    share = fresh / members if members else 0.0
    detail = {
        "expected": expected.isoformat(),
        "newest": str(row["newest"]),
        "members": members,
        "fresh": fresh,
        "share": round(share, 4),
    }
    text = f"{fresh} of {members} members have the {expected} close (newest {row['newest']})"
    if share >= cfg["prices"]["min_share_fresh"]:
        return Result(DONE, text, detail)
    return Result(FAILED, "Prices are stale: " + text, detail)


def github(path: str, client: httpx.Client) -> dict | list:
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    r = client.get(f"https://api.github.com{path}", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def check_evening(
    started: dt.datetime, now: dt.datetime, cfg: dict, client: httpx.Client
) -> Result:
    """The scheduled Claude session's commit on main since the run started (it runs after
    the ingest, at its own time), then a successful Pages run for it."""
    ev = cfg["evening"]
    late = (now - started).total_seconds() / 3600 >= ev["wait_hours"]
    commits = github(
        f"/repos/{ev['repo']}/commits?sha=main&since={stamp(started)}Z&per_page=30", client
    )
    ours = [c for c in commits if c["commit"]["message"].startswith(ev["commit_prefix"])]
    if not ours:
        if late:
            return Result(
                FAILED,
                f"No '{ev['commit_prefix']}' commit on main {ev['wait_hours']} hours after "
                "the run started (is the Claude routine enabled?)",
                {},
            )
        return Result(NOT_YET, "Waiting for the evening session's commit", {})
    sha = ours[0]["sha"]
    runs = github(
        f"/repos/{ev['repo']}/actions/workflows/{ev['pages_workflow']}/runs?head_sha={sha}",
        client,
    )["workflow_runs"]
    detail = {"commit": sha, "message": ours[0]["commit"]["message"].splitlines()[0]}
    done = [r for r in runs if r["status"] == "completed"]
    if any(r["conclusion"] == "success" for r in done):
        return Result(DONE, f"Evening commit {sha[:7]} published to the site", detail)
    if done:
        return Result(FAILED, f"The Pages run for {sha[:7]} ended {done[0]['conclusion']}", detail)
    if late:
        return Result(FAILED, f"The Pages run for {sha[:7]} has not finished", detail)
    return Result(NOT_YET, f"Waiting for the Pages run of {sha[:7]}", detail)


def marker(rows: list[dict], now: dt.datetime, cfg: dict) -> Result:
    """The evening session's first step: is the last trading day's data ready? `rows` are
    ops_pipeline_run rows."""
    day = last_close(now, cfg)
    mine = [r for r in rows if str(r["run_date"]) == day.isoformat()]
    if any(r["status"] in ("ready", "ok") for r in mine):
        return Result(DONE, f"The data for {day} is ready", {})
    if any(r["status"] == "failed" for r in mine):
        return Result(FAILED, f"The {day} pipeline run failed: the data is not ready", {})
    return Result(NOT_YET, f"The data for {day} is not ready yet", {})


def audit(rows: list[dict], now: dt.datetime, cfg: dict) -> Result:
    """The morning check, run from GitHub Actions: the last trading day has an ok run.
    `rows` are ops_pipeline_run rows (any order)."""
    day = last_close(now, cfg)
    mine = [r for r in rows if str(r["run_date"]) == day.isoformat()]
    if any(r["status"] == "ok" for r in mine):
        return Result(DONE, f"The {day} pipeline run finished ok", {})
    if not mine:
        return Result(FAILED, f"No pipeline run for {day}: was the PC or Airflow off?", {})
    states = ", ".join(sorted({r["status"] for r in mine}))
    return Result(FAILED, f"The {day} pipeline run did not finish ok ({states})", {})


# ---------------------------------------------------------------- alerts


def alert(subject: str, body: str, cfg: dict, client: httpx.Client) -> bool:
    """One email through Brevo. Returns False (and sends nothing) when a setting is missing."""
    a = cfg["alerts"]
    key = os.environ.get(a["key_env"])
    sender = os.environ.get(a["from_env"])
    to = os.environ.get(a["to_env"]) or os.environ.get("WATCHLIST_EMAIL_TO")
    if not (key and sender and to):
        return False
    _, address = parseaddr(sender)  # "Name <address>", as the evening email takes it
    message = {
        "sender": {"email": address, "name": "Stock pipeline"},
        "to": [{"email": t.strip()} for t in to.split(",") if t.strip()][:5],
        "subject": subject,
        "textContent": body,
    }
    r = client.post(BREVO, json=message, headers={"api-key": key}, timeout=60)
    r.raise_for_status()
    return True
