"""The steps Airflow runs after Claude submitted a run (issue #60), each repeatable:

python -m stock_analysis.report render RUN_KEY     # PDFs into the store
python -m stock_analysis.report validate RUN_KEY   # exit 1 when the reports are broken
python -m stock_analysis.report email RUN_KEY      # once per run
"""

from __future__ import annotations

import argparse

from ..data import DbData
from ..db import Database
from . import email, validate
from .run import load_run, render_run, save_report
from .store import open_store


def step(command: str, run_key: str, data, store) -> int:
    run, analyses = load_run(data, run_key)
    if command == "render":
        report = render_run(data, run, analyses, store)
        print(f"Stored {len(report['files'])} reports: {', '.join(report['files'])}")
        for f in report["failed"]:
            print(f"Failed: {f}")
        return 0
    if command == "validate":
        own, behind = validate.run_checks(run, store, data)
        print(validate.report(own + behind))
        fails = [f"{c.name}: {c.detail}" for c in behind if c.level == "FAIL"]
        if run["report"]:
            data.write_steps([save_report(run_key, {**run["report"], "checks": fails})])
        return 1 if validate.overall(own) == "FAIL" else 0
    print(email.send_run(data, run, store))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stock_analysis.report", description=__doc__)
    ap.add_argument("command", choices=["render", "validate", "email"])
    ap.add_argument("run_key")
    ap.add_argument("--target")
    args = ap.parse_args(argv)
    from ..db.azure import JobFirewall

    with JobFirewall(args.target, rule=f"{args.command}-job"):
        db = Database.open(args.target)
        try:
            return step(args.command, args.run_key, DbData(db, db), open_store())
        finally:
            db.close()


if __name__ == "__main__":
    raise SystemExit(main())
