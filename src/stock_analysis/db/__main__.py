"""Command line: python -m stock_analysis.db {init,load-files,build,status,check}."""

from __future__ import annotations

import argparse
import json
import sys

from . import connect, db_path, table_counts, target_settings
from .build import build
from .check import check
from .load_files import load_all


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m stock_analysis.db", description=__doc__)
    parser.add_argument("command", choices=["init", "load-files", "build", "status", "check"])
    parser.add_argument("--target", help="a target in config/database.toml (default: selected)")
    parser.add_argument("--data", help="load-files: folder to import from (default: data/)")
    parser.add_argument("--strict", action="store_true", help="check: exit 1 on WARN too")
    args = parser.parse_args(argv)
    if args.command == "check":
        return check(args.target, args.strict)
    path = db_path(target_settings(args.target)["url"])
    con = connect(path)
    if args.command == "load-files":
        print("Rows added:", json.dumps(load_all(con, args.data), indent=2))
    elif args.command == "build":
        print("Build:", json.dumps(build(con), indent=2))
    else:
        print(f"Database: {path}")
        for name, n in table_counts(con).items():
            print(f"{name:28} {n:>10,}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
