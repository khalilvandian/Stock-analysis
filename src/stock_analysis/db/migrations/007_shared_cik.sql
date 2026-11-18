-- Migration 007: two listed share classes of one company share its SEC CIK (issue #29).
-- GOOG and GOOGL, FOX and FOXA, NWS and NWSA are separate S&P 500 members with one set of
-- filings; with a unique CIK only one class got the company's fundamentals.

ALTER TABLE core_company DROP CONSTRAINT core_company_cik_key;
CREATE INDEX core_company_cik ON core_company (cik);
