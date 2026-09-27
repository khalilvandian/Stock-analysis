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

## Development

```bash
uv run pytest           # tests (no network, API calls are mocked)
uv run ruff check .     # lint
uv run ruff format .    # format
```
