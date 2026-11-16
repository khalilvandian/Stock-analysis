-- Migration 002: daily open, high and low, for technical analysis (ranges, candles, ATR,
-- 52-week highs and lows). Split-adjusted, like close.

ALTER TABLE raw_yahoo_price ADD COLUMN open DOUBLE PRECISION;
ALTER TABLE raw_yahoo_price ADD COLUMN high DOUBLE PRECISION;
ALTER TABLE raw_yahoo_price ADD COLUMN low DOUBLE PRECISION;

ALTER TABLE core_price_daily ADD COLUMN open DOUBLE PRECISION;
ALTER TABLE core_price_daily ADD COLUMN high DOUBLE PRECISION;
ALTER TABLE core_price_daily ADD COLUMN low DOUBLE PRECISION;
