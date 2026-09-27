# Stock Analysis

Python 3.11+ project managed with `uv`. Source in `src/stock_analysis/`, tests in `tests/`.

- Market data: `stock_analysis.fetch` (Yahoo Finance via yfinance) saves CSVs to `data/<SYMBOL>/`. `FMPClient` wraps Financial Modeling Prep, but the free plan blocks most symbols (HTTP 402).
- The API key is read from the `FMP_API_KEY` env var. Never hardcode or commit it.
- Tests must not hit the network; mock HTTP with `respx`.
- Before committing: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
