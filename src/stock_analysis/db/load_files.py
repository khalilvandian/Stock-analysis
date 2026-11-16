"""Import the data files already in the repository. Makes no network calls.

Source data goes into the raw layer. Each file is one row in raw_fetch (the file as `url`, when
its data was fetched, a SHA-256 of its contents). A file loaded before with the same contents
is skipped, and only rows that are new or changed are stored, so rerunning is safe and a
changed file adds just its differences.

- data/<SYMBOL>/prices_daily.csv               -> raw_yahoo_price
- data/<SYMBOL>/{income,balance_sheet,cash_flow}_{annual,quarterly}.csv -> raw_yahoo_statement
- data/screener/YYYY-MM-DD.csv (TradingView, S&P 500) -> raw_tv_constituent
- data/sector/history.csv (SEC-based yearly history) -> raw_project_history

Analysis results go into the out layer:

- data/screener/stage1.csv and top.csv (the latest screener run) -> out_screener_*
- dcf_fair_value in data/sector/utilities.csv and data/peers/*.csv -> out_valuation

The other derived tables (absolute_*, history_yahoo.csv) are not imported.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from . import ROOT

STATEMENT_FILES = {
    f"{statement}_{frequency}.csv": (statement, frequency)
    for statement in ("income", "balance_sheet", "cash_flow")
    for frequency in ("annual", "quarterly")
}
PRICE_COLUMNS = {
    "date": "date",
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
SNAPSHOT = re.compile(r"^\d{4}-\d{2}-\d{2}\.csv$")
UNIVERSE = "SP:SPX"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def rows(df: pd.DataFrame) -> list[tuple]:
    """Plain Python values with None for missing, as the database driver needs."""
    obj = df.astype(object)
    return [tuple(r) for r in obj.where(pd.notna(obj), None).itertuples(index=False)]


def as_json(df: pd.DataFrame) -> list[str]:
    obj = df.astype(object)
    obj = obj.where(pd.notna(obj), None)
    return [json.dumps(r, default=str) for r in obj.to_dict("records")]


def file_time(path: Path) -> str:
    """When a file's data was produced: its last git commit, else its modification time."""
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    if out:
        return datetime.fromisoformat(out).astimezone(UTC).isoformat(timespec="seconds")
    return datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")


def meta_time(folder: Path) -> str | None:
    meta = folder / "_meta.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8")).get("fetched_at")
    return None


def repo_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------- raw


def start_fetch(
    con: sqlite3.Connection, source: str, request_key: str, path: Path, fetched_at: str
) -> int | None:
    """Log a file as a fetch; None if the same contents were loaded before."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    seen = con.execute(
        "SELECT fetch_id FROM raw_fetch "
        "WHERE source = ? AND request_key = ? AND payload_sha256 = ?",
        (source, request_key, sha),
    ).fetchone()
    if seen:
        return None
    cur = con.execute(
        "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status, "
        "payload_sha256) VALUES (?, ?, ?, ?, ?, 'ok', ?)",
        (source, request_key, "file:" + repo_path(path), fetched_at, now(), sha),
    )
    return cur.lastrowid


def finish_fetch(con: sqlite3.Connection, fetch_id: int, received: int, stored: int) -> None:
    con.execute(
        "UPDATE raw_fetch SET row_count = ?, rows_stored = ?, status = ? WHERE fetch_id = ?",
        (received, stored, "ok" if received else "empty", fetch_id),
    )


def store_changed(
    con: sqlite3.Connection,
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
    old = pd.read_sql(
        f"SELECT {', '.join(cols)} FROM {table} WHERE {key[0]} = ? ORDER BY fetch_id",
        con,
        params=[df[key[0]].iloc[0]],
    ).drop_duplicates(key, keep="last")
    new = df[cols].copy()
    if not old.empty:
        for k in key:  # match types (dates come back as text)
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
    if new.empty:
        return 0
    new.insert(0, "fetch_id", fetch_id)
    con.executemany(
        f"INSERT INTO {table} (fetch_id, {', '.join(cols)}) "
        f"VALUES ({', '.join('?' * (len(cols) + 1))})",
        rows(new),
    )
    return len(new)


def load_prices(con: sqlite3.Connection, folder: Path) -> int:
    path = folder / "prices_daily.csv"
    if not path.exists():
        return 0
    symbol = folder.name
    fetch_id = start_fetch(con, "yahoo_prices", symbol, path, meta_time(folder) or file_time(path))
    if fetch_id is None:
        return 0
    df = pd.read_csv(path).rename(columns=PRICE_COLUMNS)[list(PRICE_COLUMNS.values())]
    df["date"] = df["date"].astype(str).str[:10]
    df["volume"] = df["volume"].round().astype("Int64")
    df.insert(0, "symbol", symbol)
    stored = store_changed(
        con,
        "raw_yahoo_price",
        df,
        ["symbol", "date"],
        ["close", "volume", "dividends", "stock_splits"],
        fetch_id,
    )
    finish_fetch(con, fetch_id, len(df), stored)
    return stored


def load_statements(con: sqlite3.Connection, folder: Path) -> int:
    symbol = folder.name
    total = 0
    for name, (statement, frequency) in STATEMENT_FILES.items():
        path = folder / name
        if not path.exists():
            continue
        fetch_id = start_fetch(
            con, "yahoo_statements", symbol, path, meta_time(folder) or file_time(path)
        )
        if fetch_id is None:
            continue
        wide = pd.read_csv(path, index_col=0)
        wide.index = wide.index.astype(str).str[:10]
        long = (
            wide.rename_axis("period_end")
            .reset_index()
            .melt(id_vars="period_end", var_name="line_item", value_name="value")
            .dropna(subset=["value"])
        )
        long = long.assign(symbol=symbol, statement=statement, frequency=frequency)
        stored = store_changed(
            con,
            "raw_yahoo_statement",
            long,
            ["symbol", "statement", "frequency", "period_end", "line_item"],
            ["value"],
            fetch_id,
        )
        finish_fetch(con, fetch_id, len(long), stored)
        total += stored
    return total


def load_tradingview(con: sqlite3.Connection, folder: Path) -> int:
    total = 0
    for path in sorted(p for p in folder.glob("*.csv") if SNAPSHOT.match(p.name)):
        # One snapshot per screener run day; the file name is the date.
        fetch_id = start_fetch(con, "tradingview", UNIVERSE, path, path.stem)
        if fetch_id is None:
            continue
        df = pd.read_csv(path)
        out = df[list(TV_COLUMNS)].rename(columns=TV_COLUMNS)
        out["extra_json"] = as_json(df[[c for c in df.columns if c not in TV_COLUMNS]])
        out.insert(0, "fetch_id", fetch_id)
        con.executemany(
            "INSERT INTO raw_tv_constituent (fetch_id, tv_symbol, symbol, name, exchange, sector, "
            "industry, country, currency, market_cap, extra_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows(out),
        )
        finish_fetch(con, fetch_id, len(out), len(out))
        total += len(out)
    return total


def load_history(con: sqlite3.Connection, path: Path) -> int:
    if not path.exists():
        return 0
    fetch_id = start_fetch(con, "project_history", path.name, path, file_time(path))
    if fetch_id is None:
        return 0
    df = pd.read_csv(path).dropna(subset=["value"]).rename(columns={"column": "item"})
    df["fiscal_year_end"] = df["fiscal_year_end"].astype(str).str[:10]
    stored = 0
    for _, g in df.groupby("symbol"):
        stored += store_changed(
            con,
            "raw_project_history",
            g,
            ["symbol", "fiscal_year_end", "item"],
            ["value", "source"],
            fetch_id,
        )
    finish_fetch(con, fetch_id, len(df), stored)
    return stored


# ---------------------------------------------------------------- out


def load_screener_run(con: sqlite3.Connection, folder: Path) -> int:
    """The latest Stage 1 and Stage 2 results, as one run dated by top.csv."""
    stage1, top = folder / "stage1.csv", folder / "top.csv"
    if not stage1.exists() or not top.exists():
        return 0
    run_date = file_time(top)[:10]
    if con.execute(
        "SELECT 1 FROM out_screener_run WHERE run_date = ? AND universe = ?",
        (run_date, UNIVERSE),
    ).fetchone():
        return 0
    run_id = con.execute(
        "INSERT INTO out_screener_run (run_date, universe, created_at, source) VALUES (?, ?, ?, ?)",
        (run_date, UNIVERSE, now(), f"file:{repo_path(stage1)}, file:{repo_path(top)}"),
    ).lastrowid
    main = ["sector", "category", "status", "rank_in_sector", "close", "cheap_price"]
    total = 0
    for stage, path in ((1, stage1), (2, top)):
        df = pd.read_csv(path)
        df["symbol"] = df["tv_symbol"].str.split(":").str[-1]
        for col in main:
            if col not in df:
                df[col] = None
        out = df[["symbol", *main]].copy()
        out["rank_in_sector"] = pd.to_numeric(out["rank_in_sector"]).astype("Int64")
        out["detail_json"] = as_json(df[[c for c in df.columns if c not in {"symbol", *main}]])
        out = out.drop_duplicates("symbol")
        out.insert(0, "stage", stage)
        out.insert(0, "run_id", run_id)
        con.executemany(
            "INSERT INTO out_screener_result (run_id, stage, symbol, sector, category, status, "
            "rank_in_sector, close, cheap_price, detail_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows(out),
        )
        total += len(out)
    return total


def load_valuations(con: sqlite3.Connection, data_dir: Path) -> int:
    """DCF fair values from the sector and peer tables."""
    files = [data_dir / "sector" / "utilities.csv", *sorted((data_dir / "peers").glob("*.csv"))]
    total = 0
    for path in files:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        if "dcf_fair_value" not in df:
            continue
        df = df.dropna(subset=["dcf_fair_value"])
        as_of = (meta_time(path.parent) or file_time(path))[:10]
        detail = [c for c in ("wacc", "fcff_before_growth", "price_vs_fair_value") if c in df]
        out = pd.DataFrame(
            {
                "symbol": df["symbol"],
                "as_of": as_of,
                "method": df["dcf_method"].fillna("dcf") if "dcf_method" in df else "dcf",
                "fair_value": df["dcf_fair_value"],
                "price": df["price"] if "price" in df else None,
                "detail_json": as_json(df[detail]),
                "source": "file:" + repo_path(path),
            }
        ).drop_duplicates(["symbol", "as_of", "method"])
        before = con.total_changes
        con.executemany(
            "INSERT INTO out_valuation (symbol, as_of, method, fair_value, price, detail_json, "
            "source) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
            rows(out),
        )
        total += con.total_changes - before
    return total


def load_all(con: sqlite3.Connection, data_dir: Path | None = None) -> dict[str, int]:
    """Import every file under `data_dir` (default data/). Returns rows added per table."""
    data_dir = Path(data_dir) if data_dir else ROOT / "data"
    added = dict.fromkeys(
        [
            "raw_yahoo_price",
            "raw_yahoo_statement",
            "raw_tv_constituent",
            "raw_project_history",
            "out_screener_result",
            "out_valuation",
        ],
        0,
    )
    with con:
        for folder in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            if (folder / "prices_daily.csv").exists() or (folder / "income_annual.csv").exists():
                added["raw_yahoo_price"] += load_prices(con, folder)
                added["raw_yahoo_statement"] += load_statements(con, folder)
        screener = data_dir / "screener"
        if screener.is_dir():
            added["raw_tv_constituent"] += load_tradingview(con, screener)
            added["out_screener_result"] += load_screener_run(con, screener)
        added["raw_project_history"] += load_history(con, data_dir / "sector" / "history.csv")
        added["out_valuation"] += load_valuations(con, data_dir)
    return added
