"""Check the selected database: the connection works, the schema is current and the data is
there. Read-only; works on any target (the local Docker PostgreSQL, the server).

    uv run python -m stock_analysis.db check                 # the selected target
    uv run python -m stock_analysis.db check --target server

Each check prints PASS, WARN or FAIL. The command exits 1 on any FAIL (with --strict, on any
WARN too). The settings (sample symbols, maximum data age, coverage) are under [check] in
config/database.toml.

FAIL means the database can't be used: it can't be reached, the schema is old, tables are
missing or empty, the last build failed, a sample company is missing, or a value is
impossible. WARN means it works but needs attention: stale data, low coverage, or tables the
loaders have not filled yet.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from datetime import date

from dotenv import load_dotenv
from sqlalchemy import text

from . import ROOT, Database, load_config, migrations, target_settings

REQUIRED_ROWS = [
    "raw_fetch",
    "core_company",
    "core_index_member",
    "core_price_daily",
    "core_fundamental",
    "core_fundamental_ttm",
    "out_screener_result",
    "user_watchlist",
    "out_watchlist_run",
]
OPTIONAL_ROWS = ["raw_sec_ticker", "raw_sec_fact", "out_valuation"]


@dataclass
class Result:
    status: str  # PASS | WARN | FAIL
    name: str
    detail: str


class Reader:
    """A read-only connection with the few calls the checks need."""

    def __init__(self, url: str, password_env: str | None = None):
        password = os.environ.get(password_env) if password_env else None
        self.db = Database(url, password, read_only=True)
        self.where = self.db.where
        self.conn = self.db.connect()

    def rows(self, sql: str) -> list[tuple]:
        return [tuple(r) for r in self.conn.execute(text(sql))]

    def one(self, sql: str):
        found = self.rows(sql)
        return found[0][0] if found else None

    def objects(self) -> set[str]:
        return self.db.objects()

    def close(self) -> None:
        self.conn.close()
        self.db.close()


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def day(value) -> date | None:
    return date.fromisoformat(str(value)[:10]) if value else None


def expected_objects() -> set[str]:
    names = set()
    for _, path in migrations():
        sql = path.read_text(encoding="utf-8")
        names |= set(re.findall(r"CREATE (?:TABLE|VIEW) (\w+)", sql))
    return names


def run_checks(db: Reader, settings: dict, today: date | None = None) -> list[Result]:
    today = today or date.today()
    out: list[Result] = []

    present = db.objects()
    missing = sorted(expected_objects() - present)
    if missing:
        out.append(Result("FAIL", "tables and views", "missing: " + ", ".join(missing)))
        return out
    out.append(Result("PASS", "tables and views", f"{len(expected_objects())} present"))

    latest = migrations()[-1][0]
    version = db.one("SELECT MAX(version) FROM schema_version") or 0
    status = "PASS" if version == latest else ("WARN" if version > latest else "FAIL")
    out.append(Result(status, "schema version", f"{version} (code expects {latest})"))

    build = db.rows(
        "SELECT status, finished_at, summary FROM core_build ORDER BY build_id DESC LIMIT 1"
    )
    if not build:
        out.append(Result("FAIL", "last build", "no build yet (run build)"))
    else:
        status, finished, _ = build[0]
        ok = status == "ok"
        out.append(Result("PASS" if ok else "FAIL", "last build", f"{status}, {finished}"))

    for table in REQUIRED_ROWS + OPTIONAL_ROWS:
        n = db.one(f"SELECT COUNT(*) FROM {table}")
        if n:
            out.append(Result("PASS", f"rows in {table}", f"{n:,}"))
        else:
            empty = "FAIL" if table in REQUIRED_ROWS else "WARN"
            out.append(Result(empty, f"rows in {table}", "empty"))

    max_age = settings.get("max_age_days", 7)
    newest = {
        "newest price": db.one("SELECT MAX(date) FROM core_price_daily"),
        "newest S&P 500 snapshot": db.one(
            "SELECT MAX(fetched_at) FROM raw_fetch WHERE source = 'tradingview'"
        ),
        "newest screener run": db.one("SELECT MAX(run_date) FROM out_screener_run"),
    }
    for name, value in newest.items():
        d = day(value)
        if d is None:
            out.append(Result("WARN", name, "none"))
            continue
        age = (today - d).days
        out.append(Result("PASS" if age <= max_age else "WARN", name, f"{d} ({age} days old)"))

    members = db.one("SELECT COUNT(*) FROM core_index_member WHERE end_date IS NULL") or 0
    min_cov = settings.get("min_coverage", 0.95)
    for name, table in (("prices", "core_price_daily"), ("fundamentals", "core_fundamental")):
        n = db.one(
            "SELECT COUNT(*) FROM core_index_member m WHERE m.end_date IS NULL AND EXISTS "
            f"(SELECT 1 FROM {table} t WHERE t.company_id = m.company_id)"
        )
        share = n / members if members else 0
        out.append(
            Result(
                "PASS" if share >= min_cov else "WARN",
                f"S&P 500 members with {name}",
                f"{n} of {members} ({share:.0%})",
            )
        )

    watch = db.one("SELECT COUNT(*) FROM user_watchlist") or 0
    if watch:
        priced = db.one(
            "SELECT COUNT(*) FROM user_watchlist w JOIN core_company c ON c.symbol = w.symbol "
            "WHERE EXISTS (SELECT 1 FROM core_price_daily p WHERE p.company_id = c.company_id)"
        )
        ran = db.one("SELECT COUNT(*) FROM v_watchlist WHERE last_run_at IS NOT NULL")
        out.append(
            Result(
                "PASS" if ran == watch else "WARN",
                "watch list",
                f"{watch} stocks, {ran} with runs, {priced} with prices in core",
            )
        )
        if priced < watch:
            out[-1] = Result("WARN", out[-1].name, out[-1].detail)

    for symbol in settings.get("sample_symbols", []):
        out.extend(check_symbol(db, symbol))

    bad = db.one("SELECT COUNT(*) FROM core_price_daily WHERE close <= 0 OR adj_close <= 0")
    out.append(
        Result("FAIL" if bad else "PASS", "prices are positive", f"{bad} bad rows" if bad else "")
    )
    bad = db.one("SELECT COUNT(*) FROM core_fundamental WHERE filed < period_end")
    out.append(
        Result(
            "FAIL" if bad else "PASS",
            "filed on or after the period end",
            f"{bad} bad rows" if bad else "",
        )
    )
    issues = dict(
        db.rows(
            "SELECT severity, COUNT(*) FROM core_quality_issue WHERE build_id = "
            "(SELECT MAX(build_id) FROM core_build) GROUP BY severity"
        )
    )
    detail = ", ".join(f"{n} {s}" for s, n in sorted(issues.items())) or "none"
    out.append(Result("FAIL" if issues.get("error") else "PASS", "quality issues", detail))
    return out


def check_symbol(db: Reader, symbol: str) -> list[Result]:
    s = quote(symbol)
    cid = db.one(f"SELECT company_id FROM core_company WHERE symbol = {s}")
    if cid is None:
        return [Result("FAIL", symbol, "not in core_company")]
    prices = db.rows(
        f"SELECT COUNT(*), MIN(date), MAX(date) FROM core_price_daily WHERE company_id = {cid}"
    )[0]
    years = db.rows(
        f"SELECT COUNT(*), MIN(fiscal_year), MAX(fiscal_year) FROM v_annual "
        f"WHERE company_id = {cid} AND revenue IS NOT NULL"
    )[0]
    out = [
        Result(
            "PASS" if prices[0] else "FAIL",
            f"{symbol} prices",
            f"{prices[0]:,} days, {str(prices[1])[:10]} to {str(prices[2])[:10]}"
            if prices[0]
            else "none",
        ),
        Result(
            "PASS" if years[0] else "FAIL",
            f"{symbol} fiscal years",
            f"{years[0]} with revenue, {years[1]} to {years[2]}" if years[0] else "none",
        ),
    ]
    last = db.rows(
        "SELECT date, close, revenue_ttm, total_debt, cash, market_cap FROM v_daily "
        f"WHERE company_id = {cid} ORDER BY date DESC LIMIT 1"
    )
    if last:
        d, close, revenue, debt, cash, cap = last[0]
        gaps = [n for n, v in (("revenue", revenue), ("debt", debt), ("cash", cash)) if v is None]
        shown = (
            f"{str(d)[:10]}: close {close:.2f}"
            + (f", revenue {revenue / 1e9:.1f}bn" if revenue else "")
            + (f", debt {debt / 1e9:.1f}bn" if debt else "")
            + (f", market value {cap / 1e9:.1f}bn" if cap else "")
            + (f" (missing {', '.join(gaps)})" if gaps else "")
        )
        out.append(Result("WARN" if gaps else "PASS", f"{symbol} latest day", shown))
    return out


def check(target: str | None = None, strict: bool = False) -> int:
    load_dotenv(ROOT / ".env")
    config = load_config()
    try:
        settings = target_settings(target, config)
    except ValueError as exc:
        print(f"FAIL  connection  {exc}")
        return 1
    started = time.perf_counter()
    try:
        db = Reader(settings["url"], settings.get("password_env"))
    except Exception as exc:  # any driver error means the connection failed
        print(f"FAIL  connection  {settings['name']}: {exc}")
        return 1
    ms = (time.perf_counter() - started) * 1000
    results = [Result("PASS", "connection", f"{settings['name']}: {db.where} ({ms:.0f} ms)")]
    try:
        results += run_checks(db, config.get("check", {}))
    finally:
        db.close()
    width = max(len(r.name) for r in results)
    for r in results:
        print(f"{r.status:4}  {r.name:<{width}}  {r.detail}")
    counts = {s: sum(r.status == s for r in results) for s in ("PASS", "WARN", "FAIL")}
    print(f"\n{counts['PASS']} pass, {counts['WARN']} warn, {counts['FAIL']} fail")
    return 1 if counts["FAIL"] or (strict and counts["WARN"]) else 0
