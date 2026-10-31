# Metrics dictionary

Generated from `config/metrics.toml` by `uv run python -m stock_analysis.metrics doc`; edit the TOML, not this file. Report 14 explains the choices to make.

Worked examples are Boston Scientific (BSX) unless they say otherwise. Yahoo figures (sector.py, peer screen) are as of the 2026-10-26 close; TradingView figures (Stage 1) as of 2026-10-27; adjusted EPS and P/E history from the 2026-10-27 20:55 watch-list run. Booking (BKNG) is used where BSX can't show a case (net cash, negative equity).

Vector status: **core** = proposed for the first vector, **candidate** = worth considering, **context** = needed to read the others, **derived** = depends on a peer group or a model.

## Summary

**Size and price** (3)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Share price](#price) | close | none | context |
| [Market value](#market-cap) | price x shares outstanding | none | context |
| [Enterprise value](#enterprise-value) | market_cap + net_debt | none | context |

**Balance sheet (absolute)** (6)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Total debt](#total-debt) | short_term_debt + long_term_debt | lower | candidate |
| [Short-term debt](#short-term-debt) | current debt + current lease liabilities; if blank, total_debt - long_term_debt | lower | candidate |
| [Long-term debt](#long-term-debt) | non-current debt + non-current lease liabilities | lower | candidate |
| [Cash and short-term investments](#cash) | cash and equivalents + short-term investments | higher | candidate |
| [Net debt](#net-debt) | total_debt - cash | lower | candidate |
| [Shareholders' equity (book value)](#book-equity) | total assets - total liabilities | higher | candidate |

**Income statement (absolute)** (8)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Revenue](#revenue) | sum of the last 4 quarters' revenue | higher | context |
| [EBITDA](#ebitda) | operating income + depreciation and amortization | higher | context |
| [Net income](#net-income) | sum of the last 4 quarters' net income | higher | context |
| [Interest expense](#interest-expense) | sum of the last 4 quarters' interest expense | lower | candidate |
| [Depreciation and amortization](#d-and-a) | from the cash-flow statement | none | context |
| [EPS, GAAP diluted](#eps-ttm) | net_income / diluted shares | higher | candidate |
| [EPS, adjusted](#eps-adj-ttm) | sum of the last 4 quarters' reported (adjusted) EPS, with eps_override corrections | higher | core |
| [Forward EPS](#eps-fwd) | consensus estimate | higher | candidate |

**Cash flow (absolute)** (4)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Operating cash flow](#operating-cf) | net income + non-cash charges +/- working-capital changes | higher | context |
| [Capital expenditure](#capex) | purchases of property, plant and equipment | none | context |
| [Free cash flow](#free-cf) | operating_cf + capex | higher | context |
| [Cash flow before growth (DCF base)](#fcff-before-growth) | operating_cf - d_and_a + interest_expense x (1 - 21% tax) | higher | candidate |

**Debt and liquidity ratios** (9)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Cash / short-term debt](#cash-to-short-term-debt) | cash / short_term_debt (no short-term debt = passes) | higher | core |
| [(Cash + operating cash flow) / short-term debt](#cash-plus-ocf-to-short-term-debt) | (cash + max(operating_cf, 0)) / short_term_debt | higher | candidate |
| [Cash / long-term debt](#cash-to-long-term-debt) | cash / long_term_debt | higher | core |
| [Cash / total debt](#cash-to-total-debt) | cash / total_debt | higher | candidate |
| [Net debt / EBITDA](#net-debt-to-ebitda) | net_debt / ebitda (net cash always passes; EBITDA <= 0 fails) | lower | core |
| [Net debt / 10-year average EBITDA](#net-debt-to-avg-ebitda) | net_debt / mean(EBITDA, last 10 fiscal years; needs 5) | lower | candidate |
| [Interest cover (EBITDA / interest)](#interest-cover) | ebitda / interest_expense (net cash always passes) | higher | core |
| [Debt / equity](#debt-to-equity) | total_debt / book_equity | lower | candidate |
| [Net cash / market value](#net-cash-to-market-cap) | -net_debt / market_cap | higher | candidate |

**Profitability** (6)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Net margin](#net-margin) | net_income / revenue | higher | core |
| [Net margin, average of fiscal years](#net-margin-avg) | mean(net income / revenue per fiscal year) | higher | candidate |
| [Net margin change, average](#margin-change-avg) | mean(margin_y - margin_y-1) | higher | candidate |
| [Net margin change, median](#margin-change-median) | median(margin_y - margin_y-1) | higher | candidate |
| [Sector median net margin](#sector-net-margin) | median(net_margin) over the sector | none | derived |
| [Return on equity](#roe) | net_income / average book_equity | higher | candidate |

**Growth** (18)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Revenue growth, average year](#revenue-growth-avg) | mean(revenue_y / revenue_y-1 - 1) | higher | candidate |
| [Revenue growth, median year](#revenue-growth-median) | median(revenue_y / revenue_y-1 - 1) | higher | core |
| [Revenue growth, 3-year compound](#revenue-cagr-3y) | (revenue_FY0 / revenue_FY-3) ^ (1/3) - 1 | higher | candidate |
| [Revenue growth, latest quarter](#revenue-growth-yoy) | revenue_Q / revenue_Q-4 - 1 | higher | candidate |
| [EBITDA growth, 3-year compound](#ebitda-cagr-3y) | (ebitda_FY0 / ebitda_FY-3) ^ (1/3) - 1 | higher | candidate |
| [EPS growth, average year](#eps-growth-avg) | mean(eps_y / eps_y-1 - 1), years with eps_y-1 > 0 | higher | candidate |
| [EPS growth, median year](#eps-growth-median) | median(eps_y / eps_y-1 - 1) | higher | core |
| [EPS growth, 3-year compound](#eps-cagr-3y) | (eps_FY0 / eps_FY-3) ^ (1/3) - 1 | higher | candidate |
| [Revenue growth, 5-year compound](#revenue-cagr-5y) | (revenue_FY0 / revenue_FY-5) ^ (1/5) - 1 | higher | candidate |
| [Years revenue rose, of the last 5](#revenue-up-years-5y) | count(revenue_y > revenue_y-1, last 5 years) | higher | candidate |
| [Net income growth, 5-year compound](#net-income-cagr-5y) | (net_income_FY0 / net_income_FY-5) ^ (1/5) - 1 | higher | candidate |
| [Years net income rose, of the last 5](#net-income-up-years-5y) | count(net_income_y > net_income_y-1, last 5 years) | higher | candidate |
| [EPS growth, 5-year compound](#eps-cagr-5y) | (eps_FY0 / eps_FY-5) ^ (1/5) - 1 | higher | candidate |
| [Earnings growth, latest quarter](#earnings-growth-yoy) | eps_Q / eps_Q-4 - 1 | higher | candidate |
| [Operating cash flow growth, average year](#ocf-growth-avg) | mean(ocf_y / ocf_y-1 - 1) | higher | candidate |
| [Operating cash flow growth, median year](#ocf-growth-median) | median(ocf_y / ocf_y-1 - 1) | higher | core |
| [Cash balance growth, average year](#cash-growth-avg) | mean(cash_y / cash_y-1 - 1) | higher | context |
| [Cash balance growth, median year](#cash-growth-median) | median(cash_y / cash_y-1 - 1) | higher | context |

**Earnings history (Lynch inputs)** (9)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [EPS against its 5-year peak](#eps-vs-5y-peak) | max(eps_ttm, eps_FY0) / max(eps, last 5 FY) - 1 | higher | candidate |
| [Losing money now](#loss-now) | eps_ttm <= 0 or eps_FY0 <= 0 | lower | candidate |
| [No profit in 5 years](#no-profit-5y) | max(eps, last 5 FY) <= 0 | lower | candidate |
| [Big EPS drops in 10 years](#eps-big-drops-10y) | count(eps_y / eps_y-1 - 1 < -30%, eps_y-1 > 0) | lower | candidate |
| [Average EPS over 10 years](#eps-avg-10y) | mean(eps, last 10 FY) | higher | candidate |
| [EPS change in recessions](#recession-eps-change) | min(eps_2009 / eps_2008 - 1, eps_2020 / eps_2019 - 1) | higher | candidate |
| [Years with a dividend, of 10](#dividend-years-10y) | count(dps > 0, last 10 FY) | higher | candidate |
| [Dividend payout ratio](#payout-ratio) | dividends per share / eps_ttm | lower | candidate |
| [Lynch category](#lynch-category) | tested in order: no_profit_5y; cyclical industry; turnaround (loss_now or eps_vs_5y_peak < -50%); cyclical history (eps_big_drops_10y >= 3, not fast); asset play (price/book < 1 or net cash > 30% of value); then eps_growth_median >= 20% fast, >= 8% stalwart, else slow | none | core |

**Quality scores** (6)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [Piotroski F-score](#piotroski-f) | sum of 9 binary tests, latest fiscal year against the one before | higher | core |
| [Altman Z-score](#altman-z) | 1.2 x working capital/assets + 1.4 x retained earnings/assets + 3.3 x EBIT/assets + 0.6 x market value/liabilities + 1.0 x sales/assets | higher | core |
| [Weighted screen: debt score](#debt-score) | mean(percentile ranks of the 4 debt ratios) | higher | derived |
| [Weighted screen: profitability and cash score](#quality-score) | weighted mean of percentile ranks | higher | derived |
| [Weighted screen: cheapness score](#cheap-score) | mean(percentile ranks, reversed) | higher | derived |
| [Weighted screen: total](#total-score) | 0.5 x debt_score + 0.25 x quality_score + 0.25 x cheap_score | higher | derived |

**Valuation (needs the price)** (18)

| Metric | Formula | Better | Vector |
|---|---|---|---|
| [P/E, trailing GAAP](#pe-ttm) | price / eps_ttm | lower | candidate |
| [P/E, trailing adjusted](#pe-adj) | price / eps_adj_ttm | lower | core |
| [P/E, forward](#pe-fwd) | price / eps_fwd | lower | candidate |
| [Expected P/E change](#pe-change-expected) | pe_fwd / pe_ttm - 1 | lower | candidate |
| [Own P/E, 10-year median](#pe-median-10y) | median(avg price_y / adjusted eps_y, last 10 years) | none | context |
| [P/E against own 10-year median](#pe-vs-own-median) | pe_adj / pe_median_10y - 1 | lower | core |
| [P/E against industry median](#pe-rel) | pe_ttm / median(pe_ttm, same industry) - 1 | lower | derived |
| [EV / EBITDA](#ev-to-ebitda) | enterprise_value / ebitda | lower | candidate |
| [EV / EBITDA against industry median](#ev-rel) | ev_to_ebitda / median(ev_to_ebitda, same industry) - 1 | lower | derived |
| [Price / sales](#price-to-sales) | market_cap / revenue | lower | candidate |
| [Price / book](#price-to-book) | market_cap / book_equity | lower | candidate |
| [Free cash flow yield](#fcf-yield) | free_cf / market_cap | higher | core |
| [Dividend yield](#dividend-yield) | dividends per share / price | none | candidate |
| [Weighted cost of capital (WACC)](#wacc) | E/(D+E) x (5.18% + (0.67 x beta + 0.33) x 5%) + D/(D+E) x (5.18% + spread) x (1 - 21%); spread 1.3% / 2% / 3% for net debt / EBITDA < 3 / < 5 / higher | none | derived |
| [DCF fair value](#dcf-fair-value) | (fcff_before_growth x 1.025 / (wacc - 2.5%) - net_debt) / shares | none | derived |
| [Price against DCF fair value](#price-vs-fair-value) | price / dcf_fair_value - 1 | lower | derived |
| [Entry price at target P/E](#entry-price) | target_pe x eps_adj_ttm | none | derived |
| [Price against own cheap price](#price-vs-cheap) | price / (min(25th percentile of own 10-year P/E, sector median P/E) x eps) - 1 | lower | core |

## Named sets

- **proposed** (16): `cash_to_short_term_debt`, `cash_to_long_term_debt`, `net_debt_to_ebitda`, `interest_cover`, `net_margin`, `revenue_growth_median`, `eps_growth_median`, `ocf_growth_median`, `piotroski_f`, `altman_z`, `lynch_category`, `eps_adj_ttm`, `pe_adj`, `pe_vs_own_median`, `fcf_yield`, `price_vs_cheap`
- **absolute_values** (17): `price`, `market_cap`, `dcf_fair_value`, `fcff_before_growth`, `total_debt`, `net_debt`, `short_term_debt`, `long_term_debt`, `cash`, `revenue`, `ebitda`, `net_income`, `eps_ttm`, `eps_fwd`, `operating_cf`, `capex`, `free_cf`
- **strict_screen** (7): `market_cap`, `net_income`, `ebitda`, `cash_to_short_term_debt`, `cash_to_long_term_debt`, `net_debt_to_ebitda`, `interest_cover`
- **weighted_screen** (19): `cash_to_short_term_debt`, `cash_to_long_term_debt`, `net_debt_to_ebitda`, `interest_cover`, `net_margin`, `margin_change_avg`, `margin_change_median`, `ocf_growth_avg`, `ocf_growth_median`, `cash_growth_avg`, `cash_growth_median`, `price_vs_fair_value`, `pe_rel`, `ev_rel`, `pe_change_expected`, `revenue_growth_avg`, `revenue_growth_median`, `eps_growth_avg`, `eps_growth_median`
- **stage1** (24): `cash_to_short_term_debt`, `cash_to_long_term_debt`, `cash_to_total_debt`, `net_debt_to_ebitda`, `net_debt_to_avg_ebitda`, `interest_cover`, `debt_to_equity`, `net_cash_to_market_cap`, `roe`, `revenue_growth_median`, `eps_growth_median`, `eps_cagr_3y`, `eps_vs_5y_peak`, `loss_now`, `no_profit_5y`, `eps_big_drops_10y`, `eps_avg_10y`, `recession_eps_change`, `dividend_years_10y`, `payout_ratio`, `price_to_book`, `piotroski_f`, `altman_z`, `lynch_category`
- **watchlist** (6): `price`, `eps_adj_ttm`, `pe_adj`, `pe_median_10y`, `pe_vs_own_median`, `entry_price`

## Left out

- **technicals**: RSI, 50- and 200-day averages, 52-week range, one-year performance (Stage 2 timing only)
- **analyst**: Analyst target upside and rating (sector.py analyst_upside, analyst_view; TradingView Recommend.All)
- **market**: Beta (used inside WACC), indices, sector breadth (market report)

## Detail

### Size and price

<a id="price"></a>
#### Share price (`price`)

Last closing price.

- **Formula:** close
- **Unit:** $; **better:** none; **period:** now
- **Source:** sector: `price`; stage1: `close`; watchlist: `price`; yahoo: `regularMarketPrice`; tradingview: `close`
- **Used in:** absolute values; watch list; screener
- **Example (BSX, 2026-10-26):** $45.58 = Yahoo close
- **Vector:** context

<a id="market-cap"></a>
#### Market value (`market_cap`)

What the stock market values all the shares at.

- **Formula:** price x shares outstanding
- **Unit:** $bn; **better:** none; **period:** now
- **Source:** sector: `market_cap`; stage1: `cap_usd_bn`; tradingview: `market_cap_basic`; yahoo: `marketCap`
- **Used in:** absolute values; strict screen (>= $1bn); screener (>= $1bn)
- **Example (BSX, 2026-10-26):** $66.1bn = $45.58 x 1.449bn shares
- **Vector:** context
- **Note:** Foreign filers are converted to US dollars at today's exchange rate (ECB in the screener).

<a id="enterprise-value"></a>
#### Enterprise value (`enterprise_value`)

Price of the whole business: the shares plus the debt, less the cash.

- **Formula:** market_cap + net_debt
- **Unit:** $bn; **better:** none; **period:** now
- **Source:** tradingview: `enterprise_value_fq`
- **Used in:** EV / EBITDA; DCF (equity = enterprise value - net debt)
- **Example (BSX, 2026-10-26):** $78.1bn = 66.06 + 12.085
- **Vector:** context

### Balance sheet (absolute)

<a id="total-debt"></a>
#### Total debt (`total_debt`)

All borrowings, short and long term, including leases.

- **Formula:** short_term_debt + long_term_debt
- **Unit:** $bn; **better:** lower; **period:** fq
- **Source:** sector: `total_debt`; stage1: `total_debt_usd_bn`; tradingview: `total_debt_fq`; yahoo: `Total Debt`; sec: `LongTermDebt + DebtCurrent (+ ShortTermBorrowings)`
- **Used in:** absolute values; debt / equity; WACC
- **Example (BSX, 2026-09-30):** $12.6bn = 1.709 short-term + 10.915 long-term
- **Vector:** candidate
- **Note:** Includes lease liabilities since 2019 (ASC 842 / IFRS 16), which makes older debt figures look lower. BSX will add about $11bn for Penumbra.

<a id="short-term-debt"></a>
#### Short-term debt (`short_term_debt`)

Debt due within a year, including the current part of long-term debt.

- **Formula:** current debt + current lease liabilities; if blank, total_debt - long_term_debt
- **Unit:** $bn; **better:** lower; **period:** fq
- **Source:** sector: `short_term_debt`; stage1: `short_term_debt_usd_bn`; tradingview: `short_term_debt_fq`; yahoo: `Current Debt And Capital Lease Obligation`; sec: `DebtCurrent / LongTermDebtCurrent + ShortTermBorrowings`
- **Used in:** absolute values; cash / short-term debt
- **Example (BSX, 2026-09-30):** $1.71bn = balance sheet, current debt
- **Vector:** candidate

<a id="long-term-debt"></a>
#### Long-term debt (`long_term_debt`)

Debt due after more than a year.

- **Formula:** non-current debt + non-current lease liabilities
- **Unit:** $bn; **better:** lower; **period:** fq
- **Source:** sector: `long_term_debt`; stage1: `long_term_debt_usd_bn`; tradingview: `long_term_debt_fq`; yahoo: `Long Term Debt And Capital Lease Obligation`; sec: `LongTermDebtNoncurrent`
- **Used in:** absolute values; cash / long-term debt
- **Example (BSX, 2026-09-30):** $10.9bn = balance sheet, long-term debt
- **Vector:** candidate

<a id="cash"></a>
#### Cash and short-term investments (`cash`)

Cash, cash equivalents and short-term investments.

- **Formula:** cash and equivalents + short-term investments
- **Unit:** $bn; **better:** higher; **period:** fq
- **Source:** sector: `cash`; stage1: `cash_usd_bn`; tradingview: `cash_n_short_term_invest_fq`; yahoo: `Cash Cash Equivalents And Short Term Investments`; sec: `CashAndCashEquivalentsAtCarryingValue`
- **Used in:** absolute values; every cash-against-debt rule
- **Example (BSX, 2026-09-30):** $0.539bn = Yahoo; TradingView has 0.648
- **Vector:** candidate
- **Note:** Yahoo and TradingView differ by what they count as short-term investments; SEC's tag is cash only.

<a id="net-debt"></a>
#### Net debt (`net_debt`)

Debt left after paying off what cash can. Negative = net cash.

- **Formula:** total_debt - cash
- **Unit:** $bn; **better:** lower; **period:** fq
- **Source:** sector: `net_debt`; stage1: `net_debt_usd_bn`; tradingview: `net_debt_fq`
- **Used in:** absolute values; net debt / EBITDA; DCF
- **Example (BSX, 2026-09-30):** $12.1bn = 12.624 - 0.539. BKNG: 20.694 - 17.508 = 3.19
- **Vector:** candidate

<a id="book-equity"></a>
#### Shareholders' equity (book value) (`book_equity`)

Assets less liabilities on the balance sheet.

- **Formula:** total assets - total liabilities
- **Unit:** $bn; **better:** higher; **period:** fq
- **Source:** tradingview: `total_equity_fq`; yahoo: `Stockholders Equity`; sec: `StockholdersEquity`
- **Used in:** debt / equity; price / book; Lynch asset play; ROE
- **Example (BSX, 2026-09-30):** $25.2bn = TradingView. BKNG: -10.78 (buybacks larger than its retained profits)
- **Vector:** candidate
- **Note:** Negative for heavy buyers of their own shares (BKNG), which makes debt / equity and ROE meaningless; Stage 1 then uses net debt / EBITDA <= 2x instead.

### Income statement (absolute)

<a id="revenue"></a>
#### Revenue (`revenue`)

Sales over the last 12 months.

- **Formula:** sum of the last 4 quarters' revenue
- **Unit:** $bn; **better:** higher; **period:** ttm
- **Source:** sector: `revenue`; stage1: `revenue_usd_bn`; tradingview: `total_revenue_ttm`; yahoo: `Total Revenue`; sec: `Revenues / RevenueFromContractWithCustomerExcludingAssessedTax`
- **Used in:** absolute values; net margin; price / sales
- **Example (BSX, 2026-09-30):** $21bn = Q4 2025 to Q3 2026
- **Vector:** context

<a id="ebitda"></a>
#### EBITDA (`ebitda`)

Earnings before interest, tax, depreciation and amortization: operating cash earnings, before paying lenders or replacing assets.

- **Formula:** operating income + depreciation and amortization
- **Unit:** $bn; **better:** higher; **period:** ttm
- **Source:** sector: `ebitda`; stage1: `ebitda_usd_bn`; tradingview: `ebitda_ttm`; yahoo: `EBITDA`; sec: `OperatingIncomeLoss + DepreciationDepletionAndAmortization`
- **Used in:** absolute values; net debt / EBITDA; interest cover; EV / EBITDA
- **Example (BSX, 2026-09-30):** $5.64bn = Yahoo; TradingView 5.991
- **Vector:** context
- **Note:** Yahoo and TradingView differ by how they treat one-offs (BSX: 5.64 vs 5.99).

<a id="net-income"></a>
#### Net income (`net_income`)

Profit after everything, attributable to shareholders (GAAP).

- **Formula:** sum of the last 4 quarters' net income
- **Unit:** $bn; **better:** higher; **period:** ttm
- **Source:** sector: `net_income`; stage1: `net_income_usd_bn`; tradingview: `net_income_ttm`; yahoo: `Net Income`; sec: `NetIncomeLoss`
- **Used in:** absolute values; strict screen (profitable); net margin
- **Example (BSX, 2026-09-30):** $3.67bn = Q4 2025 to Q3 2026
- **Vector:** context

<a id="interest-expense"></a>
#### Interest expense (`interest_expense`)

What the company pays its lenders in a year.

- **Formula:** sum of the last 4 quarters' interest expense
- **Unit:** $bn; **better:** lower; **period:** ttm
- **Source:** yahoo: `Interest Expense`; sec: `InterestExpense`
- **Used in:** interest cover; DCF (after-tax interest added back)
- **Example (BSX, 2026-09-30):** $0.363bn = EBITDA 5.637 / interest cover 15.53
- **Vector:** candidate

<a id="d-and-a"></a>
#### Depreciation and amortization (`d_and_a`)

The yearly cost of wearing out assets and writing off acquired intangibles.

- **Formula:** from the cash-flow statement
- **Unit:** $bn; **better:** none; **period:** ttm
- **Source:** yahoo: `Depreciation And Amortization`; sec: `DepreciationDepletionAndAmortization`
- **Used in:** standard DCF (stands in for maintenance capex)
- **Example (BSX, 2026-09-30):** $1.41bn = 4.529 OCF + 0.363 x 0.79 - 3.403 DCF base
- **Vector:** context

<a id="eps-ttm"></a>
#### EPS, GAAP diluted (`eps_ttm`)

Net income per share, after counting options and convertibles.

- **Formula:** net_income / diluted shares
- **Unit:** $; **better:** higher; **period:** ttm
- **Source:** sector: `eps_ttm`; stage1: `eps`; tradingview: `earnings_per_share_diluted_ttm`; yahoo: `trailingEps`; sec: `EarningsPerShareDiluted`
- **Used in:** absolute values; trailing P/E; screener P/E history; Lynch categories
- **Example (BSX, 2026-09-30):** $2.47 = 3.675bn / about 1.49bn diluted shares
- **Vector:** candidate
- **Note:** Includes amortization and one-offs, so it understates acquisitive companies like BSX (adjusted EPS $3.21).

<a id="eps-adj-ttm"></a>
#### EPS, adjusted (`eps_adj_ttm`)

EPS without amortization of acquired intangibles and one-offs, on the same basis as analysts' estimates. Babak's 'true' EPS.

- **Formula:** sum of the last 4 quarters' reported (adjusted) EPS, with eps_override corrections
- **Unit:** $; **better:** higher; **period:** ttm
- **Source:** watchlist: `eps_adj_ttm`; yahoo: `earnings_dates: Reported EPS`
- **Used in:** watch list: own-history P/E and entry price; screener Stage 2 (top stocks)
- **Example (BSX, 2026-09-30):** $3.21 = sum of the last 4 reported quarters
- **Vector:** core
- **Note:** Company-defined, so not identical across companies. One-offs Yahoo still includes are fixed by hand in config/watchlist.toml (NFLX).

<a id="eps-fwd"></a>
#### Forward EPS (`eps_fwd`)

Analysts' average EPS estimate for the next fiscal year.

- **Formula:** consensus estimate
- **Unit:** $; **better:** higher; **period:** fy
- **Source:** sector: `eps_fwd`; tradingview: `earnings_per_share_forecast_next_fy`; yahoo: `forwardEps`
- **Used in:** absolute values; forward P/E; getting-cheaper test
- **Example (BSX, 2026-10-26):** $3.38 = Yahoo consensus, adjusted basis
- **Vector:** candidate
- **Note:** Not from the statements: an estimate. Keep or drop is an open choice.

### Cash flow (absolute)

<a id="operating-cf"></a>
#### Operating cash flow (`operating_cf`)

Cash the business brought in from operations, after tax and interest, before investing.

- **Formula:** net income + non-cash charges +/- working-capital changes
- **Unit:** $bn; **better:** higher; **period:** ttm
- **Source:** sector: `operating_cf`; stage1: `ocf_usd_bn`; tradingview: `cash_f_operating_activities_ttm`; yahoo: `Operating Cash Flow`; sec: `NetCashProvidedByUsedInOperatingActivities`
- **Used in:** absolute values; turnaround and asset-play rules (positive OCF); DCF
- **Example (BSX, 2026-09-30):** $4.53bn = Q4 2025 to Q3 2026
- **Vector:** context

<a id="capex"></a>
#### Capital expenditure (`capex`)

Cash spent on property, plant and equipment (negative number = spent).

- **Formula:** purchases of property, plant and equipment
- **Unit:** $bn; **better:** none; **period:** ttm
- **Source:** sector: `capex`; stage1: `capex_usd_bn`; tradingview: `capital_expenditures_ttm`; yahoo: `Capital Expenditure`; sec: `PaymentsToAcquirePropertyPlantAndEquipment`
- **Used in:** absolute values; free cash flow
- **Example (BSX, 2026-09-30):** $-2.72bn = Yahoo; TradingView -0.904
- **Vector:** context
- **Note:** Yahoo's capex can include acquisitions and stakes (BSX: -2.72 vs -0.90 on TradingView and SEC). Check SEC.

<a id="free-cf"></a>
#### Free cash flow (`free_cf`)

Cash left after keeping the business going and growing it: what can pay debt, dividends and buybacks.

- **Formula:** operating_cf + capex
- **Unit:** $bn; **better:** higher; **period:** ttm
- **Source:** sector: `free_cf`; stage1: `fcf_usd_bn`; tradingview: `free_cash_flow_ttm`
- **Used in:** absolute values; FCF yield
- **Example (BSX, 2026-09-30):** $1.81bn = 4.529 - 2.723 (Yahoo); 3.625 on TradingView
- **Vector:** context

<a id="fcff-before-growth"></a>
#### Cash flow before growth (DCF base) (`fcff_before_growth`)

Cash the whole firm earns before growth investment and before paying lenders: the standard DCF's starting cash flow.

- **Formula:** operating_cf - d_and_a + interest_expense x (1 - 21% tax)
- **Unit:** $bn; **better:** higher; **period:** ttm
- **Source:** sector: `fcff_before_growth`
- **Used in:** absolute values; standard DCF
- **Example (BSX, 2026-09-30):** $3.4bn = 4.529 - 1.413 + 0.363 x 0.79
- **Vector:** candidate
- **Note:** Treats depreciation as maintenance capex, so all capex above it counts as growth.

### Debt and liquidity ratios

<a id="cash-to-short-term-debt"></a>
#### Cash / short-term debt (`cash_to_short_term_debt`)

Can today's cash pay what falls due this year? Babak's first must-have.

- **Formula:** cash / short_term_debt (no short-term debt = passes)
- **Unit:** x; **better:** higher; **period:** fq
- **Source:** sector: `cash_to_short_term_debt`; stage1: `cash_to_short_term_debt`
- **Used in:** strict screen (>= 1); weighted debt score; every Stage 1 rule set (>= 1)
- **Example (BSX, 2026-09-30):** 0.32x = 0.539 / 1.709: fails. BKNG: 17.5 / 2.0 = 8.8
- **Vector:** core
- **Clipped in the vector:** upper 50.00x

<a id="cash-plus-ocf-to-short-term-debt"></a>
#### (Cash + operating cash flow) / short-term debt (`cash_plus_ocf_to_short_term_debt`)

Same test, counting a year's operating cash flow as well as cash on hand.

- **Formula:** (cash + max(operating_cf, 0)) / short_term_debt
- **Unit:** x; **better:** higher; **period:** fq
- **Source:** sector: `cash_plus_ocf_to_short_term_debt`
- **Used in:** sector table (shown, not a rule)
- **Example (BSX, 2026-09-30):** 2.97x = (0.539 + 4.529) / 1.709
- **Vector:** candidate
- **Clipped in the vector:** upper 50.00x
- **Note:** Open choice: a fairer version of the first must-have for companies that keep little cash (BSX passes this, fails the strict one).

<a id="cash-to-long-term-debt"></a>
#### Cash / long-term debt (`cash_to_long_term_debt`)

Is there a cash cushion against long-term debt? Babak's second must-have.

- **Formula:** cash / long_term_debt
- **Unit:** x; **better:** higher; **period:** fq
- **Source:** sector: `cash_to_long_term_debt`; stage1: `cash_to_long_term_debt`
- **Used in:** strict screen (>= 5%); weighted debt score; Stage 1 slow grower, stalwart, cyclical (>= 5%)
- **Example (BSX, 2026-09-30):** 0.05x = 0.539 / 10.915: just under 5% (TradingView's 0.648 gives 5.9%)
- **Vector:** core
- **Clipped in the vector:** upper 50.00x

<a id="cash-to-total-debt"></a>
#### Cash / total debt (`cash_to_total_debt`)

Share of all debt cash could repay today.

- **Formula:** cash / total_debt
- **Unit:** x; **better:** higher; **period:** fq
- **Source:** stage1: `cash_to_total_debt`
- **Used in:** Stage 1 turnaround (>= 25%)
- **Example (BSX, 2026-09-30):** 0.05x = 0.648 / 12.624 (TradingView)
- **Vector:** candidate
- **Clipped in the vector:** upper 50.00x
- **Note:** Overlaps cash / short-term and cash / long-term debt.

<a id="net-debt-to-ebitda"></a>
#### Net debt / EBITDA (`net_debt_to_ebitda`)

Years of operating earnings needed to repay the net debt. The standard leverage measure.

- **Formula:** net_debt / ebitda (net cash always passes; EBITDA <= 0 fails)
- **Unit:** x; **better:** lower; **period:** ttm
- **Source:** sector: `net_debt_to_ebitda`; stage1: `net_debt_to_ebitda`
- **Used in:** strict screen (<= 4.5x); weighted debt score; Stage 1 slow grower, stalwart (<= 4.5x), REITs (<= 7x); debt_to_ebitda.py history
- **Example (BSX, 2026-09-30):** 2.14x = 12.085 / 5.637. BKNG: 3.19 / 10.65 = 0.30
- **Vector:** core
- **Clipped in the vector:** lower 0.00x
- **Note:** Negative when net cash; clipped at 0 for the vector (open choice 6, default until Babak decides), so every net-cash company counts the same.

<a id="net-debt-to-avg-ebitda"></a>
#### Net debt / 10-year average EBITDA (`net_debt_to_avg_ebitda`)

Leverage against earnings over a whole cycle rather than today's point in it.

- **Formula:** net_debt / mean(EBITDA, last 10 fiscal years; needs 5)
- **Unit:** x; **better:** lower; **period:** history
- **Source:** stage1: `net_debt_to_avg_ebitda`
- **Used in:** Stage 1 cyclical (<= 2.5x)
- **Example (BSX, 2026-09-30):** 3.97x = 11.976 / 3.02 average 2016-2025 EBITDA
- **Vector:** candidate
- **Clipped in the vector:** lower 0.00x
- **Note:** For growing companies it overstates leverage (BSX 3.97x against 2.0x on today's EBITDA).

<a id="interest-cover"></a>
#### Interest cover (EBITDA / interest) (`interest_cover`)

How many times operating earnings cover the interest bill.

- **Formula:** ebitda / interest_expense (net cash always passes)
- **Unit:** x; **better:** higher; **period:** ttm
- **Source:** sector: `ebitda_to_interest`; stage1: `interest_cover`; tradingview: `ebitda_interst_cover_ttm`
- **Used in:** strict screen (>= 4x); weighted debt score; Stage 1 (>= 4x; REITs >= 2.5x)
- **Example (BSX, 2026-09-30):** 15.53x = 5.637 / 0.363 (TradingView 18.3)
- **Vector:** core
- **Clipped in the vector:** upper 50.00x

<a id="debt-to-equity"></a>
#### Debt / equity (`debt_to_equity`)

Borrowed money against owners' money. Lynch's balance-sheet test for fast growers.

- **Formula:** total_debt / book_equity
- **Unit:** x; **better:** lower; **period:** fq
- **Source:** sector: `debt_to_equity`; stage1: `debt_to_equity`; tradingview: `debt_to_equity_fq`
- **Used in:** Stage 1 fast grower and asset play (<= 1.0)
- **Example (BSX, 2026-09-30):** 0.51x = 12.624 / 24.93. BKNG: undefined (negative equity)
- **Vector:** candidate
- **Note:** Lynch's 'normal' was 0.33 before leases counted as debt; Stage 1 uses 1.0. Meaningless with negative equity.

<a id="net-cash-to-market-cap"></a>
#### Net cash / market value (`net_cash_to_market_cap`)

Part of the price covered by net cash. Lynch's asset-play signal.

- **Formula:** -net_debt / market_cap
- **Unit:** fraction; **better:** higher; **period:** fq
- **Source:** stage1: `net_cash_to_cap`
- **Used in:** Lynch category: asset play (> 30%)
- **Example (BSX, 2026-10-27):** -18.3% = -11.976 / 65.41 (net debt, so negative)
- **Vector:** candidate

### Profitability

<a id="net-margin"></a>
#### Net margin (`net_margin`)

Profit kept from each dollar of sales.

- **Formula:** net_income / revenue
- **Unit:** fraction; **better:** higher; **period:** ttm
- **Source:** sector: `net_margin`; tradingview: `net_margin_ttm`
- **Used in:** weighted quality score (weight 2)
- **Example (BSX, 2026-09-30):** +17.5% = 3.675 / 20.996
- **Vector:** core

<a id="net-margin-avg"></a>
#### Net margin, average of fiscal years (`net_margin_avg`)

Average yearly net margin over the fiscal years on record (Yahoo: 4).

- **Formula:** mean(net income / revenue per fiscal year)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `net_margin_avg`
- **Used in:** sector table
- **Example (BSX, FY2022-FY2025):** +10.5% = mean(5.5%, 11.2%, 11.1%, 14.4%)
- **Vector:** candidate

<a id="margin-change-avg"></a>
#### Net margin change, average (`margin_change_avg`)

Is the margin widening? Average yearly change in percentage points.

- **Formula:** mean(margin_y - margin_y-1)
- **Unit:** pp; **better:** higher; **period:** history
- **Source:** sector: `margin_change_avg`
- **Used in:** weighted quality score (weight 1)
- **Example (BSX, FY2022-FY2025):** +3.0 pp = mean(+5.7, -0.1, +3.3) pp = +3.0 pp a year
- **Vector:** candidate

<a id="margin-change-median"></a>
#### Net margin change, median (`margin_change_median`)

Median yearly change in net margin: the typical year, less swayed by one jump.

- **Formula:** median(margin_y - margin_y-1)
- **Unit:** pp; **better:** higher; **period:** history
- **Source:** sector: `margin_change_median`
- **Used in:** weighted quality score (weight 1)
- **Example (BSX, FY2022-FY2025):** +3.4 pp = median(+5.7, -0.1, +3.3) pp
- **Vector:** candidate

<a id="sector-net-margin"></a>
#### Sector median net margin (`sector_net_margin`)

Median 12-month net margin of every screened company in the same TradingView sector (sectors of 5 or more). The growth screener's margin floor when above 10%.

- **Formula:** median(net_margin) over the sector
- **Unit:** fraction; **better:** none; **period:** ttm
- **Source:** growth: `sector_net_margin`
- **Used in:** growth screener (net margin >= max(10%, sector median))
- **Example (BSX, 2026-10-31):** +14.4% = Health Technology, S&P 500 members
- **Vector:** derived

<a id="roe"></a>
#### Return on equity (`roe`)

Profit on the owners' money.

- **Formula:** net_income / average book_equity
- **Unit:** fraction; **better:** higher; **period:** ttm
- **Source:** stage1: `return_on_equity_fq`; tradingview: `return_on_equity_fq`
- **Used in:** Stage 1 banks and insurers (>= 8%)
- **Example (BSX, 2026-09-30):** +15.5% = 3.675 / about 23.7 average equity
- **Vector:** candidate
- **Note:** Flattered by debt and buybacks; undefined with negative equity (BKNG). Return on invested capital would avoid both: not yet used, candidate to add.

### Growth

<a id="revenue-growth-avg"></a>
#### Revenue growth, average year (`revenue_growth_avg`)

Average yearly revenue growth over the fiscal years on record.

- **Formula:** mean(revenue_y / revenue_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `revenue_growth_avg`
- **Used in:** weighted screen growth gate (> 0)
- **Example (BSX, FY2022-FY2025):** +16.6% = mean(+12.3%, +17.6%, +19.9%)
- **Vector:** candidate
- **Note:** sector.py uses Yahoo's 3-4 years; Stage 1 uses 5 years from TradingView. Open choice: which window.

<a id="revenue-growth-median"></a>
#### Revenue growth, median year (`revenue_growth_median`)

Median yearly revenue growth: the typical year.

- **Formula:** median(revenue_y / revenue_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `revenue_growth_median`; stage1: `revenue_growth_median`
- **Used in:** weighted screen growth gate (> 0); Stage 1 growth rule (> 0 over 5 years)
- **Example (BSX, FY2022-FY2025):** +17.6% = median(+12.3%, +17.6%, +19.9%); 5-year TradingView also 17.6%
- **Vector:** core

<a id="revenue-cagr-3y"></a>
#### Revenue growth, 3-year compound (`revenue_cagr_3y`)

Yearly growth rate that turns revenue 3 years ago into revenue now.

- **Formula:** (revenue_FY0 / revenue_FY-3) ^ (1/3) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `revenue_cagr_3y`
- **Used in:** sector table
- **Example (BSX, FY2022-FY2025):** +16.5% = (1.123 x 1.176 x 1.199) ^ (1/3) - 1
- **Vector:** candidate

<a id="revenue-growth-yoy"></a>
#### Revenue growth, latest quarter (`revenue_growth_yoy`)

Latest quarter's revenue against the same quarter a year before.

- **Formula:** revenue_Q / revenue_Q-4 - 1
- **Unit:** fraction; **better:** higher; **period:** ttm
- **Source:** sector: `revenue_growth_yoy`; yahoo: `revenueGrowth`
- **Used in:** sector table
- **Example (BSX, Q3 2026):** +7.5% = Yahoo
- **Vector:** candidate
- **Note:** Shows a slowdown before the yearly figures do (BSX 7.5% now vs 17.6% median).

<a id="ebitda-cagr-3y"></a>
#### EBITDA growth, 3-year compound (`ebitda_cagr_3y`)

Compound yearly EBITDA growth over 3 fiscal years.

- **Formula:** (ebitda_FY0 / ebitda_FY-3) ^ (1/3) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `ebitda_cagr_3y`
- **Used in:** sector table
- **Example (BSX, FY2022-FY2025):** +22.9% = Yahoo yearly EBITDA
- **Vector:** candidate

<a id="eps-growth-avg"></a>
#### EPS growth, average year (`eps_growth_avg`)

Average yearly GAAP EPS growth.

- **Formula:** mean(eps_y / eps_y-1 - 1), years with eps_y-1 > 0
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `eps_growth_avg`
- **Used in:** weighted screen growth gate (> 0)
- **Example (BSX, FY2022-FY2025):** +69.9% = mean(+137.8%, +16.8%, +55.2%)
- **Vector:** candidate
- **Note:** One recovery year dominates the average (BSX 2023). The median is steadier.

<a id="eps-growth-median"></a>
#### EPS growth, median year (`eps_growth_median`)

Median yearly GAAP EPS growth. Sorts Lynch's growers: >= 20% fast, >= 8% stalwart, else slow.

- **Formula:** median(eps_y / eps_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `eps_growth_median`; stage1: `eps_growth_median`
- **Used in:** weighted screen growth gate; Stage 1 growth rule; Lynch category
- **Example (BSX, FY2020-FY2025):** +35.9% = TradingView 5 years (2021 skipped: 2020 was a loss); Yahoo 3 years gives 55%
- **Vector:** core

<a id="eps-cagr-3y"></a>
#### EPS growth, 3-year compound (`eps_cagr_3y`)

Compound yearly GAAP EPS growth over the last 3 fiscal years. Lynch: a fast grower must still grow fast now.

- **Formula:** (eps_FY0 / eps_FY-3) ^ (1/3) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `eps_cagr_3y`; stage1: `eps_growth_3y`
- **Used in:** Stage 1 fast grower (>= 20%); sector table
- **Example (BSX, FY2022-FY2025):** +63.2% = (1.939 / 0.446) ^ (1/3) - 1
- **Vector:** candidate

<a id="revenue-cagr-5y"></a>
#### Revenue growth, 5-year compound (`revenue_cagr_5y`)

Yearly growth rate that turns revenue 5 fiscal years ago into revenue in the latest fiscal year.

- **Formula:** (revenue_FY0 / revenue_FY-5) ^ (1/5) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** growth: `revenue_cagr`; tradingview: `total_revenue_fy_h`
- **Used in:** growth screener (> 0)
- **Example (BSX, FY2020-FY2025):** +15.2% = (20.074 / 9.913) ^ (1/5) - 1 (TradingView, 2026-10-31)
- **Vector:** candidate

<a id="revenue-up-years-5y"></a>
#### Years revenue rose, of the last 5 (`revenue_up_years_5y`)

In how many of the last 5 fiscal years revenue was above the year before: how steady the growth is.

- **Formula:** count(revenue_y > revenue_y-1, last 5 years)
- **Unit:** count; **better:** higher; **period:** history
- **Source:** growth: `revenue_up_years`; tradingview: `total_revenue_fy_h`
- **Used in:** growth screener (>= 4)
- **Example (BSX, FY2020-FY2025):** 5 = 9.9, 11.9, 12.7, 14.2, 16.7, 20.1 ($bn): up every year
- **Vector:** candidate

<a id="net-income-cagr-5y"></a>
#### Net income growth, 5-year compound (`net_income_cagr_5y`)

Yearly growth rate that turns net income 5 fiscal years ago into net income in the latest fiscal year. Blank when either end is a loss.

- **Formula:** (net_income_FY0 / net_income_FY-5) ^ (1/5) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** growth: `net_income_cagr`; tradingview: `net_income_fy_h`
- **Used in:** growth screener (> 0)
- **Example (INTU, FY2021-FY2026):** +17.2% = (4.566 / 2.062) ^ (1/5) - 1 (TradingView, 2026-10-31)
- **Vector:** candidate
- **Note:** BSX is blank: a loss in FY2020 (-$0.08bn).

<a id="net-income-up-years-5y"></a>
#### Years net income rose, of the last 5 (`net_income_up_years_5y`)

In how many of the last 5 fiscal years net income was above the year before.

- **Formula:** count(net_income_y > net_income_y-1, last 5 years)
- **Unit:** count; **better:** higher; **period:** history
- **Source:** growth: `net_income_up_years`; tradingview: `net_income_fy_h`
- **Used in:** growth screener (>= 3)
- **Example (INTU, FY2021-FY2026):** 5 = 2.06, 2.07, 2.38, 2.96, 3.87, 4.57 ($bn)
- **Vector:** candidate

<a id="eps-cagr-5y"></a>
#### EPS growth, 5-year compound (`eps_cagr_5y`)

Compound yearly GAAP diluted EPS growth over the last 5 fiscal years. Above net income growth when the company buys back shares.

- **Formula:** (eps_FY0 / eps_FY-5) ^ (1/5) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** growth: `eps_cagr`; tradingview: `earnings_per_share_diluted_fy_h`
- **Used in:** growth screener (> 0)
- **Example (INTU, FY2021-FY2026):** +16.9% = (16.48 / 7.55) ^ (1/5) - 1
- **Vector:** candidate

<a id="earnings-growth-yoy"></a>
#### Earnings growth, latest quarter (`earnings_growth_yoy`)

Latest quarter's earnings against the same quarter a year before.

- **Formula:** eps_Q / eps_Q-4 - 1
- **Unit:** fraction; **better:** higher; **period:** ttm
- **Source:** sector: `earnings_growth_yoy`; yahoo: `earningsGrowth`
- **Used in:** sector table
- **Example (BSX, Q3 2026):** +15.1% = Yahoo
- **Vector:** candidate

<a id="ocf-growth-avg"></a>
#### Operating cash flow growth, average year (`ocf_growth_avg`)

Average yearly growth in operating cash flow.

- **Formula:** mean(ocf_y / ocf_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `ocf_growth_avg`
- **Used in:** weighted quality score (weight 1)
- **Example (BSX, FY2022-FY2025):** +44.4% = mean(+64.0%, +37.2%, +32.0%)
- **Vector:** candidate

<a id="ocf-growth-median"></a>
#### Operating cash flow growth, median year (`ocf_growth_median`)

Median yearly growth in operating cash flow.

- **Formula:** median(ocf_y / ocf_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `ocf_growth_median`
- **Used in:** weighted quality score (weight 1)
- **Example (BSX, FY2022-FY2025):** +37.2% = median(+64.0%, +37.2%, +32.0%)
- **Vector:** core

<a id="cash-growth-avg"></a>
#### Cash balance growth, average year (`cash_growth_avg`)

Average yearly change in the cash balance.

- **Formula:** mean(cash_y / cash_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `cash_growth_avg`
- **Used in:** weighted quality score (weight 0.5)
- **Example (BSX, FY2022-FY2025):** +105.2% = mean(-6.8%, -52.1%, +374.6%)
- **Vector:** context
- **Note:** Cash swings with deals and debt raises (BSX +375% in 2025), so it is noisy. Context only, not for the vector (open choice 9, default until Babak decides); kept because the weighted screen uses it.

<a id="cash-growth-median"></a>
#### Cash balance growth, median year (`cash_growth_median`)

Median yearly change in the cash balance.

- **Formula:** median(cash_y / cash_y-1 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** sector: `cash_growth_median`
- **Used in:** weighted quality score (weight 0.5)
- **Example (BSX, FY2022-FY2025):** -6.8% = median(-6.8%, -52.1%, +374.6%)
- **Vector:** context
- **Note:** Context only, not for the vector, like the average (open choice 9).

### Earnings history (Lynch inputs)

<a id="eps-vs-5y-peak"></a>
#### EPS against its 5-year peak (`eps_vs_5y_peak`)

How far today's EPS is below (or above) the best of the last 5 fiscal years. Below -50% = Lynch turnaround.

- **Formula:** max(eps_ttm, eps_FY0) / max(eps, last 5 FY) - 1
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** stage1: `eps_vs_5y_peak`
- **Used in:** Lynch category: turnaround
- **Example (BSX, 2026-09-30):** +27.2% = 2.466 / 1.939 - 1: 27% above the old peak
- **Vector:** candidate

<a id="loss-now"></a>
#### Losing money now (`loss_now`)

EPS of the last 12 months or of the latest fiscal year is zero or below.

- **Formula:** eps_ttm <= 0 or eps_FY0 <= 0
- **Unit:** bool; **better:** lower; **period:** ttm
- **Source:** stage1: `loss_now`
- **Used in:** Lynch category: turnaround
- **Example (BSX, 2026-09-30):** False = 2.47 > 0 and 1.94 > 0
- **Vector:** candidate

<a id="no-profit-5y"></a>
#### No profit in 5 years (`no_profit_5y`)

Loss in every one of the last 5 fiscal years. Not a Lynch category: Stage 1 fails these.

- **Formula:** max(eps, last 5 FY) <= 0
- **Unit:** bool; **better:** lower; **period:** history
- **Source:** stage1: `no_profit_5y`
- **Used in:** Stage 1 (fail)
- **Example (BSX, FY2021-FY2025):** False = best year 1.94
- **Vector:** candidate

<a id="eps-big-drops-10y"></a>
#### Big EPS drops in 10 years (`eps_big_drops_10y`)

Years in the last 10 when EPS fell by more than 30%. 3 or more = cyclical by history (unless a fast grower).

- **Formula:** count(eps_y / eps_y-1 - 1 < -30%, eps_y-1 > 0)
- **Unit:** count; **better:** lower; **period:** history
- **Source:** stage1: `eps_big_drops_10y`
- **Used in:** Lynch category: cyclical
- **Example (BSX, FY2015-FY2025):** 3 = 2017 (-70%), 2020 (a loss after 2019's one-off tax gain), 2022 (-35%)
- **Vector:** candidate
- **Note:** GAAP one-offs count as drops (BSX's 2019 tax gain), so this flags lumpy accounting as well as real cycles.

<a id="eps-avg-10y"></a>
#### Average EPS over 10 years (`eps_avg_10y`)

Mean diluted EPS over the last 10 fiscal years (needs 5). For a cyclical, profit over the cycle.

- **Formula:** mean(eps, last 10 FY)
- **Unit:** $; **better:** higher; **period:** history
- **Source:** stage1: `eps_avg_10y`
- **Used in:** Stage 1 cyclical (> 0)
- **Example (BSX, FY2016-FY2025):** $1.02 = mean of 1.94, 1.25, 1.07, 0.45, 0.69, -0.08, 3.33, 1.19, 0.07, 0.25
- **Vector:** candidate
- **Note:** In dollars per share, so it doesn't compare across stocks; use eps_ttm / eps_avg_10y if it goes in the vector.

<a id="recession-eps-change"></a>
#### EPS change in recessions (`recession_eps_change`)

Worst yearly EPS change in the 2009 and 2020 fiscal years. Lynch: stalwarts hold up in recessions.

- **Formula:** min(eps_2009 / eps_2008 - 1, eps_2020 / eps_2019 - 1)
- **Unit:** fraction; **better:** higher; **period:** history
- **Source:** stage1: `recession_eps_change`
- **Used in:** Stage 1 stalwart (no worse than -30%)
- **Example (BSX, FY2020):** -102.4% = -0.081 / 3.332 - 1 (2019 had a one-off tax gain)
- **Vector:** candidate

<a id="dividend-years-10y"></a>
#### Years with a dividend, of 10 (`dividend_years_10y`)

How many of the last 10 fiscal years paid a dividend.

- **Formula:** count(dps > 0, last 10 FY)
- **Unit:** count; **better:** higher; **period:** history
- **Source:** stage1: `dividend_years_10y`
- **Used in:** Stage 1 slow grower (10 of 10; none at all passes)
- **Example (BSX, FY2016-FY2025):** 0 = no dividend. BKNG: 2 (since 2024)
- **Vector:** candidate

<a id="payout-ratio"></a>
#### Dividend payout ratio (`payout_ratio`)

Share of earnings paid out as dividends. Lynch: leaves a cushion in hard times.

- **Formula:** dividends per share / eps_ttm
- **Unit:** fraction; **better:** lower; **period:** ttm
- **Source:** stage1: `dividend_payout_ratio_ttm`; tradingview: `dividend_payout_ratio_ttm`
- **Used in:** Stage 1 slow grower (<= 80%)
- **Example (BKNG, 2026-09-30):** +17.8% = TradingView (BSX pays none: 0)
- **Vector:** candidate

<a id="lynch-category"></a>
#### Lynch category (`lynch_category`)

Peter Lynch's six kinds of stock (One Up on Wall Street, ch. 7): slow grower, stalwart, fast grower, cyclical, turnaround, asset play; plus no_profit.

- **Formula:** tested in order: no_profit_5y; cyclical industry; turnaround (loss_now or eps_vs_5y_peak < -50%); cyclical history (eps_big_drops_10y >= 3, not fast); asset play (price/book < 1 or net cash > 30% of value); then eps_growth_median >= 20% fast, >= 8% stalwart, else slow
- **Unit:** category; **better:** none; **period:** history
- **Source:** stage1: `category`
- **Used in:** Stage 1: picks each company's rule set
- **Example (BSX, 2026-10-27):** fast_grower = EPS median growth 36% >= 20%; 3 big drops but fast growers are exempt
- **Vector:** core
- **Note:** A label, not a number: in the vector it would be one-hot (six 0/1 columns) or used to compare stocks only within a category (open choice).

### Quality scores

<a id="piotroski-f"></a>
#### Piotroski F-score (`piotroski_f`)

Nine pass/fail tests of financial strength, one point each (Piotroski 2000). Profit: net income > 0, OCF > 0, ROA up, OCF > net income. Balance sheet: long-term debt ratio down, current ratio up, no new shares. Efficiency: gross margin up, asset turnover up.

- **Formula:** sum of 9 binary tests, latest fiscal year against the one before
- **Unit:** score; **better:** higher; **period:** fy
- **Source:** stage1: `piotroski_f_score_ttm`; tradingview: `piotroski_f_score_ttm`
- **Used in:** Stage 1 (>= 5, all non-financial categories but cyclical, turnaround, asset play)
- **Example (BSX, 2026-10-27):** 8 = TradingView; BKNG 7
- **Vector:** core
- **Note:** Computed by TradingView; we don't recompute the nine parts. Recomputing from SEC filings is possible (open choice).

<a id="altman-z"></a>
#### Altman Z-score (`altman_z`)

Bankruptcy-risk score (Altman 1968). Below 1.81 = distress zone, 1.81-2.99 grey, above 2.99 safe.

- **Formula:** 1.2 x working capital/assets + 1.4 x retained earnings/assets + 3.3 x EBIT/assets + 0.6 x market value/liabilities + 1.0 x sales/assets
- **Unit:** score; **better:** higher; **period:** fq
- **Source:** stage1: `altman_z_score_ttm`; tradingview: `altman_z_score_ttm`
- **Used in:** Stage 1 (>= 1.8, not utilities, banks, insurers or REITs)
- **Example (BSX, 2026-10-27):** 2.93 = TradingView: grey zone, just under safe. BKNG 6.17
- **Vector:** core
- **Note:** Built for manufacturers; it penalizes asset-heavy and lease-heavy businesses.

<a id="debt-score"></a>
#### Weighted screen: debt score (`debt_score`)

Percentile (0-100) within the peer group, averaged over cash / short-term debt, cash / long-term debt, net debt / EBITDA and interest cover.

- **Formula:** mean(percentile ranks of the 4 debt ratios)
- **Unit:** score; **better:** higher; **period:** fq
- **Source:** sector: `debt_score`
- **Used in:** weighted screen (50% of the total)
- **Example (BSX, 2026-10-27):** 29.5 = against 9 medical-device peers (report 11)
- **Vector:** derived
- **Note:** Relative to whichever peers it is run on, so not a property of the stock. Built from the ratios above; the vector can take the ratios instead.

<a id="quality-score"></a>
#### Weighted screen: profitability and cash score (`quality_score`)

Weighted percentile of net margin (2), margin change avg and median (1 each), OCF growth avg and median (1 each), cash growth avg and median (0.5 each).

- **Formula:** weighted mean of percentile ranks
- **Unit:** score; **better:** higher; **period:** history
- **Source:** sector: `quality_score`
- **Used in:** weighted screen (25%)
- **Example (BSX, 2026-10-27):** 77 = against 9 medical-device peers (report 11)
- **Vector:** derived

<a id="cheap-score"></a>
#### Weighted screen: cheapness score (`cheap_score`)

Percentile of price vs DCF, P/E vs industry median, EV/EBITDA vs industry median and expected P/E change (lower = cheaper = higher score).

- **Formula:** mean(percentile ranks, reversed)
- **Unit:** score; **better:** higher; **period:** now
- **Source:** sector: `cheap_score`
- **Used in:** weighted screen (25%)
- **Example (BSX, 2026-10-27):** 80.6 = against 9 medical-device peers (report 11)
- **Vector:** derived

<a id="total-score"></a>
#### Weighted screen: total (`total_score`)

Babak's weighted score: debt 50%, profitability and cash 25%, cheapness 25%.

- **Formula:** 0.5 x debt_score + 0.25 x quality_score + 0.25 x cheap_score
- **Unit:** score; **better:** higher; **period:** now
- **Source:** sector: `total_score`
- **Used in:** weighted screen ranking
- **Example (BSX, 2026-10-27):** 54.1 = 0.5 x 29.5 + 0.25 x 77.0 + 0.25 x 80.6; 5th of 9 (report 11)
- **Vector:** derived

### Valuation (needs the price)

<a id="pe-ttm"></a>
#### P/E, trailing GAAP (`pe_ttm`)

Price against the last 12 months' GAAP EPS.

- **Formula:** price / eps_ttm
- **Unit:** x; **better:** lower; **period:** now
- **Source:** sector: `pe_ttm`; tradingview: `price_earnings_ttm`; yahoo: `trailingPE`
- **Used in:** peer screen; cheap score (vs industry median)
- **Example (BSX, 2026-10-26):** 18.45x = 45.58 / 2.47
- **Vector:** candidate

<a id="pe-adj"></a>
#### P/E, trailing adjusted (`pe_adj`)

Price against adjusted EPS: Babak's 'true' P/E.

- **Formula:** price / eps_adj_ttm
- **Unit:** x; **better:** lower; **period:** now
- **Source:** watchlist: `pe_adj`
- **Used in:** watch list; entry price
- **Example (BSX, 2026-10-27):** 14.02x = 45.02 / 3.21
- **Vector:** core

<a id="pe-fwd"></a>
#### P/E, forward (`pe_fwd`)

Price against next year's consensus EPS.

- **Formula:** price / eps_fwd
- **Unit:** x; **better:** lower; **period:** now
- **Source:** sector: `pe_fwd`; yahoo: `forwardPE`
- **Used in:** getting-cheaper test
- **Example (BSX, 2026-10-26):** 13.50x = 45.58 / 3.38
- **Vector:** candidate

<a id="pe-change-expected"></a>
#### Expected P/E change (`pe_change_expected`)

How much the P/E falls at today's price if next year's estimate is met.

- **Formula:** pe_fwd / pe_ttm - 1
- **Unit:** fraction; **better:** lower; **period:** now
- **Source:** sector: `pe_change_expected`
- **Used in:** cheap score; getting-cheaper test (<= -15%)
- **Example (BSX, 2026-10-26):** -26.8% = 13.50 / 18.45 - 1
- **Vector:** candidate
- **Note:** Mixes adjusted (forward) and GAAP (trailing) EPS, so it overstates the drop for acquisitive companies.

<a id="pe-median-10y"></a>
#### Own P/E, 10-year median (`pe_median_10y`)

Median of the stock's yearly P/E (average price / adjusted EPS) over 10 calendar years.

- **Formula:** median(avg price_y / adjusted eps_y, last 10 years)
- **Unit:** x; **better:** none; **period:** history
- **Source:** watchlist: `pe_median_10y`; stage2: `pe_median_10y`
- **Used in:** watch list; Stage 2
- **Example (BSX, 2016-2025):** 25.17x = watch list, adjusted EPS
- **Vector:** context

<a id="pe-vs-own-median"></a>
#### P/E against own 10-year median (`pe_vs_own_median`)

How cheap the stock is against its own history.

- **Formula:** pe_adj / pe_median_10y - 1
- **Unit:** fraction; **better:** lower; **period:** now
- **Source:** computed from the formula
- **Used in:** watch list (shown); panic-sell screen
- **Example (BSX, 2026-10-27):** -44.3% = 14.02 / 25.17 - 1
- **Vector:** core

<a id="pe-rel"></a>
#### P/E against industry median (`pe_rel`)

Trailing P/E against the median of its industry in the peer group.

- **Formula:** pe_ttm / median(pe_ttm, same industry) - 1
- **Unit:** fraction; **better:** lower; **period:** now
- **Source:** sector: `pe_rel`; stage2: `pe_vs_sector`
- **Used in:** strict and weighted screens (cheapness)
- **Example (BSX, 2026-10-26):** -34.2% = 18.45 / 28.04 Medical Devices median - 1
- **Vector:** derived

<a id="ev-to-ebitda"></a>
#### EV / EBITDA (`ev_to_ebitda`)

Price of the whole business against its operating earnings; unaffected by how it is financed.

- **Formula:** enterprise_value / ebitda
- **Unit:** x; **better:** lower; **period:** now
- **Source:** sector: `ev_to_ebitda`; tradingview: `enterprise_value_ebitda_ttm`
- **Used in:** peer screen; cheap score
- **Example (BSX, 2026-10-26):** 13.86x = 78.14 / 5.637
- **Vector:** candidate

<a id="ev-rel"></a>
#### EV / EBITDA against industry median (`ev_rel`)

EV / EBITDA against its industry's median.

- **Formula:** ev_to_ebitda / median(ev_to_ebitda, same industry) - 1
- **Unit:** fraction; **better:** lower; **period:** now
- **Source:** sector: `ev_rel`; stage2: `ev_ebitda_vs_sector`
- **Used in:** strict and weighted screens (cheapness)
- **Example (BSX, 2026-10-26):** -10.9% = 13.86 / 15.56 Medical Devices median - 1
- **Vector:** derived

<a id="price-to-sales"></a>
#### Price / sales (`price_to_sales`)

Market value against revenue.

- **Formula:** market_cap / revenue
- **Unit:** x; **better:** lower; **period:** now
- **Source:** sector: `price_to_sales`
- **Used in:** sector table
- **Example (BSX, 2026-10-26):** 3.15x = 66.06 / 20.996
- **Vector:** candidate

<a id="price-to-book"></a>
#### Price / book (`price_to_book`)

Market value against book equity.

- **Formula:** market_cap / book_equity
- **Unit:** x; **better:** lower; **period:** now
- **Source:** sector: `price_to_book`; tradingview: `price_book_fq`; yahoo: `priceToBook`
- **Used in:** Lynch category: asset play (< 1)
- **Example (BSX, 2026-10-26):** 2.65x = 66.06 / 24.93
- **Vector:** candidate

<a id="fcf-yield"></a>
#### Free cash flow yield (`fcf_yield`)

Free cash flow as a share of the market value: the cash return at today's price.

- **Formula:** free_cf / market_cap
- **Unit:** fraction; **better:** higher; **period:** now
- **Source:** sector: `fcf_yield`; stage2: `fcf_yield`
- **Used in:** sector table; Stage 2 (shown)
- **Example (BSX, 2026-10-26):** +2.7% = 1.806 / 66.06 (5.5% with TradingView's capex)
- **Vector:** core

<a id="dividend-yield"></a>
#### Dividend yield (`dividend_yield`)

Dividends over the last year against the price.

- **Formula:** dividends per share / price
- **Unit:** fraction; **better:** none; **period:** now
- **Source:** sector: `dividend_yield`; tradingview: `dividends_yield`
- **Used in:** sector table
- **Example (BSX, 2026-10-26):** +0.0% = no dividend
- **Vector:** candidate

<a id="wacc"></a>
#### Weighted cost of capital (WACC) (`wacc`)

Return investors require on the whole firm: the DCF discount rate.

- **Formula:** E/(D+E) x (5.18% + (0.67 x beta + 0.33) x 5%) + D/(D+E) x (5.18% + spread) x (1 - 21%); spread 1.3% / 2% / 3% for net debt / EBITDA < 3 / < 5 / higher
- **Unit:** fraction; **better:** none; **period:** now
- **Source:** sector: `wacc`
- **Used in:** standard DCF
- **Example (BSX, 2026-10-26):** +8.2% = beta 0.575; equity 66.06, debt 12.62
- **Vector:** derived

<a id="dcf-fair-value"></a>
#### DCF fair value (`dcf_fair_value`)

Value per share if the DCF base cash flow grows at inflation (2.5%) for ever: what the stock is worth with no growth premium.

- **Formula:** (fcff_before_growth x 1.025 / (wacc - 2.5%) - net_debt) / shares
- **Unit:** $; **better:** none; **period:** now
- **Source:** sector: `dcf_fair_value`
- **Used in:** absolute values; cheap score
- **Example (BSX, 2026-10-26):** $34.09 = (3.403 x 1.025 / (8.17% - 2.5%) - 12.085) / 1.449
- **Vector:** derived

<a id="price-vs-fair-value"></a>
#### Price against DCF fair value (`price_vs_fair_value`)

Premium (positive) or discount to the no-growth DCF value: the growth the price assumes.

- **Formula:** price / dcf_fair_value - 1
- **Unit:** fraction; **better:** lower; **period:** now
- **Source:** sector: `price_vs_fair_value`
- **Used in:** strict and weighted screens (cheapness)
- **Example (BSX, 2026-10-26):** +33.7% = 45.58 / 34.09 - 1
- **Vector:** derived

<a id="entry-price"></a>
#### Entry price at target P/E (`entry_price`)

The price at which the stock reaches Babak's target multiple.

- **Formula:** target_pe x eps_adj_ttm
- **Unit:** $; **better:** none; **period:** now
- **Source:** watchlist: `entry_price`
- **Used in:** watch list
- **Example (BSX, 2026-10-27):** $41.73 = 13 x 3.21
- **Vector:** derived
- **Note:** Depends on a chosen target, so it belongs to the decision, not the vector.

<a id="price-vs-cheap"></a>
#### Price against own cheap price (`price_vs_cheap`)

Stage 2's ranking measure: price against the stock's own bottom-quarter P/E times today's EPS.

- **Formula:** price / (min(25th percentile of own 10-year P/E, sector median P/E) x eps) - 1
- **Unit:** fraction; **better:** lower; **period:** now
- **Source:** stage2: `vs_cheap`
- **Used in:** Stage 2 ranking
- **Example (IPS, 2026-10-27):** -8.2% = Ipsos: 35.46 / (9.67 x 3.99) - 1. BSX failed Stage 1, so has no Stage 2 row
- **Vector:** core

