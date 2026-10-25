# US utilities sector overview (102 companies)

*Data as of 2026-09-28 (Yahoo Finance screener, sector = Utilities, US exchanges). Written 2026-09-28.*

## Universe

- The screener returned 125 listings. After removing preferred shares, notes, warrants, an ETF and duplicate share classes, **102 companies** remain.
- 12 of them report in another currency (Brazil, Chile, Korea, the UK, Canada, Argentina, Israel and others). They are marked "converted" and need checking against their filings.
- Combined market value: **$1.66tn**.

| Sub-industry | Companies | Market value |
|---|---|---|
| Regulated electric | 39 | $1,150bn |
| Power producers (IPPs) | 9 | $188bn |
| Diversified | 6 | $97bn |
| Regulated gas | 15 | $96bn |
| Regulated water | 11 | $66bn |
| Renewables | 22 | $61bn |

## Medians by sub-industry

| | Power producers | Reg. electric | Reg. gas | Reg. water | Renewables | Diversified | **All** |
|---|---|---|---|---|---|---|---|
| Net debt / EBITDA | 4.1x | 5.3x | 4.6x | 4.3x | 6.1x | 5.9x | **5.1x** |
| EBITDA / interest | 3.6x | 4.5x | 4.1x | 5.1x | negative | 3.3x | **4.2x** |
| Revenue growth, 3-year | 8.9% | 3.4% | 2.6% | 7.6% | 8.7% | −1.3% | **4.0%** |
| Profitable | 33% | 97% | 93% | 100% | 32% | 100% | **77%** |
| Negative free cash flow | 33% | 77% | 80% | 82% | 77% | 100% | **75%** |
| **Trailing P/E** (profitable companies only) | 25.9 | 19.0 | 17.4 | 20.9 | 38.7 | 18.5 | **19.7** |
| Dividend yield | 1.2% | 3.8% | 4.0% | 2.8% | 5.5% | 5.0% | **3.7%** |
| Below 52-week high | −40% | −17% | −18% | −13% | −55% | −20% | **−20%** |
| Price vs standard DCF fair value | +2% | +10% | +7% | +27% | +25% | −24% | **+8%** |

## Findings

1. **Fairly to slightly expensively valued.** The median utility trades 8% above its standard DCF value, at about 20x trailing earnings.
2. **Most spend more cash than they make.** 75% have negative free cash flow because they are investing in grids and new plants and funding it with debt. Typical leverage is 5.1x.
3. **Growth and risk are concentrated in three groups:**
   - **Power producers:** revenue is growing about 9% a year on data-center demand. Only a third are profitable, because the group includes early-stage nuclear companies. Shares have fallen the most, a median 40% below their highs.
   - **Water:** the most expensive group, valued for stable regulated growth.
   - **Renewables:** the most stretched. Most are loss-making, leverage is 6.1x, and prices are 55% below their highs.
4. **Regulated electric** is about 70% of the sector's value. It is slow and steady.

## Standard DCF used for the whole sector

- **Starting cash flow:** operating cash flow minus depreciation (as a proxy for maintenance capex), plus after-tax interest.
- **Valuation:** that cash flow grows 2.5% a year forever and is discounted at each company's WACC, then net debt is subtracted.
- **Coverage:** 77 of 102 companies get a value. The rest have negative cash flow.
- **CEG, VST, NRG and TLN** use the guidance-based enterprise DCF instead (report 06).

Reproduce: `uv run python analysis/sector.py`, then `uv run python dashboard/build_sector.py`.
Dashboard: `dashboard/sector.html`.
