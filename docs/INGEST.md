# The ingest job

Status: built and tested locally, 2026-11-17 ([issue #18](https://github.com/khalilvandian/Stock-analysis/issues/18)).
The job fills the database ([`DATABASE.md`](DATABASE.md)) from every free source on a schedule,
as much as each source allows per run. It runs in backfill mode until the S&P 500 is complete,
then switches to maintenance mode, which keeps the data current with fewer calls. How
"complete" is measured is in [`COVERAGE.md`](COVERAGE.md); the coverage page on the site shows it.

```bash
uv run python -m stock_analysis.db ingest                  # one run on the selected target
uv run python -m stock_analysis.db ingest --limit 3        # a small test: 3 tasks per source
uv run python -m stock_analysis.db ingest --sources yahoo_prices --no-build
uv run python -m stock_analysis.db ingest --due-now sec_companyfacts   # refetch a source now
uv run python -m stock_analysis.db reparse     # SEC facts of newly mapped tags, from kept files
uv run python -m stock_analysis.db tasks                   # the to-do list, by source and status
uv run python -m stock_analysis.db coverage                # today's coverage (and the snapshot)
```

Every command takes `--target`. On Azure the job runs as `server-writer`.

## One run

1. **Lock.** A PostgreSQL advisory lock allows one run per database. A second run that starts
   while one is going (a run that overran into the next schedule, or one started by hand)
   stops at once with status `skipped`. A run still marked `running` from before was killed
   part-way and is marked `failed`.
2. **Plan.** It makes sure every task exists, in `ops_task`:
   - the global tasks `tradingview` (the index members), `sec_tickers` (the CIKs) and
     `ecb_rates`
   - one task per S&P 500 member for `sec_companyfacts`, `yahoo_prices`, `yahoo_earnings` and
     `yahoo_statements`
   - one `sec_companyfacts` task per predecessor CIK (`CIK` + number, `[[predecessor]]` in
     `config/companies.toml`): a company's filings from before a new holding company took
     over

   The members are the newest TradingView snapshot, one listing per company (the primary
   listing where it is a member, otherwise the member listing: BRK.B, BF.B, GM). A company that leaves the index keeps
   its data, but its tasks become inactive. A new member gets its tasks and is fetched first.
3. **Mode.** `backfill` while any task has never been fetched, or the last coverage snapshot
   has less than `present_share_to_maintain` (90%) of the required values. Otherwise
   `maintain`. Backfill means "fetch everything once"; the gaps left after it are mapping work,
   not fetching. `--mode` forces one.
4. **Fetch.** The sources run in the `order` of `config/ingest.toml`. For each one it takes
   the tasks that are due: never-fetched ones first, then the most overdue. Each task runs in
   its own transaction, so a failure loses only that task. A source group stops when:
   - its request **budget** for the run is used
   - the source answers **"too many requests"** (HTTP 429, or SEC's 403)
   - **15 failures in a row** (10 for SEC)
   - the run has passed **`max_minutes`** (150)

   After a success the task is due again after the source's `refresh_days` for that mode.
   After a failure it's due after 6 hours, doubling with each further failure, up to a day.
   "Nothing there" (a 404, a company without a CIK) is `empty` and is tried again after 7
   days. A rate limit isn't a failure: the task stays due for the next run.
5. **Build** the core layer, if anything new was stored ([`DATABASE.md`](DATABASE.md), "Build rules").
6. **Coverage snapshot** of the day (`out_coverage_snapshot`).
7. **Site.** It asks GitHub to rebuild the site (the Pages workflow, through `workflow_dispatch`),
   so the Data page shows the new coverage a few minutes later. This needs
   `GITHUB_DISPATCH_TOKEN`: a fine-grained personal access token for this repository only,
   with "Actions: Read and write". Without it, the workflow's daily schedule (05:15 UTC)
   rebuilds the page.
8. The run is a row in `ops_run`: requests and results per source, what stopped each
   source, the build, the coverage, and status `ok`, `partial` (something stopped or failed)
   or `failed`.

## Sources

| Task | What it stores | Calls | Limit | Due again (backfill / maintain) |
|---|---|---|---|---|
| `tradingview` | The S&P 500 members (`raw_tv_constituent`): one scan of the US market, filtered to the index | 1 | None published | 1 / 1 day |
| `sec_tickers` | Ticker to CIK (`raw_sec_ticker`) | 1 | 10 a second | 7 / 7 days |
| `ecb_rates` | Exchange rates, last 10 days (`raw_ecb_rate`) | 1 | None | 1 / 1 day |
| `sec_companyfacts` | Every filed value of the mapped tags (`raw_sec_fact`), with the real filing date | 1 per company | 10 a second; a `SEC_USER_AGENT` naming you is required | 30 / 7 days |
| `sec_xbrl` | The full XBRL of a 10-K or 10-Q (edgartools), for the facts company facts leaves out: a value reported only per share class (`raw_sec_xbrl_fact`, with its axis and member). Only the filings that report a missing value of a company with a `[[share_class]]` in `config/companies.toml` | About 8 per filing | Shares the SEC group's rate and budget | Once (3650 days) |
| `yahoo_prices` | Daily prices (`raw_yahoo_price`): from 2015-12-01 the first time, then from 10 days before the newest stored day. A split in the new days fetches the whole history again (it rescales every price) | 1, or 2 after a split | Yahoo throttles; budget 4,000 / 1,200 calls per run | 1 / 1 day |
| `yahoo_earnings` | Earnings dates with estimated and reported EPS (`raw_yahoo_earnings`) | 1 | as above | 30 / 7 days |
| `yahoo_statements` | Six statements, annual and quarterly (`raw_yahoo_statement`) | 6 | as above | 30 / 7 days |

Every payload is kept as the source returned it, gzip-compressed, in `raw_payload` (one row
per distinct payload, on its `raw_fetch`): the SEC files, TradingView's scan, the ECB's CSV,
and the tables yfinance returns. The raw tables hold what is parsed from them. Payloads seen
before are not stored again, and only new or changed rows go into the raw tables. This
follows the same rules as `load-files`: every row points to its `raw_fetch`.

`raw_sec_fact` keeps only the SEC tags in `config/db_items.toml`, about 4,700 of a company's
roughly 27,000 facts; the whole file (about 0.25 MB compressed, 4 MB as JSON) is in
`raw_payload`. After mapping a new tag, read it from the kept files instead of asking SEC
again:

```bash
uv run python -m stock_analysis.db reparse    # the new tag's facts, from the kept files
                                               # (company facts, full filings, data-set quarters)
uv run python -m stock_analysis.db build
```

Files fetched before the payloads were kept (before migration 008) get their copy on their
next fetch.

How long a backfill takes: SEC needs about 500 calls (about 10 minutes) and Yahoo about 4,000
(about an hour), so the S&P 500 can fill in one or two nights if Yahoo doesn't throttle.

## Files downloaded by hand (`db import`)

A file found or downloaded on this PC is loaded instead of being fetched again:

```bash
uv run python -m stock_analysis.db import inbox/sec_companyfacts/companyfacts.zip                  # local
uv run python -m stock_analysis.db import inbox/sec_companyfacts/companyfacts.zip --target server  # Azure
uv run python -m stock_analysis.db import FILE --symbols COST,KR                                   # a sample
```

The file goes through the same parser as its API source, into the same raw tables: a
`raw_fetch` row per payload with `url` `file:<name>`, the payload kept in `raw_payload`, and a
payload seen before skipped. The tasks it covered count as fetched on the file's date
(`ops_task`), so the job, here or on the server, doesn't download them again. With
`--target server` the Azure database receives the data from this PC; the cloud job never
needs the file. Files wait in `inbox/<kind>/` (ignored by git); the folder's name is the
kind, or pass `--kind`.

| Kind | File | Notes |
|---|---|---|
| `sec_companyfacts` | SEC's `companyfacts.zip` (every company's company facts, 1.4 GB, rebuilt nightly at sec.gov/Archives/edgar/daily-index/xbrl/), or one `CIK##########.json` | Only the companies the database follows (the universe and the predecessors) |
| `sec_fsds` | A quarter of SEC's Financial Statement Data Sets (`2026q3.zip`, about 80 MB, at sec.gov/files/dera/data/financial-statement-data-sets/) | Every filing's numbers, with the companies' own tags and the dimensions company facts leaves out. For the followed companies' 10-K and 10-Q, into `raw_sec_xbrl_fact`: their own tags; the values per share class of the concepts read per class; and the mapped standard tags of the filings company facts lacks (some never reach it: DTE's, Dominion's and Digital Realty's 10-Qs for June 2026). Subsidiaries' values (co-registrants) are left out. About 10 seconds a quarter |

A payload larger than 50 MB (a data-set quarter) is not copied into the database, to keep the
free Azure server small: the file stays in `inbox/` and `raw_fetch.url` names it. Downloading:
`curl -A "$SEC_USER_AGENT" -o inbox/sec_fsds/2026q3.zip https://www.sec.gov/files/dera/data/financial-statement-data-sets/2026q3.zip`
(SEC serves these files to any client that names itself, no browser needed).

## Sending the PC's data to the server (`db push`)

The analysis and the heavy loading (bulk files, full filings) happen on this PC; the server
should not ingest them again:

```bash
uv run python -m stock_analysis.db push --target server            # from the selected (local) db
uv run python -m stock_analysis.db push --target server --sources sec_xbrl
```

A push replays every kept payload the target lacks (same source, request key and content
fingerprint) for `sec_companyfacts` and `sec_xbrl`: the payload is stored there and parsed on
this PC by the source's own loader, so the target keeps its own "new or changed rows only"
history; the target's tasks count as fetched. Data-set quarters are imported into the target
from their file in `inbox/`. Yahoo, TradingView and the ECB are cheap and fetched by the server
itself. Raw rows are never copied table to table: they are stored relative to the sending
database's own earlier versions. The server's next job run rebuilds core because raw data
arrived after its last build, even though the run itself stored nothing. Run a push only
after the branch is merged and deployed, so the server has the migrations.

## Where it runs

| | |
|---|---|
| **Service** | Azure Container Apps **Job** `stock-ingest`, in the environment `stock-jobs-env` (resource group `stock-rg`, workload-profiles mode, Consumption profile; an "Express" environment, which newer CLIs create by default, cannot run jobs). Billed per second while it runs, inside the monthly free grant (180,000 vCPU-seconds, 360,000 GiB-seconds) |
| **Schedule** | Every day at 22:30 UTC (`30 22 * * *`), after the US close. At most 3 hours, no retries: the next run carries on |
| **Size** | 1.5 vCPU, 3 GiB. The full build of the S&P 500 peaks at 1.7 GiB (measured in the container at 2 GiB) and takes about 11 minutes |
| **Image** | `ghcr.io/khalilvandian/stock-analysis-ingest:latest`, built from the `Dockerfile` by the workflow `ingest-image.yml` on every push to `main` that changes `src/`, `config/` or the dependencies. The job pulls it at every run, without a password: the package is public because the repository is |
| **Settings** | `STOCK_DB_TARGET=server-writer`; secrets `STOCK_WRITER_DB_PASSWORD`, `SEC_USER_AGENT` and (optional) `GITHUB_DISPATCH_TOKEN`; `AZURE_SUBSCRIPTION_ID` |
| **Database access** | The firewall admits only listed addresses, and the job's address changes. So each run uses the job's managed identity to set the firewall rule `ingest-job` to its own address, and deletes the rule at the end (`JobFirewall` in `src/stock_analysis/db/azure.py`). The identity is Contributor on the database server only |
| **Deploy or update** | `powershell -ExecutionPolicy Bypass -File deploy\ingest-job.ps1` (add `-RunNow` to start a run). It also applies the migrations and the users' rights on the server |
| **See the runs** | `az containerapp job execution list -n stock-ingest -g stock-rg -o table`, a run's output with `az containerapp job logs show -n stock-ingest -g stock-rg --execution <name> --container stock-ingest --format text`, the logs in the job's Log Analytics workspace, `ops_run` in the database, and the coverage page |

The same image runs locally against the Docker database:

```bash
docker build -t stock-ingest .
docker run --rm -e DATABASE_URL=postgresql://stock_writer@host.docker.internal:5432/stock \
  -e PGPASSWORD=<the writer password> stock-ingest ingest --limit 3
```

## Settings (`config/ingest.toml`)

- `max_minutes`: when the run stops starting new tasks.
- `[groups.*]`: the budget per mode, the pause between calls (`min_interval_s`) and the
  failures in a row that stop the group (`stop_after_errors`).
- `[sources.*]`:
  - `group`
  - `order`
  - `requests` per task, which counts against the budget
  - `refresh_days` per mode
- `prices_from`, `price_overlap_days`, `error_retry_hours`, `empty_retry_days`.

Code: `src/stock_analysis/ingest/` (`job.py` the queue and runs; `sec.py`, `yahoo.py` and
`market.py` the sources; `common.py` the raw-layer helpers). Tests: `tests/test_ingest.py`
(HTTP mocked with respx, Yahoo through a fake client, the database tests on the local Docker
PostgreSQL).
