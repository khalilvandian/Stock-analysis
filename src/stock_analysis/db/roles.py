"""The two working users of the database, created or updated by the owner (admin) account.

- stock_reader: reads every table and view. Used by analyses, viewers and the API's reads.
- stock_writer: reads, adds and changes data (the ingest, build, the analyses' results, the
  API's writes), but can't change the schema or schema_version, and can only add to the raw
  tables (append only: no UPDATE or DELETE there, except raw_fetch's row counts).

    python -m stock_analysis.db create-roles --target server

Passwords come from STOCK_READER_DB_PASSWORD and STOCK_WRITER_DB_PASSWORD; missing ones are
generated into .env first. Rerunning updates passwords and rights (new tables included).
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from sqlalchemy import inspect

from . import ROOT, Database, scalar

ROLES = {"stock_reader": "STOCK_READER_DB_PASSWORD", "stock_writer": "STOCK_WRITER_DB_PASSWORD"}


def ensure_passwords(env_file: Path = ROOT / ".env") -> list[str]:
    """Generate a password into .env for every role that has none. Returns the names added."""
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    added = []
    for env in ROLES.values():
        if os.environ.get(env) or f"\n{env}=" in "\n" + existing:
            continue
        value = secrets.token_urlsafe(32)  # letters, digits, - and _: safe in SQL and URLs
        with env_file.open("a", encoding="utf-8") as f:
            f.write(
                f"{'' if existing.endswith(chr(10)) or not existing else chr(10)}{env}={value}\n"
            )
        existing += f"\n{env}={value}\n"
        os.environ[env] = value
        added.append(env)
    return added


def create_roles(db: Database) -> dict[str, str]:
    """Create or update both roles and their rights. Returns what was done per role."""
    insp = inspect(db.engine)
    tables = insp.get_table_names()
    raw_data = [t for t in tables if t.startswith("raw_") and t != "raw_fetch"]
    done = {}
    with db.begin() as conn:
        database = scalar(conn, "SELECT current_database()")
        for role, env in ROLES.items():
            password = os.environ[env]
            if any(c in password for c in "'\\"):
                raise ValueError(f"{env} must not contain quotes or backslashes")
            exists = scalar(conn, "SELECT 1 FROM pg_roles WHERE rolname = :r", {"r": role})
            verb = "ALTER" if exists else "CREATE"
            conn.exec_driver_sql(f"{verb} ROLE {role} WITH LOGIN PASSWORD '{password}'")
            done[role] = "updated" if exists else "created"
            conn.exec_driver_sql(f'GRANT CONNECT ON DATABASE "{database}" TO {role}')
            conn.exec_driver_sql(f"GRANT USAGE ON SCHEMA public TO {role}")
        statements = [
            "GRANT SELECT ON ALL TABLES IN SCHEMA public TO stock_reader",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO stock_reader",
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO stock_writer",
            "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO stock_writer",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO stock_writer",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES "
            "TO stock_writer",
            "REVOKE INSERT, UPDATE, DELETE ON schema_version FROM stock_writer",
            *(f"REVOKE UPDATE, DELETE ON {t} FROM stock_writer" for t in raw_data),
        ]
        for statement in statements:
            conn.exec_driver_sql(statement)
    return done
