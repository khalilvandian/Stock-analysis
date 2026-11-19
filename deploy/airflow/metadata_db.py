"""Airflow's metadata database on stock-db-bk (deploy/airflow.ps1, issue #30): the login role
`airflow`, owner of the database `airflow` (created by the script with az), with the password
in AIRFLOW_DB_PASSWORD_NEW. Runs as the server's admin (the target `server` in
config/database.toml, password STOCK_SERVER_DB_PASSWORD in .env); opening it also applies the
stock database's pending migrations, such as 011 (the pipeline's run log). Safe to rerun: an
existing role gets the password again."""

from __future__ import annotations

import os

from psycopg import sql

from stock_analysis.db import Database


def main() -> None:
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
    print(f"Role airflow {verb.lower()}d; it owns the database airflow")


if __name__ == "__main__":
    main()
