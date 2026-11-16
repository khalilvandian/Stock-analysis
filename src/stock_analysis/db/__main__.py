"""Command line: python -m stock_analysis.db {init,load-files,build,status,check,allow-my-ip}
[--target]."""

from __future__ import annotations

import argparse
import json
import sys

from . import Database
from .build import build
from .check import check
from .load_files import load_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stock_analysis.db", description=__doc__)
    parser.add_argument(
        "command", choices=["init", "load-files", "build", "status", "check", "allow-my-ip"]
    )
    parser.add_argument("--target", help="a target in config/database.toml (default: selected)")
    parser.add_argument("--data", help="load-files: folder to import from (default: data/)")
    parser.add_argument("--strict", action="store_true", help="check: exit 1 on WARN too")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check(args.target, args.strict)
    if args.command == "allow-my-ip":
        from .azure import allow_my_ip

        print(allow_my_ip(args.target or "server"))
        return 0
    db = Database.open(args.target)  # applies any new migrations
    print(f"Database: {db.target} ({db.where})")
    if args.command == "load-files":
        print("Rows added:", json.dumps(load_all(db, args.data), indent=2))
    elif args.command == "build":
        print("Build:", json.dumps(build(db), indent=2))
    else:
        for name, n in db.table_counts().items():
            print(f"{name:28} {n:>10,}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
