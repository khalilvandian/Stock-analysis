-- Stock analysis database, migration 001 (docs/DATABASE.md).
-- Written to run on SQLite and PostgreSQL: {{ID}} becomes the dialect's auto-numbered key.
--
-- raw_*  : what each source returned. Append only; a row is added when it is new or its
--          values changed, never edited.
-- core_* : the cleaned, standard layer, rewritten by the build from raw.
-- out_*  : results of the analyses (screener runs, valuations), by symbol.
-- v_*    : views for analysis.

CREATE TABLE schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at      TIMESTAMP NOT NULL
);

-- ---------------------------------------------------------------- raw

CREATE TABLE raw_fetch (
    fetch_id        {{ID}},
    source          TEXT NOT NULL,      -- tradingview | yahoo_prices | yahoo_statements | project_history | sec_tickers | sec_companyfacts
    request_key     TEXT NOT NULL,      -- symbol, CIK, index ('SP:SPX') or file name
    url             TEXT,               -- the URL, or 'file:<path>' for a file from the repo
    fetched_at      TIMESTAMP NOT NULL, -- when the source returned the data
    loaded_at       TIMESTAMP NOT NULL,
    status          TEXT NOT NULL CHECK (status IN ('ok', 'empty', 'error')),
    row_count       INTEGER,            -- rows received
    rows_stored     INTEGER,            -- rows that were new or changed
    payload_sha256  TEXT,
    error           TEXT
);
CREATE UNIQUE INDEX raw_fetch_once ON raw_fetch (source, request_key, payload_sha256)
    WHERE payload_sha256 IS NOT NULL;

-- One full snapshot per fetch (prices and fundamentals change daily, so nothing to dedupe).
CREATE TABLE raw_tv_constituent (
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    tv_symbol       TEXT NOT NULL,      -- 'NASDAQ:AAPL'
    symbol          TEXT NOT NULL,
    name            TEXT,
    exchange        TEXT,
    sector          TEXT,
    industry        TEXT,
    country         TEXT,
    currency        TEXT,
    market_cap      DOUBLE PRECISION,
    extra_json      TEXT,               -- every other column, as returned
    PRIMARY KEY (fetch_id, tv_symbol)
);

CREATE TABLE raw_sec_ticker (
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    ticker          TEXT NOT NULL,
    cik             BIGINT NOT NULL,
    title           TEXT,
    PRIMARY KEY (ticker, fetch_id)
);

-- close is split-adjusted as Yahoo returns it. The dividend-adjusted close is computed in
-- core, so a new dividend does not rewrite the whole history here.
CREATE TABLE raw_yahoo_price (
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    symbol          TEXT NOT NULL,
    date            DATE NOT NULL,
    close           DOUBLE PRECISION,
    volume          BIGINT,
    dividends       DOUBLE PRECISION,
    stock_splits    DOUBLE PRECISION,
    PRIMARY KEY (symbol, date, fetch_id)
);

CREATE TABLE raw_yahoo_statement (
    raw_id          {{ID}},
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    symbol          TEXT NOT NULL,
    statement       TEXT NOT NULL CHECK (statement IN ('income', 'balance_sheet', 'cash_flow')),
    frequency       TEXT NOT NULL CHECK (frequency IN ('annual', 'quarterly')),
    period_end      DATE NOT NULL,
    line_item       TEXT NOT NULL,      -- Yahoo's name, e.g. 'Total Revenue'
    value           DOUBLE PRECISION NOT NULL
);
CREATE INDEX raw_yahoo_statement_key ON raw_yahoo_statement (symbol, statement, frequency, period_end, line_item);

CREATE TABLE raw_project_history (
    raw_id          {{ID}},
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    symbol          TEXT NOT NULL,
    fiscal_year_end DATE NOT NULL,
    item            TEXT NOT NULL,      -- the file's column name
    value           DOUBLE PRECISION NOT NULL,   -- money in $bn, per share split-adjusted
    source          TEXT                -- 'SEC', 'Yahoo', 'Yahoo price x SEC shares'
);
CREATE INDEX raw_project_history_key ON raw_project_history (symbol, fiscal_year_end, item);

CREATE TABLE raw_sec_fact (
    raw_id          {{ID}},
    fetch_id        BIGINT NOT NULL REFERENCES raw_fetch (fetch_id),
    cik             BIGINT NOT NULL,
    taxonomy        TEXT NOT NULL,      -- us-gaap | dei | ifrs-full
    tag             TEXT NOT NULL,
    unit            TEXT NOT NULL,
    period_start    DATE,               -- empty for balance-sheet facts
    period_end      DATE NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    fy              INTEGER,
    fp              TEXT,
    form            TEXT,
    filed           DATE NOT NULL,
    accn            TEXT NOT NULL
);
CREATE INDEX raw_sec_fact_key ON raw_sec_fact (cik, taxonomy, tag, period_end);

-- ---------------------------------------------------------------- core

CREATE TABLE core_build (
    build_id        {{ID}},
    started_at      TIMESTAMP NOT NULL,
    finished_at     TIMESTAMP,
    git_sha         TEXT,
    max_fetch_id    BIGINT,
    status          TEXT NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    summary         TEXT                -- JSON: rows per table, or the error
);

CREATE TABLE core_company (
    company_id      {{ID}},             -- kept across builds
    symbol          TEXT NOT NULL UNIQUE,
    cik             BIGINT UNIQUE,      -- empty until the SEC ticker file is loaded
    name            TEXT,
    exchange        TEXT,
    sector          TEXT,               -- TradingView's sectors
    industry        TEXT,
    currency        TEXT
);

-- Spells of index membership seen in the snapshots; end_date empty = still a member.
CREATE TABLE core_index_member (
    company_id      BIGINT NOT NULL REFERENCES core_company (company_id),
    index_code      TEXT NOT NULL,      -- 'SP:SPX'
    start_date      DATE NOT NULL,      -- first snapshot it was in (the history starts with the first snapshot)
    end_date        DATE,               -- last snapshot it was in, if it has left
    PRIMARY KEY (company_id, index_code, start_date)
);

CREATE TABLE core_item (
    item            TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('flow', 'instant')),
    unit            TEXT NOT NULL,
    derive          TEXT                -- 'a + b': computed from other items when they exist
);

CREATE TABLE core_item_tag (
    item            TEXT NOT NULL REFERENCES core_item (item),
    taxonomy        TEXT NOT NULL,      -- us-gaap | dei | history | yahoo
    tag             TEXT NOT NULL,
    priority        INTEGER NOT NULL,   -- 1 is tried first
    scale           DOUBLE PRECISION NOT NULL DEFAULT 1,
    PRIMARY KEY (item, taxonomy, tag)
);

CREATE TABLE core_price_daily (
    company_id      BIGINT NOT NULL REFERENCES core_company (company_id),
    date            DATE NOT NULL,
    close           DOUBLE PRECISION,   -- split-adjusted
    adj_close       DOUBLE PRECISION,   -- split- and dividend-adjusted (total return)
    volume          BIGINT,
    dividend        DOUBLE PRECISION,
    split_ratio     DOUBLE PRECISION,   -- empty on days without a split
    PRIMARY KEY (company_id, date)
);

-- Every version of every value: a restated period has one row per filing date.
CREATE TABLE core_fundamental (
    company_id      BIGINT NOT NULL REFERENCES core_company (company_id),
    item            TEXT NOT NULL REFERENCES core_item (item),
    period_type     TEXT NOT NULL CHECK (period_type IN ('Q', 'FY', 'I')),  -- quarter, fiscal year, instant
    period_end      DATE NOT NULL,
    filed           DATE NOT NULL,      -- when the value became public
    filed_estimated BOOLEAN NOT NULL DEFAULT FALSE,
    fiscal_year     INTEGER,
    fiscal_period   TEXT,               -- Q1..Q4, FY
    value           DOUBLE PRECISION NOT NULL,   -- as reported
    split_factor    DOUBLE PRECISION NOT NULL DEFAULT 1,  -- splits after filing (shares, per share)
    method          TEXT NOT NULL,      -- reported | derived
    source          TEXT NOT NULL,      -- sec | history:SEC | history:Yahoo | yahoo | derived
    tag             TEXT,               -- the source field
    raw_table       TEXT,               -- the raw row it came from (empty when derived)
    raw_id          BIGINT,
    PRIMARY KEY (company_id, item, period_type, period_end, filed)
);

-- Trailing twelve months, for each version: at a fiscal year end the fiscal-year value,
-- otherwise the sum of four quarters as known on `filed`; instants as they are.
CREATE TABLE core_fundamental_ttm (
    company_id      BIGINT NOT NULL REFERENCES core_company (company_id),
    item            TEXT NOT NULL REFERENCES core_item (item),
    period_end      DATE NOT NULL,
    filed           DATE NOT NULL,
    filed_estimated BOOLEAN NOT NULL,
    basis           TEXT NOT NULL CHECK (basis IN ('fy', '4q', 'instant')),
    value           DOUBLE PRECISION NOT NULL,   -- as reported
    value_adj       DOUBLE PRECISION NOT NULL,   -- on today's share basis
    source          TEXT NOT NULL,
    PRIMARY KEY (company_id, item, period_end, filed)
);
CREATE INDEX core_fundamental_ttm_asof ON core_fundamental_ttm (company_id, item, period_end, filed);

CREATE TABLE core_quality_issue (
    issue_id        {{ID}},
    build_id        BIGINT NOT NULL REFERENCES core_build (build_id),
    company_id      BIGINT REFERENCES core_company (company_id),
    item            TEXT,
    at_date         DATE,
    check_name      TEXT NOT NULL,
    severity        TEXT NOT NULL CHECK (severity IN ('info', 'warn', 'error')),
    detail          TEXT
);

-- ---------------------------------------------------------------- out (analysis results)

CREATE TABLE out_screener_run (
    run_id          {{ID}},
    run_date        DATE NOT NULL,
    universe        TEXT NOT NULL,      -- 'SP:SPX'
    created_at      TIMESTAMP NOT NULL,
    source          TEXT,               -- the script or file that produced it
    UNIQUE (run_date, universe)
);

CREATE TABLE out_screener_result (
    run_id          BIGINT NOT NULL REFERENCES out_screener_run (run_id),
    stage           INTEGER NOT NULL CHECK (stage IN (1, 2)),
    symbol          TEXT NOT NULL,
    sector          TEXT,
    category        TEXT,               -- Lynch category
    status          TEXT,               -- Stage 1: pass | fail | ...
    rank_in_sector  INTEGER,            -- Stage 2
    close           DOUBLE PRECISION,
    cheap_price     DOUBLE PRECISION,   -- Stage 2
    detail_json     TEXT,               -- every other column of the result
    PRIMARY KEY (run_id, stage, symbol)
);

CREATE TABLE out_valuation (
    symbol          TEXT NOT NULL,
    as_of           DATE NOT NULL,
    method          TEXT NOT NULL,      -- e.g. the DCF method
    fair_value      DOUBLE PRECISION,   -- per share
    price           DOUBLE PRECISION,
    detail_json     TEXT,               -- inputs: WACC, cash flow, growth
    source          TEXT,
    PRIMARY KEY (symbol, as_of, method)
);

-- ---------------------------------------------------------------- views

-- The latest filed version of each period.
CREATE VIEW v_fundamental_latest AS
SELECT company_id, item, period_type, period_end, filed, filed_estimated, fiscal_year,
       fiscal_period, value, split_factor, method, source, tag
FROM (
    SELECT f.*, ROW_NUMBER() OVER (
        PARTITION BY company_id, item, period_type, period_end ORDER BY filed DESC) AS rn
    FROM core_fundamental f
) latest
WHERE rn = 1;

-- One row per company and fiscal year: the absolute values as reported in the latest
-- filing (flows for the year, balance sheet at the year end; shares and EPS on today's basis).
CREATE VIEW v_annual AS
SELECT f.company_id, c.symbol, f.fiscal_year,
       MAX(CASE WHEN f.period_type = 'FY' THEN f.period_end END) AS period_end,
       MAX(CASE WHEN f.item = 'revenue' THEN f.value END) AS revenue,
       MAX(CASE WHEN f.item = 'ebitda' THEN f.value END) AS ebitda,
       MAX(CASE WHEN f.item = 'net_income' THEN f.value END) AS net_income,
       MAX(CASE WHEN f.item = 'eps_diluted' THEN f.value / f.split_factor END) AS eps_diluted,
       MAX(CASE WHEN f.item = 'operating_cf' THEN f.value END) AS operating_cf,
       MAX(CASE WHEN f.item = 'capex' THEN f.value END) AS capex,
       MAX(CASE WHEN f.item = 'operating_cf' THEN f.value END)
         + MAX(CASE WHEN f.item = 'capex' THEN f.value END) AS free_cf,
       MAX(CASE WHEN f.item = 'interest_expense' THEN f.value END) AS interest_expense,
       MAX(CASE WHEN f.item = 'cash' THEN f.value END) AS cash,
       MAX(CASE WHEN f.item = 'short_term_debt' THEN f.value END) AS short_term_debt,
       MAX(CASE WHEN f.item = 'long_term_debt' THEN f.value END) AS long_term_debt,
       MAX(CASE WHEN f.item = 'total_debt' THEN f.value END) AS total_debt,
       MAX(CASE WHEN f.item = 'total_debt' THEN f.value END)
         - MAX(CASE WHEN f.item = 'cash' THEN f.value END) AS net_debt,
       MAX(CASE WHEN f.item = 'total_assets' THEN f.value END) AS total_assets,
       MAX(CASE WHEN f.item = 'total_liabilities' THEN f.value END) AS total_liabilities,
       MAX(CASE WHEN f.item = 'equity' THEN f.value END) AS equity,
       MAX(CASE WHEN f.item = 'shares_outstanding' THEN f.value * f.split_factor END) AS shares_outstanding
FROM v_fundamental_latest f
JOIN core_company c ON c.company_id = f.company_id
WHERE f.period_type = 'FY' OR (f.period_type = 'I' AND f.fiscal_period = 'Q4')
GROUP BY f.company_id, c.symbol, f.fiscal_year;

-- One row per company and trading day: the price and the absolute values as known that day
-- (the latest period whose value was filed on or before the day, in its latest version by
-- then), on today's share basis. Flows end in _ttm (trailing twelve months).
CREATE VIEW v_daily AS
SELECT d.*,
       d.close * d.shares_outstanding        AS market_cap,
       d.total_debt - d.cash                 AS net_debt,
       d.operating_cf_ttm + d.capex_ttm      AS free_cf_ttm
FROM (
    SELECT p.company_id, c.symbol, p.date, p.close, p.adj_close, p.volume,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'revenue' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS revenue_ttm,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'ebitda' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS ebitda_ttm,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'net_income' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS net_income_ttm,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'eps_diluted' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS eps_diluted_ttm,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'operating_cf' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS operating_cf_ttm,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'capex' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS capex_ttm,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'cash' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS cash,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'short_term_debt' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS short_term_debt,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'long_term_debt' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS long_term_debt,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'total_debt' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS total_debt,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'equity' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS equity,
        (SELECT t.value_adj FROM core_fundamental_ttm t WHERE t.company_id = p.company_id
            AND t.item = 'shares_outstanding' AND t.filed <= p.date ORDER BY t.period_end DESC, t.filed DESC LIMIT 1) AS shares_outstanding
    FROM core_price_daily p
    JOIN core_company c ON c.company_id = p.company_id
) d;
