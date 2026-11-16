"""One way for every script, and for Claude, to read and write the project's data: straight
from the PostgreSQL database (reads as stock_reader, writes as stock_writer).

    from stock_analysis.data import Data

    data = Data.open()                     # picks the backend (see below)
    data.watchlist()                       # DataFrame
    data.annual("NEE")
    data.daily("NEE", start="2025-01-01")
    data.sql("SELECT symbol, revenue FROM v_annual WHERE fiscal_year = 2025")
    data.save_note("NFLX", "## Thesis ...")

The targets come from config/database.toml: STOCK_DATA_TARGET (default server-reader) for
reads and STOCK_DATA_WRITE_TARGET (default server-writer) for writes. Every method returns a
DataFrame with dates as ISO text.
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd

from .db import ROOT, Database, frame, records, run

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
    def open(read_target: str | None = None, write_target: str | None = None) -> DbData:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
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


def insert_rows(conn, table: str, columns: list[str], rows: list[dict]) -> int:
    """Insert the given columns of each row; existing keys are left alone."""
    unknown = {k for r in rows for k in r} - set(columns)
    if unknown:
        raise ValueError(f"Unknown fields for {table}: {', '.join(sorted(unknown))}")
    if not rows:
        return 0
    full = [{c: r.get(c) for c in columns} for r in rows]
    res = run(
        conn,
        f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
        f"({', '.join(':' + c for c in columns)}) ON CONFLICT DO NOTHING",
        full,
    )
    return res.rowcount if res.rowcount is not None and res.rowcount >= 0 else len(full)


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
                [{"subject": subject, "updated_at": now_utc(), "text": text, "source": "script"}],
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

    def set_watchlist(self, stocks: list[dict]) -> int:
        """Replace the watch list: [{symbol, target_pe, target_note, stakes_per_share,
        peers: [...], eps_override: [{reported, eps, reason}]}]."""
        w = pd.DataFrame(
            [
                {
                    "symbol": s["symbol"],
                    "position": i,
                    "target_pe": s.get("target_pe"),
                    "target_note": s.get("target_note"),
                    "stakes_per_share": s.get("stakes_per_share"),
                }
                for i, s in enumerate(stocks, start=1)
            ]
        )
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
        with self.writer.begin() as conn:
            for table in ("user_eps_override", "user_watchlist_peer", "user_watchlist"):
                run(conn, f"DELETE FROM {table}")
            n = insert_rows(conn, "user_watchlist", list(w.columns), records(w))
            n += insert_rows(conn, "user_watchlist_peer", ["symbol", "peer", "position"], peers)
            n += insert_rows(
                conn, "user_eps_override", ["symbol", "reported", "eps", "reason"], overrides
            )
        return n
