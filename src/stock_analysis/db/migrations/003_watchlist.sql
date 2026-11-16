-- Migration 003: the watch list and its evening runs.
--
-- user_* : what people decide (here the watch list). For now config/watchlist.toml is the
--          master copy and load-files mirrors it; later the interface edits these tables.

CREATE TABLE user_watchlist (
    symbol          TEXT PRIMARY KEY,
    position        INTEGER NOT NULL,   -- order in the list
    target_pe       DOUBLE PRECISION,   -- entry price = target_pe x trailing adjusted EPS
    target_note     TEXT,               -- where the target comes from, whether confirmed
    stakes_per_share DOUBLE PRECISION   -- after-tax equity stakes per share, kept out of the P/E
);

CREATE TABLE user_watchlist_peer (
    symbol          TEXT NOT NULL REFERENCES user_watchlist (symbol),
    peer            TEXT NOT NULL,
    position        INTEGER NOT NULL,
    PRIMARY KEY (symbol, peer)
);

-- One-off corrections to a quarter's adjusted EPS, by report date.
CREATE TABLE user_eps_override (
    symbol          TEXT NOT NULL REFERENCES user_watchlist (symbol),
    reported        DATE NOT NULL,
    eps             DOUBLE PRECISION NOT NULL,
    reason          TEXT,
    PRIMARY KEY (symbol, reported)
);

-- One row per stock per evening run (analyses/<SYMBOL>/runs.csv, analysis/watchlist.py).
CREATE TABLE out_watchlist_run (
    symbol          TEXT NOT NULL,
    run_at          TIMESTAMP NOT NULL, -- UTC
    file            TEXT,               -- the dated PDF in analyses/<SYMBOL>/
    price           DOUBLE PRECISION,
    eps_adj_ttm     DOUBLE PRECISION,
    pe_adj          DOUBLE PRECISION,
    pe_median_10y   DOUBLE PRECISION,
    target_pe       DOUBLE PRECISION,
    entry_price     DOUBLE PRECISION,
    to_entry        DOUBLE PRECISION,   -- entry_price / price - 1
    verdict         TEXT,
    stakes_per_share DOUBLE PRECISION,
    PRIMARY KEY (symbol, run_at)
);

-- The watch list with each stock's latest run.
CREATE VIEW v_watchlist AS
SELECT w.symbol, w.position, w.target_pe, w.stakes_per_share, w.target_note,
       r.run_at AS last_run_at, r.price, r.eps_adj_ttm, r.pe_adj, r.pe_median_10y,
       r.entry_price, r.to_entry, r.verdict
FROM user_watchlist w
LEFT JOIN (
    SELECT o.*, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY run_at DESC) AS rn
    FROM out_watchlist_run o
) r ON r.symbol = w.symbol AND r.rn = 1;
