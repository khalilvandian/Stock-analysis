# Stock Analysis

Python 3.11+ project managed with `uv`. Source in `src/stock_analysis/`, tests in `tests/`.

- Market data lives in the database only (issue #33): the scheduled ingest job fetches Yahoo,
  SEC EDGAR, TradingView and the ECB (all free), and no script fetches anything itself. A
  value the database lacks is added to the ingest (`config/db_items.toml`, a source), not
  fetched in a script. SEC also comes in bulk (`companyfacts.zip`, the quarterly Financial
  Statement Data Sets): files downloaded by hand wait in `inbox/<kind>/` (never committed)
  and are loaded with `uv run python -m stock_analysis.db import FILE [--target server]`
  (docs/INGEST.md), which marks their tasks fetched so the job doesn't download them again.
  Every payload is kept as received (`raw_payload`); `db reparse` re-reads kept SEC files
  after a tag mapping change. edgartools reads full filings (source `sec_xbrl`).
- Never hardcode or commit a key or password. The SEC downloader identifies itself with
  `SEC_USER_AGENT`; never hardcode a personal email.
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
  build`, then `check` (each takes `--target`; `ping` diagnoses a connection). The ingest job
  (issue #18, `docs/INGEST.md`) fills it on a schedule: `db ingest` (TradingView, SEC, Yahoo,
  ECB) for the S&P 500, the watch list's stocks and peers, `extra_symbols` in
  `config/ingest.toml` and the market report's instruments (`config/market.toml`);
  running as the Azure Container Apps Job `stock-ingest`; `db coverage` measures completeness
  against `config/coverage.toml` (`docs/COVERAGE.md`), shown on the site's Data page. To read
  or write data in a script or analysis, use `stock_analysis.data.Data.open()` (reads as
  `stock_reader`, writes as `stock_writer`; `data.sql(...)` for any read-only query) and
  `stock_analysis.stocks` (a stock's row of absolute values, ratios, growth and DCF; its yearly
  history; prices; earnings dates; the latest screener run). On a PC it connects to the
  database directly; in cloud sessions it goes through the web API (`api/`,
  https://stock-api-bk.azurewebsites.net, used when `STOCK_API_URL` is set). Prices are the
  latest close the ingest stored, not live quotes.
- Orchestration (issue #30, `docs/ORCHESTRATION.md`): Airflow 3 runs every timed piece as
  a task. `stock_nightly` (22:30 UTC on weekdays) starts the `stock-ingest` job for the fetch,
  build, quality check, coverage and nightly analyses, checks each one, sets the ready
  marker (`python -m stock_analysis.pipeline marker`), rebuilds the site and waits for the
  Claude session's commit; `stock_quotes` (hourly, weekdays) starts the quotes job. The jobs
  have no schedule of their own and there is no fallback cron. Every step is logged in
  `ops_pipeline_run` and `ops_pipeline_step`, and failures are emailed through Brevo.
  Developed locally in Docker (`orchestration/compose.yaml`); production is Azure: a free VM
  (`airflow-vm`, Spain Central) runs the always-on parts, the UI is the scale-to-zero
  Container App `airflow-ui`. Merging to `main` deploys everything (`deploy.yml`, OIDC).
  `pipeline-watch.yml` audits every 3 hours, from outside Airflow, that the night and the
  quotes ran.
- Tests must not hit the network; mock HTTP with `respx`. The database tests use the
  local Docker PostgreSQL (`stock_test` database, or `STOCK_TEST_PG_URL`) and skip when it
  isn't running; they seed it with `tests/seed_files.py`.
- Before committing: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.

## Analysis workflow

**Step 1 is always the absolute-values screen.** Before any ratio, score, ranking, DCF
interpretation or summary, look at and show the absolute numbers for the companies in
question: price, market value, DCF fair value, debt (total, net, short-term, long-term),
cash, revenue, EBITDA, net income, EPS, operating cash flow, capex and free cash flow.
Ratios and scores hide important information, so they come after, never instead.

- The list lives in `config/absolute_values.toml`. It will grow: when the user names a
  new absolute value, add it there (and to `stock_analysis/stocks.py` if the column doesn't
  exist yet). `tests/test_absolute.py` fails if a configured column is missing.
- Run it with `uv run python -m claude absolute TICKERS` (any company in the database;
  one the database lacks is added to `extra_symbols` in `config/ingest.toml` or the watch
  list's peers). For a peer group, `uv run python -m claude peer_screen NAME TICKERS`
  adds the strict and weighted screens.
- **Always look at the history, not just the latest year:** `uv run python -m
  claude absolute --history TICKERS` shows every fiscal year on record (at least
  the last 5; SEC filings back to 2016, Yahoo fills gaps, each value records its source)
  next to the latest 12 months. Values not reported by SEC are converted from the
  company's reporting currency at the ECB's latest rate, and market value is only shown
  for US-dollar filers.
- In answers, present the absolute-values table first, then ratios, scores and conclusions.
- Market screener: `uv run python -m stock_analysis.screener` screens the S&P 500 (the
  ingest's universe; settings in `config/screeners.toml`, `docs/SCREENER.md`) in two stages from the
  database (the TradingView snapshot, prices, earnings dates, core values) and saves the run
  there. Stage 1 (`stock_analysis/screener/stage1.py`) puts
  each company in one of Peter Lynch's six categories and keeps those with good financial
  statements by the rules for their category (banks, insurers, REITs by kind of business).
  Stage 2 (`stock_analysis/screener/stage2.py`) takes Stage 1's output and lists the top 3 cheap or
  close-to-cheap survivors per sector against each stock's own cheap P/E. The nightly
  analyses run it after the ingest, and the market report, the site's Screener page and the
  email show its top 3 per sector.
- Other tools after step 1: `screen TICKERS` (strict and weighted screens) and `peer_screen`
  (the same on a peer group); `uv run python -m claude` lists them all. Use a tool when one fits,
  so the same question gets the same answer.
- **Where Claude's scripts go: `claude/`** (`claude/README.md`). One-off: `claude/scratch/` (never
  committed). Worth using again: `claude/tools/`, with a description and a test. A calculation the
  PDFs or the site also need: `src/stock_analysis/`, never a second copy. The app never imports
  `claude/`; `tests/test_claude_folder.py` checks all of this.

## Metrics dictionary

Every fundamental metric is defined once in `config/metrics.toml` (definition, formula,
source columns, worked example, draft vector status). When a new metric is used, add it
there and regenerate `docs/METRICS.md` with `uv run python -m claude metrics doc`
(`tests/test_metrics.py` fails if the doc is stale). `claude.tools.metrics.build_vectors`
builds a per-stock vector from any chosen set.

## Watch list and the evening run

The watch list is `config/watchlist.toml` (symbol, sector peers, target P/E, one-off EPS
corrections). Every weekday evening (Monday to Friday) at 21:00 Italy time a scheduled session follows
`docs/EVENING_RUN.md`. **The session only interprets**: every number is computed on the
server after each night's ingest (`stock_analysis.nightly`, `db nightly`: the screener, each
watch-list stock's numbers, the market report's numbers, stored in `out_screener_*`,
`out_stock_numbers`, `out_market_numbers`). The session reads them, updates Claude's notes
(`analyses/<SYMBOL>/notes.md`, `analyses/market/notes.md`, `analyses/summaries/notes.md`),
runs `uv run python analysis/watchlist.py` (which renders the PDFs from the stored numbers
and the notes, and computes on the spot only a stock whose numbers are missing or whose
watch-list settings changed), checks the outputs with `analysis/validate.py`, commits the
dated PDFs and notes to `main` and emails Babak. It records its runs and notes in the
database. When Babak asks to change the watch list or who gets the report email, use the application
(`uv run python -m claude app watchlist-set | recipient-add | recipient-remove ...`,
every command in `claude/client.py`): it checks and logs the change. Never write an
email address into the repository. Work that needs no judgement belongs in the nightly analyses, not in the session.
Every run is kept: `analyses/<SYMBOL>/YYYY-MM-DD_HHMM.pdf` plus a dated list in each
stock folder's `README.md`, rebuilt from `out_watchlist_run` (market reports and summaries are listed in
`analyses/README.md`). Call it a list of dated analyses, not an archive. The public page of all dated analyses is
https://khalilvandian.github.io/Stock-analysis/, built by `analysis/site.py` and published by
`.github/workflows/pages.yml` on every push to `main` that changes `analyses/` or the site
script, and by Airflow after each night's build. Adjusted EPS for
the own-history P/E is Yahoo's reported quarterly EPS (split-adjusted).

## Reports

Every distinct analysis is written up as a numbered report in `reports/` (see
`reports/README.md` for the index and layout: data date, absolute values first, method,
findings, caveats, command to reproduce). When an analysis is redone with new data,
update its report and the date rather than leaving stale numbers. Add new reports to the
index.
