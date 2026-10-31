# Components and entities

What the project works with: its data sources, the things it defines (absolute values,
metrics, the watch list, Lynch categories, screener types), what it produces (reports,
dated analyses, the site, the email) and the formats of its main files.

## Data sources

All sources in use are free and need no key. Each one's limits and fallbacks are listed so
a gap in one can be traced.

| Source | Access | What it gives | Used by | Limits | Fallback |
|---|---|---|---|---|---|
| **Yahoo Finance** (`yfinance`) | No key. Hosts `query1/query2.finance.yahoo.com`, `fc.yahoo.com` (cookie) | Prices (daily and monthly, split-adjusted), statements (about 4 annual years and 5-6 quarters), company info, sector screener, earnings dates with **reported (adjusted) quarterly EPS** and estimates, splits, FX pairs (`EURUSD=X` style) | `sector.py`, `history.py` (gaps, prices), `watchlist.py`, `market.py`, `stage1.fill_gaps`, `stage2.py`, `stock_analysis.fetch` | Unofficial: fields and the cookie/crumb handshake change; rate limits under heavy use; GAAP EBITDA and EPS include one-offs; capex can include stakes (BSX's MiRus) | SEC for history; TradingView for the screener; retries in `watchlist.fetch_row` |
| **SEC EDGAR** | No key; send `SEC_USER_AGENT`. Hosts `www.sec.gov`, `data.sec.gov` | `company_tickers.json` (ticker to CIK); **company facts** (every XBRL fact a company filed: annual 10-K, 20-F, 40-F figures, back to 2016 here); **frames API** (`/api/xbrl/frames/us-gaap/<concept>/<unit>/CY<year>.json`: one concept for every filer in a calendar year) | `history.py`, `watchlist.sec_years` (company facts); `stage2.sec_check` (frames, `EarningsPerShareDiluted`) | US filers only; tag choice varies by company (the tag lists in `history.py`); values keep the share basis of the filing (split adjustment needed); about 250 MB for the utilities; frames are by calendar year | Yahoo annual statements fill gaps; every value records its `source` |
| **TradingView screener** | No key. `POST scanner.tradingview.com/<market>/scan` | Every listed company per market: current fundamentals, ratios, Piotroski and Altman scores, up to 20 years of yearly EPS, revenue, EBITDA and dividends (`*_fy_h`), technicals (SMA50, SMA200, RSI, 52-week range, technical rating), index membership (`indexes`) | `stage1.fetch_universe` via `stock_analysis.tradingview` | Unofficial interface; field names can change (note the `ebitda_interst_cover_ttm` spelling); market values and statements in the company's own currency, prices in the trading currency (London in pence); sectors are TradingView's 20, not GICS | Yahoo fills debt, cash, EBITDA, interest and cash-flow gaps; each fill is named in `filled` |
| **ECB** | No key. `data-api.ecb.europa.eu` | Latest daily euro reference rates, turned into US dollars per unit, plus GBX | `stage1.run` via `stock_analysis.ecb` | About 30 currencies; a company whose statement or trading currency the ECB doesn't publish is dropped from the screener | None (such companies are left out) |
| **Financial Modeling Prep** | `FMP_API_KEY` | Quotes, statements, ratios (`stable` endpoints) | `FMPClient` only; no analysis uses it | Free plan returns HTTP 402 for most symbols; the current key is invalid | Yahoo, SEC, TradingView |
| **Wikipedia S&P 500 list** | By hand | `config/market_universe.csv`: symbol, name, GICS sector, GICS sub-industry (503 share classes) | `market.py` (breadth: share of S&P 500 stocks above their 200-day average, near 52-week highs and lows) | Refreshed by hand, occasionally; not the screener's universe (that is TradingView's `SP:SPX` membership, 497 companies) | None needed |
| **Web search** | Built into Claude | Guidance, deal terms, news for `notes.md` | Claude, during analyses and the evening run | Not reproducible by a script | Filings on SEC EDGAR |

## Absolute values

Screened first for every company, before any ratio or score (`config/absolute_values.toml`).

| Group | Value | Column | Unit | Yearly history column |
|---|---|---|---|---|
| Price and value | Share price | `price` | $ | `price` |
| | Market value | `market_cap` | $bn | `market_cap` |
| | DCF fair value | `dcf_fair_value` | $ | none (today only) |
| | Cash flow before growth (DCF base) | `fcff_before_growth` | $bn | `fcff_before_growth` |
| Debt and cash | Total debt | `total_debt` | $bn | `total_debt` |
| | Net debt | `net_debt` | $bn | `net_debt` |
| | Short-term debt | `short_term_debt` | $bn | `short_term_debt` |
| | Long-term debt | `long_term_debt` | $bn | `long_term_debt` |
| | Cash | `cash` | $bn | `cash` |
| Earnings | Revenue (12m) | `revenue` | $bn | `revenue` |
| | EBITDA (12m) | `ebitda` | $bn | `ebitda` |
| | Net income (12m) | `net_income` | $bn | `net_income` |
| | EPS (12m) | `eps_ttm` | $ | `eps` |
| | Forward EPS | `eps_fwd` | $ | none (today only) |
| Cash flow | Operating cash flow | `operating_cf` | $bn | `operating_cf` |
| | Capex | `capex` | $bn | `capex` |
| | Free cash flow | `free_cf` | $bn | `free_cf` |

`column` must exist in `data/sector/utilities.csv` (from `sector.py`) and `history` in
`data/sector/history.csv` (from `history.py`); `tests/test_absolute.py` checks both. The
screener's own absolute-values table uses TradingView's fields in US dollars
(`screen_common.ABSOLUTE`).

## Metrics dictionary

Every fundamental metric the project uses (81 at the time of writing) is defined once in
`config/metrics.toml`: id, name, group, unit, direction, period, definition, formula,
source column in each table (`sector`, `stage1`, `stage2`, `watchlist`), where it is used, a
worked example and its draft vector status (core, candidate, context, derived). The readable
version is [`METRICS.md`](METRICS.md), generated by
`uv run python -m stock_analysis.metrics doc`. Named sets (`proposed`, `absolute_values`,
`strict_screen`, `weighted_screen`, `stage1`, `watchlist`) select metrics for a vector.
Report 14 explains the open choices; [`DECISIONS.md`](DECISIONS.md) records the defaults taken.

## The watch list

`config/watchlist.toml` lists the stocks analysed every evening.

| Field | Required | Meaning |
|---|---|---|
| `timezone` (top level) | No, default `Europe/Rome` | Time zone of the dated file names and run labels |
| `[[stock]]` | One block per stock | |
| `symbol` | Yes | Yahoo ticker |
| `peers` | Yes (may be empty) | Sector peers for the ratios and the strict and weighted screens in the PDF |
| `target_pe` | Yes | Entry multiple: entry price = `target_pe` x trailing 12-month adjusted EPS |
| `target_note` | Yes | Where the target comes from and whether Babak has confirmed it |
| `stakes_per_share` | No, default 0 | After-tax value of equity stakes per share. The P/E becomes (price - stakes) / adjusted EPS and the entry price `target_pe` x EPS + stakes (report 17's core P/E ex-stakes) |
| `eps_override` | No | One-off corrections: `{ reported = "YYYY-MM-DD", eps = 0.73, reason = "..." }` replaces the adjusted EPS of the quarter reported that day |

Current stocks: BSX (target 13x), BKNG (15x), NFLX (20x), GOOGL (22x ex-stakes, report 17) and UBER (20x). The
BKNG, NFLX, GOOGL and UBER targets are marked "not yet confirmed by Babak". GOOGL and UBER
have `eps_override` entries that take out equity-stake revaluations (and UBER's tax release);
GOOGL also sets `stakes_per_share` (Anthropic, SpaceX and other stakes, $14.93 after tax).

## Peter Lynch's categories

From *One Up on Wall Street* (1989), chapter 7. Stage 1 puts each company in one category,
testing in this order (thresholds from `[lynch]` in `config/screeners.toml`):

| Order | Category | Test |
|---|---|---|
| 1 | No profit (not a Lynch category) | No positive EPS in any of the last 5 fiscal years. Fails Stage 1. |
| 2 | Cyclical (by industry) | Industry in `cyclical_industries` (autos, airlines, steel, metals, chemicals, oil and gas, drilling, shipping, homebuilding, chip equipment, machinery, paper, building materials, hotels and cruise lines) |
| 3 | Turnaround | Loss now (12 months or latest fiscal year), or both the 12-month and latest-year EPS more than 50% below the best of the last 5 fiscal years |
| 4 | Cyclical (by history) | EPS fell more than 30% in 3 or more of the last 10 years, and median growth is under 20% |
| 5 | Asset play | Price below book value (positive book), or net cash above 30% of market value |
| 6 | Fast grower | Median yearly EPS growth over 5 years of 20% or more |
| 7 | Stalwart | 8% to 20% |
| 8 | Slow grower | Under 8% |
| | (blank) | Fewer than 3 yearly EPS changes: "incomplete", too little history |

## Screener types

Each company gets one screener type from its TradingView industry or sector
(`[types]` in `config/screeners.toml`). The type decides which rule set applies.

| Type | Who | Rules |
|---|---|---|
| `general` | Everyone not listed below | The rules of its Lynch category |
| `banks` | Major, regional and savings banks, financial conglomerates, investment banks and brokers | `[screener.banks]`: profitable, ROE, growth. No debt rules |
| `insurers` | Multi-line, property and casualty, life and health, specialty insurance | `[screener.insurers]`: same as banks |
| `reits` | Real estate investment trusts | `[screener.reits]`: debt rules with REIT thresholds |
| `utilities` | Sector "Utilities" | Its Lynch category's rules without the Altman score |
| excluded | Investment trusts and mutual funds | Skipped: not companies to own for their earnings |

The full rule tables are in [`SCREENER.md`](SCREENER.md).

## Reports

`reports/NN-<topic>.md`, numbered in order, indexed in `reports/README.md`. Each states its
data date and the command that reproduces it. Since report 11 the layout is three parts:
**1. Summary** (verdict and four one-line points: cheap, strong, weak, uncertain),
**2. The numbers** (absolute values first, then history, method, ratios and screens),
**3. Analysis** (Claude's reading), then caveats and the reproduce command. A report is
updated in place, with a new date, when its analysis is redone.

## Dated analyses

Everything the evening run writes lives in `analyses/`. Nothing is overwritten.

| Path | What it is |
|---|---|
| `analyses/<SYMBOL>/YYYY-MM-DD_HHMM.pdf` | One stock's analysis: summary, the numbers, analysis. A second run in the same minute gets `-2`, `-3` |
| `analyses/<SYMBOL>/runs.csv` | One line per run (format below) |
| `analyses/<SYMBOL>/notes.md` | Claude's notes, copied into the PDF: `Updated:` line, then `## Verdict`, `## Summary`, `## Business`, `## Risks`, `## News`, `## What to watch` |
| `analyses/<SYMBOL>/README.md` | The stock's dated list, newest first, rebuilt each run |
| `analyses/market/YYYY-MM-DD_HHMM.pdf`, `runs.csv`, `notes.md` | The market report. Notes sections: Verdict, Summary, What is driving the market, Stocks to look at, What to watch |
| `analyses/summaries/YYYY-MM-DD_HHMM.pdf`, `notes.md` | The watch-list summary. Notes sections: Verdict, Analysis |
| `analyses/README.md` | The overview: latest run per stock, links to every dated list, and the market and summary PDFs |

A stock removed from the watch list keeps its folder and appears as "off the list".

## The site

https://khalilvandian.github.io/Stock-analysis/, built by `analysis/site.py` (standard
library only) and published by `.github/workflows/pages.yml` on pushes to `main` that
touch `analyses/`, `data/screener/`, `analysis/site.py` or the workflow, or by hand
(`workflow_dispatch`). Pages: **Watch list** (one summary panel per stock, sidebar of current
and former stocks), one page per stock (verdict, key numbers, a PDF viewer over every dated
analysis, Claude's notes, the dated table), **Market** (latest strip and every dated report),
**Screener** (the latest Stage 1 pass counts by category and the top 3 per sector from
`data/screener/`), and **Summaries**. PDFs are copied next to the pages.

## The email

One email per evening run, sent by `analysis/send_email.py` through Brevo's transactional
email API, to Babak only. The body (`.cache/watchlist/email.html`) has the market verdict
and figures, the screener's pass counts and cheapest names, the watch-list verdict, one line
per stock, and links to every PDF on the site; every PDF of the run is attached as
`<FOLDER>_<YYYY-MM-DD_HHMM>.pdf`.

| Setting | Meaning |
|---|---|
| `BREVO_API_KEY` | Brevo API key |
| `WATCHLIST_EMAIL_FROM` | Sender, `Name <address>`, verified in the Brevo account |
| `WATCHLIST_EMAIL_TO` | Recipients, comma separated (the code accepts up to 5; the decision is Babak only), or `--to` |
| `WATCHLIST_BRANCH` | Optional: branch for the email's links when not `main` (links then go to GitHub instead of the site) |

All are cloud-environment settings, never written into the repository.

## The schedule

A scheduled Claude Code session starts every evening at 21:00 Europe/Rome and follows
[`EVENING_RUN.md`](EVENING_RUN.md). The schedule lives in Claude Code, not in this
repository. The only automation inside the repository is the Pages workflow.

## File formats

### `analyses/<SYMBOL>/runs.csv`

| Column | Meaning |
|---|---|
| `run` | Run label, `YYYY-MM-DD HH:MM <zone>` (for example `2026-10-27 20:55 CET`) |
| `file` | PDF name in the same folder |
| `price` | Latest price |
| `eps_adj_ttm` | Trailing 12-month adjusted EPS (sum of the last four reported quarters, with overrides) |
| `pe_adj` | `price / eps_adj_ttm` |
| `pe_median_10y` | Median of the yearly P/E over the last 10 years |
| `target_pe` | From the watch list |
| `entry_price` | `target_pe x eps_adj_ttm` |
| `to_entry` | `entry_price / price - 1` (negative: the entry price is below today's price) |
| `verdict` | First sentence of the Verdict in `notes.md` |

### `analyses/market/runs.csv`

| Column | Meaning |
|---|---|
| `run`, `file` | As above |
| `sp500`, `sp500_day` | S&P 500 level and day change |
| `vix` | VIX level |
| `above_200d` | Share of S&P 500 stocks above their 200-day average |
| `stocks_to_look_at` | Tickers of the screener's 10 cheapest listed names, cheapest first (before 2026-10-27 night: the panic-sell screen's names) |
| `screener_date` | Date of the screener run used (the latest `data/screener/YYYY-MM-DD.csv`) |
| `screener_screened`, `screener_passed`, `screener_listed` | Companies screened in Stage 1, passed Stage 1, listed by Stage 2 |

### `.cache/watchlist/last_run.json`

| Key | Meaning |
|---|---|
| `subject` | `Watch list analyses, <run label>` |
| `html` | Path of the email body, `.cache/watchlist/email.html` |
| `files` | Paths of every PDF the run wrote (market, each stock, summary) |

### `data/screener/stage1.csv`

One row per company screened, indexed by TradingView symbol (`EXCHANGE:TICKER`), sorted by
region, sector and market value. Key columns:

| Column | Meaning |
|---|---|
| `description`, `region`, `sector`, `industry` | Company name and TradingView classification |
| `type` | Screener type (general, banks, insurers, reits, utilities) |
| `category` | Lynch category (`no_profit`, `cyclical`, `turnaround`, `asset_play`, `fast_grower`, `stalwart`, `slow_grower`, or blank) |
| `rule_set` | The rules applied: the category, or banks, insurers, reits |
| `status` | `pass`, `fail` or `incomplete` |
| `failed` | Rules failed, `; ` separated |
| `missing` | Required rules with no data (status incomplete) |
| `flags` | Optional rules skipped for lack of data, and other warnings |
| `filled` | Values filled from Yahoo or derived (short-term debt as total minus long-term, net debt as debt minus cash) |
| `close`, `cap_usd_bn`, `*_usd_bn`, `eps` | Absolute values: price (trading currency), market value and statement amounts in US$ billions, 12-month diluted EPS |
| Ratios and history measures | `cash_to_short_term_debt`, `cash_to_long_term_debt`, `cash_to_total_debt`, `net_debt_to_ebitda`, `net_debt_to_avg_ebitda`, `net_cash_to_cap`, `interest_cover`, `debt_to_equity`, `price_book_fq`, `return_on_equity_fq`, growth medians, `eps_growth_3y`, `eps_vs_5y_peak`, `loss_now`, `no_profit_5y`, `eps_big_drops_10y`, `eps_avg_10y`, `recession_eps_change`, `dividend_years_10y`, `dividend_payout_ratio_ttm`, `piotroski_f_score_ttm`, `altman_z_score_ttm` |

### `data/screener/top.csv`

The top `top_per_sector` (3) per region and sector, among Stage 1 passes that are cheap or
close to cheap. It carries every Stage 1 column except the yearly lists, plus Stage 2's.
Key columns:

| Column | Meaning |
|---|---|
| `tv_symbol` | TradingView symbol (index) |
| `name`, `description` | Ticker and company name |
| `region`, `sector`, `category`, `type` | As in `stage1.csv` |
| `close`, `currency` | Price and trading currency |
| `eps`, `eps_basis` | EPS used for the cheap price, `adjusted` (Yahoo) or `diluted` (TradingView) |
| `pe_now` | Price / EPS (in the statements' currency) |
| `pe_years`, `pe_median_10y`, `pe_low_10y` | The stock's own yearly P/E history |
| `cheap_pe` | Bottom-quartile own P/E |
| `sector_pe` | Median `pe_now` of the region and sector |
| `cheap_multiple`, `cheap_basis` | The lower of the two, and which one set it (`own history` or `sector median`) |
| `cheap_price` | `cheap_multiple x eps`, in the trading currency |
| `vs_cheap` | `close / cheap_price - 1` (the ranking measure) |
| `cheapness` | `cheap` (at or below) or `close` (up to 15% above) |
| `rank_in_sector` | 1 to 3 |
| `trend`, `rsi_read`, `in_52w_range`, `tv_rating` | Technicals, for timing only |
| `pe_vs_sector`, `ev_ebitda_vs_sector`, `fcf_yield` | Context measures, not used in the ranking |
| `sec_eps` | SEC EDGAR diluted EPS for the latest fiscal year (US only) |
| `why` | One line: P/E against the cheap multiple, 10-year median, leverage, growth, trend |

### `data/screener/growth.csv`

The growth screener's full table (report 15): every company, passes first in rank order.
Columns: `description`, `region`, `sector`, `industry`, `type`, `status` (pass, fail,
incomplete), `failed`, `missing`, `rank`, `flags`, the absolute values (as in `top.csv`),
`revenue_cagr`, `revenue_up_years`, `net_income_cagr`, `net_income_up_years`, `eps_cagr`,
`eps_cagr_3y`, `net_margin` (12 months), `sector_net_margin`, `net_margin_change` (latest
fiscal year minus 5 years before), `net_debt_to_fcf` (years of free cash flow to repay net
debt; 0 = net cash), `short_term_debt_cover` ((cash + free cash flow) / debt due within a
year), `filled` (values filled from Yahoo), `pe_now`, `pe_median`, `pe_low`, `pe_years`,
`pe_vs_median` (the ranking measure), `pe_percentile`.

`data/screener/growth_backtest.csv`: one row per backtest pick: `fiscal_year`, `entry`,
symbol, company, sector, rank, the growth and margin measures, P/E against own median, and
`return_1y` and `return_to_date` (price only).

### `data/screener/YYYY-MM-DD.csv`

Every company of the day's run with both stages' columns (no yearly lists). `market.py` and
`site.py` take the screener's run date from the newest of these files.
