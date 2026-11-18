"""The project database, on PostgreSQL: a raw layer per source, a cleaned core layer, the
user's choices (the watch list) and the analyses' results (docs/DATABASE.md).

Which database: `config/database.toml` names the targets (`local` = PostgreSQL in Docker on
this machine, `server` = the Oracle Cloud server) and the selected one; `--target` or the
DATABASE_URL environment variable overrides it. Passwords come only from the environment
(.env is read). The tables come from the numbered SQL files in `migrations/`;
`schema_version` records which have been applied, and opening a database applies new ones.

    python -m stock_analysis.db init         create the tables (apply the migrations)
    python -m stock_analysis.db load-files   import the data already in data/ (no network)
    python -m stock_analysis.db build        rebuild the core layer from raw
    python -m stock_analysis.db status       rows per table
    python -m stock_analysis.db check        connection, schema and data present
"""

from __future__ import annotations

import datetime as dt
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

from . import tunnel

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = Path(__file__).with_name("migrations")
CONFIG = ROOT / "config" / "database.toml"
DEFAULT_URL = "postgresql://stock@127.0.0.1:5432/stock"


# ---------------------------------------------------------------- targets


def load_config(path: Path = CONFIG) -> dict:
    if not Path(path).exists():
        return {"selected": "local", "targets": {"local": {"url": DEFAULT_URL}}}
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def target_settings(target: str | None = None, config: dict | None = None) -> dict:
    """The url (and password_env) of a target: --target, else DATABASE_URL, else
    STOCK_DB_TARGET, else `selected` in config/database.toml."""
    config = config or load_config()
    if target is None and os.environ.get("DATABASE_URL"):
        check_url(os.environ["DATABASE_URL"])
        return {"name": "DATABASE_URL", "url": os.environ["DATABASE_URL"]}
    # STOCK_DB_TARGET picks the default target per machine (e.g. server-writer in Claude's
    # cloud environment) without editing the config.
    name = target or os.environ.get("STOCK_DB_TARGET") or config.get("selected", "local")
    targets = config.get("targets", {})
    if name not in targets:
        raise ValueError(f"No target {name!r} in config/database.toml (have: {', '.join(targets)})")
    settings = {"name": name, **targets[name]}
    if not settings.get("url"):
        raise ValueError(f"Target {name!r} has no url in config/database.toml yet")
    check_url(settings["url"])
    return settings


def check_url(url: str) -> None:
    if not url.startswith(("postgresql://", "postgres://")):
        raise ValueError(f"Only PostgreSQL URLs are supported, not {url.split(':')[0]}")


def hide_password(url: str) -> str:
    return re.sub(r"//([^:@/]+):[^@/]*@", r"//\1:***@", url)


# ---------------------------------------------------------------- the database


class Database:
    """One PostgreSQL database, opened through SQLAlchemy and psycopg."""

    def __init__(self, url: str, password: str | None = None, read_only: bool = False):
        check_url(url)
        self.url = url
        self.where = hide_password(url)
        self.target = "url"
        args: dict = {"connect_timeout": 10}
        if password:
            args["password"] = password
        if read_only:
            args["options"] = "-c default_transaction_read_only=on"
        parsed = urlparse(url)
        self.local_port = tunnel.route(parsed.hostname or "", parsed.port or 5432)
        if self.local_port:  # through the HTTP proxy; TLS still checks the real host name
            args.update(hostaddr="127.0.0.1", port=str(self.local_port))
        sa_url = re.sub(r"^postgres(ql)?://", "postgresql+psycopg://", url)
        self.engine: Engine = create_engine(sa_url, connect_args=args, pool_pre_ping=True)

    @classmethod
    def open(cls, target: str | None = None, read_only: bool = False) -> Database:
        """The database of a target in config/database.toml, migrated unless read-only."""
        load_dotenv(ROOT / ".env")
        settings = target_settings(target)
        env = settings.get("password_env")
        db = cls(settings["url"], os.environ.get(env) if env else None, read_only)
        db.target = settings["name"]
        if not read_only:
            db.migrate()
        return db

    def begin(self):
        """A transaction: `with db.begin() as conn:` commits at the end, rolls back on error."""
        return self.engine.begin()

    def connect(self):
        return self.engine.connect()

    def objects(self) -> set[str]:
        """Names of the tables and views."""
        insp = inspect(self.engine)
        return set(insp.get_table_names()) | set(insp.get_view_names())

    def schema_version(self) -> int:
        tables = set(inspect(self.engine).get_table_names())
        if "schema_version" not in tables:
            if "raw_fetch" in tables:
                raise RuntimeError(
                    "This database predates the migrations. Empty it and run init, "
                    "load-files and build again (everything in it comes from data/)."
                )
            return 0
        with self.connect() as conn:
            return scalar(conn, "SELECT COALESCE(MAX(version), 0) FROM schema_version")

    def migrate(self) -> int:
        current = self.schema_version()
        for version, path in migrations():
            if version > current:
                with self.begin() as conn:
                    for statement in statements(path.read_text(encoding="utf-8")):
                        conn.exec_driver_sql(statement)
                    run(
                        conn,
                        "INSERT INTO schema_version (version, applied_at) VALUES (:v, :t)",
                        {"v": version, "t": dt.datetime.now(dt.UTC).isoformat(timespec="seconds")},
                    )
                current = version
        return current

    def table_counts(self) -> dict[str, int]:
        names = sorted(inspect(self.engine).get_table_names())
        with self.connect() as conn:
            return {n: scalar(conn, f"SELECT COUNT(*) FROM {n}") for n in names}

    def close(self) -> None:
        self.engine.dispose()


def migrations() -> list[tuple[int, Path]]:
    return sorted((int(p.name[:3]), p) for p in MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))


def statements(sql: str) -> list[str]:
    """Split a migration into statements (comments removed; no ';' inside strings)."""
    no_comments = "\n".join(line.split("--")[0] for line in sql.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


# ---------------------------------------------------------------- helpers for the loaders


def run(conn: Connection, sql: str, params=None):
    """Execute SQL with :named parameters (a dict, or a list of dicts for many rows)."""
    return conn.execute(text(sql), params if params is not None else {})


def scalar(conn: Connection, sql: str, params: dict | None = None):
    return run(conn, sql, params).scalar()


def iso(value):
    """Dates as 'YYYY-MM-DD' and timestamps as ISO text; anything else unchanged."""
    if isinstance(value, dt.datetime | pd.Timestamp):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def frame(conn: Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    """A query as a DataFrame, with dates and timestamps as ISO text (the build compares
    them as text)."""
    df = pd.read_sql(text(sql), conn, params=params or {})
    for col in df.columns:
        s = df[col]
        if pd.api.types.is_datetime64_any_dtype(s):
            df[col] = s.map(lambda x: x.isoformat() if pd.notna(x) else None)
        elif s.dtype == object:
            first = s.dropna().head(1)
            if len(first) and isinstance(first.iloc[0], dt.date):
                df[col] = s.map(lambda x: iso(x) if x is not None else None)
    return df


def records(df: pd.DataFrame) -> list[dict]:
    """Rows as dicts of plain Python values, with None for missing."""
    obj = df.astype(object)
    obj = obj.where(pd.notna(obj), None)
    return obj.to_dict("records")


def insert_df(conn: Connection, table: str, df: pd.DataFrame, chunk: int = 20_000) -> int:
    """Insert every row, `chunk` rows at a time, so a large table (1.3 million prices) never
    exists as one list of Python dicts."""
    if df.empty:
        return 0
    cols = list(df.columns)
    raw = getattr(conn.connection, "driver_connection", None)
    if raw is not None and hasattr(raw, "cursor") and type(raw).__module__.startswith("psycopg"):
        # COPY: several times faster than INSERT for the build's millions of rows.
        with raw.cursor() as cur, cur.copy(f"COPY {table} ({', '.join(cols)}) FROM STDIN") as cp:
            for start in range(0, len(df), chunk):
                obj = df.iloc[start : start + chunk].astype(object)
                for row in obj.where(pd.notna(obj), None).itertuples(index=False, name=None):
                    cp.write_row(row)
        return len(df)
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"
    for start in range(0, len(df), chunk):
        run(conn, sql, records(df.iloc[start : start + chunk]))
    return len(df)
