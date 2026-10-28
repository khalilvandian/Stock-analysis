# Reports

Each report covers one piece of analysis. It states the data date, the method, the findings, the caveats, and the command that reproduces it. Figures are as of the date in each report; rerun the commands to refresh them.

| # | Report | What it covers |
|---|---|---|
| 01 | [Data sources and API access](01-data-sources-and-api-access.md) | FMP test (HTTP 402 on utilities), Yahoo Finance, SEC EDGAR, network hosts |
| 02 | [CEG overview](02-ceg-overview.md) | Constellation's absolute values, history and business |
| 03 | [CEG debt in 2026](03-ceg-debt-2026.md) | Why debt rose from $9bn to $24.7bn, and where the money goes |
| 04 | [Calpine](04-calpine.md) | The acquired company and its debt, instrument by instrument |
| 05 | [Peer comparison](05-peer-comparison.md) | CEG vs Vistra, NRG, Talen and regulated utilities: debt, growth, valuation |
| 06 | [DCF valuation](06-dcf-valuation.md) | Enterprise and equity DCF, fair values, sensitivity, why utilities need a dividend model |
| 07 | [Valuation methods](07-valuation-methods.md) | Reference list of ways to value a stock, and which ones the project uses |
| 08 | [Utilities sector overview](08-utilities-sector-overview.md) | All 102 US-listed utilities, medians by sub-industry |
| 09 | [Screening](09-screening-low-debt-cheap-growth.md) | Seven rounds of screen design, ending with the current weighted top 5 |
| 10 | [Absolute values](10-absolute-values-sector.md) | The absolute-values-first framework and sector totals FY2018–FY2025 |
| 11 | [Boston Scientific](11-bsx-fundamentals.md) | Summary, then BSX absolute values, ratios and screens against 13 medical-device peers, then analysis (P/E vs its own history, entry price) |
| 12 | [Booking Holdings](12-bkng-fundamentals.md) | Summary, then BKNG absolute values, ratios and screens against 6 online-travel peers, then analysis (adjusted P/E vs its own history, entry prices) |
| 13 | [Market screener](13-market-screener.md) | The S&P 500 (497 companies; the US and Europe above $1bn with one setting). Stage 1: Peter Lynch's six categories and financial-statement rules per category (banks, insurers, REITs by kind of business). Stage 2: each survivor's own cheap price, top 3 cheap or close-to-cheap names per sector, technicals for timing |
| 14 | [Metrics dictionary](14-metrics-dictionary.md) | Every fundamental metric used so far, defined with formula, source and a worked example; the proposed first vector and the choices to make (issue #8) |
| 16 | [Lynch's six categories in numbers](16-lynch-categories.md) | Lynch's own growth numbers, Validea's and AAII's quant versions, our Stage 1 rules against them, and a proposed revision (growth measure, revenue check, cyclicals by sales and profit, asset plays, borderline flag) with its effect on today's S&P 500. Not adopted yet |

## Writing a new report

Number it after the last report. Since report 11 every report has three parts, in order
(Babak, 2026-10-27):
1. A short high-level summary, with no detail.
2. The numbers: data date, absolute values first (with history), then ratios, screens,
   DCF and P/E against the stock's own history.
3. Claude's analysis: method, findings, caveats and the command to reproduce.

Then add it to the table above.
