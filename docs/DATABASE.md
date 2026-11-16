# Database

Status: **schema version 3** (migrations `001` to `003`), 2026-11-16. **PostgreSQL 16**,
locally in Docker (`compose.yaml`) and later on the Oracle Cloud server. SQLite was dropped
on 2026-11-16 (see `docs/DECISIONS.md`). It holds the data already in `data/` and the watch
list. No API has been called to fill it, and no analysis reads it yet. The roadmap is
[issue #16](https://github.com/khalilvandian/Stock-analysis/issues/16).

The design follows how the project analyses a company:
- the absolute values first, for every fiscal year and as of any day
- the prices for technical analysis
- the screener's results, valuations, and the watch list with its evening runs
- a clear record of where every number came from

Only what those need is stored.

## Use

```bash
# once: put STOCK_DB_PASSWORD=<a long random value> in .env (see .env.example)
docker compose up -d --wait                     # PostgreSQL 16 on 127.0.0.1:5432, healthy
uv run python -m stock_analysis.db init         # create the tables (apply the migrations)
uv run python -m stock_analysis.db load-files   # import data/ and the watch list (no network)
uv run python -m stock_analysis.db build        # rebuild the core layer from raw
uv run python -m stock_analysis.db status       # rows per table
uv run python -m stock_analysis.db check        # connection, schema and data (see below)
```

Every command takes `--target local | server`. Without it, the `selected` target in
`config/database.toml` (`local`) is used, or `DATABASE_URL` if that is set.

Four queries answer most questions:

```sql
SELECT * FROM v_annual WHERE symbol = 'NEE' ORDER BY fiscal_year;       -- absolute values per year
SELECT * FROM v_daily  WHERE symbol = 'NEE' AND date = '2026-09-25';     -- as known that day
SELECT * FROM out_screener_result WHERE stage = 2 ORDER BY sector, rank_in_sector;
SELECT * FROM v_watchlist ORDER BY position;                              -- watch list, last run
```

- **Targets** (`config/database.toml`):

  | Target | What it is | Password |
  |---|---|---|
  | `local` | PostgreSQL 16 in Docker on this machine (`compose.yaml`), at `127.0.0.1:5432`, database `stock` | `STOCK_DB_PASSWORD` |
  | `server` | PostgreSQL on the Oracle Cloud server. The URL is empty until it exists | `STOCK_DB_PASSWORD` |

  Passwords are never in the config. A target reads its password from the environment
  variable named in `password_env`, and `.env` (gitignored) is read automatically.
- **Docker:** `compose.yaml` runs only the database. It uses the official `postgres:16`
  image, binds the port to `127.0.0.1` so only this machine can connect, keeps the data in
  the `stock-db` volume, and has a health check. Our migrations create the tables, not the
  container. `docker compose down` stops it and keeps the data; `down -v` deletes the data.
- **Not committed:** the database is never committed. The data lives in the Docker volume,
  and the repository holds only the code and the migrations that build it.
- **Rerunning:** `load-files` can be run again safely, and only stores what is new or
  changed. `build` rewrites core each time, in one transaction.
- **Code:** `src/stock_analysis/db/`, through SQLAlchemy and psycopg:
  - `__init__.py`: targets, the `Database` class, migrations, helpers
  - `migrations/`: numbered SQL files
  - `load_files.py`
  - `build.py`
  - `check.py`
- **Items:** `config/db_items.toml` lists the items and their source fields.
- **Tests:** `tests/test_db.py` runs on the `stock_test` database in the same container, or
  on `STOCK_TEST_PG_URL`. Every test empties that database first, so never point it at
  `stock`. Without a reachable PostgreSQL the database tests are skipped, and the rest of
  the suite still runs. To create the test database once:
  `docker compose exec db psql -U stock -c "CREATE DATABASE stock_test"`.

### Checking a database

`check` connects read-only to a target and prints PASS, WARN or FAIL for each check. It
exits 1 on any FAIL, and with `--strict` on any WARN too.

| Check | FAIL when | WARN when |
|---|---|---|
| connection | the target has no URL, or the server can't be reached | none |
| tables and views | any table or view in the migrations is missing | none |
| schema version | the database is behind the code | the database is ahead of the code |
| last build | there is no build, or it failed | none |
| rows per table | a core, user or out table that should have rows is empty | `raw_sec_*` or `out_valuation` is empty |
| newest price, S&P 500 snapshot, screener run | none | older than `max_age_days` (7) |
| S&P 500 members with prices and with fundamentals | none | below `min_coverage` (95%) |
| watch list | none | a stock has no evening run, or no prices in core |
| each of `sample_symbols` (NEE, DUK, SO) | not a company, no prices, or no fiscal year with revenue | the latest day lacks revenue, debt or cash |
| prices are positive; filed on or after the period end | any row breaks the rule | none |
| quality issues | any of severity `error` | none |

The settings are under `[check]` in `config/database.toml`.

Today, on `local`: 28 pass, 6 warn, 0 fail. The warnings are:
- prices 52 days old
- 6 and 30 of 497 members with prices and with fundamentals
- no SEC data yet
- the 5 watch list stocks have no prices in core, because there are no local price files
  for them

## SQL conventions

- **Types:** `DATE`, `TIMESTAMP` (UTC), `BOOLEAN`, `DOUBLE PRECISION`, `BIGINT`, `TEXT`.
- **Keys:** auto-numbered keys are `BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`.
- **Migrations:** `schema_version` records which migrations have been applied. A new
  change is a new numbered file, and existing ones are never edited. Opening a database
  applies any new ones, so an older database upgrades in place (`002` adds open, high and
  low; `003` adds the watch list).
- **Dates in Python:** reads return dates as `YYYY-MM-DD` text and timestamps as ISO text
  (`frame()` in `__init__.py`).
- **JSON:** the JSON columns are `TEXT`, and can become `jsonb` later.

## Layers

| Layer | Holds | Written by | Rule |
|---|---|---|---|
| `raw_*` | What each source returned, one table per source | The loaders (`load_files.py` now, API loaders later) | Append only. A row is stored when it is **new or its values changed** since the last version of the same key, and nothing is ever edited. Each row points to its `raw_fetch` |
| `core_*` | One cleaned, standard version: companies, index membership, daily prices, fundamentals with every filed version, trailing twelve months, quality issues | `build.py`, from raw and `config/db_items.toml` only | Rewritten on every build. `core_company` is updated in place so `company_id` stays the same |
| `user_*` | What people decide: the watch list (stocks, peers, target P/E, equity stakes, EPS corrections) | For now `load-files` mirrors `config/watchlist.toml`, the master copy. Later the interface edits these tables | Keyed by symbol. A changed TOML replaces the mirror, and an unchanged one changes nothing |
| `out_*` | Results of the analyses: screener runs, valuations, the watch list's evening runs | The analyses (for now `load_files.py`, from their output files) | Keyed by **symbol and date**, so an analysis can write without a build |
| `v_*` | Views for analysis | none | `v_annual`, `v_daily`, `v_watchlist`, `v_fundamental_latest` |

## UML class diagram

`<<table>>` is a stored table and `<<view>>` is a SQL view. Solid arrows are foreign keys,
one to many. Dotted arrows show where the build reads raw data, or where a view reads its
tables.

```mermaid
classDiagram
  class raw_fetch {
    <<table>>
    BIGINT fetch_id PK
    TEXT source
    TEXT request_key
    TEXT url
    TIMESTAMP fetched_at
    TIMESTAMP loaded_at
    TEXT status
    INTEGER row_count
    INTEGER rows_stored
    TEXT payload_sha256
    TEXT error
  }
  class raw_tv_constituent {
    <<table>>
    BIGINT fetch_id PK FK
    TEXT tv_symbol PK
    TEXT symbol
    TEXT name
    TEXT exchange
    TEXT sector
    TEXT industry
    TEXT country
    TEXT currency
    DOUBLE market_cap
    TEXT extra_json
  }
  class raw_sec_ticker {
    <<table>>
    TEXT ticker PK
    BIGINT fetch_id PK FK
    BIGINT cik
    TEXT title
  }
  class raw_yahoo_price {
    <<table>>
    TEXT symbol PK
    DATE date PK
    BIGINT fetch_id PK FK
    DOUBLE open
    DOUBLE high
    DOUBLE low
    DOUBLE close
    BIGINT volume
    DOUBLE dividends
    DOUBLE stock_splits
  }
  class raw_yahoo_statement {
    <<table>>
    BIGINT raw_id PK
    BIGINT fetch_id FK
    TEXT symbol
    TEXT statement
    TEXT frequency
    DATE period_end
    TEXT line_item
    DOUBLE value
  }
  class raw_project_history {
    <<table>>
    BIGINT raw_id PK
    BIGINT fetch_id FK
    TEXT symbol
    DATE fiscal_year_end
    TEXT item
    DOUBLE value
    TEXT source
  }
  class raw_sec_fact {
    <<table>>
    BIGINT raw_id PK
    BIGINT fetch_id FK
    BIGINT cik
    TEXT taxonomy
    TEXT tag
    TEXT unit
    DATE period_start
    DATE period_end
    DOUBLE value
    INTEGER fy
    TEXT fp
    TEXT form
    DATE filed
    TEXT accn
  }
  class core_build {
    <<table>>
    BIGINT build_id PK
    TIMESTAMP started_at
    TIMESTAMP finished_at
    TEXT git_sha
    BIGINT max_fetch_id
    TEXT status
    TEXT summary
  }
  class core_company {
    <<table>>
    BIGINT company_id PK
    TEXT symbol UK
    BIGINT cik UK
    TEXT name
    TEXT exchange
    TEXT sector
    TEXT industry
    TEXT currency
  }
  class core_index_member {
    <<table>>
    BIGINT company_id PK FK
    TEXT index_code PK
    DATE start_date PK
    DATE end_date
  }
  class core_item {
    <<table>>
    TEXT item PK
    TEXT label
    TEXT kind
    TEXT unit
    TEXT derive
  }
  class core_item_tag {
    <<table>>
    TEXT item PK FK
    TEXT taxonomy PK
    TEXT tag PK
    INTEGER priority
    DOUBLE scale
  }
  class core_price_daily {
    <<table>>
    BIGINT company_id PK FK
    DATE date PK
    DOUBLE open
    DOUBLE high
    DOUBLE low
    DOUBLE close
    DOUBLE adj_close
    BIGINT volume
    DOUBLE dividend
    DOUBLE split_ratio
  }
  class core_fundamental {
    <<table>>
    BIGINT company_id PK FK
    TEXT item PK FK
    TEXT period_type PK
    DATE period_end PK
    DATE filed PK
    BOOLEAN filed_estimated
    INTEGER fiscal_year
    TEXT fiscal_period
    DOUBLE value
    DOUBLE split_factor
    TEXT method
    TEXT source
    TEXT tag
    TEXT raw_table
    BIGINT raw_id
  }
  class core_fundamental_ttm {
    <<table>>
    BIGINT company_id PK FK
    TEXT item PK FK
    DATE period_end PK
    DATE filed PK
    BOOLEAN filed_estimated
    TEXT basis
    DOUBLE value
    DOUBLE value_adj
    TEXT source
  }
  class core_quality_issue {
    <<table>>
    BIGINT issue_id PK
    BIGINT build_id FK
    BIGINT company_id FK
    TEXT item
    DATE at_date
    TEXT check_name
    TEXT severity
    TEXT detail
  }
  class out_screener_run {
    <<table>>
    BIGINT run_id PK
    DATE run_date
    TEXT universe
    TIMESTAMP created_at
    TEXT source
  }
  class out_screener_result {
    <<table>>
    BIGINT run_id PK FK
    INTEGER stage PK
    TEXT symbol PK
    TEXT sector
    TEXT category
    TEXT status
    INTEGER rank_in_sector
    DOUBLE close
    DOUBLE cheap_price
    TEXT detail_json
  }
  class out_valuation {
    <<table>>
    TEXT symbol PK
    DATE as_of PK
    TEXT method PK
    DOUBLE fair_value
    DOUBLE price
    TEXT detail_json
    TEXT source
  }
  class user_watchlist {
    <<table>>
    TEXT symbol PK
    INTEGER position
    DOUBLE target_pe
    TEXT target_note
    DOUBLE stakes_per_share
  }
  class user_watchlist_peer {
    <<table>>
    TEXT symbol PK FK
    TEXT peer PK
    INTEGER position
  }
  class user_eps_override {
    <<table>>
    TEXT symbol PK FK
    DATE reported PK
    DOUBLE eps
    TEXT reason
  }
  class out_watchlist_run {
    <<table>>
    TEXT symbol PK
    TIMESTAMP run_at PK
    TEXT file
    DOUBLE price
    DOUBLE eps_adj_ttm
    DOUBLE pe_adj
    DOUBLE pe_median_10y
    DOUBLE target_pe
    DOUBLE entry_price
    DOUBLE to_entry
    TEXT verdict
    DOUBLE stakes_per_share
  }
  class v_watchlist {
    <<view>>
    each watch list stock with its latest run
  }
  class v_fundamental_latest {
    <<view>>
    latest filed version of each period
  }
  class v_annual {
    <<view>>
    company, fiscal_year
    the absolute values of that year
  }
  class v_daily {
    <<view>>
    company, date, close, adj_close
    the absolute values as known that day
    market_cap, net_debt, free_cf_ttm
  }

  raw_fetch "1" --> "*" raw_tv_constituent : fetch_id
  raw_fetch "1" --> "*" raw_sec_ticker : fetch_id
  raw_fetch "1" --> "*" raw_yahoo_price : fetch_id
  raw_fetch "1" --> "*" raw_yahoo_statement : fetch_id
  raw_fetch "1" --> "*" raw_project_history : fetch_id
  raw_fetch "1" --> "*" raw_sec_fact : fetch_id
  core_company "1" --> "*" core_index_member : company_id
  core_company "1" --> "*" core_price_daily : company_id
  core_company "1" --> "*" core_fundamental : company_id
  core_company "1" --> "*" core_fundamental_ttm : company_id
  core_company "1" --> "*" core_quality_issue : company_id
  core_item "1" --> "*" core_item_tag : item
  core_item "1" --> "*" core_fundamental : item
  core_build "1" --> "*" core_quality_issue : build_id
  out_screener_run "1" --> "*" out_screener_result : run_id
  user_watchlist "1" --> "*" user_watchlist_peer : symbol
  user_watchlist "1" --> "*" user_eps_override : symbol
  v_watchlist ..> user_watchlist : reads
  v_watchlist ..> out_watchlist_run : latest run
  raw_tv_constituent ..> core_company : builds
  raw_tv_constituent ..> core_index_member : builds
  raw_sec_ticker ..> core_company : adds cik
  raw_yahoo_price ..> core_price_daily : builds
  raw_yahoo_statement ..> core_fundamental : raw_table + raw_id
  raw_project_history ..> core_fundamental : raw_table + raw_id
  raw_sec_fact ..> core_fundamental : raw_table + raw_id
  core_fundamental ..> core_fundamental_ttm : builds
  v_fundamental_latest ..> core_fundamental : reads
  v_annual ..> v_fundamental_latest : reads
  v_daily ..> core_price_daily : reads
  v_daily ..> core_fundamental_ttm : as of filed date
```

## What is in it now

From the repository files, 2026-11-16 (28 MB):

| Table | Rows | Contents |
|---|---|---|
| `raw_yahoo_price` | 46,769 | Daily open, high, low, close, volume, dividends and splits for NEE, DUK, SO, NRG, VST, CEG and TLN, all history to 2026-09-25 |
| `raw_yahoo_statement` | 11,145 | The Yahoo statements of the same 7 companies |
| `raw_tv_constituent` | 4,470 | The 9 TradingView S&P 500 snapshots, 2026-10-27 to 2026-11-13, with all 116 columns |
| `raw_project_history` | 12,562 | `data/sector/history.csv`: 102 utilities, fiscal years 2016–2025 |
| `raw_sec_fact`, `raw_sec_ticker` | 0 | Need the SEC API |
| `core_company`, `core_index_member` | 499, 499 | 497 current S&P 500 members and 2 that left. No CIKs yet |
| `core_price_daily` | 14,475 | The 6 S&P 500 companies with local prices, from 2016-01-04 |
| `core_fundamental` | 3,518 | 30 companies (17 items) |
| `core_fundamental_ttm` | 3,352 | Trailing figures |
| `core_quality_issue` | 122 | Last build |
| `out_screener_result` | 527 | The 2026-11-13 run: 497 from Stage 1, 30 from Stage 2 |
| `user_watchlist`, `user_watchlist_peer`, `user_eps_override` | 5, 41, 11 | `config/watchlist.toml`: BSX, BKNG, NFLX, GOOGL, UBER |
| `out_watchlist_run` | 52 | `analyses/<SYMBOL>/runs.csv`, 2026-10-27 to 2026-11-13 (times in UTC) |
| `out_valuation` | 97 | DCF fair values from `utilities.csv` and the peer tables, 2026-09-28 to 2026-10-27 |

## Tables

### Raw

| Table | One row per | Notes |
|---|---|---|
| `raw_fetch` | Download or imported file | `source` is one of `tradingview`, `yahoo_prices`, `yahoo_statements`, `project_history`, `sec_tickers` or `sec_companyfacts`. `url` is `file:<path>` for a repository file. `row_count` is the rows received and `rows_stored` the rows that were new or changed. A file with the same SHA-256 as one loaded before is skipped |
| `raw_tv_constituent` | Company in one S&P 500 snapshot | The whole snapshot is stored, since its prices change daily. `extra_json` holds the columns that have no field of their own |
| `raw_yahoo_price` | Symbol, day and version | Open, high, low and close (split-adjusted), volume, dividends and splits. The dividend-adjusted close is **computed in core**, so a dividend does not rewrite the history here, and Yahoo's own adjusted close isn't stored. Open, high and low were added by migration `002` for technical analysis |
| `raw_yahoo_statement` | Line item, period and version | Yahoo's own names (`Total Revenue`) |
| `raw_project_history` | Value in `history.csv` and version | As in the file: money in $bn |
| `raw_sec_fact` | XBRL fact and version | Only the tags in `config/db_items.toml`. A tag added later is fetched again from SEC, which is free and takes a few minutes |

### Core

| Table | One row per | Notes |
|---|---|---|
| `core_company` | Company | By `company_id`. `symbol` comes from TradingView, and `cik` is filled once the SEC ticker file is loaded |
| `core_index_member` | Run of consecutive snapshots a company was in | An empty `end_date` means it is still a member. Membership history only starts at the first snapshot (2026-10-27) |
| `core_item`, `core_item_tag` | Item, and item plus source field | From the config, on every build |
| `core_price_daily` | Company and trading day, from 2016-01-01 | `adj_close` = close × the product of (1 − dividend ÷ prior close) over later ex-dates. That is Yahoo's method, and on the local data it matches Yahoo's figure to within 1e-6 |
| `core_fundamental` | Company, item, period and **filing date** | Every version is kept. `period_type` is `Q`, `FY` or `I` (instant). `method` is `reported` or `derived`. `raw_table` and `raw_id` name the raw row |
| `core_fundamental_ttm` | Company, item, period end and filing date | Trailing twelve months **for each version**, so a restated quarter gives a second value from the day it was filed. `value_adj` is on today's share basis |
| `core_quality_issue` | Problem found by a build | Kept for every build |
| `core_build` | Build | Raw data used, git commit, row counts or the error |

### Out

| Table | One row per | Notes |
|---|---|---|
| `out_screener_run` | Screener run (date and universe) | Today only the latest run exists as files. Every evening run will add one |
| `out_screener_result` | Symbol in Stage 1 or Stage 2 of a run | The fields the site and email show (sector, category, status, rank, close, cheap price). Every other column goes in `detail_json` |
| `out_watchlist_run` | Watch list stock and evening run | Price, adjusted EPS (12 months), P/E, 10-year median P/E, target P/E, entry price, distance to entry, the verdict. `run_at` is UTC, converted from the Rome time in `runs.csv` |
| `out_valuation` | Symbol, date and method | Fair value per share, the price, and the inputs (WACC, cash flow) in `detail_json` |

### User

| Table | One row per | Notes |
|---|---|---|
| `user_watchlist` | Watch list stock | `position` (order), `target_pe`, `target_note`, `stakes_per_share` |
| `user_watchlist_peer` | Stock and peer | The sector peers for the ratios and screens, in order |
| `user_eps_override` | Stock and report date | One-off corrections to a quarter's adjusted EPS, with the reason |

### Views

| View | One row per | Gives |
|---|---|---|
| `v_annual` | Company and fiscal year | The absolute values in their latest filed version: revenue, EBITDA, net income, EPS, operating cash flow, capex, free cash flow, interest, cash, the three debts, net debt, assets, liabilities, equity and shares. Shares and EPS are on today's basis. This is what `absolute.py --history` shows |
| `v_daily` | Company and trading day | The close, the adjusted close and the absolute values as known that day. Flows are trailing twelve months (`_ttm`). Also `market_cap`, `net_debt` and `free_cf_ttm` |
| `v_watchlist` | Watch list stock | Its settings and its latest evening run (price, P/E, entry price, distance to entry, verdict) |
| `v_fundamental_latest` | Company, item and period | The latest filed version |

## The 17 items

The full field lists are in `config/db_items.toml`.

| Item | Kind | Derived as | Yahoo (first field) | history.csv |
|---|---|---|---|---|
| `revenue` | flow | none | Total Revenue | revenue |
| `operating_income` | flow | none | Operating Income | none |
| `d_and_a` | flow | none | Reconciled Depreciation | none |
| `ebitda` | flow | operating_income + d_and_a (as `analysis/history.py`) | EBITDA (fallback) | ebitda |
| `net_income` | flow | none | Net Income | net_income |
| `eps_diluted` | flow | none | Diluted EPS | eps |
| `interest_expense` | flow | none | Interest Expense | none |
| `operating_cf` | flow | none | Operating Cash Flow | operating_cf |
| `capex` | flow, negative | none | Capital Expenditure | capex |
| `cash` | instant | none | Cash And Cash Equivalents | cash |
| `short_term_debt` | instant | none | Current Debt | short_term_debt |
| `long_term_debt` | instant | none | Long Term Debt | long_term_debt |
| `total_debt` | instant | short_term_debt + long_term_debt | Total Debt (fallback) | total_debt |
| `total_assets` | instant | none | Total Assets | none |
| `total_liabilities` | instant | none | Total Liabilities Net Minority Interest | none |
| `equity` | instant | none | Stockholders Equity | none |
| `shares_outstanding` | instant | none | Ordinary Shares Number | none |

Free cash flow, net debt and market value are calculated in the views, not stored.

## Build rules

1. **Companies:** core covers companies in the TradingView S&P 500 snapshots. Raw keeps
   everything else too, such as TLN and the non-S&P 500 utilities.
2. **One source per period:** for each company, item, period type and period end, the build
   takes the best source (SEC, then `history.csv`, then Yahoo), then the first field in the
   config order. It keeps every filing date (version) of that source.
3. **Derived items:** a derived item (`ebitda`, `total_debt`) is computed wherever all its
   parts exist. It replaces a reported value from the same or a lower-ranked source, never
   one from a better source. For example, `history.csv`'s SEC EBITDA is not overridden by
   Yahoo's operating income + D&A.
4. **Periods:** the fiscal quarter is counted from the company's fiscal year-end month, with
   52/53-week ends rounded to the nearest month end. Balance-sheet items are `I` whatever
   file they came from.
5. **Filing dates:** no source loaded so far records filing dates. They are estimated as
   the period end plus the latest SEC deadline (90 days after a year, 45 after a quarter)
   and marked `filed_estimated`. The view can show a figure late but never early. SEC
   facts will bring real dates.
6. **Splits:** Yahoo shares and EPS are adjusted for the splits after their filing date.
   `history.csv` is meant to be adjusted already (see the caveat below).
7. **Trailing twelve months:** at a fiscal year end, the fiscal-year value. Otherwise, the
   sum of four consecutive quarters (ends 250–300 days apart), using each quarter's
   latest version as of each filing date.
8. **Checks** (`core_quality_issue`, last build):

| Check | Count | Meaning |
|---|---|---|
| `jump_10x` | 50 | A value moved more than 10× from one period to the next |
| `sources_disagree` | 48 | `history.csv` and Yahoo differ by more than 2% for the same period |
| `balance_sheet_identity` | 13 | Assets − liabilities − equity is more than 2% of assets (minority interest at NEE and SO) |
| `implied_shares_jump` | 6 | Net income ÷ EPS moved 1.8× or more in a year, usually a split not applied to EPS |
| `missing_period` | 5 | A quarter or year is missing |
| `short_trading_year` | 0 | Fewer than 200 trading days in a full year |

**Caveat found by these checks:** `history.csv` has EPS and market value that were never
split-adjusted. NEE's EPS for 2016–2017 is in pre-2020-split shares (6.24 and 11.39 against
3.47 in 2018), and so is its 2016–2017 market value. ETR and SRE look the same. The cause is
in `analysis/history.py`'s `split_adjust`, not in the database. The database stores the file
as it is and flags it.

## Not done yet

- **API loaders:**
  - TradingView daily
  - the SEC ticker file (gives the CIKs)
  - SEC company facts (10 years, real filing dates)
  - Yahoo prices for the whole S&P 500 from 2016, fetching only new days
- **Analyses writing to `out_*`:** the evening run and the screener writing their results
  to the database.
- **Readers:** no analysis, dashboard or the site reads the database yet.
- **Server:** PostgreSQL, run with the same migration.
- **Older index membership:** S&P 500 membership before 2026-10-27, needed before any
  backtest.
