"""What this PC has ingested, sent to another database (the server) without asking any source
again (issue #29).

    python -m stock_analysis.db push --target server                 # from the selected db
    python -m stock_analysis.db push --target server --sources sec_xbrl

The PC does the analysis and the heavy loading (bulk files, full filings); the server's job
should not do it again. A push replays every kept payload the target lacks (the same source,
request key and content fingerprint): the payload is stored there, parsed on this PC by the
source's own loader and written to the target's raw tables, so the target keeps its own
"new or changed rows only" history. The target's tasks for what was sent count as fetched.
Payloads kept only as files (the data-set quarters in inbox/) are imported into the target
from the file. Yahoo, TradingView and the ECB are cheap and fetched by the server itself.

Raw rows are not copied table to table: they are stored relative to the source database's
own earlier versions, so copying them would leave gaps or duplicates on the target.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..db import Database, frame
from ..db.raw import finish_fetch, store_changed
from . import xbrl
from .common import read_payload, start_fetch
from .files import followed_ciks, import_file, mark_fetched
from .sec import mapped_tags, parse_companyfacts

SOURCES = ("sec_companyfacts", "sec_xbrl", "sec_fsds")


def missing_on(src: Database, dst: Database, source: str) -> list[tuple]:
    """The source's fetches in src that dst lacks: (fetch_id, request_key, url, fetched_at,
    sha), oldest first. Fetches with a kept payload, or a data-set file."""
    payload = "" if source == "sec_fsds" else "JOIN raw_payload p ON p.fetch_id = f.fetch_id "
    with src.connect() as conn:
        mine = frame(
            conn,
            "SELECT f.fetch_id, f.request_key, f.url, f.fetched_at, f.payload_sha256 "
            f"FROM raw_fetch f {payload}WHERE f.source = :s AND f.status IN ('ok', 'empty') "
            "AND f.payload_sha256 IS NOT NULL ORDER BY f.fetch_id",
            {"s": source},
        )
    with dst.connect() as conn:
        theirs = frame(
            conn,
            "SELECT request_key, payload_sha256 FROM raw_fetch WHERE source = :s "
            "AND payload_sha256 IS NOT NULL",
            {"s": source},
        )
    have = set(zip(theirs["request_key"], theirs["payload_sha256"], strict=True))
    return [
        tuple(r) for r in mine.itertuples(index=False) if (r[1], r[4]) not in have
    ]  # fmt: skip


def replay(dst: Database, source: str, key: str, url: str, when, sha: str, content: bytes):
    """One kept payload into dst, through its source's loader. Returns rows stored."""
    when = datetime.fromisoformat(str(when)[:19])
    with dst.begin() as conn:
        fetch_id = start_fetch(conn, source, key, url, sha, when, payload=content)
        if fetch_id is None:
            return 0
        if source == "sec_companyfacts":
            cik = int(key[3:]) if key.startswith("CIK") else int(key)
            stored, received = parse_companyfacts(conn, content, cik, mapped_tags(), fetch_id)
            keys = followed_ciks(conn).get(cik, [])
        else:  # sec_xbrl
            df = xbrl.facts_frame(json.loads(content), xbrl.mapped_concepts())
            stored = store_changed(
                conn, "raw_sec_xbrl_fact", df, xbrl.FACT_KEY, xbrl.FACT_VALUES, fetch_id
            )
            received, keys = len(df), [key]
        finish_fetch(conn, fetch_id, received, stored)
        if keys:
            mark_fetched(conn, source, keys, when, fetch_id)
    return stored


def push(src: Database, dst: Database, sources: list[str] | None = None) -> dict:
    """Every kept payload of these sources that dst lacks, replayed into dst."""
    out = {}
    for source in sources or SOURCES:
        todo = missing_on(src, dst, source)
        done = {"payloads": len(todo), "stored": 0, "missing_files": 0}
        for fetch_id, key, url, when, sha in todo:
            if source == "sec_fsds":
                path = Path(str(url).removeprefix("file:"))
                if not path.exists():
                    done["missing_files"] += 1
                    continue
                symbols = key.split(":", 1)[1].split(",") if ":" in key else None
                done["stored"] += import_file(dst, path, "sec_fsds", symbols).get("stored", 0)
                continue
            with src.connect() as conn:
                content = read_payload(conn, int(fetch_id))
            done["stored"] += replay(dst, source, key, url, when, sha, content)
        out[source] = done
    return out
