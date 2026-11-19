-- Migration 013: intraday quotes (issue #35). 011 and 012 are kept for the orchestrator
-- branch (issue #30). Every hour while the US market can be open, one TradingView request
-- returns the last price of every company in the universe (15 minutes delayed). The daily
-- close in core_price_daily (Yahoo) stays the price of record; the quotes are what the
-- explorer's summary shows between two closes, and every price-dependent value on the page
-- is recomputed from them.

CREATE TABLE raw_tv_quote (
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    tv_symbol       TEXT NOT NULL,      -- 'NASDAQ:AAPL'
    symbol          TEXT NOT NULL,
    price           DOUBLE PRECISION NOT NULL CHECK (price > 0),  -- last trade, regular session
    change_pct      DOUBLE PRECISION,   -- against the previous close, in %
    change_abs      DOUBLE PRECISION,
    volume          DOUBLE PRECISION,   -- the day's so far
    currency        TEXT,
    session         TEXT,               -- market | pre_market | post_market | out_of_session
    delay_s         INTEGER NOT NULL,   -- how old TradingView says the price is (900 = 15 min)
    PRIMARY KEY (fetch_id, tv_symbol)
);
CREATE INDEX raw_tv_quote_symbol ON raw_tv_quote (symbol, fetch_id DESC);

-- The newest quote of each company. Read straight from raw on purpose: a quote is shown as it
-- came, and rebuilding core every hour for it would cost far more than it adds.
-- price_at (UTC) = the fetch time less TradingView's delay while the market is open; outside
-- the session the price is the latest close and price_at is empty.
CREATE VIEW v_quote_latest AS
SELECT DISTINCT ON (q.symbol)
       q.symbol, c.company_id, q.price, q.change_pct, q.change_abs, q.volume, q.currency,
       q.session, q.delay_s, f.fetched_at,
       CASE WHEN q.session = 'market'
            THEN f.fetched_at - make_interval(secs => q.delay_s) END AS price_at,
       q.fetch_id
FROM raw_tv_quote q
JOIN raw_fetch f ON f.fetch_id = q.fetch_id
LEFT JOIN core_company c ON c.symbol = q.symbol
ORDER BY q.symbol, q.fetch_id DESC;
