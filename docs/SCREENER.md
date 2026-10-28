# The market screener: reference

The screener finds companies worth owning and then those whose price is cheap. It has two
stages, run as separate programs:

- **Stage 1, good financial statements** (`analysis/stage1.py`): puts each company in one of
  Peter Lynch's categories and keeps those that pass every rule for their category or kind
  of business. The price plays no part.
- **Stage 2, cheapness** (`analysis/stage2.py`): reads only Stage 1's output, sets each
  survivor's own cheap price, and lists the top 3 cheap or close-to-cheap names per sector.
  Technicals are shown for timing and never change the ranking.

`analysis/screener.py` runs both. Settings: `config/screeners.toml`. Results and their
discussion: [report 13](../reports/13-market-screener.md). The methods doc with every rule's
source, "Stage 1 screening methods and their sources", is at
https://claude.ai/artifact/XXxnx8ZMtM8GwfnsfS4mza. Commands and the step-by-step run are in
[`PROCESSES.md`](PROCESSES.md#5-the-market-screener).

## Settings

| Setting | Value | Meaning |
|---|---|---|
| `min_market_cap_usd` | 1e9 | Minimum market value in US dollars, converted at ECB rates |
| `top_per_sector` | 3 | Names listed per region and sector |
| `close_to_cheap` | 0.15 | Up to 15% above the cheap price counts as "close" |
| `cheap_percentile` | 0.25 | The cheap P/E is the bottom quarter of the stock's own yearly P/Es |
| `history_years` | 10 | Fiscal years of P/E history looked at |
| `min_history_years` | 6 | Years of positive P/E needed for a cheap price |
| `[universe] index` | `"SP:SPX"` | Only S&P 500 members (TradingView's index code). `""` = every company above the floor |
| `[universe] regions` | `["US"]` | Regions scanned (`[]` = all) |
| `[regions] US` | `america` | TradingView market for the US |
| `[regions] Europe` | 17 markets | UK, Germany, France, Italy, Spain, Netherlands, Switzerland, Sweden, Denmark, Norway, Finland, Belgium, Austria, Portugal, Ireland, Poland, Greece |

**Scope for now: the S&P 500** (Babak, 2026-10-27: "for now, we're focusing on the S&P 500").
The code screens the US and 17 European markets with one setting change (`index = ""`,
`regions = []`); the earlier all-market run that day covered 3,432 companies.

## Universe

TradingView's screener, market by market, primary listings of common stock only, market
value above $50m in local currency as a first cut, then above `min_market_cap_usd` after
conversion. With `index = "SP:SPX"` only rows whose `indexes` list S&P 500 membership remain:
497 companies on 2026-10-27 (the index has about 503 share classes). Companies whose
statement or trading currency has no ECB rate are dropped.

## Screener types

| Type | TradingView industry (or sector) | Rule set |
|---|---|---|
| banks | Major Banks, Regional Banks, Savings Banks, Financial Conglomerates, Investment Banks/Brokers | `[screener.banks]` |
| insurers | Multi-Line, Property/Casualty, Life/Health, Specialty Insurance | `[screener.insurers]` |
| reits | Real Estate Investment Trusts | `[screener.reits]` |
| utilities | Sector "Utilities" | The Lynch category's rules, without `min_altman_z` |
| general | Everything else | The Lynch category's rules |
| excluded | Investment Trusts/Mutual Funds | Skipped |

## Lynch categories

*One Up on Wall Street* (Peter Lynch, 1989), chapter 7, sorts companies into six kinds: slow
growers, stalwarts, fast growers, cyclicals, turnarounds, asset plays. Tested in this order;
the first that fits wins.

| Order | Category | Test | Setting |
|---|---|---|---|
| 1 | no profit (not Lynch's) | No positive diluted EPS in any of the last 5 fiscal years (at least 3 needed). Fails, unless the company is a bank, insurer or REIT (they get their own rules) | |
| 2 | cyclical | Industry in the cyclical list | `cyclical_industries` |
| 3 | turnaround | Loss now (12-month or latest-year EPS at or below 0), or the higher of 12-month and latest-year EPS more than 50% below the best of the last 5 fiscal years | `turnaround_drop = 0.50` |
| 4 | cyclical | EPS fell more than 30% in 3 or more of the last 10 yearly changes, and median 5-year EPS growth is below 20% | `cyclical_drops = 3`, `cyclical_drop_size = 0.30` |
| 5 | asset play | Price / book above 0 and below 1, or net cash above 30% of market value | `asset_price_to_book = 1.0`, `asset_net_cash = 0.30` |
| 6 | fast grower | Median yearly EPS growth over 5 years of 20% or more | `growth_years = 5`, `fast_growth = 0.20` |
| 7 | stalwart | 8% to under 20% | `stalwart_growth = 0.08` |
| 8 | slow grower | Under 8% | |
| | blank | Fewer than 3 yearly EPS changes: status "incomplete" (too little history) | |

Lynch's own ranges: fast growers 20-25% a year, stalwarts 10-12%, slow growers about the
economy's 2-4%. The 8% and 20% cut-offs fill the gaps between his ranges; they are judgement
calls listed in the methods doc for review.

[Report 16](../reports/16-lynch-categories.md) compares these tests with Lynch's own numbers
and published quant versions (Validea, AAII) and proposes a revision, not adopted yet.
`uv run python analysis/lynch_compare.py` shows how today's companies would move.

## Stage 1 rules

A stock must pass **every** rule of its rule set. A rule with missing data makes the stock
**incomplete** (not a pass), unless the rule is listed under `optional`; then it is skipped
and noted in `flags`. "Net cash passes" means a company whose net debt is zero or below
passes that rule whatever the ratio.

### Rule definitions

| Rule | Definition | Special cases |
|---|---|---|
| `cash_to_short_term_debt` | Cash and short-term investments / debt due within a year, at least the value | No short-term debt passes |
| `cash_to_long_term_debt` | Cash / long-term debt, at least the value | No long-term debt passes |
| `max_net_debt_to_ebitda` | Net debt / 12-month EBITDA, at most the value | Net cash passes; EBITDA at or below 0 fails |
| `max_net_debt_to_avg_ebitda` | Net debt / average yearly EBITDA over up to 10 years (5 needed), at most the value | Net cash passes; average EBITDA at or below 0 fails |
| `min_interest_cover` | EBITDA / interest expense (TradingView, or Yahoo EBITDA / interest when blank), at least the value | Net cash passes |
| `max_debt_to_equity` | Total debt / equity, at most the value | Net cash passes. **Negative equity** (equity below 0, or debt/equity and price/book both blank, with debt): net debt / EBITDA at most 2.0x instead; EBITDA at or below 0 fails |
| `min_cash_to_total_debt` | Cash / total debt, at least the value | No debt passes |
| `profitable` | 12-month net income, diluted EPS and EBITDA all above 0 | Banks and insurers: EBITDA not checked |
| `profitable_10y_avg` | Average yearly diluted EPS over up to 10 years (5 needed) above 0 | |
| `positive_ocf` | 12-month operating cash flow above 0 | |
| `growth_years` | Revenue and EPS: average and median yearly growth over this many years all above 0 | At least 3 yearly changes needed |
| `min_eps_growth_3y` | Diluted EPS growth a year, compounded from 3 fiscal years ago to the latest, at least the value | Both years' EPS must be positive |
| `min_dividend_years` | Years with a dividend in the last 10 fiscal years, at least the value | A company that paid no dividend in all 10 years passes |
| `max_payout` | Dividends / earnings (12 months), at most the value | |
| `max_recession_eps_drop` | Worst yearly EPS change in the 2009 and 2020 fiscal years, no worse than minus the value | `recession_years = [2009, 2020]` |
| `min_roe` | Return on equity, latest quarter, percent, at least the value | |
| `min_piotroski` | Piotroski F-score (0-9), at least the value | |
| `min_altman_z` | Altman Z-score, above the value | |

### Rule sets and sources

Sources in the tables: **Babak** = Babak's own debt rules, set in the utilities screening
work (report 09, rounds 1-4); **Lynch** = *One Up on Wall Street*, chapter 7 (the categories) and
his final checklist of what to check for each category; **Piotroski 2000** = Joseph
Piotroski, "Value Investing: The Use of Historical Financial Statement Information to
Separate Winners from Losers", *Journal of Accounting Research*, 2000; **Altman 1968** =
Edward Altman, "Financial Ratios, Discriminant Analysis and the Prediction of Corporate
Bankruptcy", *Journal of Finance*, 1968; **Judgement** = a threshold chosen for this screener
(report 13 and the methods doc list them for review).

**Slow grower.** Babak's debt rules, and Lynch's dividend checks: slow growers are bought for
the dividend, so check it has been paid regularly and that the payout leaves a cushion.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak (report 09, round 3) |
| `cash_to_long_term_debt` | 0.05 | Babak (report 09, round 4) |
| `max_net_debt_to_ebitda` | 4.5 | Babak (report 09, rounds 2 and 4) |
| `min_interest_cover` | 4.0 | Babak (report 09, round 1) |
| `profitable` | yes | Report 09, round 2 |
| `growth_years` | 5 | Report 09, round 6 (average and median above 0), over 5 years |
| `min_dividend_years` | 10 | Lynch (dividends paid every year) |
| `max_payout` | 0.8 | Lynch (payout leaves a cushion); 80% is judgement |
| `min_piotroski` | 5 (optional) | Piotroski 2000; 5 is judgement (he buys 8-9 and shorts 0-1) |
| `min_altman_z` | 1.8 (optional) | Altman 1968: 1.81 and below is the distress zone |

**Stalwart.** Babak's debt rules and growth, and Lynch's test of how it held up in past
recessions.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak |
| `cash_to_long_term_debt` | 0.05 | Babak |
| `max_net_debt_to_ebitda` | 4.5 | Babak |
| `min_interest_cover` | 4.0 | Babak |
| `profitable` | yes | Report 09 |
| `growth_years` | 5 | Report 09 |
| `max_recession_eps_drop` | 0.30 (optional) | Lynch (how it fared in past recessions); 30% is judgement |
| `min_piotroski` | 5 (optional) | Piotroski 2000 |
| `min_altman_z` | 1.8 (optional) | Altman 1968 |

**Fast grower.** Lynch: fast growers must not be over-borrowed, and the growth must still be
fast now.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak |
| `max_debt_to_equity` | 1.0 | Lynch's balance-sheet check, adjusted for leases (see judgement calls) |
| `min_interest_cover` | 4.0 | Babak |
| `profitable` | yes | Report 09 |
| `min_eps_growth_3y` | 0.20 | Lynch (fast growers grow 20-25% a year) |
| `min_piotroski` | 5 (optional) | Piotroski 2000 |
| `min_altman_z` | 1.8 (optional) | Altman 1968 |

**Cyclical.** Lynch: a cyclical must survive the downturn, so debt is measured against
average EBITDA over the cycle and profit on average over 10 years, not at today's point in
the cycle.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak |
| `cash_to_long_term_debt` | 0.05 | Babak |
| `max_net_debt_to_avg_ebitda` | 2.5 | Lynch (survive the downturn); 2.5x is judgement |
| `min_interest_cover` | 4.0 | Babak |
| `profitable_10y_avg` | yes | Lynch (judge a cyclical over the whole cycle) |
| `min_altman_z` | 1.8 (optional) | Altman 1968 |

**Turnaround.** Lynch: for a turnaround the question is survival: how much cash, how much
debt, and whether cash is coming in.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak |
| `min_cash_to_total_debt` | 0.25 | Lynch (can it survive its creditors); 25% is judgement |
| `positive_ocf` | yes | Lynch (cash coming in) |

**Asset play.** Lynch: an asset play's assets are only worth what is left after the debt.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak |
| `max_debt_to_equity` | 1.0 | Lynch (debt detracts from the assets); 1.0 is judgement |
| `positive_ocf` | yes | Judgement |

**Banks and insurers.** Deposits, funding and insurance float make the debt rules
meaningless, so they are judged on returns.

| Rule | Threshold | Source |
|---|---|---|
| `profitable` | yes (without EBITDA) | Report 09 |
| `min_roe` | 8 (percent) | Judgement |
| `growth_years` | 5 | Report 09 |

**REITs.** They carry more debt by design; EPS understates their cash earnings because of
depreciation.

| Rule | Threshold | Source |
|---|---|---|
| `cash_to_short_term_debt` | 1.0 | Babak |
| `max_net_debt_to_ebitda` | 7.0 | Judgement (higher than Babak's 4.5x for the business model) |
| `min_interest_cover` | 2.5 | Judgement |
| `profitable` | yes | Report 09 |

**Utilities** use their Lynch category's table without `min_altman_z`: the Z-score was built
on manufacturers and does not fit regulated companies.

### Status

| Status | Meaning |
|---|---|
| `pass` | Every rule passed (optional rules with no data skipped and flagged) |
| `fail` | At least one rule failed (listed in `failed`), or no profit in 5 years |
| `incomplete` | No rule failed, but a required rule had no data (listed in `missing`), or no category |

## Stage 2

### Cheap price

1. **Own yearly P/E (diluted).** For each of the last 10 fiscal years: the average of
   Yahoo's monthly closes over the fiscal year (at least 9 months, converted to the
   statements' currency) divided by TradingView's diluted EPS for that year. Years with EPS
   at or below 0 are left out.
2. **Own cheap P/E** = the 25th percentile of those P/Es, with at least 6 years. With fewer,
   the stock has no cheap price and is not ranked.
3. **Sector cap.** The sector P/E is the median current P/E of all Stage 1 companies in the
   same region and sector. **Cheap multiple = the lower of the own cheap P/E and the sector
   P/E.** `cheap_basis` says which set it. The sector median is a cap, not a substitute for a
   short history.
4. **Cheap price** = cheap multiple x 12-month EPS, in the trading currency.
5. **Adjusted EPS.** For the 9 closest names in each region and sector, Yahoo's reported
   quarterly EPS (adjusted, split-adjusted, the watch list's method) replaces diluted EPS,
   and its own calendar-year P/E history replaces the diluted one, when that history has at
   least 6 years and the adjusted 12-month EPS is between half and twice diluted EPS. Outside
   that band the adjusted figure is treated as a data error and flagged. `eps_basis` records
   which EPS was used.

### Ranking

| Step | Rule |
|---|---|
| Who | Stage 1 `pass` only |
| Measure | `vs_cheap` = price / cheap price - 1 |
| Listed | `vs_cheap` at most 0.15 |
| Label | `cheap` at or below the cheap price; `close` up to 15% above |
| Order | Lowest `vs_cheap` first, inside each region and sector |
| Kept | Top 3 per region and sector |

Stage 1 decides who gets in; only cheapness sets the order. Nothing else (growth, quality
scores, technicals) changes the ranking.

### Technicals (timing only)

| Measure | Rule |
|---|---|
| `trend` | `uptrend`: price and the 50-day average above the 200-day; `downtrend`: both below; `mixed` otherwise |
| `rsi_read` | `oversold` below 30, `overbought` above 70 |
| `in_52w_range` | 0 at the 52-week low, 1 at the high |
| `tv_rating` | TradingView's technical rating (`Recommend.All`): 0.5 and above strong buy, 0.1 buy, -0.1 and below sell, -0.5 strong sell, otherwise neutral |

### Cross-checks and fills

- **SEC EDGAR.** For US names on the list, TradingView's latest-year diluted EPS is compared
  with SEC's frames API (`us-gaap/EarningsPerShareDiluted/USD-per-shares/CY<year>`). A gap
  above 10% is written to `flags`; `sec_eps` holds SEC's figure. On 2026-10-27 all 29 names
  were found and none was off by more than 10%.
- **Cash flows.** Blank 12-month operating cash flow, capex or free cash flow of a listed name
  is filled from Yahoo's last four quarters and named in `filled`.

## Judgement calls

| Call | What the code does | Why |
|---|---|---|
| Fast-grower debt / equity at 1.0, not Lynch's 0.33 | `max_debt_to_equity = 1.0` | Lynch's "normal" balance sheet is 75% equity and 25% debt (debt/equity 0.33), from before leases were counted as debt (US rules since 2019). With leases in the debt, debt no larger than equity is the comparable bar |
| Non-dividend slow growers pass the dividend rule | `min_dividend_years` passes when no dividend was paid in any of the 10 years | Lynch's check is on the record of companies that pay a dividend; a company that returns cash only through buybacks is not penalised |
| Negative equity uses net debt / EBITDA at most 2x | In `max_debt_to_equity`, when equity is negative (or debt/equity and price/book are both blank) and there is debt | Debt / equity means nothing with negative equity, which mostly comes from years of buybacks (Booking, McDonald's). 2x is S&P's "modest" leverage level. No EBITDA to carry the debt fails |
| S&P 500 only, for now | `[universe] index = "SP:SPX"`, `regions = ["US"]` | Babak, 2026-10-27. The US and Europe remain one setting away |
| Utilities without the Altman score | `min_altman_z` removed for type `utilities` | The Z-score was built on manufacturers; regulated utilities score low by design |
| No debt rules for banks and insurers | Returns and growth only | Deposits and float are not debt in the usual sense |
| REITs on EPS | Same EPS-based rules | Funds from operations are not available from these free sources; EPS understates REIT cash earnings |
| Category from GAAP EPS | Diluted EPS history decides the category | Free yearly adjusted EPS is not available for the whole market. A write-down year can mislabel a company; the category is shown next to every name so it can be checked |
| Cheap P/E capped at the sector median | `min(own cheap P/E, sector P/E)` | So a stock whose whole history was priced for hyper-growth (Amazon, Netflix) isn't called cheap at a multiple its peers never get |
| No fear or sell-off signal | Not part of the ranking | Babak's method ranks on the stock's own cheap price; the earlier panic-sell screen was a one-off |
| Technicals for timing only | Shown, never ranked | Fundamentals decide what to buy; technicals only when |

## Caveats

- TradingView's and Yahoo's interfaces are unofficial; field names can change and Yahoo
  rate-limits heavy use. Each run caches its downloads for the day in `.cache/screener/`.
- Own history is not destiny: a stock far below its cheap price may have been re-rated for a
  reason. The screen finds candidates; each needs the full single-stock analysis.
- Cyclicals at low P/Es may be at peak earnings (Lynch's warning).
- The SEC check uses calendar-year frames; for companies whose fiscal year doesn't end in
  December it may compare a different 12 months.
- Sectors are TradingView's 20, not GICS.
- DCF fair value is not part of the screener yet.
