"""A small, general web API in front of the database, for Claude's cloud sessions (they can only
reach the internet over HTTPS, not PostgreSQL directly). Not one route per question: any SQL,
with the database users' rights deciding what is allowed.

    GET  /health    no key; says the app is up
    POST /query     {"sql": "SELECT ...", "params": {...}, "limit": 50000}
                    one SELECT or WITH statement, run as stock_reader in a read-only
                    transaction (30 s limit). Answer: {"columns", "rows", "truncated"}
    POST /execute   {"steps": [{"sql": "INSERT ...", "rows": [{...}, ...]}, ...]}
                    write statements run as stock_writer, all steps in one transaction (all or
                    nothing); each step runs once per row, or once if it has no rows.
                    Answer: {"rowcounts": [...]}

Parameters use :name placeholders (SQLAlchemy style). Every route but /health needs the header
`X-API-Key: <STOCK_API_KEY>`. App settings: DATABASE_URL (stock_reader), DATABASE_WRITER_URL
(stock_writer), STOCK_API_KEY. stock_writer can't change the schema, can't touch
schema_version and can't change or delete raw data, so neither can this API.
No dependency on the rest of the repository, so it deploys as this folder alone.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hmac
import os
import re
from functools import cache

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, StatementError

MAX_ROWS = 50_000
QUERY_TIMEOUT_S = 30
EXECUTE_TIMEOUT_S = 120
READ_START = ("select", "with")
WRITE_START = ("insert", "update", "delete", "with", "merge")

app = FastAPI(title="stock-api", docs_url=None, redoc_url=None, openapi_url=None)


class Query(BaseModel):
    sql: str
    params: dict = Field(default_factory=dict)
    limit: int = MAX_ROWS


class Step(BaseModel):
    sql: str
    rows: list[dict] = Field(default_factory=list)


class Execute(BaseModel):
    steps: list[Step]


@cache
def engine(setting: str) -> Engine:
    url = re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", os.environ[setting])
    return create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=2,
                         connect_args={"connect_timeout": 10})  # fmt: skip


def check_key(key: str | None) -> None:
    expected = os.environ.get("STOCK_API_KEY", "")
    if not expected or not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="missing or wrong X-API-Key")


def one_statement(sql: str, allowed: tuple[str, ...]) -> str:
    statement = sql.strip().rstrip(";").strip()
    if not statement:
        raise HTTPException(status_code=400, detail="empty SQL")
    if ";" in statement:
        raise HTTPException(status_code=400, detail="one statement per query or step")
    if statement.split(None, 1)[0].lower() not in allowed:
        raise HTTPException(status_code=400, detail=f"must start with {' / '.join(allowed)}")
    return statement


def plain(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime | dt.time):
        return value.isoformat()
    return value


def database_error(exc: Exception) -> HTTPException:
    message = str(getattr(exc, "orig", exc)).strip().split("\n")[0]
    return HTTPException(status_code=400, detail=f"database: {message}"[:500])


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.post("/query")
def query(body: Query, x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    statement = one_statement(body.sql, READ_START)
    limit = max(1, min(body.limit, MAX_ROWS))
    try:
        with engine("DATABASE_URL").connect() as conn, conn.begin() as trans:
            conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{QUERY_TIMEOUT_S}s'")
            result = conn.execute(text(statement), body.params)
            columns = list(result.keys())
            rows = [[plain(v) for v in row] for row in result.fetchmany(limit + 1)]
            trans.rollback()
    except (DBAPIError, StatementError) as exc:
        raise database_error(exc) from exc
    return {"columns": columns, "rows": rows[:limit], "truncated": len(rows) > limit}


@app.post("/execute")
def execute(body: Execute, x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    if not body.steps:
        raise HTTPException(status_code=400, detail="no steps")
    statements = [one_statement(step.sql, WRITE_START) for step in body.steps]
    counts = []
    try:
        with engine("DATABASE_WRITER_URL").begin() as conn:
            conn.exec_driver_sql(f"SET LOCAL statement_timeout = '{EXECUTE_TIMEOUT_S}s'")
            for statement, step in zip(statements, body.steps, strict=True):
                result = conn.execute(text(statement), step.rows or {})
                counts.append(result.rowcount if result.rowcount is not None else -1)
    except (DBAPIError, StatementError) as exc:
        raise database_error(exc) from exc
    return {"rowcounts": counts}
