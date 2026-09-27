# Stock Analysis

Python 3.11+ project managed with `uv`. Source in `src/stock_analysis/`, tests in `tests/`.

- Data comes from Financial Modeling Prep via `stock_analysis.fmp.FMPClient` (`stable` endpoints).
- The API key is read from the `FMP_API_KEY` env var. Never hardcode or commit it.
- Tests must not hit the network; mock HTTP with `respx`.
- Before committing: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
