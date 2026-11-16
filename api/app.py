"""The smallest possible web API in front of the database, to test access from Claude's
cloud sessions (they can only reach the internet over HTTPS, not PostgreSQL directly).

    GET /health                      no key; says the app is up
    GET /annual/{symbol}             the latest row of v_annual for one company

Every request except /health needs the header `X-API-Key: <STOCK_API_KEY>`. The app reads the
database as `stock_reader` (DATABASE_URL, password included, set as an app setting on Azure).
No dependency on the rest of the repository, so it deploys as this folder alone.
"""

from __future__ import annotations

import datetime as dt
import decimal
import hmac
import os

import psycopg
from fastapi import FastAPI, Header, HTTPException
from psycopg.rows import dict_row

app = FastAPI(title="stock-api", docs_url=None, redoc_url=None, openapi_url=None)


def check_key(key: str | None) -> None:
    expected = os.environ.get("STOCK_API_KEY", "")
    if not expected or not key or not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=401, detail="missing or wrong X-API-Key")


def plain(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, dt.date | dt.datetime):
        return value.isoformat()
    return value


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/annual/{symbol}")
def annual(symbol: str, x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    with psycopg.connect(
        os.environ["DATABASE_URL"],
        connect_timeout=10,
        options="-c default_transaction_read_only=on",
        row_factory=dict_row,
    ) as conn:
        row = conn.execute(
            "SELECT * FROM v_annual WHERE symbol = %s ORDER BY fiscal_year DESC LIMIT 1",
            (symbol.upper(),),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"no annual data for {symbol.upper()}")
    return {k: plain(v) for k, v in row.items()}
