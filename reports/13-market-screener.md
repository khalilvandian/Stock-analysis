# Market screener: cheap or close-to-cheap stocks in the US and Europe

*Data as of 2026-10-27 (prices at the 2026-10-27 close for Europe, intraday for the US). Written 2026-10-27. Tool: `analysis/screener.py`, settings in `config/screeners.toml`.*

## 1. Summary

- **3,431 companies** above $1bn market value in the US and 17 European markets were screened in about two minutes, all from free sources with no keys.
- **880 pass** the fundamentals rules of their screener (general, utilities, banks, insurers, REITs). **263 of them are cheap or close to cheap** against their own cheap price; the top 3 per sector make an **85-name list** (42 US, 43 Europe).
- **Cheapest against their own history (US):** Trade Desk, Adobe, Intuit, Euronet, Maximus, Zoetis, Incyte. **Europe:** Aena, naturenergie, H&K, Novo Nordisk, Fielmann, Vitec Software. Most cheap names are in a downtrend: the technicals say to wait for the trend to turn.
- **No bank made the list** in either region: the 200 banks that pass are all priced above their own cheap multiple after the 2023–2026 rally.

## 2. The numbers

Absolute values first, then the cheap price and the timing read. Full table of every company with its status, the rules it failed and the source of every filled value: `data/screener/2026-10-27.csv`; the top list: `data/screener/top.csv`.

### US: absolute values

Price in the trading currency; amounts in US$ billions; EPS (12 months, diluted) in the reporting currency.

| Company | Sector | Price | Market value | Total debt | Net debt | Short-term debt | Long-term debt | Cash | Revenue | EBITDA | Net income | EPS | Op. cash flow | Capex | Free cash flow |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Euronet Worldwide, Inc. (EEFT) | Commercial Services | 59.89 USD | 2.2 | 2.8 | 0.6 | 0.9 | 1.9 | 2.2 | 4.4 | 0.7 | 0.3 | 6.37 | 0.4 | -0.1 | 0.2 |
| MAXIMUS, Inc. (MMS) | Commercial Services | 62.77 USD | 3.3 | 1.7 | 1.6 | 0.1 | 1.6 | 0.2 | 5.2 | 0.7 | 0.4 | 6.77 | 0.5 | -0.0 | 0.4 |
| PayPal Holdings, Inc. (PYPL) | Commercial Services | 55.77 USD | 47.7 | 14.2 | 3.0 | 2.7 | 11.6 | 11.3 | 34.3 | 7.5 | 4.9 | 5.29 | 7.5 | -0.9 | 6.6 |
| La-Z-Boy Incorporated (LZB) | Consumer Durables | 29.78 USD | 1.2 | 0.5 | 0.3 | 0.1 | 0.5 | 0.3 | 2.1 | 0.3 | 0.1 | 1.97 | 0.2 | -0.1 | 0.1 |
| Dorman Products, Inc. (DORM) | Consumer Durables | 124.11 USD | 3.7 | 0.5 | 0.4 | 0.0 | 0.5 | 0.1 | 2.2 | 0.4 | 0.2 | 7.22 | 0.3 | -0.0 | 0.2 |
| NVR, Inc. (NVR) | Consumer Durables | 5,715.00 USD | 15.2 | 1.1 | -0.1 | 0.0 | 1.1 | 1.2 | 9.2 | 1.8 | 1.0 | 362.72 | 1.1 | -0.0 | 1.0 |
| Deckers Outdoor Corporation (DECK) | Consumer Non-Durables | 79.78 USD | 10.9 | 0.5 | -0.7 | 0.1 | 0.5 | 1.2 | 5.6 | 1.4 | 1.1 | 7.54 | 1.2 | -0.1 | 1.1 |
| Marzetti Company (MZTI) | Consumer Non-Durables | 107.69 USD | 2.9 | 0.3 | 0.2 | 0.0 | 0.2 | 0.0 | 1.9 | 0.3 | 0.2 | 6.98 | 0.3 | -0.1 | 0.2 |
| PepsiCo, Inc. (PEP) | Consumer Non-Durables | 132.69 USD | 180.8 | 51.9 | 40.7 | 9.2 | 42.7 | 11.2 | 98.2 | 20.0 | 10.9 | 7.96 | 14.6 | -4.1 | 10.5 |
| Arcos Dorados Holdings, Inc. Class A (ARCO) | Consumer Services | 7.05 USD | 1.5 | 2.2 | 1.9 | 0.2 | 2.0 | 0.3 | 5.0 | 0.5 | 0.3 | 1.22 | 0.3 | -0.2 | 0.1 |
| Stride, Inc. (LRN) | Consumer Services | 79.52 USD | 3.3 | 0.6 | -0.2 | 0.5 | 0.1 | 0.8 | 2.5 | 0.6 | 0.3 | 7.26 | 0.5 | -0.1 | 0.5 |
| Strategic Education, Inc. (STRA) | Consumer Services | 81.04 USD | 1.8 | 0.1 | -0.0 | 0.0 | 0.1 | 0.1 | 1.3 | 0.2 | 0.1 | 6.00 | 0.2 | -0.0 | 0.2 |
| Sysco Corporation (SYY) | Distribution Services | 82.14 USD | 40.4 | 15.0 | 13.2 | 1.4 | 13.6 | 1.8 | 84.6 | 4.7 | 1.8 | 3.65 | 2.6 | -0.7 | 1.9 |
| Universal Display Corporation (OLED) | Electronic Technology | 90.18 USD | 4.1 | 0.0 | -0.4 | 0.0 | 0.0 | 0.5 | 0.6 | 0.3 | 0.2 | 4.13 | 0.3 | -0.1 | 0.2 |
| Textron Inc. (TXT) | Electronic Technology | 78.19 USD | 13.4 | 4.2 | 2.6 | 0.4 | 3.8 | 1.6 | 15.3 | 1.4 | 0.9 | 5.30 | 1.2 | -0.5 | 0.8 |
| Cirrus Logic, Inc. (CRUS) | Electronic Technology | 114.09 USD | 5.7 | 0.1 | -0.8 | 0.0 | 0.1 | 0.9 | 2.0 | 0.5 | 0.4 | 8.17 | 0.6 | -0.0 | 0.6 |
| Allstate Corporation (ALL) | Finance | 251.59 USD | 63.6 | 7.5 | 6.7 | 0.0 | 7.5 |  | 70.1 |  | 13.3 | 50.07 | 12.5 | -0.2 | 12.2 |
| XP Inc. Class A (XP) | Finance | 16.23 USD | 8.4 | 17.9 | 16.4 | 17.4 | 0.6 | 1.5 | 3.6 | 1.2 | 1.0 | 1.92 | 9.0 | -0.1 | 8.9 |
| T. Rowe Price Group, Inc. (TROW) | Finance | 103.75 USD | 22.1 | 0.6 | -2.6 | 0.0 | 0.6 | 3.2 | 7.6 | 3.2 | 2.2 | 9.97 | 3.1 | -0.3 | 2.8 |
| Addus HomeCare Corporation (ADUS) | Health Services | 120.80 USD | 2.3 | 0.1 | 0.0 | 0.0 | 0.1 | 0.1 | 1.5 | 0.2 | 0.1 | 5.70 | 0.2 | -0.0 | 0.2 |
| Zoetis, Inc. Class A (ZTS) | Health Technology | 78.89 USD | 32.6 | 9.2 | 7.6 | 0.0 | 9.2 | 1.7 | 9.5 | 4.1 | 2.6 | 6.08 | 2.9 | -0.5 | 2.4 |
| Incyte Corporation (INCY) | Health Technology | 115.64 USD | 23.4 | 0.0 | -4.5 | 0.0 | 0.0 | 4.5 | 5.8 | 1.9 | 1.6 | 7.85 | 2.0 | -0.1 | 1.9 |
| Neurocrine Biosciences, Inc. (NBIX) | Health Technology | 144.61 USD | 14.7 | 0.4 | 0.0 | 0.0 | 0.4 | 0.4 | 3.4 | 0.9 | 0.7 | 6.83 | 0.8 | -0.0 | 0.8 |
| Plains GP Holdings LP Class A (PAGP) | Industrial Services | 28.45 USD | 5.6 | 8.6 | 7.6 | 0.0 | 8.6 | 1.1 | 52.2 | 2.4 | 0.6 | 2.73 | 3.0 | -0.6 | 2.4 |
| Installed Building Products, Inc. (IBP) | Industrial Services | 205.18 USD | 5.5 | 1.2 | 0.8 | 0.1 | 1.1 | 0.4 | 3.0 | 0.5 | 0.3 | 9.29 | 0.4 | -0.1 | 0.3 |
| Tetra Tech, Inc. (TTEK) | Industrial Services | 36.93 USD | 9.5 | 1.0 | 0.8 | 0.1 | 0.9 | 0.2 | 5.1 | 0.7 | 0.4 | 1.66 | 0.6 | -0.0 | 0.5 |
| CRH public limited company (CRH) | Non-Energy Minerals | 85.88 USD | 57.1 | 19.8 | 16.7 | 2.9 | 16.9 | 3.1 | 38.6 | 7.7 | 3.8 | 5.67 | 5.6 | -2.7 | 2.9 |
| Eagle Materials Inc. (EXP) | Non-Energy Minerals | 174.54 USD | 5.4 | 1.8 | 1.6 | 0.0 | 1.8 | 0.2 | 2.3 | 0.7 | 0.4 | 12.64 | 0.6 | -0.5 | 0.2 |
| Seaboard Corporation (SEB) | Process Industries | 3,877.56 USD | 3.7 | 2.0 | 0.7 | 0.8 | 1.2 | 1.2 | 10.3 | 0.7 | 0.6 | 661.84 | 0.5 | -0.5 | -0.0 |
| PPG Industries, Inc. (PPG) | Process Industries | 111.37 USD | 24.8 | 7.5 | 5.9 | 0.8 | 6.6 | 1.6 | 16.4 | 2.7 | 1.6 | 6.96 | 2.2 | -0.8 | 1.4 |
| Axalta Coating Systems Ltd. (AXTA) | Process Industries | 34.48 USD | 7.4 | 3.1 | 2.4 | 0.5 | 2.5 | 0.6 | 5.2 | 1.0 | 0.3 | 1.62 | 0.7 | -0.2 | 0.5 |
| Xylem Inc. (XYL) | Producer Manufacturing | 94.89 USD | 22.2 | 3.1 | 1.8 | 0.7 | 2.4 | 1.3 | 9.1 | 2.0 | 1.0 | 4.21 | 1.3 | -0.4 | 0.9 |
| Mueller Water Products, Inc. Class A (MWA) | Producer Manufacturing | 22.40 USD | 3.5 | 0.5 | -0.0 | 0.0 | 0.5 | 0.5 | 1.5 | 0.4 | 0.2 | 1.41 | 0.2 | -0.1 | 0.2 |
| LCI Industries (LCII) | Producer Manufacturing | 89.25 USD | 2.2 | 1.1 | 0.9 | 0.0 | 1.1 | 0.2 | 4.0 | 0.4 | 0.2 | 8.60 | 0.3 | -0.1 | 0.3 |
| Copart, Inc. (CPRT) | Retail Trade | 28.95 USD | 26.8 | 0.1 | -4.4 | 0.0 | 0.1 | 4.5 | 4.7 | 1.9 | 1.5 | 1.55 | 1.6 | -0.3 | 1.3 |
| Sprouts Farmers Market, Inc. (SFM) | Retail Trade | 64.16 USD | 6.0 | 2.1 | 1.9 | 0.2 | 1.9 | 0.2 | 9.0 | 1.0 | 0.5 | 5.22 | 0.7 | -0.3 | 0.4 |
| Burlington Stores, Inc. (BURL) | Retail Trade | 235.25 USD | 14.8 | 5.9 | 5.2 | 0.5 | 5.4 | 0.7 | 12.2 | 1.4 | 0.7 | 11.15 | 1.4 | -1.0 | 0.4 |
| Trade Desk, Inc. Class A (TTD) | Technology Services | 12.77 USD | 6.0 | 0.4 | -1.1 | 0.1 | 0.4 | 1.5 | 3.0 | 0.7 | 0.4 | 0.84 | 1.1 | -0.2 | 0.9 |
| Adobe Inc. (ADBE) | Technology Services | 249.50 USD | 97.1 | 6.8 | 1.1 | 1.7 | 5.1 | 5.6 | 26.0 | 10.2 | 7.3 | 17.93 | 10.8 | -0.2 | 10.6 |
| Intuit Inc. (INTU) | Technology Services | 326.19 USD | 87.2 | 8.4 | 1.2 | 1.3 | 7.1 | 7.2 | 21.4 | 7.0 | 4.6 | 16.50 | 8.8 | -0.2 | 8.6 |
| DHT Holdings, Inc. (DHT) | Transportation | 24.41 USD | 3.9 | 0.4 | 0.3 | 0.0 | 0.4 | 0.2 | 0.7 | 0.5 | 0.5 | 2.94 | 0.5 | -0.4 | 0.0 |
| Atmos Energy Corporation (ATO) | Utilities | 170.87 USD | 28.9 | 10.3 | 9.8 | 0.5 | 9.8 | 0.5 | 4.9 | 2.6 | 1.4 | 8.40 | 2.0 | -4.0 | -2.0 |

### US: cheap price and timing

| Company | Sector | P/E now | Cheap P/E | Set by | Cheap price | Price vs cheap | Label | EPS used | Trend | RSI | TradingView rating |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Euronet Worldwide, Inc. | Commercial Services | 5.8x | 14.0x | own history | 144.77 USD | -59% | cheap | adjusted | downtrend | 33 | strong sell |
| MAXIMUS, Inc. | Commercial Services | 8.1x | 18.0x | own history | 139.72 USD | -55% | cheap | adjusted | downtrend | 66 | buy |
| PayPal Holdings, Inc. | Commercial Services | 10.3x | 17.0x | own history | 91.76 USD | -39% | cheap | adjusted | uptrend | 51 | buy |
| La-Z-Boy Incorporated | Consumer Durables | 9.9x | 13.1x | own history | 39.46 USD | -25% | cheap | adjusted | downtrend | 47 | sell |
| Dorman Products, Inc. | Consumer Durables | 13.9x | 17.7x | own history | 157.25 USD | -21% | cheap | adjusted | uptrend | 50 | neutral |
| NVR, Inc. | Consumer Durables | 15.8x | 14.6x | own history | 5,297.66 USD | +8% | close | adjusted | downtrend | 40 | strong sell |
| Deckers Outdoor Corporation | Consumer Non-Durables | 10.6x | 15.4x | own history | 116.18 USD | -31% | cheap | adjusted | downtrend | 40 | sell |
| Marzetti Company | Consumer Non-Durables | 16.0x | 21.6x | sector median | 145.26 USD | -26% | cheap | adjusted | downtrend | 57 | buy |
| PepsiCo, Inc. | Consumer Non-Durables | 15.8x | 20.9x | own history | 175.78 USD | -25% | cheap | adjusted | downtrend | 52 | sell |
| Arcos Dorados Holdings, Inc. Class A | Consumer Services | 5.7x | 11.1x | own history | 13.69 USD | -48% | cheap | adjusted | downtrend | 36 | strong sell |
| Stride, Inc. | Consumer Services | 9.6x | 15.4x | own history | 127.54 USD | -38% | cheap | adjusted | downtrend | 47 | sell |
| Strategic Education, Inc. | Consumer Services | 12.4x | 18.0x | own history | 117.46 USD | -31% | cheap | adjusted | uptrend | 51 | buy |
| Sysco Corporation | Distribution Services | 17.8x | 18.0x | own history | 82.90 USD | -1% | cheap | adjusted | uptrend | 56 | buy |
| Universal Display Corporation | Electronic Technology | 21.8x | 36.1x | own history | 149.28 USD | -40% | cheap | adjusted | downtrend | 70 | buy |
| Textron Inc. | Electronic Technology | 12.3x | 13.6x | own history | 86.30 USD | -9% | cheap | adjusted | downtrend | 54 | buy |
| Cirrus Logic, Inc. | Electronic Technology | 11.9x | 12.3x | own history | 117.80 USD | -3% | cheap | adjusted | downtrend | 52 | neutral |
| Allstate Corporation | Finance | 5.2x | 9.2x | own history | 439.37 USD | -43% | cheap | adjusted | uptrend | 59 | buy |
| XP Inc. Class A | Finance | 8.5x | 12.8x | own history | 24.59 USD | -34% | cheap | diluted | mixed | 30 | sell |
| T. Rowe Price Group, Inc. | Finance | 10.0x | 13.3x | own history | 138.04 USD | -25% | cheap | adjusted | uptrend | 49 | neutral |
| Addus HomeCare Corporation | Health Services | 18.1x | 21.0x | own history | 140.51 USD | -14% | cheap | adjusted | uptrend | 63 | buy |
| Zoetis, Inc. Class A | Health Technology | 12.0x | 25.9x | own history | 170.51 USD | -54% | cheap | adjusted | downtrend | 59 | neutral |
| Incyte Corporation | Health Technology | 12.9x | 24.9x | own history | 222.80 USD | -48% | cheap | adjusted | uptrend | 48 | buy |
| Neurocrine Biosciences, Inc. | Health Technology | 16.4x | 24.4x | own history | 215.92 USD | -33% | cheap | adjusted | downtrend | 53 | neutral |
| Plains GP Holdings LP Class A | Industrial Services | 10.5x | 10.7x | own history | 29.15 USD | -2% | cheap | adjusted | uptrend | 68 | buy |
| Installed Building Products, Inc. | Industrial Services | 18.5x | 17.0x | own history | 188.69 USD | +9% | close | adjusted | downtrend | 58 | buy |
| Tetra Tech, Inc. | Industrial Services | 23.7x | 21.5x | own history | 33.57 USD | +10% | close | adjusted | uptrend | 69 | buy |
| CRH public limited company | Non-Energy Minerals | 15.1x | 14.2x | own history | 80.74 USD | +6% | close | diluted | downtrend | 53 | neutral |
| Eagle Materials Inc. | Non-Energy Minerals | 13.8x | 12.5x | own history | 158.24 USD | +10% | close | adjusted | downtrend | 50 | neutral |
| Seaboard Corporation | Process Industries | 5.9x | 7.8x | own history | 5,180.39 USD | -25% | cheap | diluted | downtrend | 42 | sell |
| PPG Industries, Inc. | Process Industries | 14.5x | 17.4x | own history | 133.87 USD | -17% | cheap | adjusted | downtrend | 60 | buy |
| Axalta Coating Systems Ltd. | Process Industries | 13.6x | 16.0x | own history | 40.63 USD | -15% | cheap | adjusted | uptrend | 57 | buy |
| Xylem Inc. | Producer Manufacturing | 17.4x | 25.2x | own history | 137.29 USD | -31% | cheap | adjusted | downtrend | 30 | strong sell |
| Mueller Water Products, Inc. Class A | Producer Manufacturing | 14.3x | 18.8x | own history | 29.44 USD | -24% | cheap | adjusted | downtrend | 55 | neutral |
| LCI Industries | Producer Manufacturing | 11.0x | 13.7x | own history | 111.84 USD | -20% | cheap | adjusted | downtrend | 59 | buy |
| Copart, Inc. | Retail Trade | 18.7x | 20.2x | sector median | 31.32 USD | -8% | cheap | adjusted | downtrend | 55 | neutral |
| Sprouts Farmers Market, Inc. | Retail Trade | 12.3x | 12.9x | own history | 67.54 USD | -5% | cheap | adjusted | downtrend | 42 | strong sell |
| Burlington Stores, Inc. | Retail Trade | 20.4x | 20.2x | sector median | 233.19 USD | +1% | close | adjusted | downtrend | 30 | strong sell |
| Trade Desk, Inc. Class A | Technology Services | 7.7x | 32.1x | sector median | 53.31 USD | -76% | cheap | adjusted | downtrend | 50 | sell |
| Adobe Inc. | Technology Services | 10.5x | 27.8x | own history | 658.27 USD | -62% | cheap | adjusted | mixed | 50 | sell |
| Intuit Inc. | Technology Services | 13.4x | 30.4x | own history | 739.72 USD | -56% | cheap | adjusted | downtrend | 54 | neutral |
| DHT Holdings, Inc. | Transportation | 9.6x | 8.7x | own history | 22.11 USD | +10% | close | adjusted | uptrend | 57 | buy |
| Atmos Energy Corporation | Utilities | 20.3x | 18.5x | own history | 155.88 USD | +10% | close | adjusted | downtrend | 65 | buy |

### Europe: absolute values

Price in the trading currency; amounts in US$ billions; EPS (12 months, diluted) in the reporting currency.

| Company | Sector | Price | Market value | Total debt | Net debt | Short-term debt | Long-term debt | Cash | Revenue | EBITDA | Net income | EPS | Op. cash flow | Capex | Free cash flow |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Ipsos SA (IPS) | Commercial Services | 35.46 EUR | 1.7 | 0.7 | 0.4 | 0.1 | 0.7 | 0.3 | 2.8 | 0.4 | 0.2 | 3.99 | 0.3 | -0.1 | 0.3 |
| Prosegur Cash SA (CASH) | Commercial Services | 0.67 EUR | 1.1 | 1.3 | 0.8 | 0.4 | 0.9 | 0.5 | 2.2 | 0.4 | 0.1 | 0.06 | 0.3 | -0.1 | 0.2 |
| 4imprint Group plc (FOUR) | Commercial Services | 4,502.00 GBX | 1.6 | 0.0 | -0.1 | 0.0 | 0.0 | 0.1 | 1.3 | 0.1 | 0.1 | 2.69 | 0.1 | -0.0 | 0.1 |
| Hellenic Telecommunications Organization SA (HTO) | Communications | 19.03 EUR | 8.3 | 1.3 | 0.4 | 0.7 | 0.6 | 0.9 | 3.9 | 1.6 | 0.6 | 1.38 | 1.2 | -0.6 | 0.6 |
| Trigano SA (TRI) | Consumer Durables | 123.70 EUR | 2.7 | 0.2 | -0.4 | 0.1 | 0.1 | 0.6 | 4.2 | 0.5 | 0.3 | 13.21 | 0.6 | -0.0 | 0.6 |
| Howden Joinery Group PLC (HWDN) | Consumer Durables | 806.50 GBX | 5.8 | 1.0 | 0.5 | 0.1 | 0.8 | 0.4 | 3.3 | 0.7 | 0.4 | 0.49 | 0.7 | -0.2 | 0.4 |
| Cairn Homes PLC (CRN) | Consumer Durables | 233.00 GBX | 1.9 | 0.3 | 0.2 | 0.1 | 0.2 | 0.1 | 1.3 | 0.2 | 0.2 | 0.22 | 0.2 | -0.0 | 0.2 |
| HUGO BOSS AG (BOSS) | Consumer Non-Durables | 38.68 EUR | 2.9 | 1.1 | 0.9 | 0.2 | 0.9 | 0.3 | 4.5 | 0.8 | 0.2 | 3.15 | 0.8 |  | 0.6 |
| Christian Dior SE (CDI) | Consumer Non-Durables | 423.20 EUR | 84.4 | 40.8 | 27.1 | 11.2 | 29.6 | 13.8 | 88.8 | 28.1 | 5.1 | 25.23 | 20.8 | -5.0 | 16.7 |
| LVMH Moet Hennessy Louis Vuitton SE (MC) | Consumer Non-Durables | 388.25 EUR | 211.6 | 40.8 | 27.2 | 11.2 | 29.6 | 13.6 | 88.8 | 26.7 | 12.1 | 21.95 | 20.8 | -4.9 | 16.8 |
| CTS Eventim AG & Co. KGaA (EVD) | Consumer Services | 62.60 EUR | 6.7 | 0.3 | -1.2 | 0.1 | 0.2 | 1.5 | 3.7 | 0.7 | 0.3 | 3.21 | 0.6 |  | 0.3 |
| DO & CO Aktiengesellschaft (DOC) | Consumer Services | 198.20 EUR | 2.4 | 0.3 | -0.0 | 0.1 | 0.2 | 0.3 | 2.8 | 0.3 | 0.1 | 10.03 | 0.3 | -0.1 | 0.3 |
| Jet2 PLC (JET2) | Consumer Services | 1,408.00 GBX | 3.4 | 1.7 | -2.7 | 0.4 | 1.3 | 4.4 | 10.0 | 1.0 | 0.5 | 1.90 | 1.2 | -0.5 | 0.7 |
| Bunzl plc (BNZL) | Distribution Services | 2,874.00 GBX | 11.9 | 3.6 | 2.8 | 0.6 | 3.0 | 0.8 | 16.0 | 1.6 | 0.7 | 1.51 | 1.3 | -0.1 | 1.2 |
| Inchcape plc (INCH) | Distribution Services | 638.00 GBX | 2.9 | 1.9 | 0.9 | 0.7 | 1.1 | 1.0 | 12.7 | 0.9 | 0.3 | 0.63 | 0.5 | -0.1 | 0.5 |
| H&K AG (MLHK) | Electronic Technology | 30.00 EUR | 1.2 | 0.1 | 0.1 | 0.0 | 0.1 | 0.0 | 0.5 | 0.1 | 0.1 | 1.89 | 0.0 | -0.0 | 0.0 |
| ATOSS Software SE (AOF) | Electronic Technology | 94.70 EUR | 1.7 | 0.0 | -0.1 | 0.0 | 0.0 | 0.1 | 0.2 | 0.1 | 0.1 | 3.22 | 0.1 | -0.0 | 0.1 |
| MTU Aero Engines AG (MTX) | Electronic Technology | 329.70 EUR | 19.6 | 2.8 | 1.4 | 0.4 | 2.4 | 1.4 | 10.3 | 1.8 | 1.1 | 17.12 | 1.1 | -0.6 | 0.6 |
| L E Lundbergforetagen AB Class B (LUND_B) | Finance | 580.00 SEK | 14.3 | 2.6 | 2.6 | 0.6 | 2.0 |  | 2.9 | 1.0 | 1.9 | 74.56 | 0.8 | -0.1 | 0.7 |
| Industrivarden AB Class A (INDU_A) | Finance | 519.00 SEK | 22.2 | 0.6 | 0.4 | 0.2 | 0.5 | 0.2 | 1.0 |  | 5.4 | 124.61 | 0.9 | 0.0 | 0.9 |
| Munchener Ruckversicherungs-Gesellschaft AG (MUV2) | Finance | 553.80 EUR | 78.2 | 8.2 | 1.8 | 0.0 | 8.2 |  | 78.9 |  | 7.7 | 53.68 |  |  |  |
| RHON-KLINIKUM AG (RHK) | Health Services | 14.30 EUR | 1.1 | 0.1 | -0.0 | 0.0 | 0.1 | 0.1 | 1.9 | 0.1 | 0.0 | 0.63 |  |  |  |
| Novo Nordisk A/S Class B (NOVO_B) | Health Technology | 259.50 DKK | 172.2 | 20.9 | 14.2 | 2.7 | 18.2 | 6.7 | 49.1 | 25.3 | 17.4 | 26.19 | 19.5 | -12.5 | 11.1 |
| Fielmann Group AG (FIE) | Health Technology | 39.95 EUR | 3.7 | 1.0 | 0.7 | 0.1 | 0.9 | 0.3 | 2.8 | 0.6 | 0.2 | 2.52 | 0.5 | -0.1 | 0.3 |
| Dermapharm Holding SE (DMP) | Health Technology | 38.40 EUR | 2.1 | 1.3 | 1.1 | 0.2 | 1.1 | 0.2 | 1.3 | 0.4 | 0.2 | 2.76 | 0.2 | -0.1 | 0.2 |
| AF Gruppen ASA Class A (AFG) | Industrial Services | 195.60 NOK | 2.4 | 0.2 | 0.0 | 0.0 | 0.1 | 0.1 | 3.7 | 0.3 | 0.1 | 10.99 | 0.3 |  | 0.3 |
| Norsk Hydro ASA (NHY) | Non-Energy Minerals | 68.70 NOK | 14.3 | 3.8 | 1.7 | 0.6 | 3.2 | 2.1 | 22.3 | 3.3 | 1.4 | 6.58 | 1.9 | -1.2 | 0.7 |
| Henkel AG & Co. KGaA (HEN) | Process Industries | 71.15 EUR | 33.6 | 6.8 | 2.3 | 3.2 | 3.6 | 4.4 | 22.8 | 4.2 | 2.1 | 4.71 | 3.0 | -0.8 | 2.3 |
| FUCHS SE (FPE) | Process Industries | 38.45 EUR | 6.1 | 0.2 | -0.0 | 0.1 | 0.1 | 0.2 | 4.2 | 0.7 | 0.4 | 2.60 | 0.4 | -0.1 | 0.3 |
| Akzo Nobel N.V. (AKZA) | Process Industries | 58.84 EUR | 11.2 | 7.2 | 3.4 | 1.1 | 6.1 | 3.8 | 11.0 | 1.1 | 0.7 | 3.80 | 1.0 | -0.3 | 0.6 |
| Burckhardt Compression Holding AG (BCHN) | Producer Manufacturing | 476.50 CHF | 1.9 | 0.2 | -0.1 | 0.0 | 0.2 | 0.3 | 1.3 | 0.2 | 0.1 | 32.60 | 0.2 | -0.0 | 0.2 |
| Krones AG (KRN) | Producer Manufacturing | 112.80 EUR | 3.9 | 0.2 | -0.3 | 0.1 | 0.1 | 0.5 | 6.3 | 0.7 | 0.3 | 9.25 | 0.5 | -0.2 | 0.3 |
| CIE Automotive, S.A. (CIE) | Producer Manufacturing | 25.45 EUR | 3.5 | 2.1 | 1.2 | 0.7 | 1.4 | 1.0 | 4.5 | 0.9 | 0.4 | 2.88 | 0.7 | -0.3 | 0.4 |
| Jeronimo Martins, SGPS S.A. (JMT) | Retail Trade | 18.12 EUR | 12.7 | 6.7 | 4.9 | 1.4 | 5.3 | 1.8 | 41.1 | 2.8 | 0.7 | 1.02 | 2.5 | -1.2 | 1.3 |
| Watches of Switzerland Group PLC (WOSG) | Retail Trade | 731.00 GBX | 2.4 | 0.7 | 0.6 | 0.1 | 0.7 | 0.1 | 2.4 | 0.4 | 0.1 | 0.43 | 0.3 | -0.1 | 0.2 |
| Jumbo S.A. (BELA) | Retail Trade | 27.40 EUR | 4.1 | 0.1 | -0.5 | 0.0 | 0.1 | 0.6 | 1.4 | 0.5 | 0.4 | 2.41 | 0.4 | -0.0 | 0.4 |
| Vitec Software Group AB Class B (VIT_B) | Technology Services | 309.60 SEK | 1.2 | 0.4 | 0.3 | 0.0 | 0.4 | 0.1 | 0.4 | 0.2 | 0.0 | 11.86 | 0.1 | -0.0 | 0.1 |
| Autotrader Group PLC (AUTO) | Technology Services | 528.20 GBX | 5.4 | 0.3 | 0.3 | 0.0 | 0.3 | 0.0 | 0.8 | 0.5 | 0.4 | 0.34 | 0.4 | -0.0 | 0.4 |
| Mony Group PLC (MONY) | Technology Services | 200.40 GBX | 1.4 | 0.1 | 0.0 | 0.0 | 0.1 | 0.0 | 0.6 | 0.2 | 0.1 | 0.16 | 0.1 | -0.0 | 0.1 |
| Ryanair Holdings PLC (RYA) | Transportation | 23.20 EUR | 26.6 | 0.2 | -3.0 | 0.0 | 0.2 | 3.2 | 17.4 | 4.0 | 2.1 | 1.77 | 3.8 | -1.9 | 1.9 |
| naturenergie holding AG (NEAG) | Utilities | 29.20 CHF | 1.2 | 0.1 | -0.2 | 0.0 | 0.1 | 0.3 | 1.6 | 0.3 | 0.2 | 4.57 | 0.3 |  |  |
| Aker Solutions ASA (AKSO) | Utilities | 38.16 NOK | 2.0 | 0.3 | -0.2 | 0.1 | 0.2 | 0.5 | 6.4 | 0.5 | 0.3 | 6.70 | 0.5 | -0.0 | 0.5 |
| Fluxys Belgium SA Class D (FLUX) | Utilities | 20.60 EUR | 1.6 | 1.2 | 0.3 | 0.1 | 1.1 | 0.9 | 0.8 | 0.4 | 0.1 | 1.28 | 0.2 | -0.3 | -0.1 |

### Europe: cheap price and timing

| Company | Sector | P/E now | Cheap P/E | Set by | Cheap price | Price vs cheap | Label | EPS used | Trend | RSI | TradingView rating |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Ipsos SA | Commercial Services | 8.9x | 9.7x | own history | 38.61 EUR | -8% | cheap | diluted | mixed | 45 | strong sell |
| Prosegur Cash SA | Commercial Services | 11.1x | 11.9x | own history | 0.71 EUR | -7% | cheap | adjusted | uptrend | 48 | neutral |
| 4imprint Group plc | Commercial Services | 16.7x | 16.0x | own history | 4,295.77 GBX | +5% | close | diluted | uptrend | 54 | strong buy |
| Hellenic Telecommunications Organization SA | Communications | 12.4x | 11.4x | own history | 17.58 EUR | +8% | close | adjusted | uptrend | 41 | sell |
| Trigano SA | Consumer Durables | 9.4x | 9.4x | own history | 124.02 EUR | -0% | cheap | diluted | downtrend | 31 | sell |
| Howden Joinery Group PLC | Consumer Durables | 16.5x | 15.0x | own history | 733.83 GBX | +10% | close | diluted | mixed | 64 | buy |
| Cairn Homes PLC | Consumer Durables | 10.5x | 9.5x | own history | 211.16 GBX | +10% | close | diluted | uptrend | 60 | strong buy |
| HUGO BOSS AG | Consumer Non-Durables | 12.3x | 16.0x | own history | 50.37 EUR | -23% | cheap | adjusted | uptrend | 60 | buy |
| Christian Dior SE | Consumer Non-Durables | 16.8x | 20.3x | sector median | 512.52 EUR | -17% | cheap | diluted | downtrend | 56 | buy |
| LVMH Moet Hennessy Louis Vuitton SE | Consumer Non-Durables | 17.7x | 20.3x | sector median | 445.78 EUR | -13% | cheap | diluted | downtrend | 44 | sell |
| CTS Eventim AG & Co. KGaA | Consumer Services | 19.5x | 21.6x | sector median | 69.43 EUR | -10% | cheap | diluted | mixed | 62 | buy |
| DO & CO Aktiengesellschaft | Consumer Services | 19.8x | 20.0x | own history | 201.02 EUR | -1% | cheap | diluted | uptrend | 54 | strong buy |
| Jet2 PLC | Consumer Services | 7.4x | 7.1x | own history | 1,352.44 GBX | +4% | close | diluted | uptrend | 47 | sell |
| Bunzl plc | Distribution Services | 19.0x | 19.1x | own history | 2,883.41 GBX | -0% | cheap | diluted | uptrend | 66 | strong buy |
| Inchcape plc | Distribution Services | 10.1x | 9.9x | own history | 624.53 GBX | +2% | close | diluted | downtrend | 33 | sell |
| H&K AG | Electronic Technology | 15.9x | 34.4x | sector median | 64.95 EUR | -54% | cheap | diluted | downtrend | 39 | strong sell |
| ATOSS Software SE | Electronic Technology | 29.4x | 31.6x | own history | 101.81 EUR | -7% | cheap | diluted | uptrend | 58 | buy |
| MTU Aero Engines AG | Electronic Technology | 18.3x | 17.9x | own history | 323.04 EUR | +2% | close | adjusted | mixed | 39 | sell |
| L E Lundbergforetagen AB Class B | Finance | 7.8x | 10.5x | own history | 779.90 SEK | -26% | cheap | diluted | uptrend | 56 | strong buy |
| Industrivarden AB Class A | Finance | 4.2x | 4.6x | own history | 572.25 SEK | -9% | cheap | diluted | uptrend | 50 | buy |
| Munchener Ruckversicherungs-Gesellschaft AG | Finance | 10.3x | 10.5x | own history | 561.78 EUR | -1% | cheap | adjusted | uptrend | 71 | buy |
| RHON-KLINIKUM AG | Health Services | 22.7x | 20.6x | sector median | 12.98 EUR | +10% | close | diluted | uptrend | 44 | sell |
| Novo Nordisk A/S Class B | Health Technology | 11.1x | 19.5x | own history | 456.45 DKK | -43% | cheap | adjusted | downtrend | 47 | sell |
| Fielmann Group AG | Health Technology | 15.8x | 26.5x | sector median | 66.71 EUR | -40% | cheap | diluted | downtrend | 66 | buy |
| Dermapharm Holding SE | Health Technology | 13.9x | 17.7x | own history | 48.90 EUR | -21% | cheap | diluted | downtrend | 49 | neutral |
| AF Gruppen ASA Class A | Industrial Services | 17.8x | 17.4x | sector median | 192.02 NOK | +2% | close | adjusted | uptrend | 59 | buy |
| Norsk Hydro ASA | Non-Energy Minerals | 9.5x | 13.0x | own history | 94.01 NOK | -27% | cheap | adjusted | downtrend | 23 | sell |
| Henkel AG & Co. KGaA | Process Industries | 15.1x | 17.5x | own history | 82.36 EUR | -14% | cheap | diluted | uptrend | 59 | buy |
| FUCHS SE | Process Industries | 14.8x | 14.5x | own history | 37.62 EUR | +2% | close | diluted | uptrend | 56 | buy |
| Akzo Nobel N.V. | Process Industries | 16.7x | 16.2x | own history | 57.11 EUR | +3% | close | adjusted | uptrend | 52 | buy |
| Burckhardt Compression Holding AG | Producer Manufacturing | 14.6x | 20.1x | own history | 656.19 CHF | -27% | cheap | diluted | downtrend | 47 | strong sell |
| Krones AG | Producer Manufacturing | 12.2x | 14.7x | own history | 135.70 EUR | -17% | cheap | adjusted | downtrend | 56 | buy |
| CIE Automotive, S.A. | Producer Manufacturing | 8.8x | 9.5x | own history | 27.32 EUR | -7% | cheap | diluted | downtrend | 47 | strong sell |
| Jeronimo Martins, SGPS S.A. | Retail Trade | 15.0x | 17.9x | sector median | 21.60 EUR | -16% | cheap | adjusted | downtrend | 55 | buy |
| Watches of Switzerland Group PLC | Retail Trade | 17.2x | 17.9x | sector median | 759.89 GBX | -4% | cheap | diluted | uptrend | 59 | buy |
| Jumbo S.A. | Retail Trade | 11.4x | 10.6x | own history | 25.44 EUR | +8% | close | diluted | uptrend | 70 | strong buy |
| Vitec Software Group AB Class B | Technology Services | 15.1x | 22.1x | sector median | 453.81 SEK | -32% | cheap | adjusted | uptrend | 67 | buy |
| Autotrader Group PLC | Technology Services | 15.5x | 21.6x | own history | 735.01 GBX | -28% | cheap | diluted | uptrend | 59 | buy |
| Mony Group PLC | Technology Services | 12.9x | 15.8x | own history | 246.96 GBX | -19% | cheap | diluted | uptrend | 62 | strong buy |
| Ryanair Holdings PLC | Transportation | 12.5x | 11.0x | own history | 20.37 EUR | +14% | close | adjusted | downtrend | 51 | buy |
| naturenergie holding AG | Utilities | 6.4x | 13.6x | own history | 62.01 CHF | -53% | cheap | diluted | downtrend | 44 | sell |
| Aker Solutions ASA | Utilities | 6.4x | 8.1x | own history | 48.57 NOK | -21% | cheap | adjusted | downtrend | 40 | sell |
| Fluxys Belgium SA Class D | Utilities | 16.1x | 17.3x | sector median | 22.18 EUR | -7% | cheap | diluted | mixed | 42 | sell |

### Status counts

| Region | Screener | Fail | Incomplete | Pass |
|---|---|---|---|---|
| Europe | banks | 41 | 4 | 84 |
| Europe | general | 732 | 41 | 226 |
| Europe | insurers | 19 | 0 | 18 |
| Europe | reits | 24 | 1 | 1 |
| Europe | utilities | 48 | 0 | 8 |
| US | banks | 68 | 13 | 116 |
| US | general | 1242 | 142 | 351 |
| US | insurers | 38 | 5 | 32 |
| US | reits | 65 | 2 | 42 |
| US | utilities | 66 | 0 | 2 |

### Rules failed

| Rule | Stocks failing it |
|---|---|
| revenue and EPS growth | 1196 |
| cash covers short-term debt | 704 |
| Altman Z-score | 673 |
| profitable | 626 |
| Piotroski score | 505 |
| net debt / EBITDA | 486 |
| interest cover | 485 |
| cash vs long-term debt | 274 |
| return on equity | 75 |

## 3. Method

1. **Universe.** TradingView's screener, primary listings of common shares above $1bn (converted at ECB reference rates): the US (NYSE, Nasdaq, NYSE American) and the UK, Germany, France, Italy, Spain, the Netherlands, Switzerland, Sweden, Denmark, Norway, Finland, Belgium, Austria, Portugal, Ireland, Poland and Greece. Funds and trusts are skipped.
2. **Gap filling.** Short-term debt left blank is total debt minus long-term debt (690 stocks). Debt, cash, EBITDA and interest cover still blank are taken from Yahoo's statements (about 400 values); blank cash flows of the listed names too. Each filled value is named in the `filled` column.
3. **Screener by kind of business.** Industry decides: banks (including brokers and financial conglomerates), insurers, REITs, utilities (Utilities sector) and general (everything else).
    - General: cash ≥ short-term debt, cash ≥ 5% of long-term debt, net debt/EBITDA ≤ 4.5x, EBITDA/interest ≥ 4x (net cash passes both), profitable (net income, EBITDA, EPS > 0), revenue and EPS growth average and median > 0 over 5 years, Piotroski ≥ 5, Altman Z > 1.8. Piotroski and Altman are skipped (and flagged) when missing.
    - Utilities: the same debt rules (Babak's original), profitable, growth, Piotroski ≥ 5; no Altman.
    - Banks and insurers: profitable, return on equity ≥ 8%, growth. No debt rules: deposits and float are not debt in the usual sense.
    - REITs: cash ≥ short-term debt, net debt/EBITDA ≤ 7x, interest cover ≥ 2.5x, profitable.
    - Missing data for a required rule makes a stock "incomplete" (208 stocks), not a pass.
4. **Cheap price.** Yearly P/E for the last 10 fiscal years = Yahoo average monthly price over the fiscal year / TradingView diluted EPS for that year (both split-adjusted, price converted to the reporting currency). The cheap multiple is the bottom quarter of those P/Es (at least 6 years needed), capped at the median P/E of the same region and sector, so a stock whose whole history was priced for fast growth isn't called cheap at a multiple its peers never get. Cheap price = cheap multiple × EPS of the last 12 months.
5. **Adjusted EPS.** For the 9 closest names per sector, Yahoo's adjusted quarterly EPS replaces diluted EPS, with its own adjusted P/E history (the watch list's method), when it has at least 6 years and is within a factor of 2 of diluted EPS (a bigger gap is a data error: XP's Yahoo EPS was rejected).
6. **Ranking.** Inside each region and sector, by price against the cheap price, lowest first. Below it = cheap; up to 15% above = close; anything higher is not listed. Debt and profitability decide who gets in, not the order.
7. **Technicals, for timing only.** Trend from the 50- and 200-day averages, RSI (below 30 oversold, above 70 overbought), position in the 52-week range, and TradingView's technical rating.
8. **Cross-check.** US names' latest fiscal-year diluted EPS is compared with SEC EDGAR (38 of 42 found, none off by more than 10%).

**Sources (all free):** TradingView screener (fundamentals, 20 years of yearly EPS and revenue, technicals), Yahoo Finance (prices, adjusted EPS, statements for gaps), SEC EDGAR (EPS cross-check), ECB (exchange rates). Tested and available for later: European ESEF filings at filings.xbrl.org (the European equivalent of SEC filings), Euronext and Nasdaq company lists, OpenFIGI (identifiers). Free-key services that could be added if Babak registers: Finnhub, Alpha Vantage, EODHD, Financial Modeling Prep (the current key is invalid).

## 4. Findings

- **Growth is the biggest filter.** 1,196 companies fail the revenue-and-EPS growth rule, more than any debt rule. Next come cash covering short-term debt (704) and the Altman Z-score (673).
- **The list leans to fallen quality names:** software and data (Adobe, Intuit, Trade Desk, Autotrader, Mony, Vitec), health care (Novo Nordisk, Zoetis, Incyte, Neurocrine), consumer brands (PepsiCo, Deckers, LVMH, Hugo Boss). This matches the October panic-sell screen (Adobe, Intuit, Booking, Boston Scientific, Netflix were among its names).
- **Netflix (44% below its cheap price) and Booking (20% below) pass and are cheap, but miss the top 3** of their sectors, where other names sit further below. **Boston Scientific fails** the rule that cash must cover short-term debt.
- **Technicals mostly say "not yet":** 44 of the 85 names are in a downtrend (price and 50-day average below the 200-day).

## 5. Caveats

- **TradingView's and Yahoo's interfaces are unofficial.** Field names can change, and Yahoo rate-limits heavy use (a run makes about 1,500 Yahoo requests). Each run caches its downloads for the day in `.cache/screener/`.
- **Own history is not destiny.** A stock far below its cheap price may have been re-rated for a reason (Adobe and Trade Desk face AI disruption; Novo Nordisk lost its obesity-drug lead). The screen finds candidates; each one needs the full analysis.
- **Diluted EPS includes one-offs** where Yahoo's adjusted EPS is not available (32 of the 85 names, mostly European). A one-off charge makes a stock look expensive; a one-off gain makes it look cheap.
- **Foreign reporters** are converted at today's exchange rate for the P/E history, so currency moves over the decade are ignored.
- **Sectors are TradingView's 20**, not GICS: Aker Solutions sits in Utilities and some holding companies (Lundberg, Industrivärden) in Finance.
- **REITs are judged on EPS**, which understates their cash earnings; funds from operations are not available from these sources.
- **DCF fair value is not part of this screen yet**; it remains in the per-stock analyses.

## 6. Reproduce

```
uv run python analysis/screener.py               # full run, about 2 minutes
uv run python analysis/screener.py --no-adjusted # skip the adjusted-EPS refinement
uv run python analysis/screener.py --refresh     # ignore today's cached downloads
```
