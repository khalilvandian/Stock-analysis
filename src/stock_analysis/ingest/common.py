"""What every source loader shares: the result of a task, the errors that stop a source, and
logging a fetched payload in raw_fetch (the same rules as load_files: a payload seen before is
not stored again, and only new or changed rows go into the raw tables), and keeping the payload
itself as the source returned it (raw_payload), so parsing it again never needs the source."""

from __future__ import annotations

import gzip
import hashlib
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.engine import Connection

from ..db import run, scalar
from ..db.raw import now


class RateLimited(Exception):
    """The source said "too many requests": stop the whole group for this run."""


class NoData(Exception):
    """The source has nothing for this key (e.g. HTTP 404): the task is 'empty'."""


@dataclass
class Outcome:
    """What one task did."""

    requests: int = 0
    received: int = 0  # rows returned by the source
    stored: int = 0  # rows new or changed
    fetch_ids: list[int] = field(default_factory=list)


def sha256(payload: bytes | str) -> str:
    data = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(data).hexdigest()


def start_fetch(
    conn: Connection,
    source: str,
    request_key: str,
    url: str,
    digest: str,
    fetched_at=None,
    payload: bytes | None = None,
    media_type: str = "application/json",
) -> int | None:
    """A new raw_fetch row for a payload, or None if the same payload was stored before. The
    payload itself, as the source returned it, goes into raw_payload; a payload seen before
    the payloads were kept gets its copy now, on the earlier fetch."""
    params = {"source": source, "key": request_key, "sha": digest}
    seen = scalar(
        conn,
        "SELECT fetch_id FROM raw_fetch WHERE source = :source AND request_key = :key "
        "AND payload_sha256 = :sha",
        params,
    )
    if seen is not None:
        if payload is not None:
            save_payload(conn, seen, payload, media_type)  # does nothing if kept already
        return None
    fetch_id = scalar(
        conn,
        "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status, "
        "payload_sha256) VALUES (:source, :key, :url, :fetched_at, :loaded_at, 'ok', :sha) "
        "RETURNING fetch_id",
        {**params, "url": url, "fetched_at": fetched_at or now(), "loaded_at": now()},
    )
    if payload is not None:
        save_payload(conn, fetch_id, payload, media_type)
    return fetch_id


def log_error(conn: Connection, source: str, request_key: str, url: str, error: str) -> int:
    """A raw_fetch row for a failed request, so failures are on record next to the data."""
    return scalar(
        conn,
        "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status, error) "
        "VALUES (:source, :key, :url, :t, :t, 'error', :error) RETURNING fetch_id",
        {"source": source, "key": request_key, "url": url, "t": now(), "error": error[:2000]},
    )


def save_payload(conn: Connection, fetch_id: int, content: bytes, media_type: str) -> None:
    """Keep a payload as the source returned it (raw_payload), gzip-compressed."""
    run(
        conn,
        "INSERT INTO raw_payload (fetch_id, media_type, encoding, size_bytes, content) "
        "VALUES (:id, :type, 'gzip', :size, :content) ON CONFLICT (fetch_id) DO NOTHING",
        {"id": fetch_id, "type": media_type, "size": len(content),
         "content": gzip.compress(content, compresslevel=6)},
    )  # fmt: skip


def read_payload(conn: Connection, fetch_id: int) -> bytes | None:
    row = conn.execute(
        text("SELECT encoding, content FROM raw_payload WHERE fetch_id = :id"), {"id": fetch_id}
    ).fetchone()
    return gzip.decompress(bytes(row[1])) if row else None
