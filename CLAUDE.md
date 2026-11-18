# Stock Analysis

Python 3.11+ project managed with `uv`. Source in `src/stock_analysis/`, tests in `tests/`.

- Market data: `stock_analysis.fetch` (Yahoo Finance via yfinance) saves CSVs to `data/<SYMBOL>/`. `FMPClient` wraps Financial Modeling Prep, but the free plan blocks most symbols (HTTP 402)
  and the current key is rejected as invalid, so Yahoo, SEC EDGAR, TradingView and the ECB are
  the working sources. SEC also comes in bulk (`companyfacts.zip`, the quarterly Financial
  Statement Data Sets): files downloaded by hand wait in `inbox/<kind>/` (never committed)
  and are loaded with `uv run python -m stock_analysis.db import FILE [--target server]`
  (docs/INGEST.md), which marks their tasks fetched so the job doesn't download them again.
  Every payload is kept as received (`raw_payload`); `db reparse` re-reads kept SEC files
  after a tag mapping change. edgartools reads full filings (source `sec_xbrl`).
- The API key is read from the `FMP_API_KEY` env var. Never hardcode or commit it. The SEC
  downloader identifies itself with `SEC_USER_AGENT`; never hardcode a personal email.
- Setup for new sessions and environments: `docs/SETUP.md`. The full documentation
  (architecture, entities, every process, the screener rules, decisions, operations) starts
  at `docs/README.md`; keep it matching the code when either changes. The pipeline diagram is
  `docs/pipeline.html` (hand-drawn SVG, published as a Claude artifact); update it and republish
  it in the same change that adds, moves or reschedules a piece.
- Database (issue #16): PostgreSQL 16. `config/database.toml` selects the target: `local` =
  Docker on this machine (`docker compose up -d --wait`, data in the `stock-db` volume, never
  committed), `server` = Azure Database for PostgreSQL `stock-db-bk` (Azure for Students;
  `allow-my-ip` when the home IP changes); passwords only from .env (`STOCK_DB_PASSWORD`,
  `STOCK_SERVER_DB_PASSWORD`). Raw, core, user (watch list, mirrored from
  `config/watchlist.toml`) and out layers through SQLAlchemy; schema and rules in
  `docs/DATABASE.md`, items in `config/db_items.toml`. `uv run python -m stock_analysis.db
  load-files`, then `build`, then `check` (each takes `--target`; `ping` diagnoses a
  connection). The ingest job (issue #18, `docs/INGEST.md`) fills it on a schedule: `db ingest`
  (TradingView, SEC, Yahoo, ECB; backfill until the S&P 500 is complete, then maintenance),
  running as the Azure Container Apps Job `stock-ingest`; `db coverage` measures completeness
  against `config/coverage.toml` (`docs/COVERAGE.md`), shown on the site's Data page. To read or write data in a script or analysis, use `stock_analysis.data.Data.open()`
  (reads as `stock_reader`, writes as `stock_writer`; `data.sql(...)` for any read-only query). On a
  PC it connects to the database directly; in cloud sessions it goes through the web API
  (`api/`, https://stock-api-bk.azurewebsites.net, used when `STOCK_API_URL` is set). The existing files stay, so older scripts keep working.
- Orchestration (issue #30, `docs/ORCHESTRATION.md`): the Airflow 3 DAG `stock_nightly`
  (`orchestration/`, Docker on the PC) waits for the ingest job, checks the prices, sets the
  ready marker the evening session reads (`python -m stock_analysis.pipeline marker`), waits
  for the evening commit and the site, logs each step in `ops_pipeline_run`/`ops_pipeline_step`
  and emails failures; `pipeline-watch.yml` audits every morning that the night ran.
- Tests must not hit the network; mock HTTP with `respx`. The database tests use the
  local Docker PostgreSQL (`stock_test` database) and skip when it isn't running.
- Before committing: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.

## Analysis workflow

**Step 1 is always the absolute-values screen.** Before any ratio, score, ranking, DCF
interpretation or summary, look at and show the absolute numbers for the companies in
question: price, market value, DCF fair value, debt (total, net, short-term, long-term),
cash, revenue, EBITDA, net income, EPS, operating cash flow, capex and free cash flow.
Ratios and scores hide important information, so they come after, never instead.

- The list lives in `config/absolute_values.toml`. It will grow: when the user names a
  new absolute value, add it there (and to `analysis/sector.py` if the column doesn't
  exist yet). `tests/test_absolute.py` fails if a configured column is missing.
- Run it with `uv run python analysis/absolute.py [TICKERS]` (refresh data first with
  `uv run python analysis/sector.py`). That table covers the utilities sector; for any
  other company, build its peer table first with `uv run python analysis/peer_screen.py
  NAME TICKERS` (data/peers/NAME.csv, same columns) as reports 11 and 12 do.
- **Always look at the history, not just the latest year:** `uv run python
  analysis/absolute.py --history TICKERS` shows every fiscal year on record (at least
  the last 5; SEC filings back to 2016) next to the latest 12 months. Build or refresh it
  with `uv run python analysis/history.py` (SEC EDGAR primary, Yahoo fills gaps, each
  value records its source; raw SEC files cache in `.cache/sec/`). Foreign filers are
  converted at today's exchange rate, and market value is only shown for US-dollar filers.
- In answers, present the absolute-values table first, then ratios, scores and conclusions.
- The sector dashboard of absolute values is `dashboard/absolute.html`, built by
  `uv run python dashboard/build_absolute.py`; it reads the same config, so new values
  appear there automatically.
- Market screener: `uv run python analysis/screener.py` screens the S&P 500 for now
  (`[universe]` in the config; "" = every US and European company above $1bn;
  TradingView, Yahoo, SEC, ECB; all free) in two separate stages
  (report 13, settings in `config/screeners.toml`). Stage 1 (`analysis/stage1.py`) puts
  each company in one of Peter Lynch's six categories and keeps those with good financial
  statements by the rules for their category (banks, insurers, REITs by kind of business).
  Stage 2 (`analysis/stage2.py`) reads Stage 1's output and lists the top 3 cheap or
  close-to-cheap survivors per sector against each stock's own cheap P/E. The evening run
  reruns it, and the market report, the site's Screener page and the email show its top 3
  per sector.
- Other tools, in the usual order after step 1: `analysis/screen.py` (strict and weighted
  screens), `analysis/peer_screen.py` (the same screens on a hand-picked peer group), `analysis/dcf_firm.py` / `analysis/dcf.py` (DCF), `analysis/compare.py`,
  `analysis/valuation.py`, `analysis/debt_to_ebitda.py`.

## Metrics dictionary

Every fundamental metric is defined once in `config/metrics.toml` (definition, formula,
source columns, worked example, draft vector status). When a new metric is used, add it
there and regenerate `docs/METRICS.md` with `uv run python -m stock_analysis.metrics doc`
(`tests/test_metrics.py` fails if the doc is stale). `stock_analysis.metrics.build_vectors`
builds a per-stock vector from any chosen set (report 14).

## Watch list and the evening run

The watch list is `config/watchlist.toml` (symbol, sector peers, target P/E, one-off EPS
corrections). Every weekday evening (Monday to Friday) at 21:00 Italy time a scheduled session follows
`docs/EVENING_RUN.md`: it updates Claude's notes (`analyses/<SYMBOL>/notes.md`,
`analyses/market/notes.md`, `analyses/summaries/notes.md`), runs
`uv run python analysis/watchlist.py` (which reruns the market screener first), checks the
outputs with `analysis/validate.py`, commits the dated PDFs and `data/screener/` to `main`
and emails Babak.
Every run is kept: `analyses/<SYMBOL>/YYYY-MM-DD_HHMM.pdf` plus a dated list in each
stock folder's `README.md` (market reports and summaries are listed in
`analyses/README.md`). Call it a list of dated analyses, not an archive. The public page of all dated analyses is
https://khalilvandian.github.io/Stock-analysis/, built by `analysis/site.py` and published by
`.github/workflows/pages.yml` on every push to `main` that changes `analyses/`, `data/screener/`
or the site script. Adjusted EPS for
the own-history P/E is Yahoo's reported quarterly EPS (split-adjusted).

## Reports

Every distinct analysis is written up as a numbered report in `reports/` (see
`reports/README.md` for the index and layout: data date, absolute values first, method,
findings, caveats, command to reproduce). When an analysis is redone with new data,
update its report and the date rather than leaving stale numbers. Add new reports to the
index.
