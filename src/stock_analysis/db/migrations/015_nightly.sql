-- Migration 015: what the nightly analyses (stock_analysis.nightly) compute after each
-- ingest for the evening run, which only reads them (issue #33).
--
-- out_stock_numbers: per watch-list stock and day, its row, yearly history, prices, adjusted
-- EPS, peers and next report (payload_json), with stock_key: the watch-list settings they
-- were computed for, so a changed target or EPS correction is computed again.
-- out_market_numbers: the market report's numbers (instruments, sectors, breadth, the
-- screener's top per sector).

CREATE TABLE out_stock_numbers (
    symbol          TEXT NOT NULL,
    as_of           DATE NOT NULL,      -- the newest price used
    computed_at     TIMESTAMP NOT NULL,
    stock_key       TEXT NOT NULL,      -- the watch-list settings used (JSON)
    payload_json    TEXT NOT NULL,
    PRIMARY KEY (symbol, as_of)
);

CREATE TABLE out_market_numbers (
    as_of           DATE PRIMARY KEY,   -- the newest price used
    computed_at     TIMESTAMP NOT NULL,
    payload_json    TEXT NOT NULL
);
