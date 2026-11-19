"""Command line: python -m stock_analysis.db
{init,build,status,check,ping,allow-my-ip,create-roles,ingest,import,reparse,push,
coverage,tasks,quotes,nightly} [--target].

quotes fetches the last price of every company in the index (TradingView, one request, 15
minutes delayed) into raw_tv_quote; the hourly job stock-quotes runs it (ingest/quotes.py).
--symbols A,B fetches only those (a sample).

nightly computes what the evening run reads (stock_analysis.nightly); the ingest runs it after
its build when `nightly = true` in config/ingest.toml.

push sends what this PC ingested (kept SEC payloads, imported data-set files) to --target
(the server) without asking SEC again (ingest/push.py); --from picks the source database.

import FILE loads a file downloaded or found by hand into the raw layer of the target database
(--target server: straight into Azure), as its API source would (ingest/files.py).

reparse reads the kept SEC payloads again (company facts, full filings, the data-set quarters in
inbox/) with today's mapping (config/db_items.toml), without asking SEC; run build afterwards.

build rebuilds core for the companies whose raw data, config/companies.toml entry or CIK
changed since the last build (the job never rebuilds the whole database); --symbols A,B
rebuilds only those; --full rebuilds every company (only when asked).

check-sample --symbols A,B builds those companies with today's code and config, shows what
would change against the values in the database, and rolls back: nothing is written. The
way to check a change of the extraction on a sample.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Database
from .build import build
from .check import check

# The commands an Azure job runs, and the firewall rule each one opens.
JOB_RULES = {
    "ingest": "ingest-job",
    "quotes": "quotes-job",
    "build": "build-job",
    "coverage": "coverage-job",
    "nightly": "nightly-job",
    "check": "check-job",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stock_analysis.db", description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "build",
            "check-sample",
            "status",
            "check",
            "ping",
            "allow-my-ip",
            "create-roles",
            "ingest",
            "import",
            "reparse",
            "push",
            "coverage",
            "tasks",
            "quotes",
            "nightly",
        ],
    )
    parser.add_argument("--target", help="a target in config/database.toml (default: selected)")
    parser.add_argument("--strict", action="store_true", help="check: exit 1 on WARN too")
    parser.add_argument("--ip", help="allow-my-ip: allow this address instead of this PC's")
    parser.add_argument("--rule", default="home", help="allow-my-ip: firewall rule name")
    parser.add_argument("--mode", choices=["backfill", "maintain"], help="ingest: force a mode")
    parser.add_argument("--sources", help="ingest: only these sources (comma-separated)")
    parser.add_argument("--max-minutes", type=float, help="ingest: stop starting tasks after")
    parser.add_argument("--limit", type=int, help="ingest: at most this many tasks per source")
    parser.add_argument("--no-build", action="store_true", help="ingest: skip build and coverage")
    parser.add_argument(
        "--no-nightly", action="store_true", help="ingest: skip the nightly analyses (db nightly)"
    )
    parser.add_argument(
        "--no-site", action="store_true", help="ingest: don't ask GitHub to rebuild the site"
    )
    parser.add_argument("--due-now", help="ingest: make SOURCE's tasks due now, then run")
    parser.add_argument("--json", help="coverage: also write the page's JSON to this file")
    parser.add_argument("file", nargs="?", help="import: the file to load")
    parser.add_argument("--kind", help="import: the kind of file (default: its folder's name)")
    parser.add_argument("--symbols", help="import, build: only these companies (comma-separated)")
    parser.add_argument(
        "--full", action="store_true", help="build: every company, not only what changed"
    )
    parser.add_argument("--from", dest="source_db", help="push: the database to send from")
    args = parser.parse_args(argv)
    if args.command in JOB_RULES:
        # A run of an Azure job (Airflow starts one per task, issue #30) lets its own address
        # through the database firewall for as long as it runs. One rule per command, so runs
        # going at the same time (coverage, check, nightly) never remove each other's rule.
        # Outside Azure (no managed identity) this does nothing.
        from .azure import JobFirewall

        rule = JOB_RULES[args.command]
        with JobFirewall(args.target, rule=rule) as ip:
            if ip:
                print(f"Firewall rule {rule} allows this run's address {ip}")
            return run_command(args, parser)
    return run_command(args, parser)


def run_command(args, parser) -> int:
    if args.command == "check":
        return check(args.target, args.strict)
    if args.command == "ping":
        from .ping import ping

        return ping(args.target)
    if args.command == "allow-my-ip":
        from .azure import allow_my_ip

        print(allow_my_ip(args.target or "server", args.rule, args.ip))
        return 0
    if args.command == "ingest":
        return run_ingest(args)
    if args.command == "quotes":
        return run_quotes(args)
    db = Database.open(args.target)  # applies any new migrations
    print(f"Database: {db.target} ({db.where})")
    if args.command == "create-roles":
        from .roles import create_roles, ensure_passwords

        for env in ensure_passwords():
            print(f"Generated {env} into .env")
        print(json.dumps(create_roles(db), indent=2))
        db.close()
        return 0
    if args.command == "nightly":
        from ..data import DbData
        from ..nightly import run as run_nightly

        summary = run_nightly(DbData(db, db))
        print("Nightly analyses:", json.dumps(summary, indent=2, default=str))
        # A failed part fails the command, so the job run (and the Airflow task) shows it.
        failed = (summary.get("stocks") or {}).get("failed")
        if failed or any(k in summary for k in ("screener_error", "market_error")):
            db.close()
            return 1
    elif args.command == "build":
        symbols = args.symbols.split(",") if args.symbols else None
        print("Build:", json.dumps(build(db, full=args.full, symbols=symbols), indent=2))
    elif args.command == "check-sample":
        if not args.symbols:
            parser.error("check-sample needs --symbols A,B")
        report = build(db, symbols=args.symbols.split(","), dry_run=True)
        print(json.dumps({k: v for k, v in report.items() if k != "changes"}, indent=2))
        for c in report["changes"]:
            print(
                f"  {c['symbol']:6} {c['item']:20} {c['period_type']:2} {c['period_end']} "
                f"filed {c['filed']}  {c['change']:8} {c['value_old']} -> {c['value_new']}"
            )
    elif args.command == "coverage":
        from .coverage import snapshot, summary_lines

        snap = snapshot(db)
        print("\n".join(summary_lines(snap["detail"])))
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(snap["detail"], default=str), encoding="utf-8")
            print(f"Wrote {args.json}")
    elif args.command == "import":
        from ..ingest.files import import_file

        symbols = args.symbols.split(",") if args.symbols else None
        print("Import:", json.dumps(import_file(db, args.file, args.kind, symbols)))
    elif args.command == "push":
        from ..ingest.push import push

        src = Database.open(args.source_db)
        if src.where == db.where:
            raise SystemExit("push: --from and --target are the same database")
        sources = args.sources.split(",") if args.sources else None
        print(f"Push from {src.target} to {db.target}:", json.dumps(push(src, db, sources)))
        src.close()
    elif args.command == "reparse":
        from ..ingest.files import reparse_all

        print("Reparse:", json.dumps(reparse_all(db)))
    elif args.command == "tasks":
        from ..ingest.job import task_table

        print(task_table(db).to_string(index=False))
    else:
        for name, n in db.table_counts().items():
            print(f"{name:28} {n:>10,}")
    db.close()
    return 0


def run_quotes(args) -> int:
    from ..ingest.quotes import fetch_quotes

    db = Database.open(args.target)
    print(f"Database: {db.target} ({db.where})")
    result = fetch_quotes(db, args.symbols.split(",") if args.symbols else None)
    print("Quotes:", json.dumps(result, default=str))
    db.close()
    return 0 if result["status"] in ("ok", "unchanged") else 1


def run_ingest(args) -> int:
    from ..ingest.job import make_due, run_job

    db = Database.open(args.target)
    print(f"Database: {db.target} ({db.where})")
    if args.due_now:
        print(f"Made {make_due(db, args.due_now)} {args.due_now} tasks due now")
    result = run_job(
        db,
        mode=args.mode,
        sources=args.sources.split(",") if args.sources else None,
        max_minutes=args.max_minutes,
        limit=args.limit,
        do_build=not args.no_build,
        do_coverage=not args.no_build,
        do_nightly=not args.no_nightly,
    )
    print("Ingest:", json.dumps(result, indent=2, default=str))
    db.close()
    # Under the orchestrator (issue #30) Airflow runs the nightly analyses and rebuilds the
    # site as tasks of their own: --no-nightly --no-site.
    if result["status"] in ("ok", "partial") and not args.no_site:
        from ..ingest.notify import publish_site

        print(publish_site())
    return 0 if result["status"] in ("ok", "partial", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
