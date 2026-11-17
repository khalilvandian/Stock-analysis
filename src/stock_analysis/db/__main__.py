"""Command line: python -m stock_analysis.db
{init,load-files,build,status,check,ping,allow-my-ip,create-roles,ingest,coverage,tasks}
[--target]."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import Database
from .build import build
from .check import check
from .load_files import load_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stock_analysis.db", description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "init",
            "load-files",
            "build",
            "status",
            "check",
            "ping",
            "allow-my-ip",
            "create-roles",
            "ingest",
            "coverage",
            "tasks",
        ],
    )
    parser.add_argument("--target", help="a target in config/database.toml (default: selected)")
    parser.add_argument("--data", help="load-files: folder to import from (default: data/)")
    parser.add_argument("--strict", action="store_true", help="check: exit 1 on WARN too")
    parser.add_argument("--ip", help="allow-my-ip: allow this address instead of this PC's")
    parser.add_argument("--rule", default="home", help="allow-my-ip: firewall rule name")
    parser.add_argument("--mode", choices=["backfill", "maintain"], help="ingest: force a mode")
    parser.add_argument("--sources", help="ingest: only these sources (comma-separated)")
    parser.add_argument("--max-minutes", type=float, help="ingest: stop starting tasks after")
    parser.add_argument("--limit", type=int, help="ingest: at most this many tasks per source")
    parser.add_argument("--no-build", action="store_true", help="ingest: skip build and coverage")
    parser.add_argument("--due-now", help="ingest: make SOURCE's tasks due now, then run")
    parser.add_argument("--json", help="coverage: also write the page's JSON to this file")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check(args.target, args.strict)
    if args.command == "ping":
        from .ping import ping

        return ping(args.target)
    if args.command == "allow-my-ip":
        from .azure import allow_my_ip

        print(allow_my_ip(args.target or "server", args.rule, args.ip))
        return 0
    if args.command == "ingest":  # on Azure, open the database firewall for this run
        from .azure import JobFirewall

        with JobFirewall(args.target) as ip:
            if ip:
                print(f"Firewall rule ingest-job allows this run's address {ip}")
            return run_ingest(args)
    db = Database.open(args.target)  # applies any new migrations
    print(f"Database: {db.target} ({db.where})")
    if args.command == "create-roles":
        from .roles import create_roles, ensure_passwords

        for env in ensure_passwords():
            print(f"Generated {env} into .env")
        print(json.dumps(create_roles(db), indent=2))
        db.close()
        return 0
    if args.command == "load-files":
        print("Rows added:", json.dumps(load_all(db, args.data), indent=2))
    elif args.command == "build":
        print("Build:", json.dumps(build(db), indent=2))
    elif args.command == "coverage":
        from .coverage import snapshot, summary_lines

        snap = snapshot(db)
        print("\n".join(summary_lines(snap["detail"])))
        if args.json:
            Path(args.json).parent.mkdir(parents=True, exist_ok=True)
            Path(args.json).write_text(json.dumps(snap["detail"], default=str), encoding="utf-8")
            print(f"Wrote {args.json}")
    elif args.command == "tasks":
        from ..ingest.job import task_table

        print(task_table(db).to_string(index=False))
    else:
        for name, n in db.table_counts().items():
            print(f"{name:28} {n:>10,}")
    db.close()
    return 0


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
    )
    print("Ingest:", json.dumps(result, indent=2, default=str))
    db.close()
    if result["status"] in ("ok", "partial"):
        from ..ingest.notify import publish_site

        print(publish_site())
    return 0 if result["status"] in ("ok", "partial", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
