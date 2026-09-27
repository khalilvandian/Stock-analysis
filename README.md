# Stock Analysis

Stock market analysis built on [Financial Modeling Prep](https://site.financialmodelingprep.com/) data.

## Setup

```bash
uv sync                 # install dependencies into .venv
cp .env.example .env    # then set FMP_API_KEY
```

## Usage

```python
from stock_analysis import FMPClient

with FMPClient() as fmp:
    print(fmp.quote("AAPL"))
```

## Fetching data

```bash
uv run python -m stock_analysis.fetch CEG      # writes data/CEG/*.csv
```

Prices, dividends, income / balance sheet / cash flow (annual and quarterly) and company info
come from Yahoo Finance via `yfinance`. The FMP free plan only covers a limited set of symbols.

## Development

```bash
uv run pytest           # tests (no network, API calls are mocked)
uv run ruff check .     # lint
uv run ruff format .    # format
```
