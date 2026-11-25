# Stock Analysis

A working process for analysing listed companies with Claude. A scheduled job pulls data from free APIs and public filings into a database; the analyses read it from there, screen the market, value companies, and record every finding as a dated PDF and a reproducible report.

The process is general. It started with the US utilities sector (reports 1-10) and now covers the S&P 500 and a watch list analysed every evening.

## How the process works

1. **Get the data.** The ingest job fills the database every night: SEC EDGAR filings (history back to 2016), Yahoo Finance prices, statements and earnings dates, TradingView's screener fields and the index members, and the ECB's exchange rates. Web search covers company guidance and deal details.
2. **Screen the absolute values first, with their history.** Look at price, market value, debt, cash, revenue, earnings and cash flow, year by year, before any ratio, score or summary. Ratios hide information.
3. **Then use ratios and comparisons.** Leverage, margins, growth (average and median of yearly rates), valuation multiples, and comparisons with peers and sub-industries.
4. **Value the companies.** Enterprise DCF (FCFF discounted at WACC), equity DCF, dividend model for utilities, and reverse DCF.
5. **Screen and rank.** Hard rules for data quality and growth, then a weighted score with debt weighted most, plus profitability and cash, plus cheapness.
6. **Write it up.** Each analysis becomes a numbered report in [`reports/`](reports/README.md); the evening run writes the dated PDFs and the public site.

Claude runs the process in Claude Code. [`CLAUDE.md`](CLAUDE.md) holds the rules every session follows.

## Repository layout

| Path | Contents |
|---|---|
| `reports/` | One report per analysis, numbered, with data date and reproduce command ([index](reports/README.md)) |
| `config/absolute_values.toml` | The absolute values screened first. Add new ones here |
| `analysis/` | The evening run's scripts and the site (see below) |
| `src/stock_analysis/` | The database (`db/`), the scheduled ingest (`ingest/`), the analyses' view of a stock (`stocks.py`), the data interface (`data.py`), the TradingView screener client, the metrics dictionary |
| `config/` | `absolute_values.toml`, `watchlist.toml`, `screeners.toml` (market screener rules), `metrics.toml` (metrics dictionary), `market.toml` (the market report's instruments), `ingest.toml`, `coverage.toml`, `database.toml`, `db_items.toml` |
| `analyses/` | The evening run's dated PDFs per stock, market and summary, with Claude's `notes.md` and the dated lists |
| `api/` | The web API in front of the database, for Claude's cloud sessions and the site |
| `docs/` | Full documentation: [start here](docs/README.md) |
| `tests/` | Tests (no network) |

Every number lives in the PostgreSQL database (`docs/DATABASE.md`), filled by the scheduled
ingest job (`docs/INGEST.md`). The scripts read it through `stock_analysis.data` and
`stock_analysis.stocks` and fetch nothing themselves.

## Scripts

| Command | What it does |
|---|---|
| `uv run python -m claude absolute TICKERS` | Absolute values, latest 12 months, for any company in the database |
| `uv run python -m claude absolute --history TICKERS` | Absolute values for every fiscal year, plus the latest 12 months |
| `uv run python -m claude peer_screen NAME TICKERS` | Metrics and the strict and weighted screens for a hand-picked peer group |
| `uv run python -m claude screen TICKERS --balanced` | Weighted ranking (debt 50%, profitability and cash 25%, cheapness 25%) with a growth requirement |
| `uv run python -m claude screen TICKERS --strict` | Strict debt rules, ranked by cheapness |
| `uv run python -m stock_analysis.screener` | Market screener: Stage 1 (Lynch category and financial-statement rules) then Stage 2 (top 3 cheap or close-to-cheap per sector); saved in the database |
| `uv run python analysis/watchlist.py` | The evening run: screener, market report, one PDF per watch-list stock and the summary, in `analyses/` |
| `uv run python analysis/market.py --numbers` | The market report's numbers (indices, sectors, breadth, the screener's top names) |
| `uv run python analysis/validate.py` | Checks the run's outputs are complete and consistent |
| `python analysis/site.py` | Builds the public site in `_site/` (GitHub Pages) |
| `uv run python analysis/send_email.py --to ADDRESS` | Emails the last run with every PDF through Brevo |
| `uv run python -m claude metrics list --set proposed` | The metrics dictionary and per-stock vectors |
| `uv run python -m stock_analysis.db ingest` | One run of the ingest job (the Azure job runs it every night) |
| `uv run python -m stock_analysis.db nightly` | The nightly analyses alone (the ingest job runs them after its build): the screener, the watch list's and the market report's numbers, stored for the evening run |

## Setup

See [`docs/SETUP.md`](docs/SETUP.md) for running this in Claude Code on the web: environment variables, network access and how to start a session.

Locally:

```bash
uv sync
cp .env.example .env   # database passwords, SEC_USER_AGENT
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

## Caveats

- Yahoo Finance data is unofficial.
- Prices are the database's latest close (the ingest runs after the US close), not live quotes.
- Reported EBITDA and EPS include hedge accounting, so they swing a lot for power producers.
- Foreign filers are converted at today's exchange rate.
- DCF assumptions (growth, required returns) are judgement calls; each report states them.

Nothing here is investment advice.
