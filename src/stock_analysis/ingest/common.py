"""What every source loader shares: the result of a task, the errors that stop a source, and
logging a fetched payload in raw_fetch (the same rules as load_files: a payload seen before is
not stored again, and only new or changed rows go into the raw tables)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from sqlalchemy.engine import Connection

from ..db import scalar
from ..db.load_files import now


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
    conn: Connection, source: str, request_key: str, url: str, digest: str, fetched_at=None
) -> int | None:
    """A new raw_fetch row for a payload, or None if the same payload was stored before."""
    params = {"source": source, "key": request_key, "sha": digest}
    if scalar(
        conn,
        "SELECT 1 FROM raw_fetch WHERE source = :source AND request_key = :key "
        "AND payload_sha256 = :sha",
        params,
    ):
        return None
    return scalar(
        conn,
        "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status, "
        "payload_sha256) VALUES (:source, :key, :url, :fetched_at, :loaded_at, 'ok', :sha) "
        "RETURNING fetch_id",
        {**params, "url": url, "fetched_at": fetched_at or now(), "loaded_at": now()},
    )


def log_error(conn: Connection, source: str, request_key: str, url: str, error: str) -> int:
    """A raw_fetch row for a failed request, so failures are on record next to the data."""
    return scalar(
        conn,
        "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status, error) "
        "VALUES (:source, :key, :url, :t, :t, 'error', :error) RETURNING fetch_id",
        {"source": source, "key": request_key, "url": url, "t": now(), "error": error[:2000]},
    )
