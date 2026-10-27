# Stock Analysis

A working process for analysing listed companies with Claude. It pulls data from free APIs and public filings, screens whole sectors, values companies, and records every finding as a reproducible report and dashboard.

The process is general. The first application is the **US utilities sector** (all 102 US-listed utilities), starting from Constellation Energy (CEG) and widening to its peers and the full sector.

## How the process works

1. **Get the data.** Yahoo Finance supplies the latest prices, statements and sector lists. SEC EDGAR supplies the history from annual filings (2016 onward). TradingView's public screener supplies whole-market fundamentals and technicals for the market screener, and the ECB supplies exchange rates. Financial Modeling Prep (FMP) is wired in but its current key is rejected, so nothing depends on it. Web search covers company guidance and deal details.
2. **Screen the absolute values first, with their history.** Look at price, market value, debt, cash, revenue, earnings and cash flow, year by year, before any ratio, score or summary. Ratios hide information.
3. **Then use ratios and comparisons.** Leverage, margins, growth (average and median of yearly rates), valuation multiples, and comparisons with peers and sub-industries.
4. **Value the companies.** Enterprise DCF (FCFF discounted at WACC), equity DCF, dividend model for utilities, and reverse DCF.
5. **Screen and rank.** Hard rules for data quality and growth, then a weighted score with debt weighted most, plus profitability and cash, plus cheapness.
6. **Write it up.** Each analysis becomes a numbered report in [`reports/`](reports/README.md), and the results go into the dashboards.

Claude runs the process in Claude Code. [`CLAUDE.md`](CLAUDE.md) holds the rules every session follows.

## Repository layout

| Path | Contents |
|---|---|
| `reports/` | One report per analysis, numbered, with data date and reproduce command ([index](reports/README.md)) |
| `config/absolute_values.toml` | The absolute values screened first. Add new ones here |
| `analysis/` | Analysis scripts (see below) |
| `dashboard/` | Dashboard builders and the generated HTML pages |
| `data/` | Saved data. `data/<TICKER>/` holds a single company; `data/sector/` holds the sector screen and history |
| `src/stock_analysis/` | Data clients: `fetch.py` (Yahoo), `fmp.py` (FMP), `tradingview.py` (TradingView screener), `ecb.py` (ECB exchange rates); `metrics.py` (metrics dictionary and vectors) |
| `config/` | `absolute_values.toml`, `watchlist.toml`, `screeners.toml` (market screener rules), `metrics.toml` (metrics dictionary), `market_universe.csv` (S&P 500 list) |
| `analyses/` | The evening run's dated PDFs per stock, market and summary, with Claude's `notes.md` |
| `docs/` | Full documentation: [start here](docs/README.md) |
| `tests/` | Tests (no network) |
| `.cache/sec/` | Raw SEC downloads (not committed) |

## Scripts

| Command | What it does |
|---|---|
| `uv run python analysis/sector.py` | Screens every US-listed utility from Yahoo and writes `data/sector/utilities.csv` (about 1 minute) |
| `uv run python analysis/history.py` | Builds the yearly history from SEC filings and writes `data/sector/history.csv` |
| `uv run python analysis/absolute.py [TICKERS]` | Absolute values, latest |
| `uv run python analysis/absolute.py --history TICKERS` | Absolute values for every fiscal year, plus the latest 12 months |
| `uv run python analysis/screen.py --balanced` | Weighted ranking (debt 50%, profitability and cash 25%, cheapness 25%) with a growth requirement |
| `uv run python analysis/screen.py --strict` | Strict debt rules, ranked by cheapness |
| `uv run python analysis/dcf_firm.py` | Enterprise DCF for the power producers, plus the utility diagnostic |
| `uv run python analysis/dcf.py` | Equity DCF, dividend model and reverse DCF |
| `uv run python analysis/compare.py CEG VST ...` | Debt and growth comparison |
| `uv run python analysis/valuation.py CEG VST ...` | Valuation multiples |
| `uv run python analysis/debt_to_ebitda.py CEG VST ...` | Leverage history |
| `uv run python analysis/debt.py CEG` | One company's leverage over time |
| `uv run python analysis/peer_screen.py NAME TICKERS` | Metrics and screens for a hand-picked peer group outside utilities |
| `uv run python -m stock_analysis.fetch CEG` | Saves one company's Yahoo data to `data/CEG/` |
| `uv run python analysis/screener.py` | Market screener: Stage 1 (Lynch category and financial-statement rules) then Stage 2 (top 3 cheap or close-to-cheap per sector); writes `data/screener/` |
| `uv run python analysis/watchlist.py` | The evening run: screener, market report, one PDF per watch-list stock and the summary, in `analyses/` |
| `uv run python analysis/market.py --numbers` | The market report's numbers (indices, sectors, breadth, the screener's top names) |
| `uv run python analysis/validate.py` | Checks the latest outputs are complete and consistent |
| `python analysis/site.py` | Builds the public site in `_site/` (GitHub Pages) |
| `uv run python analysis/send_email.py --to ADDRESS` | Emails the last run with every PDF through Brevo |
| `uv run python -m stock_analysis.metrics list --set proposed` | The metrics dictionary and per-stock vectors |

## Dashboards

The pages are built from the saved data and published as Claude artifacts. They are private until shared from the page's Share menu.

| Page | Build | Published |
|---|---|---|
| US Utilities Absolute Values | `uv run python dashboard/build_absolute.py` → `dashboard/absolute.html` | https://claude.ai/artifact/KsT1wqQXQmimANRYfPa4yt |
| US Utilities Sector Screen | `uv run python dashboard/build_sector.py` → `dashboard/sector.html` | https://claude.ai/artifact/5wD1VfDLCzCidMs5DP9a6B |
| Constellation Energy Dashboard | `uv run python dashboard/build.py` → `dashboard/index.html` | https://claude.ai/artifact/R39P1BoAQMcpfvNTVnEBQX |

## Refreshing everything

```bash
uv run python analysis/sector.py && uv run python analysis/history.py
uv run python dashboard/build_absolute.py && uv run python dashboard/build_sector.py && uv run python dashboard/build.py
```

After a refresh, ask Claude to republish the dashboards and update the reports.

## Setup

See [`docs/SETUP.md`](docs/SETUP.md) for running this in Claude Code on the web: environment variables, network access and how to start a session.

Locally:

```bash
uv sync
cp .env.example .env   # optional: FMP_API_KEY, SEC_USER_AGENT
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

## Caveats

- Yahoo Finance data is unofficial.
- Reported EBITDA and EPS include hedge accounting, so they swing a lot for power producers.
- Foreign filers are converted at today's exchange rate.
- DCF assumptions (growth, required returns) are judgement calls; each report states them.

Nothing here is investment advice.
