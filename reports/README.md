# Reports

Each report covers one piece of analysis. It states the data date, the method, the findings,
the caveats, and the command that reproduces it. Figures are as of the date in each report;
rerun the commands to refresh them.

There are no reports yet from the database era. The next one is number 15.

## Removed reports (01-14)

Reports 01-14 came from the project's first, file-based experiments (2026-09 to 2026-10).
They read files under `data/` and scripts that were removed when everything moved to the
database (issue #33), so they were deleted too. The docs still cite them by number where a
decision or a screener threshold came from one. To read one, check it out from the last
commit that has it:

```
git show 741444f:reports/09-screening-low-debt-cheap-growth.md
```

| # | File | What it covered |
|---|---|---|
| 01 | `01-data-sources-and-api-access.md` | FMP test (HTTP 402 on utilities), Yahoo Finance, SEC EDGAR, network hosts |
| 02 | `02-ceg-overview.md` | Constellation's absolute values, history and business |
| 03 | `03-ceg-debt-2026.md` | Why CEG's debt rose from $9bn to $24.7bn |
| 04 | `04-calpine.md` | The acquired company and its debt |
| 05 | `05-peer-comparison.md` | CEG against Vistra, NRG, Talen and regulated utilities |
| 06 | `06-dcf-valuation.md` | Enterprise and equity DCF, fair values, sensitivity |
| 07 | `07-valuation-methods.md` | Ways to value a stock, and which ones the project uses |
| 08 | `08-utilities-sector-overview.md` | The 102 US-listed utilities, medians by sub-industry |
| 09 | `09-screening-low-debt-cheap-growth.md` | Seven rounds of screen design: the source of the debt thresholds |
| 10 | `10-absolute-values-sector.md` | The absolute-values-first framework |
| 11 | `11-bsx-fundamentals.md` | Boston Scientific against medical-device peers; BSX's target P/E |
| 12 | `12-bkng-fundamentals.md` | Booking Holdings against online-travel peers; BKNG's target P/E |
| 13 | `13-market-screener.md` | The first market screener run and the discussion of its rules (now `docs/SCREENER.md`) |
| 14 | `14-metrics-dictionary.md` | The metrics dictionary and its open choices (now `docs/METRICS.md`, `docs/DECISIONS.md`) |

## Writing a new report

Number it after the last report. Every report has three parts, in order (Babak,
2026-10-27):
1. A short high-level summary, with no detail.
2. The numbers: data date, absolute values first (with history), then ratios, screens,
   DCF and P/E against the stock's own history. Read them with `analysis/absolute.py`,
   `analysis/peer_screen.py` or `stock_analysis.stocks`.
3. Claude's analysis: method, findings, caveats and the command to reproduce.

Then add it to a table above.
