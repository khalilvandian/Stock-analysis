"""The scheduled ingest job: python -m stock_analysis.db ingest (config/ingest.toml).

One run:
1. plans the tasks: one per global source (the index members, the SEC ticker file, the ECB
   rates) and one per company and per-company source (SEC company facts, Yahoo prices,
   statements and earnings dates) for every current member of the universe;
2. picks the due tasks source by source, the never-fetched ones first, and runs each in its
   own transaction, until the source group's request budget is used, the source answers
   "too many requests", too many fail in a row, or the run's time is up;
3. rebuilds the core layer if anything was stored, and takes the day's coverage snapshot;
4. runs the nightly analyses (stock_analysis.nightly: the screener, the watch list's and the
   market report's numbers) for the evening run to read.

The mode is "backfill" until the universe is complete (config/coverage.toml), then
"maintain": smaller budgets and the refresh intervals of that mode. Every run is a row in
ops_run, every task a row in ops_task.
"""

from __future__ import annotations

import json
import platform
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..db import ROOT, Database, frame, run, scalar
from ..db.build import load_companies
from . import market, sec, xbrl, yahoo
from .common import NoData, Outcome, RateLimited, log_error

CONFIG = ROOT / "config" / "ingest.toml"
GLOBAL = {
    "tradingview": None,
    "tradingview_watchlist": market.WATCHLIST_KEY,
    "sec_tickers": "all",
    "ecb_rates": "EUR",
}
PER_COMPANY = ["sec_companyfacts", "yahoo_prices", "yahoo_earnings", "yahoo_statements"]
MARKET_CONFIG = ROOT / "config" / "market.toml"
EARNINGS_WINDOW_DAYS = 4  # earnings dates are fetched daily this long after a report


def load_config(path: Path = CONFIG) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None, microsecond=0)


def stamp(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


# ---------------------------------------------------------------- planning


def members(conn: Connection, index: str) -> list[str]:
    """Symbols in the newest TradingView snapshot of the index."""
    df = frame(
        conn,
        "SELECT symbol FROM raw_tv_constituent WHERE fetch_id = (SELECT MAX(f.fetch_id) "
        "FROM raw_fetch f JOIN raw_tv_constituent c ON c.fetch_id = f.fetch_id "
        "WHERE f.source = 'tradingview' AND f.request_key = :u)",
        {"u": index},
    )
    return sorted(set(df["symbol"]))


def watch_symbols(conn: Connection, config: dict | None = None) -> list[str]:
    """The watch list's stocks and their peers (user_watchlist, user_watchlist_peer) and the
    config's extra_symbols: fetched like the index members, whether in the index or not."""
    df = frame(
        conn,
        "SELECT symbol FROM user_watchlist UNION SELECT peer FROM user_watchlist_peer",
    )
    extra = [s.upper() for s in (config or {}).get("extra_symbols", [])]
    return sorted(set(df["symbol"]) | set(extra))


def instruments(path: Path | None = None) -> list[str]:
    """The market report's indices, rates, commodities, currencies and sector ETFs."""
    cfg = tomllib.loads(Path(path or MARKET_CONFIG).read_text(encoding="utf-8"))
    return sorted({s for group in cfg.values() for s in group})


def xbrl_items() -> set[str]:
    """The items read per share class from full filings: sec_class in config/db_items.toml,
    and the items a [[share_class]] converts from another class's units (Berkshire's shares)."""
    from ..db.build import load_companies, load_items

    _, tags = load_items()
    converted = {r["item"] for c in load_companies().get("share_class", [])
                 for r in c.get("convert", [])}  # fmt: skip
    return set(tags.loc[tags["taxonomy"] == "sec_class", "item"]) | converted


def plan(conn: Connection, config: dict, now: datetime) -> dict[str, int]:
    """Create the missing tasks, activate the members' and deactivate the others'. Returns
    the number of active tasks per source."""
    index = config["universe"]
    rows = [
        {"source": s, "key": key or index, "symbol": None}
        for s, key in GLOBAL.items()
        if s in config["sources"]
    ]
    index_members = members(conn, index)
    symbols = sorted(set(index_members) | set(watch_symbols(conn, config)))
    rows += [
        {"source": s, "key": sym, "symbol": sym}
        for s in PER_COMPANY
        if s in config["sources"]
        for sym in symbols
    ]
    if "sec_companyfacts" in config["sources"]:  # earlier filings under a predecessor's CIK
        rows += [
            {"source": "sec_companyfacts", "key": f"CIK{int(p['cik'])}", "symbol": p["symbol"]}
            for p in load_companies().get("predecessor", [])
            if p["symbol"] in symbols
        ]
    if "sec_xbrl" in config["sources"]:  # the filings that report a missing value
        items = sorted(xbrl_items())
        rows += [
            {"source": "sec_xbrl", "key": f["accession"], "symbol": f["symbol"]}
            for f in xbrl.filings_for_gaps(conn, items)
            if f["symbol"] in symbols
        ]
    market_symbols = instruments() if "yahoo_market" in config["sources"] else []
    rows += [{"source": "yahoo_market", "key": s, "symbol": None} for s in market_symbols]
    if rows:
        run(
            conn,
            "INSERT INTO ops_task (source, request_key, symbol, created_at, next_due_at) "
            "VALUES (:source, :key, :symbol, :t, :t) ON CONFLICT (source, request_key) DO NOTHING",
            [{**r, "t": stamp(now)} for r in rows],
        )
    if symbols:  # leavers keep their data but are no longer fetched
        run(
            conn,
            "UPDATE ops_task SET active = (symbol = ANY(:symbols)) WHERE symbol IS NOT NULL",
            {"symbols": symbols},
        )
    if "yahoo_market" in config["sources"]:  # instruments taken off config/market.toml
        run(
            conn,
            "UPDATE ops_task SET active = (request_key = ANY(:k)) WHERE source = 'yahoo_market'",
            {"k": market_symbols},
        )
    if "yahoo_earnings" in config["sources"]:
        earnings_due(conn, now)
    counts = run(
        conn, "SELECT source, COUNT(*) FROM ops_task WHERE active GROUP BY source"
    ).fetchall()
    return {s: n for s, n in counts}


def earnings_due(conn: Connection, now: datetime) -> int:
    """Make a company's earnings dates due on every run from its report day until a fetch at
    least a day after it, for reports in the last EARNINGS_WINDOW_DAYS days: the reported EPS
    is in the database the night it comes out (or the next), not up to a week later."""
    return run(
        conn,
        "UPDATE ops_task t SET next_due_at = :t WHERE t.source = 'yahoo_earnings' AND t.active "
        "AND t.next_due_at > :t AND EXISTS (SELECT 1 FROM raw_yahoo_earnings e "
        "WHERE e.symbol = t.request_key AND e.report_date <= CAST(:t AS DATE) "
        "AND e.report_date >= CAST(:t AS DATE) - :days "
        "AND (t.last_success_at IS NULL OR CAST(t.last_success_at AS DATE) < e.report_date + 1))",
        {"t": stamp(now), "days": EARNINGS_WINDOW_DAYS},
    ).rowcount


def choose_mode(conn: Connection, threshold: float) -> str:
    """Backfill until every task has been fetched once and the last coverage snapshot has at
    least `threshold` of the required values. Gaps left after that are mapping work (a tag
    to add, a derivation), which more fetching would not fill."""
    never = scalar(conn, "SELECT COUNT(*) FROM ops_task WHERE active AND last_success_at IS NULL")
    snap = run(
        conn,
        "SELECT cells_required, cells_present FROM out_coverage_snapshot "
        "ORDER BY snapshot_date DESC LIMIT 1",
    ).fetchone()
    if never or not snap or not snap[0] or snap[1] / snap[0] < threshold:
        return "backfill"
    return "maintain"


def due(conn: Connection, source: str, now: datetime) -> list[dict]:
    return frame(
        conn,
        "SELECT source, request_key, symbol, attempts FROM ops_task "
        "WHERE active AND source = :s AND next_due_at <= :t "
        "ORDER BY (last_success_at IS NULL) DESC, next_due_at, request_key",
        {"s": source, "t": stamp(now)},
    ).to_dict("records")


# ---------------------------------------------------------------- running


@dataclass
class Group:
    name: str
    budget: int
    min_interval_s: float
    stop_after_errors: int
    requests: int = 0
    ok: int = 0
    empty: int = 0
    failed: int = 0
    rows: int = 0
    errors_in_a_row: int = 0
    stopped: str | None = None
    errors: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        keys = ("requests", "budget", "ok", "empty", "failed", "rows", "stopped")
        return {k: getattr(self, k) for k in keys} | {"errors": self.errors[:10]}


@dataclass
class Context:
    """What the task handlers need; tests pass fakes."""

    config: dict
    http: httpx.Client
    sec_http: httpx.Client
    yahoo: object
    sleep: Callable[[float], None] = time.sleep
    _ciks: dict[str, int] | None = None
    _tags: set | None = None
    _concepts: set | None = None

    def cik(self, conn: Connection, symbol: str) -> int | None:
        if self._ciks is None:
            self._ciks = sec.ciks(conn)
        return self._ciks.get(symbol)

    def concepts(self) -> set:
        if self._concepts is None:
            self._concepts = xbrl.mapped_concepts()
        return self._concepts

    def tags(self) -> set:
        if self._tags is None:
            self._tags = sec.mapped_tags()
        return self._tags


def handle(conn: Connection, task: dict, ctx: Context) -> Outcome:
    source, key, cfg = task["source"], task["request_key"], ctx.config
    if source == "tradingview":
        return market.load_constituents(conn, ctx.http, cfg.get("market", "america"), key)
    if source == "tradingview_watchlist":
        extra = set(watch_symbols(conn, cfg)) - set(members(conn, cfg["universe"]))
        return market.load_watch_companies(conn, ctx.http, cfg.get("market", "america"), extra)
    if source == "sec_tickers":
        out = sec.load_tickers(conn, ctx.sec_http)
        ctx._ciks = None
        return out
    if source == "ecb_rates":
        return market.load_rates(conn, ctx.http)
    if source == "sec_xbrl":
        return xbrl.load_filing(conn, key, ctx.concepts())
    if source == "sec_companyfacts":
        cik = int(key[3:]) if key.startswith("CIK") else ctx.cik(conn, key)
        if cik is None:
            raise NoData(f"no CIK for {key} in the SEC ticker file")
        return sec.load_companyfacts(conn, ctx.sec_http, cik, ctx.tags())
    if source == "yahoo_prices":
        return yahoo.load_prices(
            conn, ctx.yahoo, key, cfg.get("prices_from", "2015-12-01"),
            int(cfg.get("price_overlap_days", 10)),
        )  # fmt: skip
    if source == "yahoo_market":
        return yahoo.load_prices(
            conn, ctx.yahoo, key, cfg.get("prices_from", "2015-12-01"),
            int(cfg.get("price_overlap_days", 10)),
        )  # fmt: skip
    if source == "yahoo_statements":
        return yahoo.load_statements(conn, ctx.yahoo, key)
    if source == "yahoo_earnings":
        return yahoo.load_earnings(conn, ctx.yahoo, key)
    raise ValueError(f"unknown source {source}")


def finish_task(
    conn: Connection, task: dict, status: str, next_due: datetime, now: datetime, **extra
) -> None:
    ok = status in ("ok", "empty")
    run(
        conn,
        "UPDATE ops_task SET status = :status, last_attempt_at = :now, next_due_at = :due, "
        "attempts = CASE WHEN :ok THEN 0 ELSE attempts + 1 END, "
        "last_success_at = CASE WHEN :ok THEN :now ELSE last_success_at END, "
        "last_fetch_id = COALESCE(:fetch_id, last_fetch_id), "
        "last_rows = CASE WHEN :ok THEN :rows ELSE last_rows END, last_error = :error "
        "WHERE source = :source AND request_key = :key",
        {
            "status": status,
            "now": stamp(now),
            "due": stamp(next_due),
            "ok": ok,
            "fetch_id": extra.get("fetch_id"),
            "rows": extra.get("rows"),
            "error": extra.get("error"),
            "source": task["source"],
            "key": task["request_key"],
        },
    )


def run_task(db: Database, task: dict, ctx: Context, group: Group, mode: str) -> None:
    cfg = ctx.config
    source = cfg["sources"][task["source"]]
    now = utcnow()
    refresh = timedelta(days=float(source["refresh_days"][mode])) - timedelta(hours=2)
    try:
        with db.begin() as conn:
            out = handle(conn, task, ctx)
            finish_task(
                conn, task, "ok", now + refresh, now,
                fetch_id=out.fetch_ids[-1] if out.fetch_ids else None, rows=out.received,
            )  # fmt: skip
        group.requests += out.requests
        group.ok += 1
        group.rows += out.stored
        group.errors_in_a_row = 0
    except RateLimited as exc:
        group.requests += 1
        group.stopped = f"rate limited: {exc}"[:300]
    except NoData as exc:
        group.requests += int(source.get("requests", 1))
        with db.begin() as conn:
            later = now + timedelta(days=float(cfg.get("empty_retry_days", 7)))
            finish_task(conn, task, "empty", later, now, error=str(exc)[:500], rows=0)
        group.empty += 1
        group.errors_in_a_row = 0
    except Exception as exc:  # any other failure: record it and go on with the next task
        group.requests += int(source.get("requests", 1))
        message = f"{type(exc).__name__}: {exc}"[:500]
        hours = min(float(cfg.get("error_retry_hours", 6)) * 2 ** int(task["attempts"]), 24)
        with db.begin() as conn:
            log_error(conn, task["source"], task["request_key"], "", message)
            finish_task(conn, task, "error", now + timedelta(hours=hours), now, error=message)
        group.failed += 1
        group.errors_in_a_row += 1
        group.errors.append(f"{task['request_key']}: {message}"[:200])
        if group.errors_in_a_row >= group.stop_after_errors:
            group.stopped = f"{group.errors_in_a_row} failures in a row"


def _run_job(
    db: Database,
    config: dict | None = None,
    *,
    mode: str | None = None,
    sources: list[str] | None = None,
    max_minutes: float | None = None,
    limit: int | None = None,
    do_build: bool = True,
    do_coverage: bool = True,
    do_nightly: bool = True,
    ctx: Context | None = None,
) -> dict:
    """One run, with the lock held."""
    from ..db.build import build
    from ..db.coverage import load_config as coverage_config
    from ..db.coverage import snapshot

    config = config or load_config()
    own = ctx is None
    ctx = ctx or Context(config, httpx.Client(timeout=60), sec.client(), yahoo.YahooClient())
    started = utcnow()
    deadline = time.monotonic() + 60 * float(max_minutes or config.get("max_minutes", 150))
    threshold = coverage_config().get("present_share_to_maintain", 0.90)
    with db.begin() as conn:
        # The lock is held, so a run still marked 'running' was killed part-way.
        run(
            conn,
            "UPDATE ops_run SET status = 'failed', summary = :s WHERE status = 'running'",
            {"s": json.dumps({"error": "interrupted (the process ended before finishing)"})},
        )
        plan(conn, config, started)
        mode = mode or choose_mode(conn, threshold)
        run_id = scalar(
            conn,
            "INSERT INTO ops_run (started_at, mode, host, status) "
            "VALUES (:t, :mode, :host, 'running') RETURNING run_id",
            {"t": stamp(started), "mode": mode, "host": platform.node()[:100]},
        )
    groups = {
        name: Group(
            name,
            int(g["budget"][mode]),
            float(g.get("min_interval_s", 0)),
            int(g.get("stop_after_errors", 10)),
        )  # fmt: skip
        for name, g in config["groups"].items()
    }
    order = sorted(config["sources"], key=lambda s: config["sources"][s].get("order", 99))
    timed_out = False
    try:
        for name in order:
            if sources and name not in sources:
                continue
            if name in PER_COMPANY:  # the universe and CIKs may have just changed
                with db.begin() as conn:
                    plan(conn, config, utcnow())
            group = groups[config["sources"][name]["group"]]
            cost = int(config["sources"][name].get("requests", 1))
            with db.connect() as conn:
                tasks = due(conn, name, utcnow())
            for task in tasks[:limit] if limit else tasks:
                if time.monotonic() > deadline:
                    timed_out = True
                    break
                if group.stopped:
                    break
                if group.requests + cost > group.budget:
                    group.stopped = "budget used"
                    break
                run_task(db, task, ctx, group, mode)
                ctx.sleep(group.min_interval_s * cost)
            if timed_out:
                break
    finally:
        if own:
            ctx.http.close()
            ctx.sec_http.close()
    with db.begin() as conn:  # the universe may have changed during the run
        plan(conn, config, utcnow())
    stored = sum(g.rows for g in groups.values())
    summary: dict = {
        "mode": mode,
        "groups": {n: g.summary() for n, g in groups.items()},
        "timed_out": timed_out,
    }
    build_id = None
    status = "ok"
    if do_build and (stored or raw_since_build(db)):
        try:
            result = build(db)
            build_id = result["build_id"]
            summary["build"] = result
        except Exception as exc:
            summary["build_error"] = repr(exc)[:500]
            status = "partial"
    if do_coverage:
        try:
            snap = snapshot(db)
            summary["coverage"] = {
                k: snap[k] for k in ("companies", "companies_covered", "share_present", "mode")
            }
        except Exception as exc:
            summary["coverage_error"] = repr(exc)[:500]
            status = "partial"
    if do_build and do_nightly and config.get("nightly", False):
        # The evening run's numbers, computed here so the scheduled session only reads them
        # (stock_analysis.nightly): the screener, the watch list, the market report.
        from .. import nightly
        from ..data import DbData

        try:
            summary["nightly"] = nightly.run(DbData(db, db))
        except Exception as exc:
            summary["nightly_error"] = repr(exc)[:500]
            status = "partial"
    failed = sum(g.failed for g in groups.values())
    if status == "ok" and (failed or timed_out or any(g.stopped for g in groups.values())):
        status = "partial"
    with db.begin() as conn:
        run(
            conn,
            "UPDATE ops_run SET finished_at = :t, status = :status, requests = :req, "
            "tasks_ok = :ok, tasks_failed = :failed, rows_stored = :rows, build_id = :b, "
            "summary = :s WHERE run_id = :id",
            {
                "t": stamp(utcnow()),
                "status": status,
                "req": sum(g.requests for g in groups.values()),
                "ok": sum(g.ok + g.empty for g in groups.values()),
                "failed": failed,
                "rows": stored,
                "b": build_id,
                "s": json.dumps(summary, default=str),
                "id": run_id,
            },
        )
    return {"run_id": run_id, "status": status, **summary}


def raw_since_build(db: Database) -> bool:
    """Raw data arrived after the last good build without this run storing it (a db push or
    db import from the PC): the core layer needs rebuilding all the same."""
    with db.connect() as conn:
        return bool(
            scalar(
                conn,
                "SELECT COALESCE(MAX(fetch_id), 0) > COALESCE((SELECT max_fetch_id FROM "
                "core_build WHERE status = 'ok' ORDER BY build_id DESC LIMIT 1), 0) "
                "FROM raw_fetch WHERE status = 'ok' AND rows_stored > 0",
            )
        )


LOCK_KEY = 18_000_018  # pg advisory lock: one ingest at a time per database


def run_job(db: Database, config: dict | None = None, **kwargs) -> dict:
    """One run of the job (see _run_job for the options). Returns its summary, also stored in
    ops_run. If another run holds the lock (a run that overran into the next schedule, or a
    second copy started by hand), this one does nothing and says so."""
    with db.connect() as lock:
        if not lock.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LOCK_KEY}).scalar():
            return {"run_id": None, "status": "skipped", "reason": "another ingest is running"}
        try:
            return _run_job(db, config, **kwargs)
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LOCK_KEY})
            lock.commit()


def make_due(db: Database, source: str, symbols: list[str] | None = None) -> int:
    """Make a source's tasks due now (e.g. after adding a tag to config/db_items.toml)."""
    with db.begin() as conn:
        sql = "UPDATE ops_task SET next_due_at = :t WHERE source = :s"
        params: dict = {"t": stamp(utcnow()), "s": source}
        if symbols:
            sql += " AND request_key = ANY(:k)"
            params["k"] = symbols
        return run(conn, sql, params).rowcount


def task_table(db: Database) -> pd.DataFrame:
    with db.connect() as conn:
        return frame(
            conn,
            "SELECT source, status, active, COUNT(*) AS tasks, "
            "SUM(CASE WHEN last_success_at IS NULL THEN 1 ELSE 0 END) AS never_fetched "
            "FROM ops_task GROUP BY source, status, active ORDER BY source, status",
        )
