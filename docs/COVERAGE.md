# Data coverage

How much of the required data is in the database, and how good it is ([issue #18](https://github.com/khalilvandian/Stock-analysis/issues/18)).
One definition, in `config/coverage.toml`, is used by three things: the
`coverage` command, the ingest job's switch from backfill to maintenance
([`INGEST.md`](INGEST.md)), and the **Data** page of the site.

```bash
uv run python -m stock_analysis.db coverage                           # print, save today's snapshot
uv run python -m stock_analysis.db coverage --json data/coverage/latest.json   # for a local site build
```

## What is required

The universe is the newest TradingView snapshot of the S&P 500, the same list the job
fetches. For each company:

| Part | Required | Cells |
|---|---|---|
| Fiscal years | Every required item for each fiscal year from 2016, or from the listing year if the company listed later, to the latest year that should be filed by now (year end + 100 days) | items × years |
| Quarters | Every required item for each of the last 8 quarters that should be filed by now (quarter end + 60 days): the quarter's value for flows, the quarter-end value for balance-sheet items | items × 8 |
| Prices | Daily prices from 2016-01-01 (or the first trading day) on at least 98% of the market's trading days, and a price at most 5 days old | 1 |
| Reported EPS | Yahoo's reported EPS for the last 8 quarterly reports (fewer for a recent listing) | 1 |

- **Items:** those in `config/db_items.toml`.
- **Optional items:** `interest_expense`, `short_term_debt`, `long_term_debt` and `total_debt`
  are measured and shown, but a gap doesn't count against the company. Many companies don't
  report these lines at all, so a gap is often a real zero.
- **Not applicable** (`[[not_applicable]]`, by TradingView industry):
  - banks, insurers and asset managers: no operating income, EBITDA, D&A or capex
  - REITs: no operating income or EBITDA
- **Explained** (`[[explained]]`): a gap checked by hand and accepted, with the reason.
  It counts as present.

A company is **covered** when every one of its cells is present or explained. The headline
number is the share of all required cells present.

**Trading calendar:** the days on which at least a fifth of the companies in the database have
a price. That avoids needing an exchange holiday calendar.

**Listing date:** a first price more than 15 days after 2016-01-01 is taken as the listing
date.

## Quality, freshness and progress

The snapshot also records:

- **By item, fiscal year and sector:** cells required and present.
- **Freshness:**
  - the newest price
  - companies whose prices are incomplete or stale
  - the newest SEC filing loaded
  - companies with no SEC filing loaded in 120 days (they file every quarter)
- **Source mix:** how many fiscal-year values come from SEC, `history.csv`, Yahoo or are
  derived.
- **Quality checks:** the issues of the last build, by check and severity
  (`core_quality_issue`, see [`DATABASE.md`](DATABASE.md)):
  - SEC against Yahoo differing by more than 2%
  - the balance-sheet identity
  - missing periods
  - 10× jumps
  - implied share jumps
  - short trading years
  - daily price jumps above 50% without a split
- **The ingest job:**
  - tasks per source and status
  - the last runs (requests, done, failed, rows, what stopped them)
  - an estimate of the runs left: tasks never fetched ÷ the average done per run
- **Per company:** its share, its prices, quarters and EPS, the share of fiscal years per item
  (the heatmap on the page), the issues and the first missing cells.

The snapshot is one row per day in `out_coverage_snapshot`, with the headline numbers as
columns (the trend) and everything else in `detail_json`. A rerun on the same day replaces it.

## The page

`analysis/site.py` builds `coverage.html` (**Project → Data coverage** in the menu). The Pages workflow
(`.github/workflows/pages.yml`) runs when the ingest job finishes (the job starts it through
GitHub's API), every day at 05:15 UTC as a fallback, and on every push. It reads the newest snapshot through the web API (`/query`, with the repository
secret `STOCK_API_KEY`), so the site stays static and no data is committed. Without the
secret, a local build uses `data/coverage/latest.json` (not committed) if present, or says
there is no snapshot yet. The page shows counts and shares only, no secrets and no raw data.

Code: `src/stock_analysis/db/coverage.py`; tests in `tests/test_ingest.py`.
