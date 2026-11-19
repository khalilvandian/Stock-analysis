-- Migration 008: the payloads as the sources returned them (issue #29). A raw table such as
-- raw_sec_fact keeps only what is parsed from a payload (for SEC, the tags mapped in
-- config/db_items.toml). With the payload kept, a new mapping is read from the stored copy
-- (python -m stock_analysis.db reparse) instead of asking the source again. One row per
-- distinct payload: raw_fetch already skips a payload seen before.

CREATE TABLE raw_payload (
    fetch_id        BIGINT PRIMARY KEY REFERENCES raw_fetch (fetch_id),
    media_type      TEXT NOT NULL,      -- 'application/json'
    encoding        TEXT NOT NULL CHECK (encoding IN ('gzip')),
    size_bytes      BIGINT NOT NULL,    -- before compression
    content         BYTEA NOT NULL
);
