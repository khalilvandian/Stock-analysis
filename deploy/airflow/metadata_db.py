"""Airflow's metadata database on stock-db-bk (deploy/airflow.ps1, issue #30): the login role
`airflow`, owner of the database `airflow` (created by the script with az), with the password
in AIRFLOW_DB_PASSWORD_NEW. Runs as the server's admin (the target `server` in
config/database.toml, password STOCK_SERVER_DB_PASSWORD in .env); opening it also applies the
stock database's pending migrations, such as 011 (the pipeline's run log). Safe to rerun: an
existing role gets the password again."""

from __future__ import annotations

import os
import re

import psycopg
from dotenv import load_dotenv
from psycopg import sql

from stock_analysis.db import ROOT, Database, target_settings


def main() -> None:
    load_dotenv(ROOT / ".env")
    password = os.environ["AIRFLOW_DB_PASSWORD_NEW"]
    db = Database.open("server")  # the admin; also applies the stock migrations (011)
    with db.engine.connect() as conn:
        raw = conn.connection.driver_connection
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_roles WHERE rolname = 'airflow'")
            verb = "ALTER" if cur.fetchone() else "CREATE"
            cur.execute(
                sql.SQL(verb + " ROLE airflow LOGIN PASSWORD {}").format(sql.Literal(password))
            )
            cur.execute("GRANT airflow TO CURRENT_USER")  # Azure's admin may only hand over its own
            cur.execute("ALTER DATABASE airflow OWNER TO airflow")
    db.close()
    # Owning the database isn't enough on Azure: the schema public inside it belongs to the
    # admin, so Airflow could create no tables. Hand it over, connected to that database.
    settings = target_settings("server")
    url = re.sub(r"/stock(\?|$)", r"/airflow\1", settings["url"])
    with psycopg.connect(url, password=os.environ[settings["password_env"]], autocommit=True) as c:
        c.execute("ALTER SCHEMA public OWNER TO airflow")
        c.execute("GRANT ALL ON SCHEMA public TO airflow")
    print(f"Role airflow {verb.lower()}d; it owns the database airflow")


if __name__ == "__main__":
    main()
