# 15. The growth screener: growing revenue and profit, high margin, historically low P/E

**Data:** TradingView figures and Yahoo prices as of the 2026-10-30 close (run 2026-10-31).
Universe: the S&P 500 (497 companies, `[universe]` in `config/screeners.toml`).

## Summary

Babak asked for a screener to test (2026-10-31): revenue growing, net profit growing, a high
net margin, EPS growing, and among these the stocks whose P/E is low **against their own
history**. 108 of 497 S&P 500 companies pass the growth and margin rules. 56 of them trade
below their own median P/E. The 20 furthest below it are listed below. Half of those 20
carry a flag (a likely one-off gain or lumpy profit) that makes the P/E less reliable.

A backtest on six past years (fiscal 2019 to 2024, bought at the end of April after each)
gives a mixed result. Over 1 year the top 10 rose 22.0% on average, against 17.4% for the
S&P 500 and 23.4% for an equal-weighted average of all the screened stocks. They beat the
S&P 500 in 4 of the 6 years. **Held to today, every one of the six yearly portfolios is
behind the S&P 500.** As built, the screen finds stocks that bounce over a year more often
than businesses that compound. It is a starting list for study, not a buy list.

## The numbers

### Absolute values: the top 20 (US dollars, billions; price and EPS per share)

| Symbol | Company | Price | Mkt value | Debt | Net debt | ST debt | LT debt | Cash | Revenue | EBITDA | Net income | EPS | OCF | Capex | FCF |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MKC | McCormick & Company | 47.29 | 12.73 | 5.02 | 4.69 | 2.11 | 2.91 | 0.33 | 7.69 | 1.58 | 1.49 | 5.53 | 1.14 | -0.21 | 0.93 |
| ADBE | Adobe | 250.23 | 97.39 | 6.76 | 1.12 | 1.69 | 5.08 | 5.64 | 25.97 | 10.22 | 7.28 | 17.93 | 10.81 | -0.21 | 10.59 |
| PTC | PTC | 195.54 | 21.24 | 1.61 | 1.26 | 0.05 | 1.56 | 0.35 | 2.95 | 1.31 | 1.23 | 10.34 | 0.95 | -0.02 | 0.93 |
| NFLX | Netflix | 62.08 | 254.92 | 17.38 | 9.16 | 2.91 | 14.47 | 8.23 | 50.00 | 33.76 | 14.77 | 3.46 | 12.31 | -0.93 | 11.38 |
| INTU | Intuit | 341.09 | 91.15 | 8.42 | 1.22 | 1.33 | 7.09 | 7.20 | 21.45 | 7.02 | 4.57 | 16.50 | 8.84 | -0.22 | 8.62 |
| FICO | Fair Isaac | 711.23 | 15.36 | 5.60 | 5.35 | 0.30 | 5.30 | 0.25 | 2.39 | 1.26 | 0.81 | 34.61 | 1.00 | -0.04 | 0.94 |
| ROP | Roper Technologies | 466.60 | 46.15 | 9.72 | 9.41 | 1.42 | 8.30 | 0.31 | 8.43 | 3.29 | 2.59 | 25.33 | 2.62 | -0.11 | 2.58 |
| AMT | American Tower | 187.78 | 87.09 | 45.29 | 43.29 | 6.01 | 39.28 | 2.01 | 11.01 | 6.96 | 3.31 | 7.10 | 5.71 | -1.75 | 3.96 |
| UDR | UDR | 35.52 | 11.41 | 5.99 | 5.96 | 1.29 | 4.70 | 0.04 | 1.72 | 0.99 | 0.52 | 1.57 | 1.13 | -0.26 | 0.88 |
| MLM | Martin Marietta Materials | 540.41 | 38.38 | 6.34 | 6.22 | 0.93 | 5.42 | 0.12 | 6.69 | 2.06 | 2.46 | 40.69 | 1.52 | -0.71 | 0.81 |
| DPZ | Domino's Pizza | 313.71 | 10.32 | 5.12 | 4.65 | 1.37 | 3.75 | 0.47 | 5.07 | 1.08 | 0.61 | 18.15 | 0.76 | -0.12 | 0.64 |
| RMD | ResMed | 229.94 | 32.34 | 0.61 | -0.42 | 0.19 | 0.42 | 1.03 | 5.73 | 2.18 | 1.59 | 10.98 | 1.77 | -0.18 | 1.61 |
| GOOG | Alphabet | 278.22 | 3,411.53 | 146.64 | -118.46 | 2.07 | 144.57 | 265.10 | 471.14 | 185.94 | 235.69 | 19.15 | 179.55 | -159.80 | 19.75 |
| DECK | Deckers Outdoor | 81.99 | 10.94 | 0.54 | -0.67 | 0.08 | 0.46 | 1.21 | 5.57 | 1.38 | 1.06 | 7.55 | 1.13 | -0.08 | 1.05 |
| BKNG | Booking | 148.13 | 111.30 | 20.69 | 3.19 | 2.00 | 18.69 | 17.51 | 28.24 | 10.65 | 7.21 | 9.04 | 9.86 | -0.32 | 9.54 |
| FRT | Federal Realty Investment Trust | 110.19 | 9.63 | 5.17 | 5.06 | 0.20 | 4.97 | 0.11 | 1.35 | 0.86 | 0.44 | 5.00 | 0.66 | -0.31 | 0.34 |
| SCHW | Charles Schwab | 88.05 | 152.27 | 40.00 | -28.50 | 16.20 | 23.80 | 68.50 | 30.50 | 17.13 | 10.64 | 5.86 |  |  |  |
| PEP | PepsiCo | 137.34 | 187.16 | 51.88 | 40.72 | 9.22 | 42.66 | 11.16 | 98.24 | 19.97 | 10.90 | 7.96 | 14.57 | -4.10 | 10.47 |
| AON | Aon | 321.67 | 68.24 | 28.95 | 13.63 | 1.90 | 27.05 | 15.32 | 17.68 | 5.94 | 3.93 | 18.26 | 3.57 | -0.31 | 3.27 |
| CPRT | Copart | 30.13 | 27.91 | 0.09 | -4.40 | 0.02 | 0.07 | 4.49 | 4.67 | 1.88 | 1.48 | 1.55 | 1.60 | -0.34 | 1.27 |

Revenue, EBITDA, net income, EPS and cash flows are the last 12 months; debt and cash are the
latest quarter. Schwab's cash flows are blank on TradingView (a broker's cash flow statement
is not comparable).

### Growth, margin and P/E against own history (5 fiscal years, lowest P/E against history first)

| Symbol | # | Sector | Rev CAGR % | Rev up | NI CAGR % | NI up | EPS CAGR % | Margin % | Sector margin % | P/E | Own median P/E | Own low P/E | Years | vs median % | Flags |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MKC | 1 | Consumer Non-Durables | 4.1 | 5/5 | 1.1 | 3/5 | 1.1 | 19.4 | 11.1 | 8.55 | 27.72 | 16.82 | 10 | -69.2 | one-off? |
| ADBE | 2 | Technology Services | 13.1 | 5/5 | 6.3 | 3/5 | 9.0 | 28.1 | 21.0 | 13.96 | 41.85 | 23.00 | 10 | -66.6 |  |
| PTC | 3 | Technology Services | 13.4 | 5/5 | 41.2 | 3/5 | 40.2 | 41.7 | 21.0 | 18.90 | 49.66 | 30.28 | 6 | -61.9 | one-off? lumpy |
| NFLX | 4 | Technology Services | 12.6 | 5/5 | 31.8 | 4/5 | 33.0 | 29.5 | 21.0 | 17.94 | 43.73 | 27.92 | 7 | -59.0 |  |
| INTU | 5 | Technology Services | 17.4 | 5/5 | 17.2 | 5/5 | 16.9 | 21.3 | 21.0 | 20.67 | 44.10 | 30.09 | 10 | -53.1 |  |
| FICO | 6 | Commercial Services | 9.0 | 5/5 | 22.5 | 4/5 | 27.4 | 34.1 | 15.8 | 20.55 | 42.50 | 30.12 | 10 | -51.6 |  |
| ROP | 7 | Technology Services | 10.2 | 4/5 | 10.1 | 4/5 | 9.6 | 30.7 | 21.0 | 18.42 | 37.48 | 20.60 | 10 | -50.9 | one-off? |
| AMT | 8 | Finance | 5.8 | 4/5 | 8.4 | 3/5 | 7.3 | 30.1 | 17.4 | 26.46 | 51.33 | 37.21 | 10 | -48.5 | lumpy |
| UDR | 9 | Finance | 6.6 | 5/5 | 42.5 | 3/5 | 40.8 | 30.4 | 17.4 | 22.63 | 43.44 | 29.35 | 6 | -47.9 | lumpy |
| MLM | 10 | Non-Energy Minerals | 5.4 | 4/5 | 9.6 | 3/5 | 10.2 | 36.7 | 13.2 | 13.28 | 24.67 | 17.43 | 10 | -46.2 | one-off? lumpy |
| DPZ | 11 | Consumer Services | 3.7 | 4/5 | 4.1 | 4/5 | 7.2 | 12.0 | 9.6 | 17.28 | 29.97 | 24.03 | 10 | -42.3 |  |
| RMD | 12 | Health Technology | 12.1 | 5/5 | 26.3 | 5/5 | 26.3 | 27.8 | 14.4 | 20.94 | 36.14 | 23.19 | 10 | -42.1 |  |
| GOOG | 13 | Technology Services | 17.2 | 5/5 | 26.8 | 4/5 | 29.8 | 50.0 | 21.0 | 14.52 | 24.52 | 20.13 | 10 | -40.8 | one-off? |
| DECK | 14 | Consumer Non-Durables | 16.4 | 5/5 | 21.8 | 5/5 | 25.6 | 19.0 | 11.1 | 10.87 | 17.98 | 13.99 | 9 | -39.6 |  |
| BKNG | 15 | Consumer Services | 31.7 | 5/5 | 146.8 | 4/5 | 158.6 | 25.5 | 9.6 | 16.38 | 26.85 | 16.76 | 9 | -39.0 |  |
| FRT | 16 | Finance | 9.6 | 5/5 | 25.7 | 4/5 | 23.5 | 32.5 | 17.4 | 22.02 | 35.10 | 21.13 | 10 | -37.2 | lumpy |
| SCHW | 17 | Finance | 18.0 | 5/5 | 21.8 | 4/5 | 17.0 | 34.9 | 17.4 | 15.02 | 22.46 | 16.35 | 10 | -33.1 |  |
| PEP | 18 | Consumer Non-Durables | 5.9 | 5/5 | 3.0 | 4/5 | 3.2 | 11.1 | 11.1 | 17.26 | 25.72 | 12.65 | 10 | -32.9 |  |
| AON | 19 | Finance | 9.4 | 5/5 | 13.4 | 3/5 | 15.0 | 22.2 | 17.4 | 17.62 | 25.88 | 20.63 | 10 | -31.9 | lumpy |
| CPRT | 20 | Retail Trade | 11.6 | 5/5 | 9.6 | 4/5 | 9.8 | 31.8 | 8.0 | 19.43 | 28.41 | 17.43 | 10 | -31.6 |  |

CAGR = compound growth a year over 5 fiscal years. "Up" = years of the 5 in which the
figure rose. Margin = 12-month net income / revenue. P/E = price / 12-month diluted EPS.
Own median and low P/E = median and lowest of the yearly P/Es over up to 10 fiscal years.
Flags: *one-off?* = 12-month net income is more than 1.5 times the latest fiscal year;
*lumpy* = net income fell more than 30% in one of the 5 years.

The full list of 108 survivors, and why each of the other 389 failed or was incomplete, is in
`data/screener/growth.csv`.

**What fails.** A company can fail several rules: net margin 263, net income growth 176,
EPS growth 169, profit every year 137, still growing 130, revenue up 4 of 5 years 130, net
income up 3 of 5 years 125, revenue growth 30. Six are incomplete because they have less
than 6 years of history (recent spin-offs: GE Vernova, Sandisk, Solventum and others).

**Survivors by sector:** Finance 23, Technology Services 16, Electronic Technology 14,
Health Technology 10, Producer Manufacturing 9, Commercial Services 7, the rest 29.

### Backtest: the same rules in past years

Each fiscal year Y from 2019 to 2024: the rules applied to the yearly figures up to Y, P/E =
price at the end of April Y+1 / EPS for Y, ranked against the P/Es before then; the 10 lowest
bought at the end of April Y+1. Price returns (no dividends).

| Fiscal year | Bought | Passed | Top 10, 1 year | All passed, 1 year | All screened, 1 year | S&P 500, 1 year | Top 10, to today | All passed, to today | All screened, to today | S&P 500, to today |
|---|---|---|---|---|---|---|---|---|---|---|
| 2019 | 2020-04-30 | 119 | +66.2% | +55.2% | +58.6% | +43.6% | +135.7% | +157.8% | +211.9% | +160.3% |
| 2020 | 2021-04-30 | 103 | -0.6% | -3.6% | +1.4% | -1.2% | +44.9% | +72.0% | +89.6% | +81.3% |
| 2021 | 2022-04-30 | 119 | +18.4% | +7.7% | +1.6% | +0.9% | +80.9% | +70.8% | +93.6% | +83.5% |
| 2022 | 2023-04-30 | 118 | +11.2% | +18.1% | +24.8% | +20.8% | +39.9% | +65.0% | +103.9% | +81.8% |
| 2023 | 2024-04-30 | 108 | +21.6% | +11.3% | +9.8% | +10.6% | +21.4% | +29.4% | +53.3% | +50.5% |
| 2024 | 2025-04-30 | 111 | +15.3% | +11.3% | +44.0% | +29.4% | +22.3% | +17.0% | +49.9% | +36.1% |
| **Average** | | | **+22.0%** | +16.7% | +23.4% | +17.4% | **+57.5%** | +68.7% | +100.4% | +82.2% |
| Average without 2019 | | | +13.2% | +9.0% | +16.3% | +12.1% | +41.9% | +50.8% | +78.1% | +66.6% |

The 60 picks are in `data/screener/growth_backtest.csv`. 65% of them rose in their first year.
Most were Finance (21 of 60, mostly REITs and insurers) and Health Technology (11).

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
- **High margin, 10% and the sector median.** Babak suggested 10% and asked for a better way
  if there is one. A fixed number is unfair across industries: S&P 500 sector median net
  margins on this data run from 2.1% (Distribution Services) and 3.8% (Process Industries) to
  17.4% (Finance) and 21.0% (Technology Services). The rule is net margin of at least 10%
  **and** at least the sector's median (over every S&P 500 company in that sector). So a
  software company needs 21%, and a restaurant chain needs the 10% floor because its sector
  median is 9.6%. Sector medians need 5 companies or more. Below that only the 10% applies
  (Communications, with 4 companies).
- **Still growing:** 12-month revenue and net income at or above the latest fiscal year, so a
  slowdown since the last annual report is caught.
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
   Netflix, Intuit, FICO, Roper): margins of 21-42%, revenue up every year, P/E 14-21
   against their own medians of 37-50. Intuit, FICO, ResMed, Deckers and Copart are the
   cleanest cases, with no flags, profit up in 4 or 5 of 5 years and margins well above their
   sector.
2. **The top name is a false positive.** McCormick's 12-month net income ($1.49bn) is nearly
   double its latest fiscal year ($0.79bn), probably a one-off gain. Its real P/E on the latest
   fiscal year is about 16, not 8.5. PTC, Roper, Martin Marietta and Alphabet carry the same
   flag. For Alphabet that is likely gains on investments: 12-month net income of $236bn
   against $132bn in fiscal 2025.
3. **Lumpy profit passes too easily.** UDR (a REIT) shows 42% a year net income growth from
   property-sale gains: $0.09bn, $0.44bn, $0.09bn, $0.38bn in successive years. The flag
   catches it, but the rules do not.
4. **The backtest beats the index over 1 year and falls behind over longer holding.** Over
   1 year the top 10 beat the S&P 500 in 4 of 6 years (by 1 to 18 percentage points) and
   averaged 22.0% against 17.4%. 2019 was luck: fiscal 2019 figures bought airlines and cruise
   lines at their April 2020 lows. Without 2019 the edge is about 1 point a year (13.2% vs
   12.1%). Held to today, every cohort trails the S&P 500. The worst picks were "cheap"
   because the business was turning down: Align, PayPal, Lululemon, Crown Castle, SBA, Comcast.
   Five years of past growth did not mean the growth would go on.
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
4. Combine with Stage 1's debt rules. AMT and UDR carry net debt above 6x EBITDA.
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
