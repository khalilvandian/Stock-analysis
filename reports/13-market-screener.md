# Market screener: cheap or close-to-cheap stocks in the US and Europe

*Data as of 2026-10-27 (prices at the 2026-10-27 close for Europe, intraday for the US). Written 2026-10-27, revised the same day for Peter Lynch's categories. Tools: `analysis/stage1.py` and `analysis/stage2.py` (or both in a row with `analysis/screener.py`), settings in `config/screeners.toml`.*

## 1. Summary

- **3,432 companies** above $1bn market value in the US and 17 European markets were screened, all from free sources with no keys.
- **Stage 1, good financial statements: 1,034 pass.** Each company is first put in one of Peter Lynch's six categories (slow grower, stalwart, fast grower, cyclical, turnaround, asset play), then judged by the rules for its category; banks, insurers and REITs keep rules for their kind of business. 267 companies with no profit in any of the last 5 years fail outright.
- **Stage 2, cheapness: 246 of the 1,034 are cheap or close to cheap** against their own cheap price; the top 3 per sector make an **88-name list** (43 US, 45 Europe).
- **Cheapest against their own history (US):** Trade Desk, Adobe, SiriusXM, Intuit, Maximus, Zoetis, Incyte, Allstate, Comcast. **Europe:** Durr, naturenergie, Novo Nordisk, Fielmann, Umicore, Vitec Software. Several of the deepest discounts (TriMas, 2020 Bulkers, K+S, Genus, Oerlikon) are one-off profits in diluted EPS, not real cheapness: check before use.
- **Netflix, Booking, Adobe and Intuit now pass Stage 1** and are cheap; Netflix and Booking miss the top 3 of their sectors. **Boston Scientific fails** (cash doesn't cover short-term debt).

## 2. The numbers

Two stages, separate programs: Stage 1 keeps the companies with good financial statements; Stage 2 ranks only those by how cheap they are. Every company with its category, status, the rules it failed and the source of every filled value: `data/screener/2026-10-27.csv`.

### Stage 1: good financial statements

Each company gets a Lynch category from its 10-year EPS history, industry and balance sheet, then must pass every rule of that category (full rules in section 3). Missing data makes a stock "incomplete", not a pass.

**1,034 of 3,432 companies pass Stage 1.** Every company with its absolute values, ratios and category: `data/screener/stage1.csv`.

#### By Lynch category

| Lynch category | US screened | US passed | Europe screened | Europe passed |
|---|---|---|---|---|
| slow grower | 334 | 87 | 215 | 40 |
| stalwart | 251 | 123 | 182 | 61 |
| fast grower | 285 | 121 | 206 | 64 |
| cyclical | 404 | 137 | 300 | 105 |
| turnaround | 454 | 146 | 222 | 84 |
| asset play | 59 | 24 | 77 | 41 |
| no profit in 5 years | 251 | 0 | 16 | 0 |
| (too little history) | 146 | 1 | 30 | 0 |

#### By sector

| Sector | US screened | US passed | Europe screened | Europe passed |
|---|---|---|---|---|
| Commercial Services | 79 | 17 | 48 | 10 |
| Communications | 18 | 4 | 28 | 6 |
| Consumer Durables | 48 | 22 | 47 | 19 |
| Consumer Non-Durables | 80 | 23 | 68 | 11 |
| Consumer Services | 97 | 20 | 46 | 6 |
| Distribution Services | 39 | 6 | 34 | 9 |
| Electronic Technology | 170 | 61 | 71 | 23 |
| Energy Minerals | 54 | 18 | 26 | 9 |
| Finance | 483 | 211 | 284 | 116 |
| Health Services | 49 | 7 | 15 | 0 |
| Health Technology | 254 | 46 | 80 | 20 |
| Industrial Services | 75 | 17 | 60 | 14 |
| Miscellaneous | 0 | 0 | 1 | 0 |
| Non-Energy Minerals | 53 | 20 | 47 | 22 |
| Process Industries | 72 | 16 | 64 | 21 |
| Producer Manufacturing | 143 | 38 | 118 | 43 |
| Retail Trade | 84 | 19 | 41 | 11 |
| Technology Services | 253 | 72 | 58 | 21 |
| Transportation | 65 | 19 | 56 | 17 |
| Utilities | 68 | 3 | 56 | 17 |
| **Total** | **2184** | **639** | **1248** | **395** |

#### By rule set

| Region | Rule set | Fail | Incomplete | Pass |
|---|---|---|---|---|
| Europe | (too little history) | 0 | 29 | 0 |
| Europe | asset play | 17 | 5 | 25 |
| Europe | banks | 41 | 4 | 84 |
| Europe | cyclical | 168 | 7 | 96 |
| Europe | fast grower | 129 | 4 | 28 |
| Europe | insurers | 19 | 0 | 18 |
| Europe | no profit in 5 years | 15 | 0 | 0 |
| Europe | reits | 24 | 1 | 1 |
| Europe | slow grower | 161 | 0 | 25 |
| Europe | stalwart | 115 | 2 | 38 |
| Europe | turnaround | 104 | 8 | 80 |
| US | (too little history) | 0 | 132 | 0 |
| US | asset play | 13 | 6 | 12 |
| US | banks | 68 | 13 | 116 |
| US | cyclical | 227 | 10 | 128 |
| US | fast grower | 146 | 8 | 70 |
| US | insurers | 38 | 5 | 32 |
| US | no profit in 5 years | 240 | 0 | 0 |
| US | reits | 65 | 2 | 42 |
| US | slow grower | 200 | 3 | 38 |
| US | stalwart | 113 | 2 | 67 |
| US | turnaround | 216 | 38 | 134 |

#### Rules failed most often

| Rule | Stocks failing it |
|---|---|
| cash covers short-term debt | 677 |
| revenue and EPS growth | 406 |
| Altman Z-score | 318 |
| cash vs total debt | 256 |
| no profit in the last 5 years | 255 |
| net debt / 10-year average EBITDA | 252 |
| interest cover | 206 |
| cash vs long-term debt | 171 |
| EPS growth, last 3 years | 159 |
| debt / equity | 148 |
| net debt / EBITDA | 125 |
| Piotroski score | 112 |
| EPS held up in recessions | 112 |
| dividend paid every year (payers) | 107 |
| profitable on average over 10 years | 85 |
| positive operating cash flow | 76 |
| return on equity | 75 |
| profitable | 48 |
| payout ratio | 33 |

### Stage 2: the cheapest survivors, top 3 per sector

Only Stage 1 survivors are ranked, purely by price against their own cheap price (section 3). Below it = cheap; up to 15% above = close. Absolute values first, then the cheap price and the timing read.

#### US: absolute values

Price in the trading currency; amounts in US$ billions; EPS (12 months, diluted) in the reporting currency.

| Company | Sector | Price | Market value | Total debt | Net debt | Short-term debt | Long-term debt | Cash | Revenue | EBITDA | Net income | EPS | Op. cash flow | Capex | Free cash flow |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MAXIMUS, Inc. (MMS) | Commercial Services | 62.80 USD | 3.3 | 1.7 | 1.6 | 0.1 | 1.6 | 0.2 | 5.2 | 0.7 | 0.4 | 7.76 | 0.5 | -0.0 | 0.4 |
| Genpact Limited (G) | Commercial Services | 39.17 USD | 6.6 | 1.4 | 0.9 | 0.1 | 1.3 | 0.5 | 5.3 | 0.9 | 0.6 | 3.92 | 0.6 | -0.1 | 0.6 |
| Morningstar, Inc. (MORN) | Commercial Services | 219.54 USD | 8.2 | 1.9 | 1.4 | 0.1 | 1.8 | 0.5 | 2.6 | 0.8 | 0.4 | 10.55 | 0.6 | -0.1 | 0.5 |
| Telephone and Data Systems, Inc. (TDS) | Communications | 36.16 USD | 3.9 | 1.2 | -0.9 | 0.0 | 1.2 | 2.2 | 1.3 | 0.3 | 0.4 | 2.99 | 0.1 | -0.4 | -0.3 |
| La-Z-Boy Incorporated (LZB) | Consumer Durables | 29.81 USD | 1.2 | 0.5 | 0.3 | 0.1 | 0.5 | 0.3 | 2.1 | 0.3 | 0.1 | 3.01 | 0.2 | -0.1 | 0.1 |
| Dorman Products, Inc. (DORM) | Consumer Durables | 125.40 USD | 3.7 | 0.5 | 0.4 | 0.0 | 0.5 | 0.1 | 2.2 | 0.4 | 0.2 | 8.90 | 0.3 | -0.0 | 0.2 |
| Hasbro, Inc. (HAS) | Consumer Durables | 119.05 USD | 16.8 | 3.5 | 2.1 | 0.9 | 2.6 | 1.4 | 5.2 | 1.7 | 1.0 | 7.16 | 1.3 | -0.2 | 1.2 |
| Deckers Outdoor Corporation (DECK) | Consumer Non-Durables | 79.77 USD | 10.9 | 0.5 | -0.7 | 0.1 | 0.5 | 1.2 | 5.6 | 1.4 | 1.1 | 7.54 | 1.2 | -0.1 | 1.1 |
| Nomad Foods Ltd. (NOMD) | Consumer Non-Durables | 11.76 USD | 1.6 | 2.6 | 2.3 | 0.0 | 2.6 | 0.3 | 3.5 | 0.6 | 0.1 | 1.55 | 0.2 | -0.1 | 0.1 |
| Marzetti Company (MZTI) | Consumer Non-Durables | 107.66 USD | 2.9 | 0.3 | 0.2 | 0.0 | 0.2 | 0.0 | 1.9 | 0.3 | 0.2 | 6.73 | 0.3 | -0.1 | 0.2 |
| SiriusXM Holdings Inc. (SIRI) | Consumer Services | 27.02 USD | 9.1 | 9.5 | 9.3 | 0.0 | 9.5 | 0.2 | 8.6 | 2.6 | 0.9 | 3.14 | 2.1 | -0.6 | 1.5 |
| Comcast Corporation Class A (CMCSA) | Consumer Services | 21.82 USD | 77.5 | 87.4 | 79.8 | 3.6 | 83.8 | 7.6 | 123.0 | 33.8 | 11.3 | 3.74 | 31.7 | -14.7 | 19.7 |
| Stride, Inc. (LRN) | Consumer Services | 79.37 USD | 3.3 | 0.6 | -0.2 | 0.5 | 0.1 | 0.8 | 2.5 | 0.6 | 0.3 | 8.29 | 0.5 | -0.1 | 0.5 |
| Universal Display Corporation (OLED) | Electronic Technology | 89.73 USD | 4.1 | 0.0 | -0.4 | 0.0 | 0.0 | 0.5 | 0.6 | 0.3 | 0.2 | 4.13 | 0.3 | -0.1 | 0.2 |
| First Solar, Inc. (FSLR) | Electronic Technology | 177.67 USD | 19.1 | 0.2 | -1.5 | 0.1 | 0.1 | 1.7 | 5.4 | 2.5 | 1.7 | 16.22 | 2.2 | -0.7 | 1.5 |
| Cirrus Logic, Inc. (CRUS) | Electronic Technology | 114.08 USD | 5.7 | 0.1 | -0.8 | 0.0 | 0.1 | 0.9 | 2.0 | 0.5 | 0.4 | 9.59 | 0.6 | -0.0 | 0.6 |
| Valero Energy Corporation (VLO) | Energy Minerals | 391.31 USD | 112.7 | 11.0 | 1.2 | 1.0 | 10.0 | 9.8 | 153.6 | 21.2 | 12.9 | 44.48 | 10.9 | -0.8 | 10.1 |
| EOG Resources, Inc. (EOG) | Energy Minerals | 161.27 USD | 84.6 | 8.2 | 3.3 | 0.4 | 7.9 | 4.9 | 26.7 | 14.4 | 6.9 | 13.46 | 13.4 | -6.7 | 6.6 |
| Allstate Corporation (ALL) | Finance | 251.52 USD | 63.6 | 7.5 | 6.7 | 0.0 | 7.5 |  | 70.1 |  | 13.3 | 47.96 | 12.5 | -0.2 | 12.2 |
| XP Inc. Class A (XP) | Finance | 16.23 USD | 8.4 | 17.9 | 16.4 | 17.4 | 0.6 | 1.5 | 3.6 | 1.2 | 1.0 | 1.92 | 9.0 | -0.1 | 8.9 |
| T. Rowe Price Group, Inc. (TROW) | Finance | 103.74 USD | 22.1 | 0.6 | -2.6 | 0.0 | 0.6 | 3.2 | 7.6 | 3.2 | 2.2 | 10.34 | 3.1 | -0.3 | 2.8 |
| Addus HomeCare Corporation (ADUS) | Health Services | 120.94 USD | 2.3 | 0.1 | 0.0 | 0.0 | 0.1 | 0.1 | 1.5 | 0.2 | 0.1 | 6.68 | 0.2 | -0.0 | 0.2 |
| Zoetis, Inc. Class A (ZTS) | Health Technology | 78.84 USD | 32.6 | 9.2 | 7.6 | 0.0 | 9.2 | 1.7 | 9.5 | 4.1 | 2.6 | 6.58 | 2.9 | -0.5 | 2.4 |
| Incyte Corporation (INCY) | Health Technology | 115.89 USD | 23.5 | 0.0 | -4.5 | 0.0 | 0.0 | 4.5 | 5.8 | 1.9 | 1.6 | 8.96 | 2.0 | -0.1 | 1.9 |
| Neurocrine Biosciences, Inc. (NBIX) | Health Technology | 144.75 USD | 14.7 | 0.4 | 0.0 | 0.0 | 0.4 | 0.4 | 3.4 | 0.9 | 0.7 | 8.84 | 0.8 | -0.0 | 0.8 |
| Installed Building Products, Inc. (IBP) | Industrial Services | 205.08 USD | 5.5 | 1.2 | 0.8 | 0.1 | 1.1 | 0.4 | 3.0 | 0.5 | 0.3 | 11.12 | 0.4 | -0.1 | 0.3 |
| Tetra Tech, Inc. (TTEK) | Industrial Services | 36.77 USD | 9.4 | 1.0 | 0.8 | 0.1 | 0.9 | 0.2 | 5.1 | 0.7 | 0.4 | 1.56 | 0.6 | -0.0 | 0.5 |
| Newmont Corporation (NEM) | Non-Energy Minerals | 112.10 USD | 116.5 | 5.6 | -3.2 | 0.1 | 5.5 | 8.8 | 26.2 | 17.2 | 9.2 | 9.72 | 13.1 | -3.0 | 10.1 |
| Anglogold Ashanti PLC (AU) | Non-Energy Minerals | 85.83 USD | 43.3 | 1.8 | -1.0 | 0.1 | 1.7 | 2.8 | 11.8 | 5.8 | 3.8 | 7.47 | 6.1 | -1.9 | 4.2 |
| TriMas Corporation (TRS) | Process Industries | 39.59 USD | 1.4 | 0.4 | -0.8 | 0.0 | 0.4 | 1.2 | 0.8 | 0.1 | 0.9 | 24.03 | 0.0 | -0.0 | -0.0 |
| Seaboard Corporation (SEB) | Process Industries | 3,881.01 USD | 3.7 | 2.0 | 0.7 | 0.8 | 1.2 | 1.2 | 10.3 | 0.7 | 0.6 | 661.84 | 0.5 | -0.5 | -0.0 |
| Pilgrim's Pride Corporation (PPC) | Process Industries | 26.95 USD | 6.4 | 3.1 | 2.7 | 0.1 | 3.1 | 0.4 | 18.4 | 1.6 | 0.5 | 3.35 | 1.2 | -0.9 | 0.3 |
| Xylem Inc. (XYL) | Producer Manufacturing | 94.22 USD | 22.0 | 3.1 | 1.8 | 0.7 | 2.4 | 1.3 | 9.1 | 2.0 | 1.0 | 5.44 | 1.3 | -0.4 | 0.9 |
| A. O. Smith Corporation (AOS) | Producer Manufacturing | 62.05 USD | 8.4 | 0.7 | 0.5 | 0.0 | 0.6 | 0.2 | 3.8 | 0.8 | 0.5 | 3.72 | 0.7 | -0.1 | 0.6 |
| Enerpac Tool Group Corp Class A (EPAC) | Producer Manufacturing | 35.76 USD | 1.8 | 0.2 | 0.1 | 0.0 | 0.2 | 0.1 | 0.6 | 0.2 | 0.1 | 1.87 | 0.1 | -0.0 | 0.1 |
| Gap, Inc. (GAP) | Retail Trade | 21.89 USD | 7.7 | 5.7 | 3.2 | 0.6 | 5.1 | 2.5 | 15.3 | 2.2 | 1.2 | 2.83 | 1.5 | -0.6 | 1.0 |
| Copart, Inc. (CPRT) | Retail Trade | 28.95 USD | 26.8 | 0.1 | -4.4 | 0.0 | 0.1 | 4.5 | 4.7 | 1.9 | 1.5 | 1.55 | 1.6 | -0.3 | 1.3 |
| Sprouts Farmers Market, Inc. (SFM) | Retail Trade | 63.81 USD | 6.0 | 2.1 | 1.9 | 0.2 | 1.9 | 0.2 | 9.0 | 1.0 | 0.5 | 5.22 | 0.7 | -0.3 | 0.4 |
| Trade Desk, Inc. Class A (TTD) | Technology Services | 12.81 USD | 6.1 | 0.4 | -1.1 | 0.1 | 0.4 | 1.5 | 3.0 | 0.7 | 0.4 | 1.66 | 1.1 | -0.2 | 0.9 |
| Adobe Inc. (ADBE) | Technology Services | 248.84 USD | 96.8 | 6.8 | 1.1 | 1.7 | 5.1 | 5.6 | 26.0 | 10.2 | 7.3 | 23.65 | 10.8 | -0.2 | 10.6 |
| Intuit Inc. (INTU) | Technology Services | 325.36 USD | 86.9 | 8.4 | 1.2 | 1.3 | 7.1 | 7.2 | 21.4 | 7.0 | 4.6 | 24.32 | 8.8 | -0.2 | 8.6 |
| DHT Holdings, Inc. (DHT) | Transportation | 24.41 USD | 3.9 | 0.4 | 0.3 | 0.0 | 0.4 | 0.2 | 0.7 | 0.5 | 0.5 | 2.55 | 0.5 | -0.4 | 0.0 |
| Atmos Energy Corporation (ATO) | Utilities | 170.74 USD | 28.9 | 10.3 | 9.8 | 0.5 | 9.8 | 0.5 | 4.9 | 2.6 | 1.4 | 8.41 | 2.0 | -4.0 | -2.0 |

#### US: category, cheap price and timing

| Company | Sector | Lynch category | P/E now | Cheap P/E | Set by | Cheap price | Price vs cheap | Label | EPS used | Trend | RSI | TradingView rating |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MAXIMUS, Inc. | Commercial Services | stalwart | 8.1x | 18.0x | own history | 139.72 USD | -55% | cheap | adjusted | downtrend | 66 | buy |
| Genpact Limited | Commercial Services | stalwart | 10.0x | 14.1x | own history | 55.13 USD | -29% | cheap | adjusted | uptrend | 61 | buy |
| Morningstar, Inc. | Commercial Services | slow grower | 20.8x | 22.4x | sector median | 236.78 USD | -7% | cheap | diluted | uptrend | 63 | buy |
| Telephone and Data Systems, Inc. | Communications | turnaround | 12.1x | 15.4x | sector median | 45.92 USD | -21% | cheap | adjusted | downtrend | 58 | buy |
| La-Z-Boy Incorporated | Consumer Durables | slow grower | 9.9x | 13.1x | own history | 39.46 USD | -24% | cheap | adjusted | downtrend | 47 | sell |
| Dorman Products, Inc. | Consumer Durables | stalwart | 14.1x | 17.7x | own history | 157.25 USD | -20% | cheap | adjusted | uptrend | 53 | neutral |
| Hasbro, Inc. | Consumer Durables | turnaround | 16.6x | 17.9x | own history | 128.46 USD | -7% | cheap | adjusted | uptrend | 88 | buy |
| Deckers Outdoor Corporation | Consumer Non-Durables | fast grower | 10.6x | 15.4x | own history | 116.18 USD | -31% | cheap | adjusted | downtrend | 40 | sell |
| Nomad Foods Ltd. | Consumer Non-Durables | asset play | 7.6x | 10.9x | own history | 16.90 USD | -30% | cheap | adjusted | uptrend | 57 | buy |
| Marzetti Company | Consumer Non-Durables | stalwart | 16.0x | 21.6x | sector median | 145.24 USD | -26% | cheap | adjusted | downtrend | 57 | buy |
| SiriusXM Holdings Inc. | Consumer Services | asset play | 8.6x | 20.1x | own history | 63.08 USD | -57% | cheap | adjusted | uptrend | 49 | sell |
| Comcast Corporation Class A | Consumer Services | asset play | 5.8x | 9.9x | own history | 37.02 USD | -41% | cheap | adjusted | downtrend | 44 | sell |
| Stride, Inc. | Consumer Services | fast grower | 9.6x | 15.4x | own history | 127.54 USD | -38% | cheap | adjusted | downtrend | 47 | sell |
| Universal Display Corporation | Electronic Technology | cyclical | 21.7x | 36.1x | own history | 149.28 USD | -40% | cheap | adjusted | downtrend | 70 | buy |
| First Solar, Inc. | Electronic Technology | cyclical | 11.0x | 16.5x | own history | 267.38 USD | -34% | cheap | adjusted | downtrend | 47 | neutral |
| Cirrus Logic, Inc. | Electronic Technology | fast grower | 11.9x | 12.3x | own history | 117.80 USD | -3% | cheap | adjusted | downtrend | 52 | neutral |
| Valero Energy Corporation | Energy Minerals | cyclical | 8.8x | 12.1x | sector median | 537.32 USD | -27% | cheap | adjusted | uptrend | 40 | sell |
| EOG Resources, Inc. | Energy Minerals | cyclical | 12.0x | 10.4x | own history | 140.27 USD | +15% | close | adjusted | uptrend | 69 | buy |
| Allstate Corporation | Finance | slow grower | 5.2x | 9.2x | own history | 439.37 USD | -43% | cheap | adjusted | uptrend | 59 | buy |
| XP Inc. Class A | Finance | stalwart | 8.5x | 12.8x | own history | 24.59 USD | -34% | cheap | diluted | mixed | 30 | sell |
| T. Rowe Price Group, Inc. | Finance | stalwart | 10.0x | 13.3x | own history | 138.04 USD | -25% | cheap | adjusted | uptrend | 49 | neutral |
| Addus HomeCare Corporation | Health Services | fast grower | 18.1x | 21.0x | own history | 140.51 USD | -14% | cheap | adjusted | uptrend | 63 | buy |
| Zoetis, Inc. Class A | Health Technology | stalwart | 12.0x | 25.9x | own history | 170.51 USD | -54% | cheap | adjusted | downtrend | 59 | neutral |
| Incyte Corporation | Health Technology | cyclical | 12.9x | 24.9x | own history | 222.80 USD | -48% | cheap | adjusted | uptrend | 49 | buy |
| Neurocrine Biosciences, Inc. | Health Technology | fast grower | 16.4x | 24.4x | own history | 215.92 USD | -33% | cheap | adjusted | downtrend | 53 | neutral |
| Installed Building Products, Inc. | Industrial Services | stalwart | 18.4x | 17.0x | own history | 188.69 USD | +9% | close | adjusted | downtrend | 58 | buy |
| Tetra Tech, Inc. | Industrial Services | stalwart | 23.6x | 21.5x | own history | 33.57 USD | +10% | close | adjusted | uptrend | 67 | buy |
| Newmont Corporation | Non-Energy Minerals | cyclical | 11.5x | 18.5x | sector median | 179.91 USD | -38% | cheap | adjusted | mixed | 43 | sell |
| Anglogold Ashanti PLC | Non-Energy Minerals | cyclical | 11.5x | 10.5x | own history | 78.40 USD | +9% | close | diluted | mixed | 37 | sell |
| TriMas Corporation | Process Industries | cyclical | 1.6x | 15.3x | own history | 368.17 USD | -89% | cheap | diluted | uptrend | 56 | buy |
| Seaboard Corporation | Process Industries | cyclical | 5.9x | 7.8x | own history | 5,180.39 USD | -25% | cheap | diluted | downtrend | 43 | sell |
| Pilgrim's Pride Corporation | Process Industries | cyclical | 8.0x | 8.8x | own history | 29.50 USD | -9% | cheap | adjusted | downtrend | 38 | strong sell |
| Xylem Inc. | Producer Manufacturing | fast grower | 17.3x | 25.2x | own history | 137.29 USD | -31% | cheap | adjusted | downtrend | 29 | strong sell |
| A. O. Smith Corporation | Producer Manufacturing | slow grower | 16.7x | 20.1x | own history | 74.78 USD | -17% | cheap | adjusted | downtrend | 66 | buy |
| Enerpac Tool Group Corp Class A | Producer Manufacturing | fast grower | 19.1x | 23.0x | own history | 43.07 USD | -17% | cheap | adjusted | downtrend | 53 | buy |
| Gap, Inc. | Retail Trade | cyclical | 7.7x | 9.8x | own history | 27.70 USD | -21% | cheap | adjusted | downtrend | 44 | sell |
| Copart, Inc. | Retail Trade | stalwart | 18.7x | 20.3x | sector median | 31.42 USD | -8% | cheap | adjusted | downtrend | 55 | neutral |
| Sprouts Farmers Market, Inc. | Retail Trade | stalwart | 12.2x | 12.5x | own history | 65.40 USD | -2% | cheap | adjusted | downtrend | 41 | strong sell |
| Trade Desk, Inc. Class A | Technology Services | cyclical | 7.7x | 32.0x | sector median | 53.10 USD | -76% | cheap | adjusted | downtrend | 50 | sell |
| Adobe Inc. | Technology Services | slow grower | 10.5x | 27.8x | own history | 658.27 USD | -62% | cheap | adjusted | mixed | 49 | sell |
| Intuit Inc. | Technology Services | fast grower | 13.4x | 30.4x | own history | 739.72 USD | -56% | cheap | adjusted | downtrend | 53 | neutral |
| DHT Holdings, Inc. | Transportation | cyclical | 9.6x | 8.7x | own history | 22.11 USD | +10% | close | adjusted | uptrend | 57 | buy |
| Atmos Energy Corporation | Utilities | stalwart | 20.3x | 18.5x | own history | 155.88 USD | +10% | close | adjusted | downtrend | 64 | buy |

#### Europe: absolute values

Price in the trading currency; amounts in US$ billions; EPS (12 months, diluted) in the reporting currency.

| Company | Sector | Price | Market value | Total debt | Net debt | Short-term debt | Long-term debt | Cash | Revenue | EBITDA | Net income | EPS | Op. cash flow | Capex | Free cash flow |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ipsos SA (IPS) | Commercial Services | 35.46 EUR | 1.7 | 0.7 | 0.4 | 0.1 | 0.7 | 0.3 | 2.8 | 0.4 | 0.2 | 3.99 | 0.3 | -0.1 | 0.3 |
| Reply S.p.A. (REY) | Commercial Services | 131.80 EUR | 5.4 | 0.2 | -0.4 | 0.1 | 0.1 | 0.6 | 2.8 | 0.5 | 0.3 | 6.97 | 0.4 | -0.1 | 0.3 |
| Prosegur Compania de Seguridad SA (PSG) | Commercial Services | 3.00 EUR | 1.8 | 2.3 | 1.5 | 0.5 | 1.8 | 0.8 | 5.6 | 0.6 | 0.1 | 0.15 | 0.4 | -0.2 | 0.3 |
| Hellenic Telecommunications Organization SA (HTO) | Communications | 19.03 EUR | 8.3 | 1.3 | 0.4 | 0.7 | 0.6 | 0.9 | 3.9 | 1.6 | 0.6 | 1.54 | 1.2 | -0.6 | 0.6 |
| Telenor ASA (TEL) | Communications | 127.70 NOK | 18.5 | 9.4 | 5.1 | 0.5 | 8.9 | 4.3 | 8.2 | 3.7 | 1.7 | 8.22 | 3.1 | -1.2 | 1.9 |
| Thule Group AB (THULE) | Consumer Durables | 192.70 SEK | 2.1 | 0.4 | 0.4 | 0.0 | 0.4 | 0.1 | 1.0 | 0.2 | 0.1 | 11.70 | 0.2 | -0.0 | 0.1 |
| Trigano SA (TRI) | Consumer Durables | 123.70 EUR | 2.7 | 0.2 | -0.4 | 0.1 | 0.1 | 0.6 | 4.2 | 0.5 | 0.3 | 13.21 | 0.6 | -0.0 | 0.6 |
| Husqvarna AB Class A (HUSQ_A) | Consumer Durables | 32.00 SEK | 1.9 | 1.3 | 0.8 | 0.4 | 1.0 | 0.5 | 4.5 | 0.6 | 0.1 | 1.79 | 0.4 | -0.1 | 0.3 |
| Karelia Tobacco Company Inc. (KARE) | Consumer Non-Durables | 420.00 EUR | 1.3 | 0.0 | -0.8 | 0.0 | 0.0 | 0.8 | 1.9 | 0.2 | 0.2 | 50.67 | 0.2 | -0.0 | 0.2 |
| Emmi AG (EMMN) | Consumer Non-Durables | 917.00 CHF | 6.0 | 1.6 | 1.1 | 0.2 | 1.3 | 0.5 | 5.8 | 0.6 | 0.3 | 43.12 | 0.5 | -0.2 | 0.3 |
| DO & CO Aktiengesellschaft (DOC) | Consumer Services | 198.20 EUR | 2.4 | 0.3 | -0.0 | 0.1 | 0.2 | 0.3 | 2.8 | 0.3 | 0.1 | 10.03 | 0.3 | -0.1 | 0.3 |
| Jet2 PLC (JET2) | Consumer Services | 1,408.00 GBX | 3.4 | 1.7 | -2.7 | 0.4 | 1.3 | 4.4 | 10.0 | 1.0 | 0.5 | 1.90 | 1.2 | -0.5 | 0.7 |
| Bunzl plc (BNZL) | Distribution Services | 2,874.00 GBX | 11.9 | 3.6 | 2.8 | 0.6 | 3.0 | 0.8 | 16.0 | 1.6 | 0.7 | 1.51 | 1.3 | -0.1 | 1.2 |
| ATOSS Software SE (AOF) | Electronic Technology | 94.70 EUR | 1.7 | 0.0 | -0.1 | 0.0 | 0.0 | 0.1 | 0.2 | 0.1 | 0.1 | 3.22 | 0.1 | -0.0 | 0.1 |
| MTU Aero Engines AG (MTX) | Electronic Technology | 329.70 EUR | 19.6 | 2.8 | 1.4 | 0.4 | 2.4 | 1.4 | 10.3 | 1.8 | 1.1 | 18.04 | 1.1 | -0.6 | 0.6 |
| Nolato AB Class B (NOLA_B) | Electronic Technology | 56.00 SEK | 1.5 | 0.1 | 0.1 | 0.0 | 0.1 | 0.0 | 0.9 | 0.2 | 0.1 | 2.78 | 0.1 |  | 0.1 |
| Galp Energia, SGPS S.A. Class B (GALP) | Energy Minerals | 20.40 EUR | 16.8 | 5.3 | 2.1 | 0.6 | 4.8 | 3.2 | 26.7 | 4.9 | 1.1 | 2.35 | 3.0 | -1.1 | 1.9 |
| Neste Corporation (NESTE) | Energy Minerals | 30.00 EUR | 26.9 | 5.2 | 4.0 | 0.5 | 4.7 | 1.2 | 23.0 | 3.4 | 1.7 | 2.37 | 2.5 | -0.9 | 1.6 |
| Shell Plc (SHEL) | Energy Minerals | 3,927.50 GBX | 302.9 | 73.4 | 41.9 | 8.6 | 64.8 | 31.5 | 294.5 | 63.0 | 25.8 | 3.38 | 46.2 | -17.5 | 28.7 |
| L E Lundbergforetagen AB Class B (LUND_B) | Finance | 580.00 SEK | 14.3 | 2.6 | 2.6 | 0.6 | 2.0 |  | 2.9 | 1.0 | 1.9 | 74.56 | 0.8 | -0.1 | 0.7 |
| Grainger plc (GRI) | Finance | 180.90 GBX | 1.8 | 2.2 | 2.0 | 0.1 | 2.1 | 0.2 | 0.3 | 0.2 | 0.2 | 0.18 | 0.1 | -0.0 | 0.1 |
| Industrivarden AB Class A (INDU_A) | Finance | 519.00 SEK | 22.2 | 0.6 | 0.4 | 0.2 | 0.5 | 0.2 | 1.0 |  | 5.4 | 124.61 | 0.9 | 0.0 | 0.9 |
| Novo Nordisk A/S Class B (NOVO_B) | Health Technology | 259.50 DKK | 172.2 | 20.9 | 14.2 | 2.7 | 18.2 | 6.7 | 49.1 | 25.3 | 17.4 | 23.35 | 19.5 | -12.5 | 11.1 |
| Fielmann Group AG (FIE) | Health Technology | 39.95 EUR | 3.7 | 1.0 | 0.7 | 0.1 | 0.9 | 0.3 | 2.8 | 0.6 | 0.2 | 2.52 | 0.5 | -0.1 | 0.3 |
| Dermapharm Holding SE (DMP) | Health Technology | 38.40 EUR | 2.1 | 1.3 | 1.1 | 0.2 | 1.1 | 0.2 | 1.3 | 0.4 | 0.2 | 2.76 | 0.2 | -0.1 | 0.2 |
| Umicore SA (UMI) | Non-Energy Minerals | 18.61 EUR | 4.7 | 3.6 | 1.6 | 1.0 | 2.6 | 2.0 | 27.4 | 1.6 | 0.5 | 2.02 | 1.1 | -0.4 | 0.8 |
| Norsk Hydro ASA (NHY) | Non-Energy Minerals | 68.70 NOK | 14.3 | 3.8 | 1.7 | 0.6 | 3.2 | 2.1 | 22.3 | 3.3 | 1.4 | 7.25 | 1.9 | -1.2 | 0.7 |
| Hochschild Mining plc (HOC) | Non-Energy Minerals | 447.20 GBX | 3.0 | 0.3 | -0.0 | 0.1 | 0.1 | 0.3 | 1.5 | 0.8 | 0.3 | 0.44 | 0.6 | -0.3 | 0.3 |
| K+S AG (SDF) | Process Industries | 12.96 EUR | 2.6 | 0.9 | -0.0 | 0.0 | 0.9 | 0.9 | 4.3 | -0.4 | 1.2 | 5.93 | 0.7 | -0.6 | 0.1 |
| Genus plc (GNS) | Process Industries | 2,340.00 GBX | 2.0 | 0.1 | 0.1 | 0.0 | 0.1 | 0.1 | 0.9 | 0.2 | 0.4 | 4.25 | 0.1 | -0.0 | 0.1 |
| OC Oerlikon Corporation AG (OERL) | Process Industries | 5.66 CHF | 2.2 | 1.3 | 0.9 | 0.0 | 1.2 | 0.4 | 1.9 | 0.4 | 0.4 | 1.03 | 0.2 | -0.1 | 0.1 |
| Durr AG (DUE) | Producer Manufacturing | 16.12 EUR | 1.3 | 1.1 | 0.2 | 0.3 | 0.8 | 0.9 | 4.6 | 0.4 | 0.2 | 4.82 | 0.3 | -0.1 | 0.3 |
| CIE Automotive, S.A. (CIE) | Producer Manufacturing | 25.45 EUR | 3.5 | 2.1 | 1.2 | 0.7 | 1.4 | 1.0 | 4.5 | 0.9 | 0.4 | 2.88 | 0.7 | -0.3 | 0.4 |
| Brembo N.V. (BRE) | Producer Manufacturing | 10.28 EUR | 5.8 | 1.5 | 0.9 | 0.6 | 1.0 | 0.6 | 4.2 | 0.6 | 0.3 | 0.72 | 0.7 | -0.4 | 0.3 |
| Colruyt Group N.V. (COLR) | Retail Trade | 35.24 EUR | 4.7 | 0.9 | 0.2 | 0.2 | 0.7 | 0.8 | 11.8 | 0.8 | 0.3 | 2.53 | 0.8 | -0.5 | 0.3 |
| Jumbo S.A. (BELA) | Retail Trade | 27.40 EUR | 4.1 | 0.1 | -0.5 | 0.0 | 0.1 | 0.6 | 1.4 | 0.5 | 0.4 | 2.41 | 0.4 | -0.0 | 0.4 |
| Koninklijke Ahold Delhaize N.V. (AD) | Retail Trade | 32.94 EUR | 31.9 | 17.4 | 13.4 | 0.0 | 17.4 | 4.0 | 101.9 | 7.7 | 2.5 | 2.66 | 7.2 | -2.9 | 4.3 |
| Vitec Software Group AB Class B (VIT_B) | Technology Services | 309.60 SEK | 1.2 | 0.4 | 0.3 | 0.0 | 0.4 | 0.1 | 0.4 | 0.2 | 0.0 | 20.57 | 0.1 | -0.0 | 0.1 |
| Temenos AG (TEMN) | Technology Services | 75.10 CHF | 6.1 | 0.8 | 0.7 | 0.0 | 0.8 | 0.1 | 1.1 | 0.4 | 0.2 | 4.47 | 0.4 | -0.1 | 0.3 |
| Capgemini SE (CAP) | Technology Services | 122.80 EUR | 23.5 | 11.3 | 8.4 | 1.2 | 10.1 | 2.9 | 26.1 | 3.8 | 1.5 | 7.87 | 2.7 | -0.3 | 2.4 |
| 2020 Bulkers Ltd. (2020) | Transportation | 12.40 NOK | 1.3 | 0.0 | -0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.2 | 0.2 | 88.07 | 0.0 | 0.0 | 0.0 |
| Ryanair Holdings PLC (RYA) | Transportation | 23.20 EUR | 26.6 | 0.2 | -3.0 | 0.0 | 0.2 | 3.2 | 17.4 | 4.0 | 2.1 | 1.86 | 3.8 | -1.9 | 1.9 |
| naturenergie holding AG (NEAG) | Utilities | 29.20 CHF | 1.2 | 0.1 | -0.2 | 0.0 | 0.1 | 0.3 | 1.6 | 0.3 | 0.2 | 4.57 | 0.3 |  |  |
| Aker Solutions ASA (AKSO) | Utilities | 38.16 NOK | 2.0 | 0.3 | -0.2 | 0.1 | 0.2 | 0.5 | 6.4 | 0.5 | 0.3 | 5.97 | 0.5 | -0.0 | 0.5 |
| PGE Polska Grupa Energetyczna S.A. (PGE) | Utilities | 16.43 PLN | 9.4 | 4.0 | 0.4 | 0.3 | 3.7 | 3.6 | 16.0 | 3.0 | 1.9 | 3.41 | 2.4 | -2.9 | -0.5 |

#### Europe: category, cheap price and timing

| Company | Sector | Lynch category | P/E now | Cheap P/E | Set by | Cheap price | Price vs cheap | Label | EPS used | Trend | RSI | TradingView rating |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ipsos SA | Commercial Services | asset play | 8.9x | 9.7x | own history | 38.61 EUR | -8% | cheap | diluted | mixed | 45 | strong sell |
| Reply S.p.A. | Commercial Services | stalwart | 18.9x | 18.0x | sector median | 125.30 EUR | +5% | close | diluted | uptrend | 64 | strong buy |
| Prosegur Compania de Seguridad SA | Commercial Services | stalwart | 20.0x | 18.0x | sector median | 2.70 EUR | +11% | close | adjusted | uptrend | 50 | neutral |
| Hellenic Telecommunications Organization SA | Communications | slow grower | 12.4x | 11.4x | own history | 17.58 EUR | +8% | close | adjusted | uptrend | 41 | sell |
| Telenor ASA | Communications | cyclical | 15.5x | 13.6x | own history | 111.44 NOK | +15% | close | adjusted | downtrend | 50 | neutral |
| Thule Group AB | Consumer Durables | cyclical | 16.5x | 16.7x | sector median | 195.47 SEK | -1% | cheap | adjusted | downtrend | 45 | sell |
| Trigano SA | Consumer Durables | cyclical | 9.4x | 9.4x | own history | 124.02 EUR | -0% | cheap | diluted | downtrend | 31 | sell |
| Husqvarna AB Class A | Consumer Durables | turnaround | 17.8x | 16.7x | sector median | 29.98 SEK | +7% | close | diluted | downtrend | 38 | sell |
| Karelia Tobacco Company Inc. | Consumer Non-Durables | asset play | 8.3x | 9.0x | own history | 454.06 EUR | -8% | cheap | diluted | uptrend | 56 | buy |
| Emmi AG | Consumer Non-Durables | slow grower | 21.3x | 20.3x | sector median | 875.90 CHF | +5% | close | diluted | uptrend | 73 | buy |
| DO & CO Aktiengesellschaft | Consumer Services | fast grower | 19.8x | 20.0x | own history | 201.02 EUR | -1% | cheap | diluted | uptrend | 54 | strong buy |
| Jet2 PLC | Consumer Services | asset play | 7.4x | 7.1x | own history | 1,352.44 GBX | +4% | close | diluted | uptrend | 47 | sell |
| Bunzl plc | Distribution Services | slow grower | 19.0x | 19.1x | own history | 2,883.41 GBX | -0% | cheap | diluted | uptrend | 66 | strong buy |
| ATOSS Software SE | Electronic Technology | stalwart | 29.4x | 31.6x | own history | 101.81 EUR | -7% | cheap | diluted | uptrend | 58 | buy |
| MTU Aero Engines AG | Electronic Technology | fast grower | 18.3x | 17.9x | own history | 323.04 EUR | +2% | close | adjusted | mixed | 39 | sell |
| Nolato AB Class B | Electronic Technology | cyclical | 20.1x | 18.5x | own history | 51.56 SEK | +9% | close | adjusted | uptrend | 54 | buy |
| Galp Energia, SGPS S.A. Class B | Energy Minerals | cyclical | 8.7x | 11.6x | own history | 27.33 EUR | -25% | cheap | adjusted | uptrend | 35 | sell |
| Neste Corporation | Energy Minerals | cyclical | 12.7x | 11.6x | sector median | 27.58 EUR | +9% | close | adjusted | uptrend | 38 | sell |
| Shell Plc | Energy Minerals | cyclical | 11.6x | 10.7x | own history | 3,608.77 GBX | +9% | close | diluted | uptrend | 63 | buy |
| L E Lundbergforetagen AB Class B | Finance | fast grower | 7.8x | 10.5x | own history | 779.90 SEK | -26% | cheap | diluted | uptrend | 56 | strong buy |
| Grainger plc | Finance | asset play | 10.2x | 12.1x | own history | 213.37 GBX | -15% | cheap | diluted | mixed | 68 | buy |
| Industrivarden AB Class A | Finance | fast grower | 4.2x | 4.6x | own history | 572.25 SEK | -9% | cheap | diluted | uptrend | 50 | buy |
| Novo Nordisk A/S Class B | Health Technology | stalwart | 11.1x | 19.5x | own history | 456.45 DKK | -43% | cheap | adjusted | downtrend | 47 | sell |
| Fielmann Group AG | Health Technology | fast grower | 15.8x | 26.5x | sector median | 66.71 EUR | -40% | cheap | diluted | downtrend | 66 | buy |
| Dermapharm Holding SE | Health Technology | stalwart | 13.9x | 17.7x | own history | 48.90 EUR | -21% | cheap | diluted | downtrend | 49 | neutral |
| Umicore SA | Non-Energy Minerals | cyclical | 9.2x | 13.9x | sector median | 27.99 EUR | -34% | cheap | diluted | mixed | 37 | sell |
| Norsk Hydro ASA | Non-Energy Minerals | cyclical | 9.5x | 13.0x | own history | 94.01 NOK | -27% | cheap | adjusted | downtrend | 23 | sell |
| Hochschild Mining plc | Non-Energy Minerals | cyclical | 10.3x | 13.9x | sector median | 603.76 GBX | -26% | cheap | diluted | downtrend | 32 | sell |
| K+S AG | Process Industries | turnaround | 2.2x | 9.2x | own history | 54.55 EUR | -76% | cheap | diluted | mixed | 30 | sell |
| Genus plc | Process Industries | cyclical | 5.5x | 21.4x | sector median | 9,076.03 GBX | -74% | cheap | diluted | downtrend | 62 | strong buy |
| OC Oerlikon Corporation AG | Process Industries | turnaround | 5.5x | 21.1x | own history | 21.65 CHF | -74% | cheap | diluted | uptrend | 51 | neutral |
| Durr AG | Producer Manufacturing | asset play | 3.3x | 12.0x | own history | 57.65 EUR | -72% | cheap | adjusted | downtrend | 44 | sell |
| CIE Automotive, S.A. | Producer Manufacturing | cyclical | 8.8x | 9.5x | own history | 27.32 EUR | -7% | cheap | diluted | downtrend | 47 | strong sell |
| Brembo N.V. | Producer Manufacturing | cyclical | 14.3x | 13.4x | own history | 9.64 EUR | +7% | close | diluted | uptrend | 53 | buy |
| Colruyt Group N.V. | Retail Trade | turnaround | 13.9x | 15.5x | own history | 39.11 EUR | -10% | cheap | diluted | mixed | 42 | sell |
| Jumbo S.A. | Retail Trade | stalwart | 11.4x | 10.6x | own history | 25.44 EUR | +8% | close | diluted | uptrend | 70 | strong buy |
| Koninklijke Ahold Delhaize N.V. | Retail Trade | stalwart | 12.4x | 11.5x | own history | 30.51 EUR | +8% | close | adjusted | downtrend | 59 | buy |
| Vitec Software Group AB Class B | Technology Services | stalwart | 15.1x | 21.0x | sector median | 431.38 SEK | -28% | cheap | adjusted | uptrend | 67 | buy |
| Temenos AG | Technology Services | stalwart | 16.8x | 21.0x | sector median | 93.74 CHF | -20% | cheap | adjusted | uptrend | 70 | buy |
| Capgemini SE | Technology Services | slow grower | 15.6x | 18.5x | own history | 145.51 EUR | -16% | cheap | diluted | uptrend | 64 | buy |
| 2020 Bulkers Ltd. | Transportation | cyclical | 0.1x | 5.0x | own history | 437.32 NOK | -97% | cheap | diluted | downtrend | 74 | buy |
| Ryanair Holdings PLC | Transportation | cyclical | 12.5x | 11.0x | own history | 20.37 EUR | +14% | close | adjusted | downtrend | 51 | buy |
| naturenergie holding AG | Utilities | asset play | 6.4x | 13.6x | own history | 62.01 CHF | -53% | cheap | diluted | downtrend | 44 | sell |
| Aker Solutions ASA | Utilities | fast grower | 6.4x | 8.1x | own history | 48.57 NOK | -21% | cheap | adjusted | downtrend | 40 | sell |
| PGE Polska Grupa Energetyczna S.A. | Utilities | turnaround | 4.8x | 6.1x | own history | 20.78 PLN | -21% | cheap | diluted | uptrend | 58 | buy |

## 3. Method

The two stages are separate programs. Stage 1 writes every company with its category, status and figures; Stage 2 reads that file, checks it has every column it needs, and ranks only the survivors. Either can be changed without touching the other. Every rule, threshold and its source is set out in the methods doc, "Stage 1 screening methods and their sources".

**Stage 1: good financial statements** (`analysis/stage1.py`)

1. **Universe.** TradingView's screener, primary listings of common shares above $1bn (converted at ECB reference rates): the US (NYSE, Nasdaq, NYSE American) and the UK, Germany, France, Italy, Spain, the Netherlands, Switzerland, Sweden, Denmark, Norway, Finland, Belgium, Austria, Portugal, Ireland, Poland and Greece. Funds and trusts are skipped.
2. **Gap filling.** Short-term debt left blank is total debt minus long-term debt (691 stocks). Debt, cash, EBITDA and interest cover still blank are taken from Yahoo's statements. Each filled value is named in the `filled` column.
3. **Lynch category** (One Up on Wall Street, ch. 7), tested in this order:
    - *No profit:* no positive EPS in any of the last 5 fiscal years. Not a Lynch category; he avoided such long shots, so these fail.
    - *Cyclical by industry:* autos, airlines, steel, metals and mining, chemicals, oil and gas, drilling, shipping, homebuilding, chip equipment, machinery, paper, building materials, hotels and cruise lines.
    - *Turnaround:* losing money now (12 months or latest fiscal year), or EPS (both measures) less than half its 5-year peak.
    - *Cyclical by history:* EPS fell more than 30% in 3 or more of the last 10 years, and it isn't growing 20% a year.
    - *Asset play:* price below book value, or net cash above 30% of market value.
    - *Fast grower / stalwart / slow grower:* median yearly EPS growth over 5 years of 20% or more / 8% to 20% / under 8%.
    - Blank when there are fewer than 3 years of EPS growth to measure (176 companies, "incomplete").
4. **Rules per category.** All must pass; Piotroski and Altman (and the recession test for stalwarts) are skipped and flagged when the data is missing.
    - *Slow grower:* Babak's four debt rules (cash ≥ short-term debt, cash ≥ 5% of long-term debt, net debt/EBITDA ≤ 4.5x, interest cover ≥ 4x; net cash passes), profitable, 5-year revenue and EPS growth above zero, a dividend in each of the last 10 years if it pays one, payout ≤ 80%, Piotroski ≥ 5, Altman Z > 1.8.
    - *Stalwart:* the debt rules, profitable, growth, EPS fell no more than 30% in the 2009 and 2020 fiscal years, Piotroski, Altman.
    - *Fast grower:* cash ≥ short-term debt, debt ≤ equity, interest cover ≥ 4x, profitable, EPS growth ≥ 20% a year over the last 3 years, Piotroski, Altman.
    - *Cyclical:* cash ≥ short-term debt, cash ≥ 5% of long-term debt, net debt ≤ 2.5x the 10-year average EBITDA, interest cover ≥ 4x, profitable on average over 10 years, Altman.
    - *Turnaround:* cash ≥ short-term debt, cash ≥ 25% of total debt, positive operating cash flow.
    - *Asset play:* cash ≥ short-term debt, debt ≤ equity, positive operating cash flow.
    - *Banks and insurers:* profitable, return on equity ≥ 8%, growth. No debt rules: deposits and float are not debt in the usual sense.
    - *REITs:* cash ≥ short-term debt, net debt/EBITDA ≤ 7x, interest cover ≥ 2.5x, profitable.
    - *Utilities:* their category's rules without the Altman score.
    - Where equity is negative (debt/equity left blank, mostly after years of buybacks, as at Booking), the debt/equity rule uses net debt/EBITDA ≤ 2x instead.

**Stage 2: cheapness, Stage 1 survivors only** (`analysis/stage2.py`)

5. **Cheap price.** Yearly P/E for the last 10 fiscal years = Yahoo average monthly price over the fiscal year / TradingView diluted EPS for that year (both split-adjusted, price converted to the reporting currency). The cheap multiple is the bottom quarter of those P/Es (at least 6 years needed), capped at the median P/E of the same region and sector, so a stock whose whole history was priced for fast growth isn't called cheap at a multiple its peers never get. Cheap price = cheap multiple × EPS of the last 12 months.
6. **Adjusted EPS.** For the 9 closest names per sector, Yahoo's adjusted quarterly EPS replaces diluted EPS, with its own adjusted P/E history (the watch list's method), when it has at least 6 years and is within a factor of 2 of diluted EPS (a bigger gap is a data error).
7. **Ranking.** Inside each region and sector, by price against the cheap price, lowest first. Below it = cheap; up to 15% above = close; anything higher is not listed. Stage 1 decides who gets in; only cheapness sets the order.
8. **Technicals, for timing only.** Trend from the 50- and 200-day averages, RSI (below 30 oversold, above 70 overbought), position in the 52-week range, and TradingView's technical rating.
9. **Cross-check.** US names' latest fiscal-year diluted EPS is compared with SEC EDGAR (39 of 43 found, none off by more than 10%).

**Sources (all free):** TradingView screener (fundamentals, 20 years of yearly EPS, revenue, EBITDA and dividends, technicals), Yahoo Finance (prices, adjusted EPS, statements for gaps), SEC EDGAR (EPS cross-check), ECB (exchange rates). Tested and available for later: European ESEF filings at filings.xbrl.org, Euronext and Nasdaq company lists, OpenFIGI (identifiers). Free-key services that could be added if Babak registers: Finnhub, Alpha Vantage, EODHD, Financial Modeling Prep (the current key is invalid).

## 4. Findings

- **Categories change who passes.** With one rule set for everyone, 880 passed and growth was the biggest filter (1,196 failures). Judged by category, 1,034 pass: slow growers and asset plays are no longer failed for slow growth, while fast growers must show 20% growth now and modest debt, and cyclicals are judged over the whole cycle.
- **Cash covering short-term debt is now the biggest filter** (677 failures), then 5-year growth (406) and the Altman score (318).
- **Stalwarts pass most often** (184 of 433), turnarounds and cyclicals about one in three, slow growers about one in four.
- **The list still leans to fallen quality names:** software and data (Adobe, Intuit, Trade Desk, Gartner, Vitec), health care (Novo Nordisk, Zoetis, Incyte, Neurocrine, Fielmann), consumer brands (Deckers, Marzetti).
- **Technicals mostly say "not yet":** 41 of the 88 names are in a downtrend (price and 50-day average below the 200-day).

## 5. Caveats

- **Categories come from reported (GAAP) EPS.** A big write-down or one-off gain can push a company into the wrong category: Bristol-Myers counts as cyclical because of write-down years, and some steady companies count as turnarounds after one bad year. The category is shown next to every name so it can be checked.
- **The category thresholds are judgement calls** based on Lynch's descriptions (fast growers 20-25% a year, stalwarts 10-12%, slow growers about the economy's growth); the methods doc lists every one for review.
- **TradingView's and Yahoo's interfaces are unofficial.** Field names can change, and Yahoo rate-limits heavy use. Each run caches its downloads for the day in `.cache/screener/`.
- **Own history is not destiny.** A stock far below its cheap price may have been re-rated for a reason (Adobe and Trade Desk face AI disruption; Novo Nordisk lost its obesity-drug lead). The screen finds candidates; each one needs the full analysis.
- **Diluted EPS includes one-offs** where Yahoo's adjusted EPS is not available (34 of the 88 names, mostly European). A one-off gain makes a stock look cheap: TriMas (89% below), 2020 Bulkers (97%), K+S (76%), Genus and Oerlikon (74%) are almost certainly this.
- **Foreign reporters** are converted at today's exchange rate for the P/E history, so currency moves over the decade are ignored.
- **Sectors are TradingView's 20**, not GICS: Aker Solutions sits in Utilities and some holding companies (Lundberg, Industrivärden) in Finance.
- **REITs are judged on EPS**, which understates their cash earnings; funds from operations are not available from these sources.
- **DCF fair value is not part of this screen yet**; it remains in the per-stock analyses.

## 6. Reproduce

```
uv run python analysis/screener.py               # both stages, a few minutes
uv run python analysis/stage1.py                 # Stage 1 only: data/screener/stage1.csv
uv run python analysis/stage2.py                 # Stage 2 only, on Stage 1's last output
uv run python analysis/screener.py --no-adjusted # skip the adjusted-EPS refinement
uv run python analysis/screener.py --refresh     # ignore today's cached downloads
```
