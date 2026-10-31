# 15. The growth screener: growing revenue and profit, high margin, historically low P/E

**Data:** TradingView figures and Yahoo prices as of the 2026-10-30 close (run 2026-10-31).
Universe: the S&P 500 (497 companies, `[universe]` in `config/screeners.toml`).

## Summary

Babak asked for a screener to test (2026-10-31): revenue growing, net profit growing, a high
net margin, EPS growing, and among these the stocks whose P/E is low **against their own
history**. A high margin means a net margin above the average of the company's sector
(Babak's choice, replacing an earlier 10% floor plus the sector median). Babak then added a
debt test to the same first step: net debt repaid by at most 5 years of free cash flow, and
cash plus a year of free cash flow covering the debt due within a year. 83 of 497 S&P 500
companies pass the growth, margin and debt rules. 39 of them trade below their own median
P/E. The 20 nearest the top of the ranking are listed below; 7 of them carry a flag (a
likely one-off gain or lumpy profit) that makes the P/E less reliable.

A backtest on six past years (fiscal 2019 to 2024, bought at the end of April after each)
gives a mixed result. Over 1 year the top 10 rose 23.8% on average, against 17.4% for the
S&P 500 and 23.4% for an equal-weighted average of all the screened stocks. They beat the
S&P 500 in 3 of the 6 years. **Held to today, five of the six yearly portfolios are behind
the S&P 500.** The sixth (fiscal 2019) is ahead only because of one stock, Comfort Systems,
up 37-fold. As built, the screen finds stocks that bounce over a year more often than
businesses that compound. It is a starting list for study, not a buy list.

## The numbers

### Absolute values: the top 20 (US dollars, billions; price and EPS per share)

| Symbol | Company | Price | Mkt value | Debt | Net debt | ST debt | LT debt | Cash | Revenue | EBITDA | Net income | EPS | OCF | Capex | FCF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ADBE | Adobe | 250.23 | 97.39 | 6.76 | 1.12 | 1.69 | 5.08 | 5.64 | 25.97 | 10.22 | 7.28 | 17.93 | 10.81 | -0.21 | 10.59 |
| PTC | PTC | 195.54 | 21.24 | 1.61 | 1.26 | 0.05 | 1.56 | 0.35 | 2.95 | 1.31 | 1.23 | 10.34 | 0.95 | -0.02 | 0.93 |
| NFLX | Netflix | 62.08 | 254.92 | 17.38 | 9.16 | 2.91 | 14.47 | 8.23 | 50.00 | 33.76 | 14.77 | 3.46 | 12.31 | -0.93 | 11.38 |
| INTU | Intuit | 341.09 | 91.15 | 8.42 | 1.22 | 1.33 | 7.09 | 7.20 | 21.45 | 7.02 | 4.57 | 16.50 | 8.84 | -0.22 | 8.62 |
| ROP | Roper Technologies | 466.60 | 46.15 | 9.72 | 9.41 | 1.42 | 8.30 | 0.31 | 8.43 | 3.29 | 2.59 | 25.33 | 2.62 | -0.11 | 2.58 |
| XYL | Xylem | 92.40 | 21.19 | 3.03 | 2.32 | 0.66 | 2.37 | 0.71 | 9.05 | 2.00 | 1.08 | 4.53 | 1.27 | -0.39 | 0.88 |
| RMD | ResMed | 229.94 | 32.34 | 0.61 | -0.42 | 0.19 | 0.42 | 1.03 | 5.73 | 2.18 | 1.59 | 10.98 | 1.77 | -0.18 | 1.61 |
| GOOG | Alphabet | 278.22 | 3,411.53 | 146.64 | -118.46 | 2.07 | 144.57 | 265.10 | 471.14 | 185.94 | 235.69 | 19.15 | 179.55 | -159.80 | 19.75 |
| DECK | Deckers Outdoor | 81.99 | 10.94 | 0.54 | -0.67 | 0.08 | 0.46 | 1.21 | 5.57 | 1.38 | 1.06 | 7.55 | 1.13 | -0.08 | 1.05 |
| BKNG | Booking | 148.13 | 111.30 | 20.69 | 3.19 | 2.00 | 18.69 | 17.51 | 28.24 | 10.65 | 7.21 | 9.04 | 9.86 | -0.32 | 9.54 |
| SCHW | Charles Schwab | 88.05 | 152.27 | 40.00 | -28.50 | 16.20 | 23.80 | 68.50 | 30.50 | 17.13 | 10.64 | 5.86 |  |  |  |
| AON | Aon | 321.67 | 68.24 | 28.95 | 13.63 | 1.90 | 27.05 | 15.32 | 17.68 | 5.94 | 3.93 | 18.26 | 3.57 | -0.31 | 3.27 |
| CPRT | Copart | 30.13 | 27.91 | 0.09 | -4.40 | 0.02 | 0.07 | 4.49 | 4.67 | 1.88 | 1.48 | 1.55 | 1.60 | -0.34 | 1.27 |
| GEN | Gen Digital | 29.13 | 17.28 | 8.12 | 7.53 | 1.08 | 7.04 | 0.59 | 5.23 | 2.73 | 1.21 | 1.98 | 1.78 | -0.02 | 1.76 |
| NVDA | NVIDIA | 204.64 | 4,931.82 | 38.86 | -60.51 | 1.51 | 37.35 | 99.37 | 302.97 | 201.26 | 192.88 | 7.91 | 134.36 | -7.35 | 127.01 |
| SYK | Stryker | 291.86 | 111.95 | 15.43 | 12.16 | 0.91 | 14.52 | 3.27 | 26.30 | 7.67 | 3.62 | 9.39 | 5.45 | -0.87 | 4.57 |
| IDXX | IDEXX Laboratories | 551.21 | 43.42 | 1.10 | 0.90 | 0.70 | 0.40 | 0.20 | 4.55 | 1.62 | 1.14 | 14.23 | 1.37 | -0.13 | 1.25 |
| FDS | FactSet Research Systems | 329.57 | 11.62 | 1.54 | 1.27 | 0.53 | 1.01 | 0.27 | 2.48 | 0.97 | 0.53 | 14.55 | 0.82 | -0.11 | 0.71 |
| STE | STERIS plc | 227.12 | 22.14 | 2.04 | 1.56 | 0.28 | 1.77 | 0.48 | 6.04 | 1.67 | 0.81 | 8.18 | 1.29 | -0.36 | 0.93 |
| MDT | Medtronic Plc | 96.54 | 123.49 | 28.15 | 19.33 | 2.54 | 25.62 | 8.82 | 37.54 | 10.42 | 5.23 | 4.06 | 8.04 | -1.90 | 6.13 |

Revenue, EBITDA, net income, EPS and cash flows are the last 12 months; debt and cash are the
latest quarter. Schwab's cash flows are blank on TradingView (a broker's cash flow statement
is not comparable).

### Growth, margin and P/E against own history (5 fiscal years, lowest P/E against history first)

| Symbol | # | Sector | Rev CAGR % | Rev up | NI CAGR % | NI up | EPS CAGR % | Margin % | Sector margin % | Net debt / FCF (yrs) | P/E | Own median P/E | Own low P/E | Years | vs median % | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ADBE | 1 | Technology Services | 13.10 | 5/5 | 6.30 | 3/5 | 9.00 | 28.10 | 20.70 | 0.11 | 13.96 | 41.85 | 23.00 | 10 | -66.60 |  |
| PTC | 2 | Technology Services | 13.40 | 5/5 | 41.20 | 3/5 | 40.20 | 41.70 | 20.70 | 1.34 | 18.90 | 49.66 | 30.28 | 6 | -61.90 | one-off? lumpy |
| NFLX | 3 | Technology Services | 12.60 | 5/5 | 31.80 | 4/5 | 33.00 | 29.50 | 20.70 | 0.81 | 17.94 | 43.73 | 27.92 | 7 | -59.00 |  |
| INTU | 4 | Technology Services | 17.40 | 5/5 | 17.20 | 5/5 | 16.90 | 21.30 | 20.70 | 0.14 | 20.67 | 44.10 | 30.09 | 10 | -53.10 |  |
| ROP | 5 | Technology Services | 10.20 | 4/5 | 10.10 | 4/5 | 9.60 | 30.70 | 20.70 | 3.65 | 18.42 | 37.48 | 20.60 | 10 | -50.90 | one-off? |
| XYL | 6 | Producer Manufacturing | 13.10 | 5/5 | 30.40 | 4/5 | 22.80 | 12.00 | 6.60 | 2.62 | 20.40 | 35.27 | 23.98 | 10 | -42.20 |  |
| RMD | 7 | Health Technology | 12.10 | 5/5 | 26.30 | 5/5 | 26.30 | 27.80 | 10.50 | 0.00 | 20.94 | 36.14 | 23.19 | 10 | -42.10 |  |
| GOOG | 8 | Technology Services | 17.20 | 5/5 | 26.80 | 4/5 | 29.80 | 50.00 | 20.70 | 0.00 | 14.52 | 24.52 | 20.13 | 10 | -40.80 | one-off? |
| DECK | 9 | Consumer Non-Durables | 16.40 | 5/5 | 21.80 | 5/5 | 25.60 | 19.00 | 11.60 | 0.00 | 10.87 | 17.98 | 13.99 | 9 | -39.60 |  |
| BKNG | 10 | Consumer Services | 31.70 | 5/5 | 146.80 | 4/5 | 158.60 | 25.50 | 11.50 | 0.33 | 16.38 | 26.85 | 16.76 | 9 | -39.00 |  |
| SCHW | 11 | Finance | 18.00 | 5/5 | 21.80 | 4/5 | 17.00 | 34.90 | 19.00 | 0.00 | 15.02 | 22.46 | 16.35 | 10 | -33.10 |  |
| AON | 12 | Finance | 9.40 | 5/5 | 13.40 | 3/5 | 15.00 | 22.20 | 19.00 | 4.17 | 17.62 | 25.88 | 20.63 | 10 | -31.90 | lumpy |
| CPRT | 13 | Retail Trade | 11.60 | 5/5 | 9.60 | 4/5 | 9.80 | 31.80 | 9.40 | 0.00 | 19.43 | 28.41 | 17.43 | 10 | -31.60 |  |
| GEN | 14 | Technology Services | 14.40 | 5/5 | 11.90 | 4/5 | 11.20 | 23.10 | 20.70 | 4.27 | 14.68 | 19.74 | 10.22 | 8 | -25.60 | lumpy |
| NVDA | 15 | Electronic Technology | 66.90 | 5/5 | 94.30 | 4/5 | 95.30 | 63.70 | 19.80 | 0.00 | 25.87 | 34.71 | 24.74 | 9 | -25.50 | one-off? lumpy |
| SYK | 16 | Health Technology | 11.80 | 5/5 | 15.20 | 4/5 | 14.80 | 13.80 | 10.50 | 2.66 | 31.09 | 41.30 | 17.89 | 10 | -24.70 |  |
| IDXX | 17 | Health Technology | 9.70 | 5/5 | 12.70 | 4/5 | 14.30 | 25.00 | 10.50 | 0.72 | 38.74 | 50.78 | 39.14 | 10 | -23.70 |  |
| FDS | 18 | Commercial Services | 9.20 | 5/5 | 5.90 | 3/5 | 7.10 | 21.50 | 18.10 | 1.80 | 22.65 | 29.53 | 17.66 | 10 | -23.30 |  |
| STE | 19 | Health Technology | 13.80 | 4/5 | 14.50 | 3/5 | 11.40 | 13.30 | 10.50 | 1.69 | 27.76 | 35.23 | 25.45 | 9 | -21.20 | lumpy |
| MDT | 20 | Health Technology | 3.80 | 4/5 | 5.90 | 3/5 | 7.00 | 13.90 | 10.50 | 3.15 | 23.77 | 29.56 | 23.80 | 10 | -19.60 |  |

CAGR = compound growth a year over 5 fiscal years. "Up" = years of the 5 in which the
figure rose. Margin = 12-month net income / revenue. P/E = price / 12-month diluted EPS.
Own median and low P/E = median and lowest of the yearly P/Es over up to 10 fiscal years.
Flags: *one-off?* = 12-month net income is more than 1.5 times the latest fiscal year;
*lumpy* = net income fell more than 30% in one of the 5 years.

The full list of 83 survivors, and why each of the other 414 failed or was incomplete, is in
`data/screener/growth.csv`.

**What fails.** A company can fail several rules: net margin 264, net income growth 176,
EPS growth 169, debt payback 148, profit every year 137, still growing 130, revenue up 4 of 5
years 130, net income up 3 of 5 years 125, short-term debt covered 67, revenue growth 30.
Six are incomplete: five recent spin-offs with too little history (GE Vernova, Sandisk,
Honeywell Aerospace and others), and Extra Space Storage, whose free cash flow neither
TradingView nor Yahoo has. Debt, cash and free cash flow blank on TradingView were filled
from Yahoo for BlackRock, Monolithic Power and Blackstone (column `filled`).

**What the debt rules removed** (all passed growth and margin before): Domino's (net debt
$4.65bn = 7.3 years of its $0.64bn free cash flow; $1.37bn due within a year against $0.47bn
cash), McCormick, Fair Isaac (5.7 years), Yum! Brands, McDonald's (6.9 years), Martin
Marietta, Sherwin-Williams (due within a year $4.39bn against cash $0.26bn plus free cash
flow $3.08bn), Oracle and the utilities NextEra, Duke and American Water (negative free cash
flow while carrying debt), and the REITs American Tower, UDR, Federal Realty, Regency,
Realty Income and Prologis (7.6 to 14.7 years).

**Survivors by sector:** Technology Services 15, Health Technology 14, Producer
Manufacturing 12, Finance 11, Electronic Technology 10, Commercial Services 5, Retail Trade 5,
the rest 11.
Four survivors have a margin under 10%, in sectors whose average is low: Avery Dennison
(7.6%, sector 5.0%), Ferguson (6.8%, 4.4%), TJX (9.7%, 9.4%), Grainger (9.9%, 4.4%).

**Sector average net margins (12 months, every S&P 500 company in the sector):**

| Sector | Companies | Average | Median |
|---|---|---|---|
| Technology Services | 47 | 20.7% | 21.0% |
| Electronic Technology | 56 | 19.8% | 15.9% |
| Finance | 95 | 19.0% | 17.4% |
| Commercial Services | 14 | 18.1% | 15.7% |
| Non-Energy Minerals | 7 | 18.0% | 13.3% |
| Energy Minerals | 13 | 15.0% | 14.7% |
| Utilities | 33 | 14.8% | 13.5% |
| Industrial Services | 11 | 12.0% | 10.3% |
| Consumer Non-Durables | 27 | 11.6% | 11.1% |
| Consumer Services | 25 | 11.5% | 9.6% |
| Transportation | 14 | 11.2% | 5.8% |
| Health Technology | 42 | 10.5% | 14.4% |
| Retail Trade | 23 | 9.4% | 8.0% |
| Consumer Durables | 11 | 8.5% | 8.7% |
| Producer Manufacturing | 33 | 6.6% | 13.6% |
| Health Services | 11 | 6.0% | 6.3% |
| Process Industries | 19 | 5.0% | 3.8% |
| Distribution Services | 9 | 4.5% | 2.1% |
| Communications | 4 | (too few: 10% used) | 11.0% |

Where the average is well below the median (Producer Manufacturing, Health Technology), a few
large losses pull it down and the bar is lower; where it is above (Transportation,
Electronic Technology), a few very profitable companies push it up.

### Backtest: the same rules in past years

The backtest was run before the debt rules were added and does not include them (TradingView's
yearly history has no free cash flow). Each fiscal year Y from 2019 to 2024: the rules applied to the yearly figures up to Y, P/E =
price at the end of April Y+1 / EPS for Y, ranked against the P/Es before then; the 10 lowest
bought at the end of April Y+1. Price returns (no dividends).

| Fiscal year | Bought | Passed | Top 10, 1 year | All passed, 1 year | All screened, 1 year | S&P 500, 1 year | Top 10, to today | All passed, to today | All screened, to today | S&P 500, to today |
|---|---|---|---|---|---|---|---|---|---|---|
| 2019 | 2020-04-30 | 125 | +72.8% | +57.1% | +58.6% | +43.6% | +474.9% | +210.5% | +211.9% | +160.3% |
| 2020 | 2021-04-30 | 111 | -3.5% | -3.9% | +1.4% | -1.2% | +42.1% | +83.6% | +89.6% | +81.3% |
| 2021 | 2022-04-30 | 118 | +18.3% | +8.2% | +1.6% | +0.9% | +77.0% | +70.6% | +93.6% | +83.5% |
| 2022 | 2023-04-30 | 125 | +11.2% | +18.3% | +24.8% | +20.8% | +39.9% | +61.5% | +103.9% | +81.8% |
| 2023 | 2024-04-30 | 112 | +28.4% | +9.7% | +9.8% | +10.6% | +28.3% | +25.8% | +53.3% | +50.5% |
| 2024 | 2025-04-30 | 110 | +15.3% | +11.2% | +44.0% | +29.4% | +22.3% | +16.6% | +49.9% | +36.1% |
| **Average** | | | **+23.8%** | +16.8% | +23.4% | +17.4% | **+114.1%** | +78.1% | +100.4% | +82.2% |
| Average without 2019 | | | +13.9% | +8.7% | +16.3% | +12.1% | +41.9% | +51.6% | +78.1% | +66.6% |

The 60 picks are in `data/screener/growth_backtest.csv`. 67% of them rose in their first year.
Most were Finance (19 of 60, mostly REITs and insurers) and Health Technology (11).

## Claude's analysis

### Method

Two steps, in this order (Babak, 2026-10-31: "first filter with the growth ... and then,
based on what's left, apply the P/E"): **step 1** filters on growth and margin only, with no
price and no P/E; **step 2** works out the P/E against its own history for the survivors
alone and ranks them by it. P/E never removes a stock; it only orders the ones step 1 kept.

- **Revenue growing:** compound growth over 5 fiscal years above 0, and up in at least 4 of
  the 5 years. Babak asked only for positive growth. The 4-of-5 test is what makes it
  "increasing": without it, one big year could carry a business that is flat or falling
  otherwise.
- **Net profit growing:** net income compound growth above 0, up in at least 3 of 5 years,
  and a profit in all 6 years. The test is looser than for revenue because profit is
  naturally lumpier.
- **EPS growing:** diluted EPS compound growth above 0. EPS can grow faster than net income
  through buybacks (Booking: 147% vs 159% a year, from its loss-hit 2020 base).
- **High margin: above the sector average.** Babak first suggested 10% and asked for a
  better way if there is one. A fixed number is unfair across industries: S&P 500 sector
  average net margins run from 4.5% (Distribution Services) to 20.7% (Technology Services).
  A first version required at least 10% *and* the sector median. Babak then chose "net
  profit more than the average of the sector": the 12-month net margin must be above the
  mean of every S&P 500 company in the same TradingView sector, losses included. Sectors with
  fewer than 5 companies use 10% instead (Communications, with 4). In practice this mostly
  raises the bar: a software company needs 20.7%. It lowers it in low-margin sectors, so four
  survivors have margins under 10% (Grainger, Ferguson, Avery Dennison, TJX). The average is
  pulled down by losses and up by one-off gains; the median, or the average of profitable
  companies only, would be steadier (`sector_margin = "median"` in the config).
- **Still growing:** 12-month revenue and net income at or above the latest fiscal year, so a
  slowdown since the last annual report is caught.
- **Debt it can pay** (Babak, after looking at Domino's: "their free cash flow is so much lower
  than their debt ... filter them out as well in the first level before the P/E"). Two rules,
  latest quarter's debt and cash against 12-month free cash flow:
  - *Debt payback:* net debt (total debt minus cash) at most 5 years of free cash flow. Net
    cash passes; net debt with zero or negative free cash flow fails. Five years is a common
    rule of thumb for debt a business can repay from its own cash; 3 would be stricter
    (it would also remove Medtronic, Aon, MSCI, Gen Digital and Roper).
  - *Short-term debt covered:* cash plus a year of free cash flow at least equal to the debt
    due within a year, so the company can meet this year's repayments without new borrowing.
    Stage 1's stricter version asks cash alone to cover it.
  - Banks and insurers skip both, as in Stage 1 (deposits and float are not debt in the
    usual sense). This includes exchanges and brokers that TradingView files as investment
    banks (CME, Cboe, ICE, Schwab). Blanks on TradingView are filled from Yahoo.
- **Historically low P/E:** today's P/E (price / 12-month diluted EPS) against the median of
  the stock's own yearly P/Es over up to 10 fiscal years (average monthly price over each
  fiscal year / that year's diluted EPS, the same history as Stage 2 of the market
  screener). Ranked by how far below the median, lowest first. Yearly P/Es above 100 are left
  out of the history: they come from years of near-zero earnings and would make any P/E look
  low. Before this cut, Insulet's median P/E was 1,140 and Salesforce's 131, and both ranked
  near the top for that reason alone. At least 6 years of P/E history are needed. Stocks with
  less are listed after the ranked ones.

### Findings

1. **Today's list leans to software and data businesses that de-rated** (Adobe, PTC,
   Netflix, Intuit, Roper): margins of 21-42%, revenue up every year, P/E 14-21 against
   their own medians of 37-50. Intuit, ResMed, Deckers and Copart are the cleanest cases:
   no flags, profit up in 4 or 5 of 5 years, margins well above their sector, and net cash
   or debt repaid in under a year of free cash flow.
2. **The debt rules remove a fifth of the survivors** (108 to 83), mostly companies that
   borrow heavily on purpose: restaurant franchisors (Domino's, McDonald's, Yum!), REITs,
   utilities and serial acquirers (McCormick, Fair Isaac). Several of these were near the top
   of the ranking: McCormick was first (its low P/E was also a one-off gain), Fair Isaac
   sixth and Domino's eleventh.
3. **Flags still matter.** PTC, Roper and Alphabet show 12-month net income more than 1.5
   times their latest fiscal year, probably one-off gains (for Alphabet, likely gains on
   investments: $236bn against $132bn in fiscal 2025), so their P/E looks lower than it is.
   Before the debt rules, the REIT UDR passed with 42% a year net income growth from
   property-sale gains ($0.09bn, $0.44bn, $0.09bn, $0.38bn in successive years); lumpy profit
   still passes the growth rules, and only the flag catches it.
4. **The backtest beats the index over 1 year and falls behind over longer holding.** Over
   1 year the top 10 beat the S&P 500 in 3 of 6 years and averaged 23.8% against 17.4%.
   2019 was luck: fiscal 2019 figures bought cruise lines at their April 2020 lows. Without
   2019 the edge is about 2 points a year (13.9% vs 12.1%). Held to today, five of six
   cohorts trail the S&P 500. The 2019 cohort leads only because Comfort Systems (FIX) rose
   37-fold; without it that cohort is about +43%, far behind the index's +160%. The worst
   picks were "cheap" because the business was turning down: Align, Charter, Lululemon,
   Crown Castle, Comcast. Five years of past growth did not mean the growth would go on.
5. **One-off gains distort the backtest too.** Cooper (fiscal 2021) and Public Storage (fiscal
   2022) passed with net margins above 100% from one-off gains, which also made their P/E
   look very low. Both did badly afterwards.

### Does the filter stop the P/E being distorted?

Babak's reasoning for filtering first (2026-10-31): with revenue, net income and margin
positive and growing year by year, the P/E should not be distorted. That holds for most of
what used to go wrong. No survivor has a loss or a near-zero EPS today, so there are no
negative or absurd P/Es. Three distortions get through:

1. **A one-off gain in the last 12 months.** It raises net income, so it *helps* a stock pass
   the growth and margin rules and lowers its P/E. McCormick's 12-month profit is nearly
   twice its latest fiscal year's, so its P/E is 8.5 instead of about 16.
2. **The past P/Es, not today's.** The growth filter checks 5 fiscal years; the P/E history
   goes back up to 10. Years of thin earnings before the 5-year window give very high past
   P/Es and make today's look low. Leaving out yearly P/Es above 100 fixes the extreme
   cases (Insulet, Salesforce), not the milder ones.
3. **Lumpy profit that still rises overall.** "Up in 3 of 5 years" lets a REIT whose profit
   swings with property sales through (UDR).

The flags in the output mark cases 1 and 3. Making them rules, or matching the P/E history
to the 6 years the filter checks, are options 1 and 6 below.

### Caveats

- **Survivorship.** The universe is today's S&P 500, so the backtest only looks at companies
  that survived and stayed in (or joined) the index. This flatters both the picks and the
  "all screened" average. The S&P 500 index itself has no such bias, so the comparison with
  it favours the screen, and the screen still lags it when held to today.
- **Price returns only.** Dividends are left out, which understates REITs and insurers (a
  third of the picks).
- **GAAP diluted EPS.** One-off gains and write-downs pass straight into the P/E and the
  growth rates. Stage 2 uses Yahoo's adjusted EPS for its top names; this screen does not yet.
- **One entry date a year** (end of April). Companies with fiscal years ending late in the
  calendar year had published their annual report by then; a few with odd year-ends may be a
  month early or late.
- **Six years is a small sample**, all from one cycle (the 2020 crash, the 2022 rate rise, the
  2023-25 rally led by a few large companies).

### What to try next (for Babak to choose)

1. Make the flags into rules (no one-off gain, no 30% profit drop), or use adjusted EPS.
2. Require margin not falling (latest margin at or above the 5-year-ago margin), so a
   business whose profit is shrinking relative to sales doesn't look cheap.
3. Require recent growth too (3-year EPS growth above 0, the latest year up), to drop
   companies whose growth has already stopped (the "cheap because declining" picks).
4. Tighten the debt rules: 3 years of free cash flow instead of 5, or cash alone covering
   the debt due within a year (Stage 1's rule).
5. Run the screener on the whole US and Europe (`--all`) for more candidates.
6. Take the P/E history over the same 6 fiscal years the filter checks (every one of them
   profitable and growing) rather than 10.

### Reproduce

```bash
uv run python analysis/growth_screen.py              # today's list -> data/screener/growth.csv
uv run python analysis/growth_screen.py --backtest   # and the backtest -> growth_backtest.csv
```

Settings are in `[growth]` of `config/screeners.toml`. The full reference is in
[`docs/SCREENER.md`](../docs/SCREENER.md#the-growth-screener).
