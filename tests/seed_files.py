"""Test seeding: load a folder laid out as the project's old data files (data/<SYMBOL>/,
data/screener/, data/sector/history.csv, analyses/, config/watchlist.toml) into a test
database, as `db load-files` did before the files were retired (issue #33). Makes no
network calls.

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
- analyses/<SYMBOL>/runs.csv (the watch list's evening runs) -> out_watchlist_run
- analyses/market/runs.csv (the market report's runs) -> out_market_run
- analyses/*/notes.md (Claude's notes; a new version when the text changes) -> out_note

The watch list itself (config/watchlist.toml, the master copy for now) is mirrored into the
user layer: user_watchlist, user_watchlist_peer, user_eps_override.

The other derived tables (absolute_*, history_yahoo.csv) are not imported.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection

from stock_analysis.db import ROOT, Database, frame, insert_df, records, run, scalar
from stock_analysis.db.raw import (
    PRICE_COLUMNS,
    STATEMENT_FILES,
    TV_COLUMNS,
    UNIVERSE,
    as_json,
    finish_fetch,
    now,
    store_changed,
)

SNAPSHOT = re.compile(r"^\d{4}-\d{2}-\d{2}\.csv$")


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


REPO_ROOT = ROOT  # the checkout being imported; load_all sets it (the API imports a download)


def repo_path(path: Path) -> str:
    for root in (REPO_ROOT, ROOT):
        try:
            return path.resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            continue
    return path.as_posix()


# ---------------------------------------------------------------- raw


def start_fetch(
    conn: Connection, source: str, request_key: str, path: Path, fetched_at: str
) -> int | None:
    """Log a file as a fetch; None if the same contents were loaded before."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    params = {"source": source, "key": request_key, "sha": sha}
    seen = scalar(
        conn,
        "SELECT fetch_id FROM raw_fetch "
        "WHERE source = :source AND request_key = :key AND payload_sha256 = :sha",
        params,
    )
    if seen:
        return None
    return scalar(
        conn,
        "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status, "
        "payload_sha256) VALUES (:source, :key, :url, :fetched_at, :loaded_at, 'ok', :sha) "
        "RETURNING fetch_id",
        {**params, "url": "file:" + repo_path(path), "fetched_at": fetched_at, "loaded_at": now()},
    )


def load_prices(conn: Connection, folder: Path) -> int:
    path = folder / "prices_daily.csv"
    if not path.exists():
        return 0
    symbol = folder.name
    fetch_id = start_fetch(conn, "yahoo_prices", symbol, path, meta_time(folder) or file_time(path))
    if fetch_id is None:
        return 0
    df = pd.read_csv(path).rename(columns=PRICE_COLUMNS)[list(PRICE_COLUMNS.values())]
    df["date"] = df["date"].astype(str).str[:10]
    df["volume"] = df["volume"].round().astype("Int64")
    df.insert(0, "symbol", symbol)
    values = ["open", "high", "low", "close", "volume", "dividends", "stock_splits"]
    stored = store_changed(conn, "raw_yahoo_price", df, ["symbol", "date"], values, fetch_id)
    finish_fetch(conn, fetch_id, len(df), stored)
    return stored


def load_statements(conn: Connection, folder: Path) -> int:
    symbol = folder.name
    total = 0
    for name, (statement, frequency) in STATEMENT_FILES.items():
        path = folder / name
        if not path.exists():
            continue
        fetch_id = start_fetch(
            conn, "yahoo_statements", symbol, path, meta_time(folder) or file_time(path)
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
            conn,
            "raw_yahoo_statement",
            long,
            ["symbol", "statement", "frequency", "period_end", "line_item"],
            ["value"],
            fetch_id,
        )
        finish_fetch(conn, fetch_id, len(long), stored)
        total += stored
    return total


def load_tradingview(conn: Connection, folder: Path) -> int:
    total = 0
    for path in sorted(p for p in folder.glob("*.csv") if SNAPSHOT.match(p.name)):
        # One snapshot per screener run day; the file name is the date.
        fetch_id = start_fetch(conn, "tradingview", UNIVERSE, path, path.stem)
        if fetch_id is None:
            continue
        df = pd.read_csv(path)
        out = df[list(TV_COLUMNS)].rename(columns=TV_COLUMNS)
        out["extra_json"] = as_json(df[[c for c in df.columns if c not in TV_COLUMNS]])
        out.insert(0, "fetch_id", fetch_id)
        insert_df(conn, "raw_tv_constituent", out)
        finish_fetch(conn, fetch_id, len(out), len(out))
        total += len(out)
    return total


def load_history(conn: Connection, path: Path) -> int:
    if not path.exists():
        return 0
    fetch_id = start_fetch(conn, "project_history", path.name, path, file_time(path))
    if fetch_id is None:
        return 0
    df = pd.read_csv(path).dropna(subset=["value"]).rename(columns={"column": "item"})
    df["fiscal_year_end"] = df["fiscal_year_end"].astype(str).str[:10]
    key = ["symbol", "fiscal_year_end", "item"]
    stored = sum(
        store_changed(conn, "raw_project_history", g, key, ["value", "source"], fetch_id)
        for _, g in df.groupby("symbol")
    )
    finish_fetch(conn, fetch_id, len(df), stored)
    return stored


# ---------------------------------------------------------------- out


def load_screener_run(conn: Connection, folder: Path) -> int:
    """The latest Stage 1 and Stage 2 results, as one run dated by top.csv."""
    stage1, top = folder / "stage1.csv", folder / "top.csv"
    if not stage1.exists() or not top.exists():
        return 0
    run_date = file_time(top)[:10]
    params = {"d": run_date, "u": UNIVERSE}
    if scalar(conn, "SELECT 1 FROM out_screener_run WHERE run_date = :d AND universe = :u", params):
        return 0
    run_id = scalar(
        conn,
        "INSERT INTO out_screener_run (run_date, universe, created_at, source) "
        "VALUES (:d, :u, :created, :source) RETURNING run_id",
        {**params, "created": now(), "source": f"file:{repo_path(stage1)}, file:{repo_path(top)}"},
    )
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
        total += insert_df(conn, "out_screener_result", out)
    return total


def load_valuations(conn: Connection, data_dir: Path) -> int:
    """DCF fair values from the sector and peer tables."""
    files = [data_dir / "sector" / "utilities.csv", *sorted((data_dir / "peers").glob("*.csv"))]
    before = scalar(conn, "SELECT COUNT(*) FROM out_valuation")
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
        if not out.empty:
            run(
                conn,
                "INSERT INTO out_valuation (symbol, as_of, method, fair_value, price, "
                "detail_json, source) VALUES (:symbol, :as_of, :method, :fair_value, :price, "
                ":detail_json, :source) ON CONFLICT DO NOTHING",
                records(out),
            )
    return scalar(conn, "SELECT COUNT(*) FROM out_valuation") - before


# ---------------------------------------------------------------- user (the watch list)


def load_watchlist(conn: Connection, path: Path) -> int:
    """Mirror config/watchlist.toml into the user tables; nothing changes if it is the same."""
    if not path.exists():
        return 0
    stocks = tomllib.loads(path.read_text(encoding="utf-8")).get("stock", [])
    w = pd.DataFrame(
        [
            {
                "symbol": st["symbol"],
                "position": i,
                "target_pe": st.get("target_pe"),
                "target_note": st.get("target_note"),
                "stakes_per_share": st.get("stakes_per_share"),
            }
            for i, st in enumerate(stocks, start=1)
        ],
        columns=["symbol", "position", "target_pe", "target_note", "stakes_per_share"],
    )
    peers = pd.DataFrame(
        [
            {"symbol": st["symbol"], "peer": peer, "position": i}
            for st in stocks
            for i, peer in enumerate(st.get("peers", []), start=1)
        ],
        columns=["symbol", "peer", "position"],
    )
    overrides = pd.DataFrame(
        [
            {"symbol": st["symbol"], "reported": str(o["reported"]), "eps": o["eps"],
             "reason": o.get("reason")}
            for st in stocks
            for o in st.get("eps_override", [])
        ],
        columns=["symbol", "reported", "eps", "reason"],
    )  # fmt: skip
    tables = {"user_watchlist": w, "user_watchlist_peer": peers, "user_eps_override": overrides}

    def norm(df: pd.DataFrame) -> list[tuple]:
        def value(v):
            if v is None or (not isinstance(v, str) and pd.isna(v)):
                return None
            return float(v) if isinstance(v, int | float | np.number) else str(v)

        return sorted((tuple(value(v) for v in r) for r in df.itertuples(index=False)), key=str)

    def same(table: str, new: pd.DataFrame) -> bool:
        old = frame(conn, f"SELECT {', '.join(new.columns)} FROM {table}")
        return norm(old) == norm(new)

    if all(same(t, df) for t, df in tables.items()):
        return 0
    for table in ("user_eps_override", "user_watchlist_peer", "user_watchlist"):
        run(conn, f"DELETE FROM {table}")
    return sum(insert_df(conn, t, df) for t, df in tables.items())


def load_watchlist_runs(conn: Connection, analyses_dir: Path, timezone: str) -> int:
    """Every row of analyses/<SYMBOL>/runs.csv for the watch list stocks (the market and
    summary folders have other columns and are left out)."""
    before = scalar(conn, "SELECT COUNT(*) FROM out_watchlist_run")
    cols = ["file", "price", "eps_adj_ttm", "pe_adj", "pe_median_10y", "target_pe"]
    cols += ["entry_price", "to_entry", "verdict", "stakes_per_share"]
    for path in sorted(analyses_dir.glob("*/runs.csv")):
        df = pd.read_csv(path)
        if "entry_price" not in df:
            continue
        local = pd.to_datetime(df["run"].str[:16])  # 'YYYY-MM-DD HH:MM CET' in Rome time
        utc = local.dt.tz_localize(ZoneInfo(timezone), ambiguous="NaT").dt.tz_convert("UTC")
        out = df.reindex(columns=cols).assign(
            symbol=path.parent.name, run_at=utc.dt.strftime("%Y-%m-%dT%H:%M:%S")
        )
        out = out.dropna(subset=["run_at"]).drop_duplicates(["symbol", "run_at"])
        names = ["symbol", "run_at", *cols]
        if not out.empty:
            run(
                conn,
                f"INSERT INTO out_watchlist_run ({', '.join(names)}) "
                f"VALUES ({', '.join(':' + c for c in names)}) ON CONFLICT DO NOTHING",
                records(out[names]),
            )
    return scalar(conn, "SELECT COUNT(*) FROM out_watchlist_run") - before


def rome_to_utc(values: pd.Series, timezone: str) -> pd.Series:
    """'YYYY-MM-DD HH:MM CET' (local time) as UTC 'YYYY-MM-DDTHH:MM:SS'."""
    local = pd.to_datetime(values.str[:16])
    utc = local.dt.tz_localize(ZoneInfo(timezone), ambiguous="NaT").dt.tz_convert("UTC")
    return utc.dt.strftime("%Y-%m-%dT%H:%M:%S")


def load_market_runs(conn: Connection, path: Path, timezone: str) -> int:
    """Every row of analyses/market/runs.csv."""
    if not path.exists():
        return 0
    df = pd.read_csv(path)
    cols = ["file", "sp500", "sp500_day", "vix", "above_200d", "stocks_to_look_at"]
    cols += ["screener_date", "screener_passed", "screener_screened", "screener_listed"]
    out = df.reindex(columns=cols).assign(run_at=rome_to_utc(df["run"], timezone))
    for col in ("screener_passed", "screener_screened", "screener_listed"):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("Int64")
    out["screener_date"] = out["screener_date"].where(out["screener_date"].notna(), None)
    out = out.dropna(subset=["run_at"]).drop_duplicates("run_at")
    names = ["run_at", *cols]
    before = scalar(conn, "SELECT COUNT(*) FROM out_market_run")
    if not out.empty:
        run(
            conn,
            f"INSERT INTO out_market_run ({', '.join(names)}) "
            f"VALUES ({', '.join(':' + c for c in names)}) ON CONFLICT DO NOTHING",
            records(out[names]),
        )
    return scalar(conn, "SELECT COUNT(*) FROM out_market_run") - before


def load_notes(conn: Connection, analyses_dir: Path) -> int:
    """analyses/<SUBJECT>/notes.md: a new version whenever the text differs from the latest."""
    added = 0
    for path in sorted(analyses_dir.glob("*/notes.md")):
        subject, text = path.parent.name, path.read_text(encoding="utf-8")
        latest = scalar(
            conn,
            "SELECT text FROM v_note_latest WHERE subject = :s",
            {"s": subject},
        )
        if latest == text:
            continue
        run(
            conn,
            "INSERT INTO out_note (subject, updated_at, text, source) "
            "VALUES (:s, :t, :text, :src) ON CONFLICT DO NOTHING",
            {
                "s": subject,
                "t": file_time(path)[:19],
                "text": text,
                "src": "file:" + repo_path(path),
            },
        )
        added += 1
    return added


def load_all(db: Database, data_dir: Path | None = None) -> dict[str, int]:
    """Import every file under `data_dir` (default data/) plus the watch list (config/ and
    analyses/ next to it), in one transaction. Returns the rows added per table."""
    global REPO_ROOT
    data_dir = Path(data_dir) if data_dir else ROOT / "data"
    root = REPO_ROOT = data_dir.parent
    watchlist = root / "config" / "watchlist.toml"
    timezone = "Europe/Rome"
    if watchlist.exists():
        timezone = tomllib.loads(watchlist.read_text(encoding="utf-8")).get("timezone", timezone)
    added = dict.fromkeys(
        [
            "raw_yahoo_price",
            "raw_yahoo_statement",
            "raw_tv_constituent",
            "raw_project_history",
            "out_screener_result",
            "out_valuation",
            "user_watchlist",
            "out_watchlist_run",
            "out_market_run",
            "out_note",
        ],
        0,
    )
    with db.begin() as conn:
        for folder in sorted(p for p in data_dir.iterdir() if p.is_dir()):
            if (folder / "prices_daily.csv").exists() or (folder / "income_annual.csv").exists():
                added["raw_yahoo_price"] += load_prices(conn, folder)
                added["raw_yahoo_statement"] += load_statements(conn, folder)
        screener = data_dir / "screener"
        if screener.is_dir():
            added["raw_tv_constituent"] += load_tradingview(conn, screener)
            added["out_screener_result"] += load_screener_run(conn, screener)
        added["raw_project_history"] += load_history(conn, data_dir / "sector" / "history.csv")
        added["out_valuation"] += load_valuations(conn, data_dir)
        added["user_watchlist"] += load_watchlist(conn, watchlist)
        added["out_watchlist_run"] += load_watchlist_runs(conn, root / "analyses", timezone)
        added["out_market_run"] += load_market_runs(
            conn, root / "analyses" / "market" / "runs.csv", timezone
        )
        added["out_note"] += load_notes(conn, root / "analyses")
    return added
