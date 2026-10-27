# Market screener: cheap or close-to-cheap S&P 500 stocks

*Data as of 2026-10-27 (US prices at the 2026-10-27 close). Written 2026-10-27, revised the same day for Peter Lynch's categories and narrowed to the S&P 500 at Babak's request. Tools: `analysis/stage1.py` and `analysis/stage2.py` (or both in a row with `analysis/screener.py`), settings in `config/screeners.toml`.*

> **Update, 2026-10-27 late evening.** A code review fixed 12 screener bugs (listed in the
> commit "Fix 12 screener bugs found in review"). Rerun: **169 of 497 pass Stage 1** (BlackRock
> now passes: its short-term debt was left blank after Yahoo filled its debt) and the **same 29
> names** are listed. The SEC cross-check now allows for splits after the 10-K, so Booking's
> 25-for-1 split no longer shows as a data mismatch. The screener now runs every evening before
> the market report, which lists its top 3 per sector; the site has a Screener page. The
> tables below are from the first run and differ only by BlackRock.

## 1. Summary

- **The S&P 500 only, for now** (Babak, 2026-10-27): 497 companies, as TradingView lists the index's members. Setting `index = ""` in `[universe]` brings back every US and European company above $1bn (3,432 companies in the earlier run today).
- **Stage 1, good financial statements: 168 pass.** Each company is first put in one of Peter Lynch's six categories (slow grower, stalwart, fast grower, cyclical, turnaround, asset play), then judged by the rules for its category; banks, insurers and REITs keep rules for their kind of business.
- **Stage 2, cheapness: 58 of the 168 are cheap or close to cheap** against their own cheap price; the top 3 per sector make a **29-name list**.
- **Cheapest against their own history:** Adobe (61% below its cheap price), Zoetis, Intuit, Incyte, Allstate, Gartner, Comcast, Valero, First Solar, Newmont, Xylem, Deckers. Booking (15% below) makes the list; Netflix (33% below) passes but misses the top 3 in Technology Services.
- **Boston Scientific fails** Stage 1 (cash doesn't cover short-term debt). Half of the 29 names (15) are in a downtrend: the technicals say to wait for the trend to turn.

## 2. The numbers

Two stages, separate programs: Stage 1 keeps the companies with good financial statements; Stage 2 ranks only those by how cheap they are. Every company with its category, status, the rules it failed and the source of every filled value: `data/screener/2026-10-27.csv`.

### Stage 1: good financial statements

Each company gets a Lynch category from its 10-year EPS history, industry and balance sheet, then must pass every rule of that category (full rules in section 3). Missing data makes a stock "incomplete", not a pass.

**168 of 497 companies pass Stage 1.** Every company with its absolute values, ratios and category: `data/screener/stage1.csv`.

#### By Lynch category

| Lynch category | Screened | Passed |
|---|---|---|
| slow grower | 113 | 29 |
| stalwart | 104 | 39 |
| fast grower | 93 | 36 |
| cyclical | 94 | 36 |
| turnaround | 68 | 26 |
| asset play | 8 | 2 |
| no profit in 5 years | 1 | 0 |
| (too little history) | 16 | 0 |

#### By sector

| Sector | Screened | Passed |
|---|---|---|
| Commercial Services | 15 | 3 |
| Communications | 4 | 0 |
| Consumer Durables | 11 | 6 |
| Consumer Non-Durables | 27 | 7 |
| Consumer Services | 25 | 5 |
| Distribution Services | 9 | 2 |
| Electronic Technology | 57 | 23 |
| Energy Minerals | 13 | 7 |
| Finance | 95 | 40 |
| Health Services | 11 | 1 |
| Health Technology | 42 | 20 |
| Industrial Services | 11 | 3 |
| Non-Energy Minerals | 7 | 4 |
| Process Industries | 19 | 5 |
| Producer Manufacturing | 33 | 10 |
| Retail Trade | 23 | 5 |
| Technology Services | 47 | 22 |
| Transportation | 15 | 4 |
| Utilities | 33 | 1 |
| **Total** | **497** | **168** |

#### By rule set

| Rule set | Fail | Incomplete | Pass |
|---|---|---|---|
| (too little history) | 0 | 15 | 0 |
| asset play | 4 | 1 | 1 |
| banks | 8 | 2 | 15 |
| cyclical | 52 | 2 | 32 |
| fast grower | 48 | 3 | 25 |
| insurers | 4 | 2 | 11 |
| no profit in 5 years | 1 | 0 | 0 |
| reits | 19 | 0 | 9 |
| slow grower | 68 | 2 | 23 |
| stalwart | 62 | 0 | 28 |
| turnaround | 32 | 4 | 24 |

#### Rules failed most often

| Rule | Stocks failing it |
|---|---|
| cash covers short-term debt | 143 |
| revenue and EPS growth | 56 |
| cash vs long-term debt | 51 |
| net debt / 10-year average EBITDA | 42 |
| Altman Z-score | 39 |
| cash vs total debt | 31 |
| debt / equity | 30 |
| EPS held up in recessions | 29 |
| EPS growth, last 3 years | 24 |
| net debt / EBITDA | 24 |
| Piotroski score | 22 |
| interest cover | 18 |
| dividend paid every year (payers) | 12 |
| payout ratio | 11 |
| profitable on average over 10 years | 7 |
| profitable | 3 |
| positive operating cash flow | 2 |
| return on equity | 2 |
| no profit in the last 5 years | 1 |

### Stage 2: the cheapest survivors, top 3 per sector

Only Stage 1 survivors are ranked, purely by price against their own cheap price (section 3). Below it = cheap; up to 15% above = close. Absolute values first, then the cheap price and the timing read.

#### Absolute values

Price in US dollars; amounts in US$ billions; EPS (12 months, diluted).

| Company | Sector | Price | Market value | Total debt | Net debt | Short-term debt | Long-term debt | Cash | Revenue | EBITDA | Net income | EPS | Op. cash flow | Capex | Free cash flow |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S&P Global, Inc. (SPGI) | Commercial Services | 448.93 USD | 132.3 | 15.7 | 11.6 | 2.7 | 13.1 | 4.1 | 16.1 | 8.4 | 4.9 | 18.72 | 5.7 | -0.2 | 5.6 |
| Hasbro, Inc. (HAS) | Consumer Durables | 118.33 USD | 16.7 | 3.5 | 2.1 | 0.9 | 2.6 | 1.4 | 5.2 | 1.7 | 1.0 | 7.16 | 1.3 | -0.2 | 1.2 |
| NVR, Inc. (NVR) | Consumer Durables | 5,806.02 USD | 15.5 | 1.1 | -0.1 | 0.0 | 1.1 | 1.2 | 9.2 | 1.8 | 1.0 | 362.71 | 1.1 | -0.0 | 1.0 |
| Deckers Outdoor Corporation (DECK) | Consumer Non-Durables | 80.54 USD | 11.0 | 0.5 | -0.7 | 0.1 | 0.5 | 1.2 | 5.6 | 1.4 | 1.1 | 7.54 | 1.2 | -0.1 | 1.1 |
| NIKE, Inc. Class B (NKE) | Consumer Non-Durables | 37.56 USD | 55.8 | 11.1 | 2.7 | 2.5 | 8.6 | 8.4 | 45.9 | 4.8 | 3.1 | 2.08 | 2.8 | -0.7 | 2.1 |
| PepsiCo, Inc. (PEP) | Consumer Non-Durables | 133.50 USD | 181.9 | 51.9 | 40.7 | 9.2 | 42.7 | 11.2 | 98.2 | 20.0 | 10.9 | 8.41 | 14.6 | -4.1 | 10.5 |
| Comcast Corporation Class A (CMCSA) | Consumer Services | 21.84 USD | 77.6 | 87.4 | 79.8 | 3.6 | 83.8 | 7.6 | 123.0 | 33.8 | 11.3 | 3.74 | 31.7 | -14.7 | 19.7 |
| Booking Holdings Inc. (BKNG) | Consumer Services | 150.14 USD | 112.8 | 20.7 | 3.2 | 2.0 | 18.7 | 17.5 | 28.2 | 10.6 | 7.2 | 9.61 | 9.9 | -0.3 | 9.5 |
| First Solar, Inc. (FSLR) | Electronic Technology | 175.85 USD | 18.9 | 0.2 | -1.5 | 0.1 | 0.1 | 1.7 | 5.4 | 2.5 | 1.7 | 16.22 | 2.2 | -0.7 | 1.5 |
| NVIDIA Corporation (NVDA) | Electronic Technology | 217.94 USD | 5,252.4 | 38.9 | -60.5 | 1.5 | 37.4 | 99.4 | 303.0 | 201.3 | 192.9 | 7.01 | 134.4 | -7.4 | 127.0 |
| Valero Energy Corporation (VLO) | Energy Minerals | 387.34 USD | 111.5 | 11.0 | 1.2 | 1.0 | 10.0 | 9.8 | 153.6 | 21.2 | 12.9 | 44.48 | 10.9 | -0.8 | 10.1 |
| Occidental Petroleum Corporation (OXY) | Energy Minerals | 62.73 USD | 62.7 | 14.6 | 10.5 | 0.6 | 14.0 | 4.2 | 24.3 | 13.3 | 4.1 | 4.41 | 11.0 | -5.7 | 5.3 |
| EOG Resources, Inc. (EOG) | Energy Minerals | 161.10 USD | 84.5 | 8.2 | 3.3 | 0.4 | 7.9 | 4.9 | 26.7 | 14.4 | 6.9 | 13.46 | 13.4 | -6.7 | 6.6 |
| Allstate Corporation (ALL) | Finance | 251.71 USD | 63.6 | 7.5 | 6.7 | 0.0 | 7.5 |  | 70.1 |  | 13.3 | 47.96 | 12.5 | -0.2 | 12.2 |
| T. Rowe Price Group, Inc. (TROW) | Finance | 103.63 USD | 22.1 | 0.6 | -2.6 | 0.0 | 0.6 | 3.2 | 7.6 | 3.2 | 2.2 | 10.34 | 3.1 | -0.3 | 2.8 |
| Charles Schwab Corp (SCHW) | Finance | 89.30 USD | 154.4 | 40.0 | -28.5 | 16.2 | 23.8 | 68.5 | 30.5 | 17.1 | 10.6 | 6.13 | 11.4 | -0.6 | 10.8 |
| Zoetis, Inc. Class A (ZTS) | Health Technology | 78.23 USD | 32.3 | 9.2 | 7.6 | 0.0 | 9.2 | 1.7 | 9.5 | 4.1 | 2.6 | 6.58 | 2.9 | -0.5 | 2.4 |
| Incyte Corporation (INCY) | Health Technology | 116.60 USD | 23.6 | 0.0 | -4.5 | 0.0 | 0.0 | 4.5 | 5.8 | 1.9 | 1.6 | 8.96 | 2.0 | -0.1 | 1.9 |
| Insulet Corporation (PODD) | Health Technology | 149.83 USD | 10.4 | 0.9 | 0.4 | 0.0 | 0.9 | 0.5 | 3.1 | 0.6 | 0.4 | 5.87 | 0.5 | -0.2 | 0.3 |
| Newmont Corporation (NEM) | Non-Energy Minerals | 112.64 USD | 117.1 | 5.6 | -3.2 | 0.1 | 5.5 | 8.8 | 26.2 | 17.2 | 9.2 | 9.72 | 13.1 | -3.0 | 10.1 |
| CF Industries Holdings, Inc. (CF) | Process Industries | 120.54 USD | 18.2 | 3.6 | 1.1 | 0.1 | 3.5 | 2.5 | 7.7 | 4.1 | 2.1 | 12.87 | 3.0 | -1.1 | 1.9 |
| Xylem Inc. (XYL) | Producer Manufacturing | 92.86 USD | 21.7 | 3.1 | 1.8 | 0.7 | 2.4 | 1.3 | 9.1 | 2.0 | 1.0 | 5.44 | 1.3 | -0.4 | 0.9 |
| A. O. Smith Corporation (AOS) | Producer Manufacturing | 62.06 USD | 8.4 | 0.7 | 0.5 | 0.0 | 0.6 | 0.2 | 3.8 | 0.8 | 0.5 | 3.72 | 0.7 | -0.1 | 0.6 |
| Pentair plc (PNR) | Producer Manufacturing | 62.29 USD | 9.9 | 1.8 | 1.7 | 0.0 | 1.7 | 0.1 | 4.0 | 1.0 | 0.7 | 4.72 | 0.8 | -0.1 | 0.7 |
| Copart, Inc. (CPRT) | Retail Trade | 28.92 USD | 26.8 | 0.1 | -4.4 | 0.0 | 0.1 | 4.5 | 4.7 | 1.9 | 1.5 | 1.55 | 1.6 | -0.3 | 1.3 |
| Adobe Inc. (ADBE) | Technology Services | 248.36 USD | 96.7 | 6.8 | 1.1 | 1.7 | 5.1 | 5.6 | 26.0 | 10.2 | 7.3 | 23.65 | 10.8 | -0.2 | 10.6 |
| Intuit Inc. (INTU) | Technology Services | 328.45 USD | 87.8 | 8.4 | 1.2 | 1.3 | 7.1 | 7.2 | 21.4 | 7.0 | 4.6 | 24.32 | 8.8 | -0.2 | 8.6 |
| Gartner, Inc. (IT) | Technology Services | 220.93 USD | 14.0 | 3.3 | 1.8 | 0.1 | 3.2 | 1.5 | 6.5 | 1.5 | 0.8 | 14.39 | 1.4 | -0.1 | 1.3 |
| Atmos Energy Corporation (ATO) | Utilities | 171.37 USD | 29.0 | 10.3 | 9.8 | 0.5 | 9.8 | 0.5 | 4.9 | 2.6 | 1.4 | 8.41 | 2.0 | -4.0 | -2.0 |

#### Category, cheap price and timing

| Company | Sector | Lynch category | P/E now | Cheap P/E | Set by | Cheap price | Price vs cheap | Label | EPS used | Trend | RSI | TradingView rating |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S&P Global, Inc. | Commercial Services | stalwart | 24.0x | 21.8x | own history | 407.33 USD | +10% | close | adjusted | uptrend | 70 | buy |
| Hasbro, Inc. | Consumer Durables | turnaround | 16.5x | 17.5x | sector median | 125.25 USD | -6% | cheap | adjusted | uptrend | 88 | buy |
| NVR, Inc. | Consumer Durables | cyclical | 16.0x | 14.6x | own history | 5,297.66 USD | +10% | close | adjusted | downtrend | 43 | sell |
| Deckers Outdoor Corporation | Consumer Non-Durables | fast grower | 10.7x | 15.4x | own history | 116.18 USD | -31% | cheap | adjusted | downtrend | 42 | sell |
| NIKE, Inc. Class B | Consumer Non-Durables | cyclical | 18.1x | 24.0x | sector median | 49.99 USD | -25% | cheap | adjusted | downtrend | 56 | buy |
| PepsiCo, Inc. | Consumer Non-Durables | slow grower | 15.9x | 20.9x | own history | 175.78 USD | -24% | cheap | adjusted | downtrend | 53 | neutral |
| Comcast Corporation Class A | Consumer Services | asset play | 5.8x | 9.9x | own history | 37.02 USD | -41% | cheap | adjusted | downtrend | 45 | sell |
| Booking Holdings Inc. | Consumer Services | fast grower | 15.6x | 18.3x | sector median | 175.64 USD | -15% | cheap | adjusted | downtrend | 33 | strong sell |
| First Solar, Inc. | Electronic Technology | cyclical | 10.8x | 16.5x | own history | 267.38 USD | -34% | cheap | adjusted | downtrend | 45 | sell |
| NVIDIA Corporation | Electronic Technology | fast grower | 31.1x | 31.2x | own history | 218.60 USD | -0% | cheap | adjusted | uptrend | 46 | sell |
| Valero Energy Corporation | Energy Minerals | cyclical | 8.7x | 13.5x | own history | 602.67 USD | -36% | cheap | adjusted | uptrend | 39 | sell |
| Occidental Petroleum Corporation | Energy Minerals | cyclical | 14.2x | 14.0x | own history | 61.74 USD | +2% | close | adjusted | uptrend | 59 | buy |
| EOG Resources, Inc. | Energy Minerals | cyclical | 12.0x | 10.4x | own history | 140.27 USD | +15% | close | adjusted | uptrend | 69 | buy |
| Allstate Corporation | Finance | slow grower | 5.2x | 9.2x | own history | 439.37 USD | -43% | cheap | adjusted | uptrend | 59 | buy |
| T. Rowe Price Group, Inc. | Finance | stalwart | 10.0x | 13.3x | own history | 138.04 USD | -25% | cheap | adjusted | mixed | 49 | neutral |
| Charles Schwab Corp | Finance | fast grower | 14.6x | 18.4x | own history | 112.85 USD | -21% | cheap | adjusted | mixed | 28 | sell |
| Zoetis, Inc. Class A | Health Technology | stalwart | 11.9x | 25.9x | own history | 170.51 USD | -54% | cheap | adjusted | downtrend | 56 | neutral |
| Incyte Corporation | Health Technology | cyclical | 13.0x | 24.9x | own history | 222.80 USD | -48% | cheap | adjusted | uptrend | 50 | buy |
| Insulet Corporation | Health Technology | fast grower | 25.5x | 35.8x | sector median | 209.87 USD | -29% | cheap | adjusted | downtrend | 67 | buy |
| Newmont Corporation | Non-Energy Minerals | cyclical | 11.6x | 17.4x | sector median | 168.72 USD | -33% | cheap | adjusted | uptrend | 44 | sell |
| CF Industries Holdings, Inc. | Process Industries | cyclical | 9.4x | 8.9x | own history | 114.79 USD | +5% | close | adjusted | uptrend | 53 | buy |
| Xylem Inc. | Producer Manufacturing | fast grower | 17.1x | 25.2x | own history | 137.29 USD | -32% | cheap | adjusted | downtrend | 28 | strong sell |
| A. O. Smith Corporation | Producer Manufacturing | slow grower | 16.7x | 20.1x | own history | 74.78 USD | -17% | cheap | adjusted | downtrend | 66 | buy |
| Pentair plc | Producer Manufacturing | slow grower | 13.2x | 14.2x | own history | 67.19 USD | -7% | cheap | adjusted | downtrend | 77 | buy |
| Copart, Inc. | Retail Trade | stalwart | 18.7x | 22.8x | sector median | 35.40 USD | -18% | cheap | adjusted | downtrend | 55 | neutral |
| Adobe Inc. | Technology Services | slow grower | 10.5x | 26.8x | sector median | 633.47 USD | -61% | cheap | adjusted | mixed | 49 | sell |
| Intuit Inc. | Technology Services | fast grower | 13.5x | 26.8x | sector median | 651.42 USD | -50% | cheap | adjusted | downtrend | 55 | neutral |
| Gartner, Inc. | Technology Services | stalwart | 15.4x | 26.8x | sector median | 385.44 USD | -43% | cheap | adjusted | uptrend | 63 | buy |
| Atmos Energy Corporation | Utilities | stalwart | 20.4x | 18.5x | own history | 155.88 USD | +10% | close | adjusted | downtrend | 66 | buy |

## 3. Method

The two stages are separate programs. Stage 1 writes every company with its category, status and figures; Stage 2 reads that file, checks it has every column it needs, and ranks only the survivors. Either can be changed without touching the other. Every rule, threshold and its source is set out in the methods doc, "Stage 1 screening methods and their sources".

**Stage 1: good financial statements** (`analysis/stage1.py`)

1. **Universe.** The S&P 500: every company TradingView's screener lists as a member of the index (`SP:SPX`), 497 companies (the index has about 503 share classes). Without the index setting the universe is every primary listing of common shares above $1bn (converted at ECB reference rates) in the US and 17 European markets. Funds and trusts are skipped.
2. **Gap filling.** Short-term debt left blank is total debt minus long-term debt (8 stocks). Debt, cash, EBITDA and interest cover still blank are taken from Yahoo's statements. Each filled value is named in the `filled` column.
3. **Lynch category** (One Up on Wall Street, ch. 7), tested in this order:
    - *No profit:* no positive EPS in any of the last 5 fiscal years. Not a Lynch category; he avoided such long shots, so these fail.
    - *Cyclical by industry:* autos, airlines, steel, metals and mining, chemicals, oil and gas, drilling, shipping, homebuilding, chip equipment, machinery, paper, building materials, hotels and cruise lines.
    - *Turnaround:* losing money now (12 months or latest fiscal year), or EPS (both measures) less than half its 5-year peak.
    - *Cyclical by history:* EPS fell more than 30% in 3 or more of the last 10 years, and it isn't growing 20% a year.
    - *Asset play:* price below book value, or net cash above 30% of market value.
    - *Fast grower / stalwart / slow grower:* median yearly EPS growth over 5 years of 20% or more / 8% to 20% / under 8%.
    - Blank when there are fewer than 3 years of EPS growth to measure (16 companies, "incomplete").
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
6. **Adjusted EPS.** For the closest names per sector, Yahoo's adjusted quarterly EPS replaces diluted EPS, with its own adjusted P/E history (the watch list's method), when it has at least 6 years and is within a factor of 2 of diluted EPS (a bigger gap is a data error).
7. **Ranking.** Inside each region and sector, by price against the cheap price, lowest first. Below it = cheap; up to 15% above = close; anything higher is not listed. Stage 1 decides who gets in; only cheapness sets the order.
8. **Technicals, for timing only.** Trend from the 50- and 200-day averages, RSI (below 30 oversold, above 70 overbought), position in the 52-week range, and TradingView's technical rating.
9. **Cross-check.** US names' latest fiscal-year diluted EPS is compared with SEC EDGAR (all 29 found, none off by more than 10%).

**Sources (all free):** TradingView screener (fundamentals, 20 years of yearly EPS, revenue, EBITDA and dividends, technicals), Yahoo Finance (prices, adjusted EPS, statements for gaps), SEC EDGAR (EPS cross-check), ECB (exchange rates). Tested and available for later: European ESEF filings at filings.xbrl.org, Euronext and Nasdaq company lists, OpenFIGI (identifiers). Free-key services that could be added if Babak registers: Finnhub, Alpha Vantage, EODHD, Financial Modeling Prep (the current key is invalid).

## 4. Findings

- **Cash covering short-term debt is the biggest filter** (143 of 497 fail it), then 5-year growth (56) and cash against long-term debt (51). Big companies often roll over short-term debt rather than hold the cash for it; this rule is Babak's and the strictest in the set.
- **Stalwarts and fast growers pass most often** (39 of 104 and 36 of 93); slow growers least (29 of 113). Only 15 of 25 banks and 9 of 28 REITs pass.
- **The list leans to fallen quality names:** software and data (Adobe, Intuit, Gartner), health care (Zoetis, Incyte, Insulet), consumer brands (Deckers, Nike, PepsiCo), as in the October panic-sell screen.
- **Cyclicals at low P/Es need care:** Valero, Newmont, First Solar and CF Industries look cheap on today's earnings, which Lynch warns may be near a peak.
- **Technicals mostly say "not yet":** 15 of the 29 names are in a downtrend (price and 50-day average below the 200-day).

## 5. Caveats

- **Categories come from reported (GAAP) EPS.** A big write-down or one-off gain can push a company into the wrong category: Bristol-Myers counts as cyclical because of write-down years, and some steady companies count as turnarounds after one bad year. The category is shown next to every name so it can be checked.
- **The category thresholds are judgement calls** based on Lynch's descriptions (fast growers 20-25% a year, stalwarts 10-12%, slow growers about the economy's growth); the methods doc lists every one for review.
- **TradingView's and Yahoo's interfaces are unofficial.** Field names can change, and Yahoo rate-limits heavy use. Each run caches its downloads for the day in `.cache/screener/`.
- **Own history is not destiny.** A stock far below its cheap price may have been re-rated for a reason (Adobe and Trade Desk face AI disruption; Novo Nordisk lost its obesity-drug lead). The screen finds candidates; each one needs the full analysis.
- **Adjusted EPS** (Yahoo) was used for all 29 listed names; where only diluted EPS is available, one-offs distort the P/E.
- **Sectors are TradingView's 20**, not GICS. The sector-median cap on the cheap multiple is now the S&P 500's sector median.
- **REITs are judged on EPS**, which understates their cash earnings; funds from operations are not available from these sources.
- **DCF fair value is not part of this screen yet**; it remains in the per-stock analyses.

## 6. Reproduce

```
uv run python analysis/screener.py               # both stages, a few minutes for the S&P 500
uv run python analysis/stage1.py                 # Stage 1 only: data/screener/stage1.csv
uv run python analysis/stage2.py                 # Stage 2 only, on Stage 1's last output
uv run python analysis/screener.py --no-adjusted # skip the adjusted-EPS refinement
uv run python analysis/screener.py --refresh     # ignore today's cached downloads
```
