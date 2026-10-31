# Processes

Every process in the project, step by step, with the exact commands. Run every command from
the repository root. Each `uv run` uses the project's locked environment.

## 1. Environment setup

**In Claude Code on the web** (the usual place): follow [`SETUP.md`](SETUP.md). In short:

1. Use the **Market analysis** cloud environment (or create one).
2. Set the environment variables in its settings, never in the repository:
   `SEC_USER_AGENT` (recommended), `BREVO_API_KEY`, `WATCHLIST_EMAIL_FROM` and
   `WATCHLIST_EMAIL_TO` (for the evening email), `FMP_API_KEY` (optional, unused).
3. Allow the network hosts: `query1.finance.yahoo.com`, `query2.finance.yahoo.com`,
   `fc.yahoo.com`, `www.sec.gov`, `data.sec.gov`, `scanner.tradingview.com`,
   `data-api.ecb.europa.eu`, `api.brevo.com`, `pypi.org`, `files.pythonhosted.org`, and
   `financialmodelingprep.com` if FMP is ever used.
4. Start a session on the repository. The SessionStart hook
   (`.claude/hooks/session-start.sh`) runs `uv sync` and puts `.venv/bin` on the `PATH`.
5. The PDFs need Chrome or Chromium. `watchlist.chrome()` looks at `CHROME_PATH`, then
   `/opt/pw-browsers/chromium-*`, then `chromium`, `chromium-browser`, `google-chrome` on the
   `PATH`.

**Locally:**

```bash
uv sync
cp .env.example .env      # optional: FMP_API_KEY, SEC_USER_AGENT; never commit .env
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

## 2. Refreshing data

The utilities data feeds the absolute-values screen, the sector screens and the dashboards.

```bash
uv run python analysis/sector.py      # Yahoo: every US-listed utility -> data/sector/utilities.csv (about 1 minute)
uv run python analysis/history.py     # SEC EDGAR, Yahoo for gaps -> data/sector/history.csv
uv run python analysis/history.py --refresh   # download the SEC company facts again
```

`history.py` needs `sector.py`'s output (`utilities.csv` and `history_yahoo.csv`). The first
SEC download is about 250 MB, cached in `.cache/sec/`. One company's full Yahoo data:

```bash
uv run python -m stock_analysis.fetch CEG     # -> data/CEG/
```

Then rebuild the dashboards and ask Claude to republish them as artifacts:

```bash
uv run python dashboard/build_absolute.py && uv run python dashboard/build_sector.py && uv run python dashboard/build.py
```

## 3. The absolute-values screen (step 1 of every analysis)

```bash
uv run python analysis/absolute.py                      # latest, every utility
uv run python analysis/absolute.py CEG VST UGI          # latest, selected companies
uv run python analysis/absolute.py --history CEG VST    # every fiscal year on record + latest 12 months
```

It writes `data/sector/absolute_values.csv` and `absolute_history.csv`. `absolute.py` reads
the utilities tables only; for any other stock the absolute values and their SEC history come
from the watch-list run or from `sector.analyse()` and `history.sec_history()` (section 4).
Show this table first in every answer, before any ratio or score.

## 4. Single-stock analysis

The method of reports 11 (BSX) and 12 (BKNG). Each step's output goes into the report in
this order.

1. **Absolute values, latest 12 months.** Run the peer group (it includes the stock itself):

   ```bash
   uv run python analysis/peer_screen.py medtech BSX ABT MDT SYK ISRG BDX EW ZBH DXCM STE PODD TFX GEHC RMD
   ```

   This calls `sector.analyse()` for each symbol and writes `data/peers/<name>.csv` with the
   absolute values and ratios. Check capex against SEC filings: Yahoo can count stakes and
   acquisitions as capex.
2. **History.** The yearly absolute values from SEC filings (Yahoo where SEC has no figure).
   The quickest route is the watch-list code, which also adjusts for splits:

   ```bash
   uv run python analysis/watchlist.py BSX --numbers     # key numbers only, writes nothing
   ```

   The stock must be on the watch list (section 13) for the full PDF; otherwise use
   `history.company_facts()`, `history.sec_history()` and `history.add_prices()` from Python.
   For utilities, `analysis/absolute.py --history` does it.
3. **Ratios.** Net debt / EBITDA, interest cover, cash / short-term debt, cash / long-term
   debt, revenue and EPS growth (average and median of yearly rates), net margin, P/E and
   EV / EBITDA against the peer median, forward against trailing P/E, price against the
   standard DCF. All are in the peer table.
4. **Screens.** `peer_screen.py` prints the strict screen (every debt rule) and the weighted
   screen (debt 50%, profit and cash 25%, cheapness 25%, growth required) within the peers.
5. **DCF.** The standard enterprise DCF is in the peer table (`dcf_fair_value`,
   `price_vs_fair_value`, `wacc`, `fcff_before_growth`). For the guided power producers use
   `uv run python analysis/dcf_firm.py` and `uv run python analysis/dcf.py`.
6. **Own-history P/E.** Adjusted EPS is Yahoo's reported quarterly EPS, split-adjusted; the
   trailing figure is the sum of four consecutive quarters. Each year's P/E is that year's
   average price over the trailing EPS at the first report after the year ends (the Q4
   report). Correct one-offs Yahoo still includes with `eps_override` in the watch list.
7. **Entry price.** Entry price = target P/E x trailing adjusted EPS. Propose the target
   against the stock's own history (decade low, 5- and 10-year medians) with a discount for
   what has changed, write the reasoning in `target_note`, and mark it "not yet confirmed by
   Babak" until they confirm it. Also give the entry price after the next report if the
   consensus estimate is met (the PDF does this).
8. **Report.** Write it up (section 12).

## 5. The market screener

Both stages in a row (about 1-2 minutes for the S&P 500 with a warm cache):

```bash
uv run python analysis/screener.py                 # Stage 1 then Stage 2
uv run python analysis/screener.py --no-adjusted   # skip Yahoo adjusted EPS (faster, diluted EPS only)
uv run python analysis/screener.py --refresh       # ignore today's cached downloads
uv run python analysis/stage1.py [--refresh]       # Stage 1 only -> data/screener/stage1.csv
uv run python analysis/stage2.py [--no-adjusted]   # Stage 2 only, on Stage 1's last output
```

Outputs: `data/screener/stage1.csv`, `data/screener/top.csv`, `data/screener/YYYY-MM-DD.csv`,
and `.cache/screener/stage1_full.pkl` (Stage 1 with its yearly lists, read by Stage 2). Every
threshold is in `config/screeners.toml`; [`SCREENER.md`](SCREENER.md) is the full reference.

### Stage 1: good financial statements (`analysis/stage1.py`)

1. **Universe.** TradingView's screener is scanned market by market for the regions in
   `[universe] regions` (now `["US"]`, the `america` market). Only primary listings of common
   stock are kept. With `[universe] index = "SP:SPX"` only S&P 500 members remain (497
   companies); with `index = ""` every company in the regions does. Cached for the day in
   `.cache/screener/tradingview_<index>_<regions>_<date>.pkl`.
2. **FX.** ECB rates convert each company's statements (`fundamental_currency_code`) and
   price (`currency`, GBX for London) to US dollars. Companies in a currency the ECB doesn't
   publish are dropped. Then the market-value floor applies: `min_market_cap_usd` ($1bn).
3. **Screener type.** From TradingView's industry: banks, insurers, REITs, utilities (by
   sector), general; funds and trusts are skipped.
4. **Derived values.** Short-term debt left blank is total minus long-term debt; no debt at
   all sets both to 0. Ratios: cash / short-term debt, cash / long-term debt, net debt /
   EBITDA, net cash, interest cover.
5. **Growth and history measures.** Yearly revenue and EPS growth over `[lynch] growth_years`
   (5): average and median, blank under 3 yearly changes. EPS CAGR over 3 years, EPS against
   its 5-year peak, loss now, no profit in 5 years, big EPS drops in 10 years, 10-year average
   EPS and EBITDA, EPS change in the 2009 and 2020 fiscal years, dividend years in the last
   10, net cash against market value.
6. **Lynch category**, tested in order: no profit, cyclical by industry, turnaround, cyclical
   by history, asset play, fast grower, stalwart, slow grower (tests in
   [`ENTITIES.md`](ENTITIES.md#peter-lynchs-categories)).
7. **Gap filling from Yahoo.** For general, utility and REIT companies still missing
   short-term or long-term debt, cash, EBITDA or total debt, or interest cover (unless net
   cash), Yahoo's latest quarterly balance sheet and annual income statement fill the
   blanks; interest cover becomes EBITDA / |interest expense|. Net debt left blank becomes
   total debt minus cash. Each filled value is named in `filled`. Cached for the day.
8. **Rules.** Banks, insurers and REITs get `[screener.<type>]`; everyone else gets
   `[category.<category>]` (utilities without `min_altman_z`). No profit fails outright; a
   blank category is "incomplete". Each rule gives pass, fail or missing; any fail = `fail`,
   otherwise any missing required rule = `incomplete`, otherwise `pass`. Optional rules with
   no data are skipped and listed in `flags`.
9. **Save.** `stage1.csv` (sorted by region, sector and market value) and the full pickle.

### Stage 2: cheapness (`analysis/stage2.py`)

1. **Load and check.** Stage 1's pickle is read and every column in `stage2.NEEDS` must be
   there, or Stage 2 stops and asks for Stage 1 to be rerun.
2. **Own P/E history (diluted).** For each Stage 1 pass: monthly Yahoo closes (cached for
   the day), converted to the statements' currency; for each of the last `history_years` (10)
   fiscal years, the average monthly close over that fiscal year (at least 9 months) divided
   by TradingView's diluted EPS for the year. Negative-EPS years are blank.
3. **Cheap P/E.** The `cheap_percentile` (0.25, the bottom quarter) of the positive yearly
   P/Es, if there are at least `min_history_years` (6). Fewer: no cheap price, not ranked.
4. **Sector cap.** The sector P/E is the median current P/E of every Stage 1 company in the
   same region and sector. The cheap multiple is the lower of the cheap P/E and the sector
   P/E (`cheap_basis` says which). This stops a stock whose whole history was priced for fast
   growth from looking cheap at a multiple its peers never get.
5. **Cheap price** = cheap multiple x 12-month EPS, in the trading currency. `vs_cheap` =
   price / cheap price - 1.
6. **Adjusted EPS refinement** (unless `--no-adjusted`). For the 9 closest names per sector
   (three times `top_per_sector`), Yahoo's reported quarterly EPS replaces diluted EPS with
   its own yearly P/E history (the watch list's method, calendar years) when it has 6 or more
   years and the adjusted figure is within a factor of 2 of diluted EPS (further apart is a
   data error, flagged). The cheap price is recomputed.
7. **Technicals, for timing only.** Trend from price and the 50- and 200-day averages, RSI
   (below 30 oversold, above 70 overbought), position in the 52-week range, TradingView's
   technical rating. None of them affects the ranking.
8. **Rank.** Stage 1 passes with `vs_cheap` at most `close_to_cheap` (0.15), sorted by
   `vs_cheap`, top `top_per_sector` (3) per region and sector. At or below the cheap price is
   "cheap"; up to 15% above is "close".
9. **SEC cross-check.** For US names on the list, the latest fiscal year's diluted EPS is
   compared with SEC EDGAR's frames API (`EarningsPerShareDiluted`, that calendar year); a
   gap over 10% is written to `flags`, and `sec_eps` records SEC's figure.
10. **Cash-flow gaps.** Blank operating cash flow, capex or free cash flow of the listed
    names are filled from Yahoo's last four quarters; then the ranking is redone.
11. **Save.** `top.csv`; `screener.py` also writes the dated full table.

### The growth screener (`analysis/growth_screen.py`)

A separate screener for testing (report 15; reference in
[`SCREENER.md`](SCREENER.md#the-growth-screener)):

```bash
uv run python analysis/growth_screen.py              # today's list -> data/screener/growth.csv
uv run python analysis/growth_screen.py --backtest   # and the backtest -> growth_backtest.csv
uv run python analysis/growth_screen.py --all        # every US and European company above $1bn
```

1. **Universe** as in Stage 1 (`stage1.fetch_universe` and `stage1.prepare`, same cache).
2. **Filter** (no price): revenue, net income and EPS growth over 5 fiscal years, profit
   every year, net margin above its sector's average, still growing in the last 12
   months.
3. **Rank the survivors** by P/E against their own yearly P/E history (Yahoo monthly prices,
   cached as `.cache/screener/prices_long_<date>.pkl`, 19 years for the backtest).
4. **Check the flags** before trusting a P/E (one-off gain, lumpy profit), then show the
   absolute values first, as for every analysis.

## 6. Metrics vectors

```bash
uv run python -m stock_analysis.metrics list --set proposed       # the 16 proposed metrics
uv run python -m stock_analysis.metrics doc                       # rewrite docs/METRICS.md
uv run python -m stock_analysis.metrics vector data/peers/medtech.csv --source sector BSX
uv run python -m stock_analysis.metrics vector data/screener/stage1.csv --source stage1 \
    --set stage1 --standardize percentile BSX
```

`--source` names the table (`sector`, `stage1`, `stage2`, `watchlist`); `--set` is a named
set, a group, a vector status or `all`; `--standardize` turns each metric into 0-100
percentiles (or z-scores) within the stocks given, with lower-is-better metrics reversed.

## 7. The evening run

[`EVENING_RUN.md`](EVENING_RUN.md) is the checklist the scheduled session follows at 21:00
Europe/Rome. What happens, in order:

1. **Set up.** `uv sync`, check out `main`, pull.
2. **Numbers first.** `uv run python analysis/screener.py` refreshes the market screener,
   then `uv run python analysis/watchlist.py --numbers` and
   `uv run python analysis/market.py --numbers` print today's figures (the market numbers
   include the screener's top names).
3. **Update Claude's notes** where the story changed (`Updated:` set to today): each stock's
   `notes.md` (search the news; after earnings update the verdict, the entry price and any
   `eps_override`), `analyses/market/notes.md` (the "Stocks to look at" section comments on
   the screener's names), `analyses/summaries/notes.md`.
4. **Build.** `uv run python analysis/watchlist.py`. In order:
   1. Fetch every watch-list stock and its peers from Yahoo.
   2. Rerun the market screener (`screener.run()`: Stage 1 then Stage 2 on the S&P 500;
      quick after step 2 because the day's downloads are cached). If it fails the run goes
      on and the market report uses the last results, marked as not from today.
      `--no-screener` skips it on purpose.
   3. Build the market report: indices, sectors, breadth, then the screener's Stage 1 pass
      counts and its top 3 cheap or close-to-cheap stocks per sector from
      `data/screener/top.csv`. Adds a line to `analyses/market/runs.csv`.
   4. One PDF per stock, a line in its `runs.csv`, its `README.md` rebuilt.
   5. The watch-list summary PDF, `analyses/README.md` rebuilt.
   6. The email body (`.cache/watchlist/email.html`) and `.cache/watchlist/last_run.json`.
5. **Check.** `uv run python analysis/validate.py` (the outputs are complete and
   consistent; a FAIL goes in the email; `--verbose` lists the rows behind each WARN), then
   `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
6. **Save.** Commit `analyses/` and `data/screener/` (`top.csv`, `stage1.csv` and the dated
   `YYYY-MM-DD.csv`), and any config or notes changes, to `main` and push. The push starts
   the Pages workflow, which also rebuilds the Screener page.
7. **Email.** `uv run python analysis/send_email.py` (recipients from `WATCHLIST_EMAIL_TO`, or
   `--to`). If Brevo is missing a setting or refuses, no email is sent: say so in the thread.

If a step fails, still commit what was built and say in the email what failed.

Useful variants:

```bash
uv run python analysis/watchlist.py BSX NFLX         # selected stocks only (no market report)
uv run python analysis/watchlist.py --no-market      # skip the market report and the screener
uv run python analysis/watchlist.py --no-screener    # market report on the last screener results
uv run python analysis/market.py                     # the market PDF alone
```

## 8. Publishing the site

Automatic: a push to `main` that touches `analyses/`, `data/screener/`, `analysis/site.py`
or the workflow runs `.github/workflows/pages.yml`, which runs `python analysis/site.py
_site` and deploys `_site/` to GitHub Pages. To run it by hand: GitHub, Actions, "Publish
analyses page", Run workflow. To preview locally:

```bash
python analysis/site.py _site
python -m http.server -d _site 8000     # then open http://localhost:8000/
```

`site.py` uses the standard library only, so it needs no `uv` environment.

## 9. Sending the email

```bash
uv run python analysis/send_email.py                 # to WATCHLIST_EMAIL_TO
uv run python analysis/send_email.py --test          # subject and body marked as a test
```

It reads `.cache/watchlist/last_run.json`, so it always sends the last run built in the same
container. It needs `BREVO_API_KEY` and `WATCHLIST_EMAIL_FROM`; the recipient is Babak, set in
`WATCHLIST_EMAIL_TO` (or passed with `--to`; at most 5 addresses). Never send it through
Babak's own Gmail.

## 10. Writing a report

1. Number it after the last report in `reports/` (`15-<topic>.md`).
2. Title, then an italic line with the data date, when it was written and the tools used.
3. **1. Summary:** the verdict in bold, then four one-line points (cheap, strong, weak,
   uncertain). Short, no detail.
4. **2. The numbers:** absolute values first (latest 12 months, then the yearly history),
   then method, ratios and screens.
5. **3. Analysis:** Claude's reading (own-history P/E, why it moved, entry price, what to
   watch).
6. **Caveats**, then **Reproduce** with the exact commands.
7. Add a line to the table in `reports/README.md`.
8. When the analysis is redone with new data, update the report and its date; don't leave
   stale numbers.

## 11. Adding a stock to the watch list

1. Run the single-stock analysis (section 4) and write its report.
2. Add a block to `config/watchlist.toml`:

   ```toml
   [[stock]]
   symbol = "XYZ"
   peers = ["AAA", "BBB", "CCC"]
   target_pe = 15
   target_note = "Proposed YYYY-MM-DD (report NN), not yet confirmed by Babak: ..."
   ```

3. Write `analyses/XYZ/notes.md` with an `Updated:` line and the sections `## Verdict`,
   `## Summary`, `## Business`, `## Risks`, `## News`, `## What to watch`. If it is missing,
   the evening session (Claude, not the code) writes a short first analysis; the PDF shows
   "Not written yet" for any missing section.
4. Check: `uv run python analysis/watchlist.py XYZ --numbers` and `uv run pytest
   tests/test_watchlist.py`.
5. Commit to `main`. The next evening run includes it. To drop a stock, delete its block; its
   dated analyses stay.

## 12. Changing screener rules

1. Edit `config/screeners.toml`: a threshold, a rule in a `[category.*]` or `[screener.*]`
   set, the `optional` list, a `[lynch]` threshold, the `[types]` industry lists or the
   `[universe]`.
2. A new kind of rule needs code: a branch in `stage1._rule()` and a label in
   `stage1.RULE_LABELS` (`tests/test_screener.py` fails on an unknown rule). If Stage 2 needs a
   new Stage 1 column, add it to `stage2.NEEDS`.
3. Run `uv run python analysis/screener.py` and compare the pass counts and the top list with
   the last run.
4. Update [`SCREENER.md`](SCREENER.md), report 13 (numbers and date), and the methods doc;
   record the change and who decided it in [`DECISIONS.md`](DECISIONS.md).
5. Run the pre-commit check and commit.

## 13. Adding an absolute value or a metric

**An absolute value** (when Babak names a new one):

1. Add it to the right group in `config/absolute_values.toml` (`column`, `label`, `unit`, and
   `history` if the yearly column has another name, or `""` if there is no history).
2. If `data/sector/utilities.csv` has no such column, compute it in `sector.analyse()`; if
   the history has none, add the tags to `history.py`.
3. Refresh: `uv run python analysis/sector.py && uv run python analysis/history.py`.
4. `uv run pytest tests/test_absolute.py`. The dashboard and the PDFs pick it up from the
   config: `uv run python dashboard/build_absolute.py`.

**A metric:**

1. Add a `[[metric]]` to `config/metrics.toml` with every field (id, name, group, unit,
   better, period, definition, formula, sources, used_in, example, vector; notes optional).
2. Add it to a named set if it belongs there.
3. `uv run python -m stock_analysis.metrics doc` to regenerate `docs/METRICS.md`.
4. `uv run pytest tests/test_metrics.py` (it fails if the doc is stale or a field is missing).
