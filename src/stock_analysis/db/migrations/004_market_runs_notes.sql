-- Migration 004: the market report's evening runs and Claude's notes, so every analysis
-- output in the repository also lives in the database.

-- One row per evening market report (analyses/market/runs.csv).
CREATE TABLE out_market_run (
    run_at          TIMESTAMP PRIMARY KEY,  -- UTC
    file            TEXT,                   -- the dated PDF in analyses/market/
    sp500           DOUBLE PRECISION,       -- S&P 500 close
    sp500_day       DOUBLE PRECISION,       -- its change that day
    vix             DOUBLE PRECISION,
    above_200d      DOUBLE PRECISION,       -- share of S&P 500 stocks above their 200-day average
    stocks_to_look_at TEXT,                 -- space-separated symbols
    screener_date   DATE,
    screener_passed INTEGER,
    screener_screened INTEGER,
    screener_listed INTEGER
);

-- Notes written by Claude or by hand (analyses/<SUBJECT>/notes.md, or through the API).
-- subject is a symbol, 'market' or 'summaries'. Every version is kept.
CREATE TABLE out_note (
    subject         TEXT NOT NULL,
    updated_at      TIMESTAMP NOT NULL,     -- UTC
    text            TEXT NOT NULL,
    source          TEXT,                   -- 'file:analyses/NFLX/notes.md', or 'api'
    PRIMARY KEY (subject, updated_at)
);

-- The latest version of each subject's notes.
CREATE VIEW v_note_latest AS
SELECT subject, updated_at, text, source
FROM (
    SELECT n.*, ROW_NUMBER() OVER (PARTITION BY subject ORDER BY updated_at DESC) AS rn
    FROM out_note n
) latest
WHERE rn = 1;
