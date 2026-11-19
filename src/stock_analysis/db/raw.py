"""Helpers for writing the raw layer, shared by the ingest's loaders (ingest/*.py): the
column names of the sources, and storing only the rows that are new or changed."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection

from . import frame, insert_df, run

UNIVERSE = "SP:SPX"
STATEMENT_FILES = {
    f"{statement}_{frequency}.csv": (statement, frequency)
    for statement in ("income", "balance_sheet", "cash_flow")
    for frequency in ("annual", "quarterly")
}
PRICE_COLUMNS = {
    "date": "date",
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "stock_splits",
}
TV_COLUMNS = {
    "tv_symbol": "tv_symbol",
    "name": "symbol",
    "description": "name",
    "exchange": "exchange",
    "sector": "sector",
    "industry": "industry",
    "country": "country",
    "currency": "currency",
    "market_cap_basic": "market_cap",
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def as_json(df: pd.DataFrame) -> list[str]:
    obj = df.astype(object)
    obj = obj.where(pd.notna(obj), None)
    return [json.dumps(r, default=str) for r in obj.to_dict("records")]


def finish_fetch(conn: Connection, fetch_id: int, received: int, stored: int) -> None:
    run(
        conn,
        "UPDATE raw_fetch SET row_count = :n, rows_stored = :s, status = :status "
        "WHERE fetch_id = :id",
        {"n": received, "s": stored, "status": "ok" if received else "empty", "id": fetch_id},
    )


def store_changed(
    conn: Connection,
    table: str,
    df: pd.DataFrame,
    key: list[str],
    values: list[str],
    fetch_id: int,
) -> int:
    """Insert the rows of `df` that are new, or whose values differ from the latest stored
    version of the same key. All rows of `df` share key[0] (the symbol)."""
    if df.empty:
        return 0
    cols = key + values
    old = frame(
        conn,
        f"SELECT {', '.join(cols)} FROM {table} WHERE {key[0]} = :k ORDER BY fetch_id",
        {"k": df[key[0]].iloc[0]},
    ).drop_duplicates(key, keep="last")
    new = df[cols].copy()
    if not old.empty:
        for k in key:  # compare keys as text (dates)
            old[k] = old[k].astype(str)
            new[k] = new[k].astype(str)
        both = new.merge(old, on=key, how="left", suffixes=("", "_old"), indicator=True)
        changed = (both["_merge"] == "left_only").to_numpy().copy()
        for v in values:
            a, b = both[v], both[f"{v}_old"]
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                same = np.isclose(
                    a.astype(float), b.astype(float), rtol=1e-12, atol=0, equal_nan=True
                )
            else:
                same = ((a == b) | (a.isna() & b.isna())).to_numpy()
            changed = changed | ~np.asarray(same, dtype=bool)
        new = new[changed]
    new.insert(0, "fetch_id", fetch_id)
    return insert_df(conn, table, new)
