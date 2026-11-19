-- Migration 014: what the analysis scripts read now that they work on the database alone
-- (issue #33).
--
-- core_market_daily: the market report's indices, rates, commodities, currencies and sector
-- ETFs (config/market.toml), from Yahoo through the ingest (source yahoo_market); rebuilt by
-- every build, like core_price_daily.
--
-- v_earnings: Yahoo's earnings dates as last fetched (estimated and reported EPS per report
-- date; a future date has no reported EPS).
--
-- v_tv_latest: the newest TradingView snapshot of each request (the index members, and the
-- watch list's own symbols), with every screener field in extra_json.


CREATE TABLE core_market_daily (
    symbol          TEXT NOT NULL,      -- Yahoo's symbol, e.g. ^GSPC, XLK, EURUSD=X
    date            DATE NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    PRIMARY KEY (symbol, date)
);

CREATE VIEW v_earnings AS
SELECT DISTINCT ON (symbol, report_date) symbol, report_date, eps_estimate, eps_reported,
       surprise_pct, fetch_id
FROM raw_yahoo_earnings
ORDER BY symbol, report_date, fetch_id DESC;

CREATE VIEW v_tv_latest AS
SELECT f.request_key, f.fetched_at, c.*
FROM raw_tv_constituent c
JOIN raw_fetch f ON f.fetch_id = c.fetch_id
WHERE c.fetch_id IN (
    SELECT MAX(f2.fetch_id) FROM raw_fetch f2
    WHERE f2.source = 'tradingview' AND f2.status = 'ok'
      AND EXISTS (SELECT 1 FROM raw_tv_constituent c2 WHERE c2.fetch_id = f2.fetch_id)
    GROUP BY f2.request_key
);
