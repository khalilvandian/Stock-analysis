# Predictive analysis: method

How `analysis/predict.py` and `src/stock_analysis/predict/` turn S&P 500 history into a
machine-learning problem: inputs known at year *t*, output = "was buying at *t* a good
idea, judged by years *t+1…t+5*". Results and the recommendation are in
[report 15](../reports/15-predictive-analysis.md); this file explains how it is built so it
can be checked, rerun and extended. Issue #10.

```
uv run python analysis/predict.py all       # resolve, download, build, study, models
uv run python analysis/predict.py models    # rerun experiments on the saved panel
```

Run time: ~15 minutes the first time (downloads ~750 SEC files and ~600 price histories into
`.cache/predict/`), ~10 minutes to build the panel, ~3 minutes for the experiments.

## 1. The problem

| | |
|---|---|
| Unit | one S&P 500 member on one decision date |
| Decision dates | June 30 of each year, 2010–2025 (config `[dates]`) |
| Inputs (x) | ~60 point-in-time features: balance sheet, income and cash-flow statements, valuation, growth, quality scores, price history |
| Output (y) | a label describing the next 5 years of holding the stock (section 3) |
| Rows | 8,031 member-years; 6,350 with complete inputs; 4,457 with complete inputs and a 5-year outcome (2010–2021) |

## 2. Data, without look-ahead

| Piece | Source | How look-ahead is avoided |
|---|---|---|
| Who was in the index | `data/predict/sp500_ticker_start_end.csv` from [fja05680/sp500](https://github.com/fja05680/sp500) (MIT), checked against Wikipedia's [change log](https://en.wikipedia.org/wiki/Historical_components_of_the_S%26P_500) | Members on each date, including companies that later left |
| Company identity | SEC ticker list, rename detection, EDGAR name search, hand-checked overrides (`data/predict/universe_overrides.csv`) → `data/predict/universe.csv` | A ticker reused by another company is detected by name and dropped (section 6) |
| Fundamentals | SEC EDGAR company facts (XBRL) | Only facts **filed before** the decision date are used; a later restatement is invisible until it is filed |
| Prices, dividends, splits | Yahoo Finance chart API (total return = adjusted close) | Features use prices up to the date; labels use prices after it |
| Benchmark | SPY total return; 13-week T-bill (^IRX) for Sharpe/Sortino | — |

Details that matter:
- **Annual figures** come from 10-K filings (period 350–380 days). For a June 30 decision
  date that is normally the fiscal year ended the previous December. Quarterly (TTM)
  figures are a possible extension.
- **Splits.** Per-share values and share counts are restated for splits made after the
  filing they came from, and the price is the price actually quoted that day, so market
  value = shares × price is consistent.
- **Market value** uses the cover-page share count, cross-checked against weighted
  diluted shares (they must agree within a factor of 1.7). Rows with a market value below
  $1bn or above $5tn are treated as data errors and not used (≈2% of rows).
- **Sector** is derived from the SEC SIC code (`features.sector_from_sic`), close to but not
  identical with GICS.

## 3. Labels (the output)

All labels use total return (dividends reinvested) over exactly the 5 years after the
decision date and compare with the S&P 500 over the same days (`labels.py`).

| Label | Definition | Higher is |
|---|---|---|
| `cagr` | annual total return | better |
| `excess_cagr` | `cagr` minus the S&P 500's | better |
| `excess_vs_sector` | `cagr` minus the median of the same sector in the same year | better |
| `sharpe` | (return − T-bill) / volatility, monthly | better |
| `sortino` | (return − T-bill) / downside deviation | better |
| `calmar` | `cagr` / worst peak-to-trough fall | better |
| `martin` | (`cagr` − T-bill) / ulcer index (root-mean-square of daily drawdowns: depth *and* duration of falls) | better |
| `info_ratio` | excess return / tracking error vs the S&P 500 | better |
| `max_dd`, `dd_vs_index` | worst fall; worst fall minus the index's worst fall | worse |
| `beat_index` | 1 if `excess_cagr > 0` | — |
| **`good`** | **1 if the stock beat the S&P 500 AND its worst fall was at most 15 points deeper than the index's worst fall in the same 5 years** | — |

Each continuous label also has a within-year percentile (`*_pct`, 0–1), which removes the
market regime (2010 cohort: S&P 500 +17%/yr; 2015 cohort: +11%/yr).

The recommendation (report 15): **`good` is the primary label**; the within-year percentile
of the Martin ratio is the continuous companion for ranking.

## 4. Features (the inputs)

Names follow `config/metrics.toml` (issue #8) where the metric exists there. Every
feature is converted to a **within-year percentile** before modelling (0 = lowest in that
year's S&P 500, 1 = highest, missing = 0.5), so scales, outliers and inflation do not matter
and coefficients read the same way for every feature.

| Group | Features |
|---|---|
| Size | `log_market_cap` |
| Valuation | `pe_ttm`, `earnings_yield`, `price_to_book`, `book_to_market`, `price_to_sales`, `sales_yield`, `ev_to_ebitda`, `ebitda_to_ev`, `fcf_yield`, `dividend_yield`, `buyback_yield`, `shareholder_yield`, `ey_vs_own_median` (earnings yield vs its own median at earlier dates) |
| Debt and liquidity | `cash_to_short_term_debt`, `cash_to_long_term_debt`, `cash_to_total_debt`, `net_debt_to_ebitda`, `interest_cover`, `debt_to_equity`, `debt_to_assets`, `net_cash_to_market_cap`, `current_ratio` |
| Profitability | `net_margin`, `gross_margin`, `operating_margin`, `fcf_margin`, `roe`, `roa`, `roic`, `ocf_to_assets`, `accruals`, `capex_to_revenue`, `rnd_to_revenue`, `payout_ratio` |
| Growth and stability | `revenue_growth_median`, `revenue_cagr_3y`, `eps_growth_median`, `eps_cagr_3y`, `ocf_growth_median`, `ebitda_cagr_3y`, `margin_change_avg`, `asset_growth`, `share_change`, `eps_vs_5y_peak`, `loss_now`, `eps_big_drops`, `roa_volatility` |
| Scores | `piotroski_f`, `altman_z`, `lynch_category` (simplified, no cyclical-industry list), `strict_screen` (Babak's must-haves from `analysis/screen.py`) |
| Price history | `mom_12_1`, `mom_6m`, `ret_1m`, `vol_1y`, `beta_3y`, `max_dd_3y`, `price_vs_200d`, `price_vs_52w_high`, `excess_return_3y` |
| Category | sector (11 dummies), Lynch category (6 dummies) |

Not used: analyst estimates and adjusted EPS (no point-in-time history for free), and
TradingView data (no history through the scanner).

## 5. Experiments (`models.py`, `study.py`)

- **Univariate:** Spearman correlation of each feature with each label, per year, then
  averaged (`ic_*.csv`), and the label rate by feature quintile (`quintiles_*.csv`).
- **Walk-forward models:** OLS, Ridge, Lasso, ElasticNet, depth-3 tree, random forest,
  gradient boosting (regression on the within-year percentile of a label);
  logistic L1/L2, tree, random forest, gradient boosting (classification of `good`);
  and a "factor score" that picks the 10 features most correlated with the label in the
  training years.
- **Purging:** a model tested on year *T* is trained only on years *c* with *c* + 5 ≤ *T*,
  i.e. outcomes fully known on date *T*. With 5-year labels that leaves 6 test years
  (2016–2021); the first is trained on 2 years only.
- **Fixed scores:** equal-weight averages of a few percentiles chosen from the literature,
  with nothing fitted (`models.FIXED_SCORES`).
- **Metrics:** AUC (0.5 = coin flip), rank correlation of prediction and outcome ("IC"),
  share `good` and average excess return in the top predicted fifth vs the bottom fifth.
- **Importance:** out-of-sample permutation importance of gradient boosting, and Ridge /
  logistic coefficients on all rows; a depth-3 tree printed as rules.

## 6. Survivorship bias

The current S&P 500 list would only contain survivors. We use each year's real members,
which brings back companies that later **left the index** but still trade (≈70 per year;
they were "good" only 10% of the time vs 30% for stayers, so including them matters).

What we cannot fix with free data: Yahoo has **no prices for delisted companies**
(acquisitions, bankruptcies). Their fundamentals are in the panel but they have no label:
32% of the 2010 members, falling to 8% of the 2021 members. Most were acquired (usually at a
premium, which would often count as "good"); a minority failed. The bias therefore runs both
ways and cannot be signed with certainty; it matters most for the early years. Fix with a
paid source of delisted prices (Norgate, EODHD, CRSP) when available.

Other known gaps: ~6% of members have no usable fundamentals (financial companies with
non-standard statements, early-XBRL gaps in 2010); the sector mapping is approximate; the
"Lynch category" lacks the cyclical-industry list.

## 7. Files

| Path | What |
|---|---|
| `config/predict.toml` | dates, horizon, benchmark, drawdown margin, filters |
| `src/stock_analysis/predict/` | `universe`, `sec`, `prices`, `features`, `labels`, `dataset`, `models`, `study`, `download` |
| `analysis/predict.py` | command line |
| `data/predict/universe.csv` | every historical member with CIK, Yahoo symbol and how it was resolved |
| `data/predict/panel.csv.gz` | the panel (features and labels), one row per member-year |
| `data/predict/results/` | every table in report 15 |
| `reports/figures/15/` | figures |
| `tests/test_predict.py` | point-in-time filtering, splits, labels, purging, rename detection |
