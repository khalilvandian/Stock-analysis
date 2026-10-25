# Absolute values: the framework and the sector in dollars

*History from SEC filings 2016–2025; latest data 2026-09-28. Written 2026-09-28.*

## Why absolute values come first

Ratios, scores and summaries hide important information. Every analysis in this project therefore starts with the absolute numbers, and their history, for each company. This rule is recorded in `CLAUDE.md`.

The values screened, configured in `config/absolute_values.toml`:

| Group | Values |
|---|---|
| Price and value | Share price, market value, DCF fair value, cash flow before growth (DCF base) |
| Debt and cash | Total debt, net debt, short-term debt, long-term debt, cash |
| Earnings | Revenue, EBITDA, net income, EPS, forward EPS |
| Cash flow | Operating cash flow, capex, free cash flow |

Adding a value to the config adds it to `analysis/absolute.py`, `analysis/absolute.py --history` and the absolute-values dashboard.

## Sector totals, FY2018 → FY2025

These totals include only companies that reported the value in every year, so each year compares the same companies.

| Value | Companies | FY2018 | FY2025 | Change |
|---|---|---|---|---|
| Revenue | 80 | $480bn | $673bn | +40% |
| Net income | 80 | $40.5bn | $82.3bn | +103% |
| Operating cash flow | 78 | $116bn | $182bn | +56% |
| Capex | 65 | −$108bn | −$208bn | spending almost doubled |
| Free cash flow | 63 | −$8bn | −$46bn | about $38bn more cash out |
| Total debt | 67 | $682bn | $1.25tn | +84% |
| Cash | 78 | $24bn | $42bn | +75% |
| Market value (US-dollar filers) | 63 | $751bn | $1.31tn | +74% |

**Finding:** the sector doubled its profits, but capital spending grew even faster. It runs a free cash flow deficit every year and funds the gap with debt, which grew almost as fast as spending.

## Latest 12 months by sub-industry (sum of companies)

| | Companies | Market value | Total debt | Short-term debt | Long-term debt |
|---|---|---|---|---|---|
| Power producers | 9 | $188bn | $80.7bn | $10.0bn | $70.7bn |
| Regulated electric | 39 | $1.15tn | $1.04tn | $91.1bn | $950bn |
| Regulated gas | 15 | $95.6bn | $79.6bn | $7.8bn | $71.8bn |
| Regulated water | 11 | $66.5bn | $39.8bn | $3.4bn | $36.4bn |
| Renewables | 22 | $61.4bn | $83.4bn | $10.7bn | $72.7bn |
| Diversified | 6 | $96.8bn | $142bn | $14.5bn | $128bn |
| **All utilities** | **102** | **$1.66tn** | **$1.47tn** | **$138bn** | **$1.33tn** |

## Data notes

- History comes from SEC EDGAR annual filings, with Yahoo filling gaps. Every value records its source.
- At least five years of history is available for 91 companies (revenue), 92 (net income and cash) and 72–78 (debt).
- Foreign filers are converted at today's exchange rate for every year.
- Market value history is shown only for companies reporting in US dollars.

**Reproduce:**
- `uv run python analysis/absolute.py --history CEG VST`
- `uv run python dashboard/build_absolute.py` (dashboard: `dashboard/absolute.html`)
