"""One way for every script, and for Claude, to read and write the project's data: straight
from the PostgreSQL database (reads as stock_reader, writes as stock_writer), or through the web
API (api/app.py) where PostgreSQL can't be reached, as in Claude's cloud sessions.

    from stock_analysis.data import Data

    data = Data.open()                     # picks the backend (see below)
    data.watchlist()                       # DataFrame
    data.annual("NEE")
    data.daily("NEE", start="2025-01-01")
    data.sql("SELECT symbol, revenue FROM v_annual WHERE fiscal_year = 2025")
    data.save_note("NFLX", "## Thesis ...")
    data.save_screener_run("2026-11-18", "SP:SPX", "stock_analysis.screener", results)

Backend: when STOCK_API_URL is set (the cloud environment sets it), the web API, with the key
from STOCK_API_KEY if set (on a PC) or attached by the cloud's network secret. Otherwise the
database targets in config/database.toml: STOCK_DATA_TARGET (default server-reader) for reads
and STOCK_DATA_WRITE_TARGET (default server-writer) for writes. Both backends run the same SQL
and return DataFrames with dates as ISO text.
"""

from __future__ import annotations

import datetime as dt
import os
import ssl

import pandas as pd

from .db import ROOT, Database, frame, run

ROW_LIMIT = 50_000
SQL_TIMEOUT_S = 20

# The named reads.
READS = {
    "watchlist": "SELECT * FROM v_watchlist ORDER BY position",
    "companies": (
        "SELECT c.symbol, c.name, c.cik, c.exchange, c.sector, c.industry, c.currency, "
        "m.start_date AS in_sp500_since FROM core_company c LEFT JOIN core_index_member m "
        "ON m.company_id = c.company_id AND m.end_date IS NULL ORDER BY c.symbol"
    ),
    "annual": "SELECT * FROM v_annual WHERE symbol = :symbol ORDER BY fiscal_year",
    "daily": (
        "SELECT * FROM v_daily WHERE symbol = :symbol AND date >= :start AND date <= :end "
        "ORDER BY date"
    ),
    "prices": (
        "SELECT c.symbol, p.date, p.open, p.high, p.low, p.close, p.adj_close, p.volume, "
        "p.dividend, p.split_ratio FROM core_price_daily p JOIN core_company c "
        "ON c.company_id = p.company_id WHERE c.symbol = :symbol AND p.date >= :start "
        "AND p.date <= :end ORDER BY p.date"
    ),
    "screener": (
        "SELECT r.run_date, s.* FROM out_screener_result s JOIN out_screener_run r "
        "ON r.run_id = s.run_id WHERE s.run_id = (SELECT MAX(run_id) FROM out_screener_run) "
        "AND (CAST(:stage AS INTEGER) IS NULL OR s.stage = CAST(:stage AS INTEGER)) "
        "ORDER BY s.stage, s.sector, s.rank_in_sector, s.symbol"
    ),
    "watchlist_runs": (
        "SELECT * FROM out_watchlist_run WHERE CAST(:symbol AS TEXT) IS NULL "
        "OR symbol = CAST(:symbol AS TEXT) ORDER BY symbol, run_at"
    ),
    "market_runs": "SELECT * FROM out_market_run ORDER BY run_at",
    "notes": (
        "SELECT * FROM v_note_latest WHERE CAST(:subject AS TEXT) IS NULL "
        "OR subject = CAST(:subject AS TEXT) ORDER BY subject"
    ),
    "valuations": (
        "SELECT * FROM out_valuation WHERE CAST(:symbol AS TEXT) IS NULL "
        "OR symbol = CAST(:symbol AS TEXT) ORDER BY symbol, as_of"
    ),
    "quality": (
        "SELECT c.symbol, i.item, i.at_date, i.check_name, i.severity, i.detail "
        "FROM core_quality_issue i LEFT JOIN core_company c ON c.company_id = i.company_id "
        "WHERE i.build_id = (SELECT MAX(build_id) FROM core_build) "
        "ORDER BY i.severity, c.symbol, i.at_date"
    ),
    "status": (
        "SELECT (SELECT MAX(version) FROM schema_version) AS schema_version, "
        "(SELECT MAX(finished_at) FROM core_build WHERE status = 'ok') AS last_build, "
        "(SELECT COUNT(*) FROM core_company) AS companies, "
        "(SELECT MAX(date) FROM core_price_daily) AS newest_price, "
        "(SELECT MAX(run_date) FROM out_screener_run) AS newest_screener_run"
    ),
}
DEFAULTS = {"start": "1900-01-01", "end": "2999-12-31", "stage": None, "symbol": None,
            "subject": None}  # fmt: skip


def now_utc() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S")


class Data:
    """The interface; `Data.open()` returns the database backend."""

    @staticmethod
    def open(read_target: str | None = None, write_target: str | None = None) -> Data:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        api = os.environ.get("STOCK_API_URL")
        if api and not (read_target or write_target):
            return ApiData(api, os.environ.get("STOCK_API_KEY"))
        read_target = read_target or os.environ.get("STOCK_DATA_TARGET", "server-reader")
        write_target = write_target or os.environ.get("STOCK_DATA_WRITE_TARGET", "server-writer")
        reader = Database.open(read_target, read_only=True)
        return DbData(reader, lambda: Database.open(write_target))

    # Reads ------------------------------------------------------------------------------
    def read(self, name: str, **params) -> pd.DataFrame:
        raise NotImplementedError

    def watchlist(self) -> pd.DataFrame:
        return self.read("watchlist")

    def companies(self) -> pd.DataFrame:
        return self.read("companies")

    def annual(self, symbol: str) -> pd.DataFrame:
        return self.read("annual", symbol=symbol)

    def daily(self, symbol: str, start: str | None = None, end: str | None = None):
        return self.read("daily", symbol=symbol, start=start, end=end)

    def prices(self, symbol: str, start: str | None = None, end: str | None = None):
        return self.read("prices", symbol=symbol, start=start, end=end)

    def screener(self, stage: int | None = None) -> pd.DataFrame:
        return self.read("screener", stage=stage)

    def watchlist_runs(self, symbol: str | None = None) -> pd.DataFrame:
        return self.read("watchlist_runs", symbol=symbol)

    def market_runs(self) -> pd.DataFrame:
        return self.read("market_runs")

    def notes(self, subject: str | None = None) -> pd.DataFrame:
        return self.read("notes", subject=subject)

    def valuations(self, symbol: str | None = None) -> pd.DataFrame:
        return self.read("valuations", symbol=symbol)

    def quality(self) -> pd.DataFrame:
        return self.read("quality")

    def status(self) -> dict:
        return self.read("status").iloc[0].to_dict()

    def sql(self, query: str, limit: int = ROW_LIMIT) -> pd.DataFrame:
        """Any read-only SQL (one SELECT or WITH statement), at most `limit` rows."""
        raise NotImplementedError

    # Writes (results of analyses) -------------------------------------------------------
    def save_note(self, subject: str, text: str) -> int:
        raise NotImplementedError

    def save_watchlist_run(self, row: dict) -> int:
        raise NotImplementedError

    def save_market_run(self, row: dict) -> int:
        raise NotImplementedError

    def save_valuations(self, rows: list[dict]) -> int:
        raise NotImplementedError

    def set_watchlist(self, stocks: list[dict]) -> int:
        raise NotImplementedError

    def save_screener_run(
        self, run_date: str, universe: str, source: str, results: list[dict]
    ) -> int:
        """One screener run (out_screener_run) and its rows (out_screener_result: stage,
        symbol, sector, category, status, rank_in_sector, close, cheap_price, detail_json).
        A second run on the same day replaces the first."""
        steps = screener_steps(run_date, universe, source, results)
        return self.write_steps(steps)[-1]

    def write_steps(self, steps: list[tuple[str, list[dict]]]) -> list[int]:
        raise NotImplementedError


SCREENER_COLUMNS = ["stage", "symbol", "sector", "category", "status", "rank_in_sector",
                    "close", "cheap_price", "detail_json"]  # fmt: skip


def screener_steps(
    run_date: str, universe: str, source: str, results: list[dict]
) -> list[tuple[str, list[dict]]]:
    key = {"d": str(run_date), "u": universe}
    run_of = "(SELECT run_id FROM out_screener_run WHERE run_date = :d AND universe = :u)"
    unknown = {k for r in results for k in r} - set(SCREENER_COLUMNS)
    if unknown:
        raise ValueError(f"Unknown fields for out_screener_result: {', '.join(sorted(unknown))}")
    rows = [{**key, **{c: r.get(c) for c in SCREENER_COLUMNS}} for r in results]
    return [
        (f"DELETE FROM out_screener_result WHERE run_id = {run_of}", [key]),
        ("DELETE FROM out_screener_run WHERE run_date = :d AND universe = :u", [key]),
        (
            "INSERT INTO out_screener_run (run_date, universe, created_at, source) "
            "VALUES (:d, :u, :t, :s)",
            [{**key, "t": now_utc(), "s": source}],
        ),
        (
            f"INSERT INTO out_screener_result (run_id, {', '.join(SCREENER_COLUMNS)}) "
            f"VALUES ({run_of}, {', '.join(':' + c for c in SCREENER_COLUMNS)})",
            rows,
        ),
    ]


def clean(params: dict) -> dict:
    out = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    return {k: (str(v) if isinstance(v, dt.date) else v) for k, v in out.items()}


WATCHLIST_RUN_COLUMNS = ["symbol", "run_at", "file", "price", "eps_adj_ttm", "pe_adj",
                         "pe_median_10y", "target_pe", "entry_price", "to_entry", "verdict",
                         "stakes_per_share"]  # fmt: skip
MARKET_RUN_COLUMNS = ["run_at", "file", "sp500", "sp500_day", "vix", "above_200d",
                      "stocks_to_look_at", "screener_date", "screener_passed",
                      "screener_screened", "screener_listed"]  # fmt: skip
VALUATION_COLUMNS = ["symbol", "as_of", "method", "fair_value", "price", "detail_json", "source"]


def insert_sql(table: str, columns: list[str], rows: list[dict]) -> tuple[str, list[dict]]:
    """The INSERT for the given columns of each row (existing keys are left alone)."""
    unknown = {k for r in rows for k in r} - set(columns)
    if unknown:
        raise ValueError(f"Unknown fields for {table}: {', '.join(sorted(unknown))}")
    sql = (
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
        f"({', '.join(':' + c for c in columns)}) ON CONFLICT DO NOTHING"
    )
    return sql, [{c: r.get(c) for c in columns} for r in rows]


def insert_rows(conn, table: str, columns: list[str], rows: list[dict]) -> int:
    sql, full = insert_sql(table, columns, rows)
    if not full:
        return 0
    res = run(conn, sql, full)
    return res.rowcount if res.rowcount is not None and res.rowcount >= 0 else len(full)


def note_row(subject: str, text: str) -> dict:
    return {"subject": subject, "updated_at": now_utc(), "text": text, "source": "script"}


def watchlist_rows(stocks: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """set_watchlist's input as rows of user_watchlist, user_watchlist_peer, user_eps_override."""
    w = [
        {
            "symbol": s["symbol"],
            "position": i,
            "target_pe": s.get("target_pe"),
            "target_note": s.get("target_note"),
            "stakes_per_share": s.get("stakes_per_share"),
        }
        for i, s in enumerate(stocks, start=1)
    ]
    peers = [
        {"symbol": s["symbol"], "peer": p, "position": i}
        for s in stocks
        for i, p in enumerate(s.get("peers", []), start=1)
    ]
    overrides = [
        {"symbol": s["symbol"], **{k: o.get(k) for k in ("reported", "eps", "reason")}}
        for s in stocks
        for o in s.get("eps_override", [])
    ]
    return w, peers, overrides


WATCHLIST_TABLES = [
    ("user_watchlist", ["symbol", "position", "target_pe", "target_note", "stakes_per_share"]),
    ("user_watchlist_peer", ["symbol", "peer", "position"]),
    ("user_eps_override", ["symbol", "reported", "eps", "reason"]),
]


class DbData(Data):
    """Straight from PostgreSQL: reads as stock_reader, writes as stock_writer."""

    def __init__(self, reader: Database, writer=None):
        self.reader = reader
        self._writer = writer  # a Database, or a function returning one (opened on first write)

    @property
    def writer(self) -> Database:
        if callable(self._writer):
            self._writer = self._writer()
        if self._writer is None:
            raise RuntimeError("No writer database configured")
        return self._writer

    def read(self, name: str, **params) -> pd.DataFrame:
        with self.reader.connect() as conn:
            return frame(conn, READS[name], clean(params))

    def sql(self, query: str, limit: int = ROW_LIMIT) -> pd.DataFrame:
        statement = query.strip().rstrip(";").strip()
        if ";" in statement:
            raise ValueError("One statement only")
        if statement.split(None, 1)[0].lower() not in ("select", "with"):
            raise ValueError("Only SELECT or WITH queries")
        limit = max(1, min(int(limit), ROW_LIMIT))
        with self.reader.connect() as conn:
            trans = conn.begin()
            try:
                conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{SQL_TIMEOUT_S}s'")
                return frame(conn, f"SELECT * FROM ({statement}) q LIMIT {limit}")
            finally:
                trans.rollback()

    def save_note(self, subject: str, text: str) -> int:
        with self.writer.begin() as conn:
            return insert_rows(
                conn,
                "out_note",
                ["subject", "updated_at", "text", "source"],
                [note_row(subject, text)],
            )

    def save_watchlist_run(self, row: dict) -> int:
        with self.writer.begin() as conn:
            return insert_rows(conn, "out_watchlist_run", WATCHLIST_RUN_COLUMNS, [row])

    def save_market_run(self, row: dict) -> int:
        with self.writer.begin() as conn:
            return insert_rows(conn, "out_market_run", MARKET_RUN_COLUMNS, [row])

    def save_valuations(self, rows: list[dict]) -> int:
        with self.writer.begin() as conn:
            return insert_rows(conn, "out_valuation", VALUATION_COLUMNS, rows)

    def write_steps(self, steps: list[tuple[str, list[dict]]]) -> list[int]:
        counts = []
        with self.writer.begin() as conn:
            for sql, rows in steps:
                res = run(conn, sql, rows or None)
                counts.append(res.rowcount if res.rowcount is not None else -1)
        return counts

    def set_watchlist(self, stocks: list[dict]) -> int:
        """Replace the watch list: [{symbol, target_pe, target_note, stakes_per_share,
        peers: [...], eps_override: [{reported, eps, reason}]}]."""
        tables = watchlist_rows(stocks)
        with self.writer.begin() as conn:
            for table, _ in reversed(WATCHLIST_TABLES):
                run(conn, f"DELETE FROM {table}")
            return sum(
                insert_rows(conn, table, columns, rows)
                for (table, columns), rows in zip(WATCHLIST_TABLES, tables, strict=True)
            )


class ApiData(Data):
    """Through the web API (api/app.py): the same SQL as DbData, sent over HTTPS. For Claude's
    cloud sessions, whose network only carries web traffic."""

    def __init__(self, url: str, key: str | None = None, client=None):
        import httpx

        headers = {"X-API-Key": key} if key else {}
        verify = os.environ.get("SSL_CERT_FILE") or ssl.create_default_context()
        self.client = client or httpx.Client(
            base_url=url.rstrip("/"), headers=headers, timeout=180, verify=verify
        )

    def _post(self, path: str, body: dict) -> dict:
        response = self.client.post(path, json=body)
        if response.status_code != 200:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"API {path} answered {response.status_code}: {detail}")
        return response.json()

    def query(self, sql: str, params: dict | None = None, limit: int = ROW_LIMIT) -> pd.DataFrame:
        answer = self._post("/query", {"sql": sql, "params": params or {}, "limit": limit})
        return pd.DataFrame(answer["rows"], columns=answer["columns"])

    def execute(self, steps: list[tuple[str, list[dict]]]) -> list[int]:
        """Write steps [(sql, rows), ...] in one transaction; returns the row count per step."""
        body = {"steps": [{"sql": sql, "rows": rows} for sql, rows in steps]}
        return self._post("/execute", body)["rowcounts"]

    def read(self, name: str, **params) -> pd.DataFrame:
        return self.query(READS[name], clean(params))

    def write_steps(self, steps: list[tuple[str, list[dict]]]) -> list[int]:
        return self.execute(steps)

    def sql(self, query: str, limit: int = ROW_LIMIT) -> pd.DataFrame:
        return self.query(query, limit=max(1, min(int(limit), ROW_LIMIT)))

    def _insert(self, table: str, columns: list[str], rows: list[dict]) -> int:
        sql, full = insert_sql(table, columns, rows)
        return sum(self.execute([(sql, full)])) if full else 0

    def save_note(self, subject: str, text: str) -> int:
        return self._insert(
            "out_note", ["subject", "updated_at", "text", "source"], [note_row(subject, text)]
        )

    def save_watchlist_run(self, row: dict) -> int:
        return self._insert("out_watchlist_run", WATCHLIST_RUN_COLUMNS, [row])

    def save_market_run(self, row: dict) -> int:
        return self._insert("out_market_run", MARKET_RUN_COLUMNS, [row])

    def save_valuations(self, rows: list[dict]) -> int:
        return self._insert("out_valuation", VALUATION_COLUMNS, rows)

    def set_watchlist(self, stocks: list[dict]) -> int:
        steps = [(f"DELETE FROM {t}", []) for t, _ in reversed(WATCHLIST_TABLES)]
        for (table, columns), rows in zip(WATCHLIST_TABLES, watchlist_rows(stocks), strict=True):
            if rows:
                steps.append(insert_sql(table, columns, rows))
        return sum(self.execute(steps)[len(WATCHLIST_TABLES) :])
