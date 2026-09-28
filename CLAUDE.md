# Stock Analysis

Python 3.11+ project managed with `uv`. Source in `src/stock_analysis/`, tests in `tests/`.

- Market data: `stock_analysis.fetch` (Yahoo Finance via yfinance) saves CSVs to `data/<SYMBOL>/`. `FMPClient` wraps Financial Modeling Prep, but the free plan blocks most symbols (HTTP 402).
- The API key is read from the `FMP_API_KEY` env var. Never hardcode or commit it.
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
- In answers, present the absolute-values table first, then ratios, scores and conclusions.
- Other tools, in the usual order after step 1: `analysis/screen.py` (strict and weighted
  screens), `analysis/dcf_firm.py` / `analysis/dcf.py` (DCF), `analysis/compare.py`,
  `analysis/valuation.py`, `analysis/debt_to_ebitda.py`.
