# Stock Analysis

Python 3.11+ project managed with `uv`. Source in `src/stock_analysis/`, tests in `tests/`.

- Market data: `stock_analysis.fetch` (Yahoo Finance via yfinance) saves CSVs to `data/<SYMBOL>/`. `FMPClient` wraps Financial Modeling Prep, but the free plan blocks most symbols (HTTP 402).
- The API key is read from the `FMP_API_KEY` env var. Never hardcode or commit it. The SEC
  downloader identifies itself with `SEC_USER_AGENT`; never hardcode a personal email.
- Setup for new sessions and environments: `docs/SETUP.md`.
- Tests must not hit the network; mock HTTP with `respx`.
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
  `uv run python analysis/sector.py`).
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
  close-to-cheap survivors per sector against each stock's own cheap P/E.
- Other tools, in the usual order after step 1: `analysis/screen.py` (strict and weighted
  screens), `analysis/dcf_firm.py` / `analysis/dcf.py` (DCF), `analysis/compare.py`,
  `analysis/valuation.py`, `analysis/debt_to_ebitda.py`.

## Watch list and the evening run

The watch list is `config/watchlist.toml` (symbol, sector peers, target P/E, one-off EPS
corrections). Every evening at 21:00 Italy time a scheduled session follows
`docs/EVENING_RUN.md`: it updates Claude's notes (`analyses/<SYMBOL>/notes.md`,
`analyses/market/notes.md`, `analyses/summaries/notes.md`), runs
`uv run python analysis/watchlist.py`, commits the dated PDFs to `main` and emails Babak.
Every run is kept: `analyses/<SYMBOL>/YYYY-MM-DD_HHMM.pdf` plus a dated list in each
folder's `README.md`. Call it a list of dated analyses, not an archive. The public page of all dated analyses is
https://khalilvandian.github.io/Stock-analysis/, built by `analysis/site.py` and published by
`.github/workflows/pages.yml` on every push to `main`. Adjusted EPS for
the own-history P/E is Yahoo's reported quarterly EPS (split-adjusted).

## Reports

Every distinct analysis is written up as a numbered report in `reports/` (see
`reports/README.md` for the index and layout: data date, absolute values first, method,
findings, caveats, command to reproduce). When an analysis is redone with new data,
update its report and the date rather than leaving stale numbers. Add new reports to the
index.
