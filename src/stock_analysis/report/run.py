"""Render a submitted analysis run (issue #60): its PDFs into the store, its rows in
out_watchlist_run and out_market_run, and what it made in out_analysis_run.report_json, which
the validation and the email read.

Rendering a run again gives the same file names (they carry the time the run was submitted)
and replaces its PDFs and rows. A subject that fails is named in the report and the email; the
others are still made. A run where nothing could be made raises.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .. import nightly
from .. import watchlist as wl
from ..data import MARKET_RUN_COLUMNS, WATCHLIST_RUN_COLUMNS, insert_sql, now_utc
from ..nightly import key_numbers, plain
from . import market as market_report
from . import render as r

MARKET, SUMMARIES = "market", "summaries"


def literal(value: str) -> str:
    """A text constant for data.sql (which takes no parameters)."""
    return "'" + value.replace("'", "''") + "'"


def load_run(data, run_key: str) -> tuple[dict, dict[str, r.Analysis]]:
    """The run and its analyses by subject."""
    found = data.sql(f"SELECT * FROM out_analysis_run WHERE run_key = {literal(run_key)}")
    if found.empty:
        raise RuntimeError(f"No analysis run {run_key}")
    run = {k: (None if pd.isna(v) else v) for k, v in found.iloc[0].to_dict().items()}
    run["subjects"] = json.loads(run.pop("subjects_json"))
    run["report"] = json.loads(run.pop("report_json") or "null")
    rows = data.sql(f"SELECT * FROM out_analysis WHERE run_key = {literal(run_key)}")
    analyses = {
        x.subject: r.Analysis(
            str(x.reviewed)[:10], json.loads(x.sections_json), json.loads(x.corrections_json)
        )
        for x in rows.itertuples()
    }
    return run, analyses


def to_pdf_bytes(page: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        file = Path(tmp) / "report.pdf"
        r.to_pdf(page, file)
        return file.read_bytes()


def replace_row(table: str, columns: list[str], row: dict, key: dict) -> list[tuple]:
    where = " AND ".join(f"{c} = :{c}" for c in key)
    return [
        (f"DELETE FROM {table} WHERE {where}", [key]),
        insert_sql(table, columns, [row]),
    ]


def render_run(data, run: dict, analyses: dict[str, r.Analysis], store) -> dict:
    """Make and store the run's reports; returns the report (files, subject, email, failures)."""
    if not run.get("submitted_at"):
        raise RuntimeError(f"Run {run['run_key']} is not submitted")
    subjects = run["subjects"]
    missing = [s for s in subjects if s not in analyses]
    if missing:
        raise RuntimeError(f"No analysis of {', '.join(missing)} in run {run['run_key']}")
    local = pd.Timestamp(run["submitted_at"]).tz_localize("UTC").tz_convert(ZoneInfo(wl.TIMEZONE))
    run_at = pd.Timestamp(run["submitted_at"]).strftime("%Y-%m-%dT%H:%M:%S")
    stamp = local.strftime("%Y-%m-%d_%H%M")
    label = local.strftime("%Y-%m-%d %H:%M ") + local.tzname()
    files, failed, steps, results, market_row = [], [], [], [], None

    def make(subject: str, page: str) -> str:
        file = f"{subject}/{stamp}.pdf"
        store.put(file, to_pdf_bytes(page))
        files.append(file)
        return f"{stamp}.pdf"

    if MARKET in subjects:
        try:
            n = nightly.stored_market(data) or nightly.market_numbers(data)
            file = make(MARKET, market_report.page(n, label, analyses[MARKET]))
            market_row = market_report.run_row(n, run_at, file)
            steps += replace_row(
                "out_market_run", MARKET_RUN_COLUMNS, market_row, {"run_at": run_at}
            )
        except Exception as e:  # noqa: BLE001 - the stocks' reports still get made
            failed.append(f"Market report: {e}")

    stocks = [s for s in wl.load(data) if s["symbol"] in subjects]
    gone = [s for s in subjects if s not in (MARKET, SUMMARIES)]
    gone = [s for s in gone if s not in {x["symbol"] for x in stocks}]
    failed += [f"{s}: no longer on the watch list" for s in gone]
    ready = nightly.stored_stocks(data, stocks)
    todo = [s for s in stocks if s["symbol"] not in ready]
    computed, errors, _ = nightly.compute_stocks(data, todo) if todo else ({}, {}, [])
    for stock in stocks:
        sym = stock["symbol"]
        try:
            d = ready.get(sym) or computed.get(sym)
            if d is None:
                raise RuntimeError(errors.get(sym, "no numbers"))
            d = {**d, "stock": stock}
            k = key_numbers(d)
            file = make(sym, r.render(d, k, label, analyses[sym]))
            row = {c: plain(k.get(c)) for c in r.RUN_COLUMNS}
            verdict = r.first_sentence(analyses[sym].sections.get("Verdict", ""))
            row |= {"symbol": sym, "run_at": run_at, "file": file, "verdict": verdict or None}
            steps += replace_row(
                "out_watchlist_run",
                WATCHLIST_RUN_COLUMNS,
                row,
                {"symbol": sym, "run_at": run_at},
            )
            results.append((d, k))
        except Exception as e:  # noqa: BLE001 - one stock doesn't stop the others
            failed.append(f"{sym}: {e}")

    if SUMMARIES in subjects and results:
        try:
            make(SUMMARIES, r.render_summary(results, label, analyses))
        except Exception as e:  # noqa: BLE001
            failed.append(f"Summary: {e}")
    if not files:
        raise RuntimeError("Nothing could be rendered: " + "; ".join(failed))
    report = {
        "subject": f"Watch list analyses, {label}",
        "html": r.email_html(label, files, results, analyses, market_row, failed),
        "files": files,
        "failed": failed,
    }
    if run.get("submit_note"):
        report["note"] = run["submit_note"]
    steps.append(save_report(run["run_key"], report))
    data.write_steps(steps)
    return report


def save_report(run_key: str, report: dict) -> tuple[str, list[dict]]:
    return (
        "UPDATE out_analysis_run SET report_json = :report, rendered_at = :at "
        "WHERE run_key = :run_key",
        [{"report": json.dumps(report), "at": now_utc(), "run_key": run_key}],
    )
