# Boston Scientific (BSX): fundamentals screen

*Prices at the 2026-10-26 close; SEC filings through 2026-06-30. Written 2026-10-27.*

The first company outside utilities. It runs the same process on BSX against 13 US medical-device peers. The full investment write-up (adjusted P/E against BSX's own history, entry price, business, risks) is in the project's Claude Doc "Boston Scientific (BSX): investment analysis".

## Absolute values, latest 12 months

| Group | Value | BSX |
|---|---|---|
| Price and value | Share price | $45.58 |
| Price and value | Market value | $66.06bn |
| Price and value | DCF fair value (standard) | $34.09 |
| Price and value | Cash flow before growth (DCF base) | $3.40bn |
| Debt and cash | Total debt | $12.62bn |
| Debt and cash | Net debt | $12.09bn |
| Debt and cash | Short-term debt | $1.71bn |
| Debt and cash | Long-term debt | $10.92bn |
| Debt and cash | Cash | $0.54bn |
| Earnings | Revenue | $21.00bn |
| Earnings | EBITDA | $5.64bn |
| Earnings | Net income | $3.67bn |
| Earnings | EPS (GAAP) | $2.47 |
| Earnings | Forward EPS (adjusted) | $3.38 |
| Cash flow | Operating cash flow | $4.53bn |
| Cash flow | Capex | $0.90bn |
| Cash flow | Free cash flow | $3.63bn |

Capex and free cash flow are from SEC filings. Yahoo reports capex of $2.72bn (free cash flow $1.81bn) because it counts the $1.5bn MiRus stake bought in Q2 2026 as a capital purchase.

## Absolute values by year (SEC)

| Year | Price | Market value | Revenue | EBITDA | Net income | EPS | Operating CF | Free CF | Net debt | Cash |
|---|---|---|---|---|---|---|---|---|---|---|
| 2025 | $95.35 | $142.5bn | $20.1bn | $5.0bn | $2.9bn | $1.94 | $4.5bn | $3.7bn | $9.5bn | $2.0bn |
| 2024 | $89.32 | $132.7bn | $16.8bn | $3.9bn | $1.9bn | $1.25 | $3.4bn | $2.6bn | $10.3bn | $0.4bn |
| 2023 | $57.81 | $84.6bn | $14.2bn | $3.5bn | $1.6bn | $1.07 | $2.5bn | $1.8bn | $8.2bn | $0.9bn |
| 2022 | $46.27 | $66.6bn | $12.7bn | $2.8bn | $0.6bn | $0.45 | $1.5bn | $0.9bn | $8.0bn | $0.9bn |
| 2021 | $42.48 | $60.9bn | $11.9bn | $2.3bn | $1.0bn | $0.69 | $1.9bn | $1.3bn | $7.1bn | $1.9bn |
| 2020 | $35.95 | $50.9bn | $9.9bn | $1.0bn | −$0.1bn | −$0.08 | $1.5bn | $1.1bn | $7.4bn | $1.7bn |
| 2019 | $45.22 | $63.8bn | $10.7bn | $2.5bn | $4.7bn | $3.33 | $1.8bn | $1.4bn | $9.8bn | $0.2bn |
| 2018 | $35.34 | $49.5bn | $9.8bn | $2.4bn | $1.7bn | $1.19 | $0.3bn | $0.0bn | $6.9bn | $0.2bn |
| 2017 | $24.79 | $34.5bn | $9.0bn | $2.1bn | $0.1bn | $0.08 | $1.4bn | $1.1bn | $5.4bn | $0.2bn |
| 2016 | $21.63 | $29.8bn | $9.1bn | $1.3bn | $0.4bn | $0.25 | $1.2bn | $0.8bn | $5.3bn | $0.2bn |

## Method

- `analysis/sector.py`'s `analyse()` for latest values and ratios, `analysis/history.py`'s `sec_history()` for the yearly history.
- `analysis/screen.py` rules and weights unchanged; peers replace the utilities universe, with one peer median for P/E and EV / EBITDA.
- Peers: ABT, MDT, SYK, ISRG, BDX, EW, ZBH, DXCM, STE, PODD, TFX, GEHC, RMD.

## Findings

**BSX passes the profit, growth and leverage rules but fails both cash-covers-debt rules, so the strict screen drops it. In the weighted screen it ranks 5th of 9: top on profitability and cash, second cheapest, bottom third on debt.**

| Measure | BSX | Rule or peer median | Result |
|---|---|---|---|
| Net debt / EBITDA | 2.14x | ≤ 4.5x | Pass |
| EBITDA / interest | 15.5x | ≥ 4x | Pass |
| Cash / short-term debt | 0.32x | ≥ 1x | Fail (2.97x with a year of operating cash flow) |
| Cash / long-term debt | 4.9% | ≥ 5% | Fail, narrowly |
| Revenue growth, average / median year (SEC, 2017–2025) | 9.6% / 9.3%, 7 of 9 years up | > 0 | Pass |
| EPS growth (GAAP), median year | 36%, 5 of 8 years up | > 0 | Pass |
| Net margin, TTM | 17.5% | | |
| P/E, trailing | 18.5x | Peer median 28.1x | 34% below |
| EV / EBITDA | 13.9x | Peer median 16.4x | 15% below |
| Forward P/E vs trailing | 27% lower | ≥ 15% lower | Getting cheaper |
| Price vs standard DCF fair value | +34% | < 0 | Not cheap |

The standard DCF assumes 2.5% growth forever on $3.40bn at an 8.2% WACC. In reverse, today's price implies about 3.7% growth forever.

Weighted screen (growth required):

| Rank | Company | Total | Debt | Profitability and cash | Cheapness |
|---|---|---|---|---|---|
| 1 | RMD | 73.4 | 80.2 | 72.2 | 61.1 |
| 2 | DXCM | 67.4 | 86.1 | 66.7 | 30.6 |
| 3 | ISRG | 61.0 | 75.0 | 69.0 | 25.0 |
| 4 | PODD | 57.7 | 59.0 | 62.7 | 50.0 |
| 5 | **BSX** | **54.1** | **29.5** | **77.0** | **80.6** |
| 6 | STE | 50.9 | 49.3 | 52.4 | 52.8 |
| 7 | MDT | 45.5 | 37.5 | 29.4 | 77.8 |
| 8 | SYK | 43.1 | 39.9 | 45.2 | 47.2 |
| 9 | GEHC | 40.6 | 30.9 | 25.4 | 75.0 |

The pending $14.5bn Penumbra deal adds about $11bn of debt, which would take net debt / EBITDA near 3.8x.

## Caveats

- The peer group is hand-picked, so percentile scores depend on it.
- GAAP EPS and margins are noisy for BSX because of amortization and one-off charges.
- Yahoo data is unofficial.

**Reproduce:** `uv run python analysis/peer_screen.py medtech BSX ABT MDT SYK ISRG BDX EW ZBH DXCM STE PODD TFX GEHC RMD`
