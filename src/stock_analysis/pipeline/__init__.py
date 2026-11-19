"""The nightly pipeline's run log, checks and small actions (issue #30, docs/ORCHESTRATION.md).

Airflow (orchestration/) imports this module in its own interpreter: on the VM the checks are
a few milliseconds of SQL, so nothing here may import pandas, SQLAlchemy or the rest of the
package. It needs only the standard library, psycopg 3 and httpx, which Airflow's image has.
Every function takes a psycopg connection (autocommit) or an httpx client, so the tests give
it the local test database and respx.

The same functions run by hand: python -m stock_analysis.pipeline (see __main__.py).
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

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config" / "pipeline.toml"
DATABASE_CONFIG = ROOT / "config" / "database.toml"
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


# ---------------------------------------------------------------- the database


def connect(target: str | None = None):
    """A psycopg connection (autocommit) to the stock database: STOCK_PIPELINE_DB_URL if set
    (a full URL, as Airflow's settings give it), else a target in config/database.toml
    (STOCK_PIPELINE_TARGET, default server-writer) with its password from the environment."""
    import psycopg

    url = os.environ.get("STOCK_PIPELINE_DB_URL")
    password = None
    if not url:
        name = target or os.environ.get("STOCK_PIPELINE_TARGET") or "server-writer"
        settings = tomllib.loads(DATABASE_CONFIG.read_text(encoding="utf-8"))["targets"][name]
        url = settings["url"]
        password = os.environ.get(settings.get("password_env", ""))
    kwargs = {"autocommit": True, "connect_timeout": 10}
    if password:
        kwargs["password"] = password
    return psycopg.connect(url, **kwargs)


def rows(conn, sql: str, params: dict | None = None) -> list[dict]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params or {})
        return cur.fetchall() if cur.description else []


def one(conn, sql: str, params: dict | None = None) -> dict | None:
    found = rows(conn, sql, params)
    return found[0] if found else None


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


def start(conn, run_key: str, pipeline: str, now: dt.datetime, cfg: dict) -> int:
    """The run's row (made once; a retried start keeps it)."""
    rows(
        conn,
        "INSERT INTO ops_pipeline_run (pipeline, run_key, run_date, started_at, status, host) "
        "VALUES (%(p)s, %(k)s, %(d)s, %(t)s, 'running', %(h)s) ON CONFLICT (run_key) DO NOTHING",
        {
            "p": pipeline,
            "k": run_key,
            "d": last_close(now, cfg),
            "t": now,
            "h": socket.gethostname(),
        },
    )
    return run_row(conn, run_key)["run_id"]


def run_row(conn, run_key: str) -> dict:
    row = one(conn, "SELECT * FROM ops_pipeline_run WHERE run_key = %(k)s", {"k": run_key})
    if row is None:
        raise LookupError(f"No pipeline run {run_key!r}: run `start` first")
    return row


def log_step(conn, run_key: str, step: str, result: Result, now: dt.datetime) -> None:
    status = {DONE: "ok", FAILED: "failed", NOT_YET: "waiting"}[result.code]
    detail = json.dumps({"message": result.message, **result.detail}, default=str)
    rows(
        conn,
        "INSERT INTO ops_pipeline_step (run_id, step, status, at, detail) "
        "SELECT run_id, %(s)s, %(st)s, %(t)s, %(d)s FROM ops_pipeline_run WHERE run_key = %(k)s "
        "ON CONFLICT (run_id, step) DO UPDATE SET status = EXCLUDED.status, at = EXCLUDED.at, "
        "detail = EXCLUDED.detail",
        {"k": run_key, "s": step, "st": status, "t": now, "d": detail},
    )


def set_status(conn, run_key: str, status: str, now: dt.datetime) -> None:
    """A failed run stays failed: a later step can't hide an earlier failure."""
    column = {"ready": "ready_at", "ok": "finished_at", "failed": "finished_at"}[status]
    keep = "" if status == "failed" else " AND status <> 'failed'"
    rows(
        conn,
        f"UPDATE ops_pipeline_run SET status = %(s)s, {column} = %(t)s WHERE run_key = %(k)s{keep}",
        {"s": status, "t": now, "k": run_key},
    )


# ---------------------------------------------------------------- checks


def check_ingest(conn, started: dt.datetime, cfg: dict) -> Result:
    """The ingest job's run (Airflow started it just before): its row in ops_run, finished.
    `failed` fails; `partial` passes with a note, because the price check that follows is the
    real test."""
    since = started - dt.timedelta(minutes=cfg["ingest"]["started_within_minutes"])
    row = one(
        conn,
        "SELECT run_id, started_at, finished_at, mode, status, requests, tasks_ok, "
        "tasks_failed, rows_stored, build_id FROM ops_run WHERE started_at >= %(t)s "
        "ORDER BY run_id DESC LIMIT 1",
        {"t": since},
    )
    if row is None:
        return Result(FAILED, f"No ingest run in ops_run since {stamp(since)}", {})
    detail = {k: (stamp(v) if isinstance(v, dt.datetime) else v) for k, v in row.items()}
    if row["status"] not in ("ok", "partial"):
        return Result(FAILED, f"The ingest run {row['run_id']} is {row['status']}", detail)
    return Result(
        DONE,
        f"Ingest run {row['run_id']} ({row['mode']}) {row['status']}: "
        f"{row['requests']} requests, {row['rows_stored']} rows stored",
        detail,
    )


def check_build(conn, started: dt.datetime) -> Result:
    """The build of the core layer (db build) since the run started: its row in core_build."""
    row = one(
        conn,
        "SELECT build_id, status, started_at, finished_at, summary FROM core_build "
        "WHERE started_at >= %(t)s ORDER BY build_id DESC LIMIT 1",
        {"t": started},
    )
    if row is None:
        return Result(FAILED, f"No build since {stamp(started)}", {})
    try:
        summary = json.loads(row["summary"] or "{}")
    except ValueError:
        summary = {"text": row["summary"]}
    detail = {"build_id": row["build_id"], "status": row["status"]}
    if row["status"] != "ok":
        error = summary.get("error") or summary.get("text") or ""
        return Result(FAILED, f"Build {row['build_id']} is {row['status']} {error}".strip(), detail)
    return Result(DONE, f"Build {row['build_id']} ok", detail)


def check_nightly(conn, started: dt.datetime) -> Result:
    """What the nightly analyses (db nightly) stored since the run started: a screener run,
    the market numbers, and the numbers of every watch-list stock."""
    screener = one(
        conn,
        "SELECT run_id, run_date FROM out_screener_run WHERE created_at >= %(t)s "
        "ORDER BY run_id DESC LIMIT 1",
        {"t": started},
    )
    market = one(
        conn,
        "SELECT as_of FROM out_market_numbers WHERE computed_at >= %(t)s "
        "ORDER BY computed_at DESC LIMIT 1",
        {"t": started},
    )
    missing = [
        r["symbol"]
        for r in rows(
            conn,
            "SELECT w.symbol FROM user_watchlist w WHERE NOT EXISTS (SELECT 1 FROM "
            "out_stock_numbers n WHERE n.symbol = w.symbol AND n.computed_at >= %(t)s) "
            "ORDER BY w.position",
            {"t": started},
        )
    ]
    problems = []
    if screener is None:
        problems.append("no screener run")
    if market is None:
        problems.append("no market numbers")
    if missing:
        problems.append(f"no numbers for {', '.join(missing)}")
    detail = {
        "screener_run": screener and screener["run_id"],
        "market_as_of": market and str(market["as_of"]),
        "stocks_missing": missing,
    }
    if problems:
        return Result(FAILED, "The nightly analyses stored " + "; ".join(problems), detail)
    return Result(
        DONE,
        f"Screener run {screener['run_id']}, market numbers as of {market['as_of']}, "
        "every watch-list stock computed",
        detail,
    )


def check_prices(conn, now: dt.datetime, cfg: dict) -> Result:
    """Enough of the current S&P 500 members have a price for the last close."""
    expected = last_close(now, cfg)
    row = one(
        conn,
        "WITH m AS (SELECT DISTINCT company_id FROM core_index_member "
        "WHERE index_code = 'SP:SPX' AND end_date IS NULL), "
        "p AS (SELECT m.company_id, MAX(d.date) AS newest FROM m "
        "LEFT JOIN core_price_daily d ON d.company_id = m.company_id "
        "GROUP BY m.company_id) "
        "SELECT COUNT(*) AS members, COUNT(*) FILTER (WHERE newest >= %(d)s) AS fresh, "
        "MAX(newest) AS newest FROM p",
        {"d": expected},
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


def check_quotes(conn, started: dt.datetime) -> Result:
    """The quotes job's run that Airflow just started: a fetch since then, stored, or nothing
    when the prices were the same as the last run's, but not an error."""
    found = rows(
        conn,
        "SELECT status, fetched_at, rows_stored, error FROM raw_fetch WHERE source = "
        "'tradingview_quotes' AND request_key = 'all' AND loaded_at >= %(t)s "
        "ORDER BY fetch_id DESC LIMIT 3",
        {"t": started},
    )
    if found and found[0]["status"] == "error":
        return Result(FAILED, f"The quotes run failed: {found[0]['error']}", {})
    if found:
        return Result(DONE, f"Quotes stored: {found[0]['rows_stored']} rows", {})
    return Result(DONE, "Same prices as the last run: nothing new to store", {})


# ---------------------------------------------------------------- GitHub


def github_headers(token: str | None = None) -> dict:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GITHUB_DISPATCH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def github(path: str, client: httpx.Client) -> dict | list:
    r = client.get(f"https://api.github.com{path}", headers=github_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def publish_site(cfg: dict, client: httpx.Client) -> Result:
    """Start the Pages workflow (workflow_dispatch); needs GITHUB_DISPATCH_TOKEN."""
    token = os.environ.get("GITHUB_DISPATCH_TOKEN")
    if not token:
        return Result(FAILED, "No GITHUB_DISPATCH_TOKEN: the site can't be rebuilt", {})
    ev = cfg["evening"]
    r = client.post(
        f"https://api.github.com/repos/{ev['repo']}/actions/workflows/"
        f"{ev['pages_workflow']}/dispatches",
        json={"ref": "main"},
        headers=github_headers(token),
        timeout=30,
    )
    if r.status_code != 204:
        return Result(FAILED, f"GitHub refused the site rebuild ({r.status_code}): {r.text}", {})
    return Result(DONE, "Site rebuild started", {})


def check_evening(
    started: dt.datetime, now: dt.datetime, cfg: dict, client: httpx.Client
) -> Result:
    """The scheduled Claude session's commit on main since the run started (it keeps its own
    schedule), then a successful Pages run for it."""
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
        return Result(NOT_YET, "Waiting for the Claude session's commit", {})
    sha = ours[0]["sha"]
    runs = github(
        f"/repos/{ev['repo']}/actions/workflows/{ev['pages_workflow']}/runs?head_sha={sha}",
        client,
    )["workflow_runs"]
    detail = {"commit": sha, "message": ours[0]["commit"]["message"].splitlines()[0]}
    done = [r for r in runs if r["status"] == "completed"]
    if any(r["conclusion"] == "success" for r in done):
        return Result(DONE, f"Commit {sha[:7]} published to the site", detail)
    if done:
        return Result(FAILED, f"The Pages run for {sha[:7]} ended {done[0]['conclusion']}", detail)
    if late:
        return Result(FAILED, f"The Pages run for {sha[:7]} has not finished", detail)
    return Result(NOT_YET, f"Waiting for the Pages run of {sha[:7]}", detail)


# ---------------------------------------------------------------- reading the log


def marker(found: list[dict], now: dt.datetime, cfg: dict) -> Result:
    """Is the last trading day's data ready? `found`: stock_nightly ops_pipeline_run rows."""
    day = last_close(now, cfg)
    mine = [r for r in found if str(r["run_date"]) == day.isoformat()]
    if any(r["status"] in ("ready", "ok") for r in mine):
        return Result(DONE, f"The data for {day} is ready", {})
    if any(r["status"] == "failed" for r in mine):
        return Result(FAILED, f"The {day} pipeline run failed: the data is not ready", {})
    return Result(NOT_YET, f"The data for {day} is not ready yet", {})


def audit(found: list[dict], now: dt.datetime, cfg: dict) -> Result:
    """The nightly run of the last trading day whose run should be over by now (`grace_hours`
    after the close, config [audit]) finished ok. `found`: stock_nightly runs."""
    day = last_close(now - dt.timedelta(hours=cfg["audit"]["grace_hours"]), cfg)
    mine = [r for r in found if str(r["run_date"]) == day.isoformat()]
    if any(r["status"] == "ok" for r in mine):
        return Result(DONE, f"The {day} pipeline run finished ok", {})
    if not mine:
        # `found` is the newest 20 runs: when there are fewer and all are later than `day`,
        # Airflow wasn't live yet on that day (go-live), which isn't a failure.
        dates = [str(r["run_date"]) for r in found]
        if found and len(found) < 20 and all(d > day.isoformat() for d in dates):
            return Result(DONE, f"No run for {day}: the pipeline started after it", {})
        return Result(FAILED, f"No pipeline run for {day}: was Airflow down?", {})
    states = ", ".join(sorted({r["status"] for r in mine}))
    return Result(FAILED, f"The {day} pipeline run did not finish ok ({states})", {})


def audit_quotes(found: list[dict], now: dt.datetime, cfg: dict) -> Result:
    """On weekdays (the quotes run every hour, Monday to Friday UTC), an ok stock_quotes run
    within `quotes_max_age_hours`. `found`: stock_quotes runs with their started_at."""
    if now.weekday() >= 5 or (now.weekday() == 0 and now.hour < 2):
        return Result(DONE, "The quotes don't run now", {})
    limit = now - dt.timedelta(hours=cfg["audit"]["quotes_max_age_hours"])
    ok = [r for r in found if r["status"] == "ok" and _naive(r["started_at"]) >= limit]
    if ok:
        return Result(DONE, f"Quotes ran ok at {ok[0]['started_at']}", {})
    return Result(
        FAILED,
        f"No ok quotes run since {stamp(limit)} UTC: is Airflow or the quotes job down?",
        {},
    )


def _naive(value) -> dt.datetime:
    t = value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
    return t.replace(tzinfo=None)


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
