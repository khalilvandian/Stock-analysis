# Data sources and API access

*Written 2026-09-27, updated 2026-10-25.*

## Summary

The project uses three free data sources. Financial Modeling Prep (FMP) was tested first. Its free plan blocks most utility tickers, so Yahoo Finance became the main source for current figures, and SEC EDGAR became the main source for history.

| Source | Used for | Access | Status |
|---|---|---|---|
| **Yahoo Finance** (`yfinance`) | Prices, latest statements, sector screener, analyst estimates | No key | Main source for latest values |
| **SEC EDGAR XBRL** (`data.sec.gov`) | Annual 10-K / 20-F figures back to 2016 | No key; set `SEC_USER_AGENT` | Main source for history |
| **Financial Modeling Prep** | Quotes, statements, ratios | `FMP_API_KEY` | Works, but the free plan returns HTTP 402 for most utilities |
| **Web search** | Company guidance, deal terms, filings context | Built into Claude | Used for research notes |

## FMP access test

- One request to `stable/quote?symbol=AAPL` returned HTTP 200 with live data, so the key works.
- For CEG, every endpoint except the company profile returned **HTTP 402**: "Special Endpoint: this value set for 'symbol' is not available under your current subscription."
- `FMPClient` (`src/stock_analysis/fmp.py`) is kept for symbols the plan covers, or for a paid plan later.
- The key must come from the `FMP_API_KEY` environment variable and never be committed. The key pasted into the original chat should be replaced.

## Yahoo Finance

- `uv run python -m stock_analysis.fetch CEG` saves prices, dividends, statements and company info to `data/CEG/`.
- `uv run python analysis/sector.py` screens every US-listed utility (sector = Utilities, US exchanges). It drops preferred shares, notes, warrants and duplicate share classes, leaving 102 companies, and writes `data/sector/utilities.csv`.
- Limits:
  - Only about 4 years of annual statements and about 6 quarters.
  - EBITDA and EPS are GAAP figures that include hedge accounting.
  - Data is unofficial and can break without warning.

## SEC EDGAR

- `uv run python analysis/history.py` downloads the "company facts" file for each company (cached in `.cache/sec/`, about 250 MB, not committed). It extracts annual values from 2016 onward and writes `data/sector/history.csv`.
- All 102 companies have an EDGAR filing record. About 81% of the historical values come from SEC filings, and Yahoo fills the gaps.
- Checks against Yahoo for 2022–2025: revenue, net income and operating cash flow agree within 5% in 93–98% of cases.
- Fixes built in:
  - Revenue uses the largest line reported each year, so partial lines (UGI 2016, NJR 2019) are not mistaken for the total.
  - Foreign filers are converted from the currency they actually report in (Enel Chile reports in CLP).
  - EPS is blanked for years before a company had public shares (CEG before its 2022 spin-off).

## Network hosts needed

`query1.finance.yahoo.com`, `query2.finance.yahoo.com`, `fc.yahoo.com`, `www.sec.gov`, `data.sec.gov`, `financialmodelingprep.com`, plus PyPI for `uv sync`.
