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

## Step 1: absolute values

Every analysis starts by screening the absolute numbers (price, market value, DCF fair value,
debt, cash, revenue, EBITDA, net income, EPS, cash flow, capex, free cash flow) before any
ratio or score:

```bash
uv run python analysis/sector.py              # refresh data for every US-listed utility
uv run python analysis/absolute.py CEG VST    # absolute values, grouped
uv run python analysis/history.py             # yearly history from SEC filings (2016+)
uv run python analysis/absolute.py --history CEG VST   # every fiscal year + latest 12m
uv run python dashboard/build_absolute.py             # rebuild dashboard/absolute.html
```

The list of values is in `config/absolute_values.toml`. Add new ones there.

## Analysis and dashboard

```bash
uv run python analysis/debt.py CEG                 # CEG leverage history
uv run python analysis/compare.py CEG VST NRG      # debt and growth vs peers
uv run python analysis/debt_to_ebitda.py CEG VST   # debt/EBITDA history
uv run python analysis/valuation.py CEG VST        # valuation snapshot
uv run python analysis/dcf.py                      # equity DCF / dividend model and reverse DCF
uv run python analysis/dcf_firm.py                 # enterprise DCF (FCFF at WACC)
uv run python dashboard/build.py                   # rebuild dashboard/index.html
uv run python analysis/sector.py                   # screen every US-listed utility
uv run python dashboard/build_sector.py            # rebuild dashboard/sector.html
```

## Development

```bash
uv run pytest           # tests (no network, API calls are mocked)
uv run ruff check .     # lint
uv run ruff format .    # format
```
