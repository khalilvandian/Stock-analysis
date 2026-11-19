# The nightly pipeline (orchestration)

Issue #30. One Apache Airflow 3 DAG, `stock_nightly`, ties the scheduled pieces together:
the Azure ingest job (with its nightly analyses), the hourly quotes job, the scheduled
Claude session and the site. It waits for each piece, checks what it produced, logs every
step in the database and emails an alert when a step fails or never happens. Before it existed, each piece ran on its own
clock and nothing noticed when one stopped. In November 2026 the evening routine was switched
off for three weekdays without anyone noticing.

The diagrams are in [`pipeline.html`](pipeline.html), section "The nightly pipeline, in
UML": an activity diagram of one night, the state machine of a run and the deployment
diagram.

## The night, in UTC (winter; Italy is UTC+1, UTC+2 in summer)

| When | What | Where |
|---|---|---|
| :05 every hour, Mon–Fri | Quotes job: the latest price of every company | Azure Container Apps Job `stock-quotes` |
| 22:30 | Ingest job: fetch, build, coverage, then the nightly analyses (screener, watch-list and market numbers) | Azure Container Apps Job `stock-ingest` |
| 22:35 | **`stock_nightly` starts** | Airflow on the PC |
| 23:00 (00:00 Italy), Tue–Sat | The scheduled Claude session: waits for the newest price, writes the notes and PDFs, commits "Watch list analyses …", emails | Anthropic's cloud |
| after that commit | The site is rebuilt | GitHub Pages |
| 05:15 | The site is rebuilt from the database | GitHub Pages |
| 07:00, Tue–Sat | Morning audit: the last trading day has an `ok` run | GitHub Actions, `pipeline-watch.yml` |

## What the DAG runs

```
start ─┬─► wait_for_ingest ─┬─► check_prices ─► mark_ready ─► wait_for_evening ─┐
       │                    └─► check_nightly ─────────────────────────────────┤
       └─► check_quotes ───────────────────────────────────────────────────────┴─► finish
```

| Step (Airflow task) | What it does | Passes when | Fails when |
|---|---|---|---|
| `start` | Opens the run log: a row in `ops_pipeline_run` (status `running`) | The row exists | The database can't be reached (retried twice) |
| `check_quotes` | The newest stored fetch of the quotes job (`raw_fetch`, source `tradingview_quotes`) | It is at most 4 hours old, or today isn't a trading day | Older: the job stopped (the last error, if any, is in the message) |
| `wait_for_ingest` | Sensor, every 5 minutes: the Azure job `stock-ingest` has a finished row in `ops_run` that started at most 20 minutes before the DAG | The row is `ok` or `partial` | The row is `failed`, or there is none after 3.5 hours |
| `check_nightly` | The nightly analyses in that run's summary | No `nightly_error`, `screener_error` or `market_error`, and no watch-list stock failed | Any of those: the evening session computes the missing numbers on the spot, so this one alerts without holding back the marker |
| `check_prices` | Each current S&P 500 member's newest price in `core_price_daily` | At least 95% have the last US close | Fewer do: the prices are stale |
| `mark_ready` | Sets the run to `ready`: the marker | Always | The database can't be reached |
| `wait_for_evening` | Sensor, every 10 minutes: GitHub has a `Watch list analyses …` commit on `main` since the run started, and a successful Pages run for it | Both are found | No commit 5 hours after the start, or the Pages run failed |
| `finish` | Sets the run to `ok` (a run already `failed` by a side check stays `failed`) | Every branch passed | The database can't be reached |

The "last US close" is the newest weekday that isn't an NYSE holiday and is at least 21:30
UTC old (`config/pipeline.toml`, `[nyse]`; `tests/test_pipeline.py` fails in December until
next year's holidays are added).

Any failure marks the run `failed`, writes the step's row, and emails `PIPELINE_ALERT_TO`
(else `WATCHLIST_EMAIL_TO`) through Brevo, with a link to the step's Airflow log. A crash
(network, database) is retried twice with backoff first. A failed check is not retried.

**When Airflow itself doesn't run** (the PC is off, Docker is stopped, the DAG is paused),
nothing on the PC can say so. The GitHub workflow `pipeline-watch.yml` runs at 07:00 UTC
Tuesday to Saturday and runs `python -m stock_analysis.pipeline audit` through the web API.
When the last trading day has no `ok` run, the workflow fails, and GitHub emails the
repository owner.

## The run log

Two tables (migration `011`, [`DATABASE.md`](DATABASE.md)):

- `ops_pipeline_run`: one row per DAG run: `run_key` (Airflow's run id), `run_date` (the
  trading day), `started_at`, `ready_at`, `finished_at`, `status` (`running` → `ready` → `ok`,
  or `failed`), `host`.
- `ops_pipeline_step`: one row per step and run: `status` (`ok`, `waiting`, `failed`), the
  time and a JSON `detail` (what the check found: ingest run id and rows, members with the
  last close, the commit found).

```sql
SELECT r.run_date, r.status, s.step, s.status, s.at, s.detail
FROM ops_pipeline_run r JOIN ops_pipeline_step s USING (run_id)
ORDER BY r.run_id DESC, s.at;
```

## The scheduled Claude session

The notes need Claude, which runs in Anthropic's cloud with its own clone of the repository.
Airflow doesn't start it (decided 2026-11-18, [`DECISIONS.md`](DECISIONS.md)). The session
keeps its own schedule, 00:00 Italy time Tuesday to Saturday, and its own wait: it checks the
newest price and waits up to an hour for the ingest. The marker tells it more:

```bash
uv run python -m stock_analysis.pipeline marker   # exit 0 = ready; 3 = not yet; 4 = the run failed
```

It reads `ops_pipeline_run` through the web API. A failed run goes at the top of the email
([`EVENING_RUN.md`](EVENING_RUN.md), step 1). Airflow then waits up to 5 hours from its own
start for the session's commit and the site.

In summer 00:00 Italy time is 22:00 UTC, before the ingest starts at 22:30 UTC. The session
still waits for the newest price (up to an hour), so it usually lands after the ingest, but
with less room than in winter.

## Running it

On the PC, from the repository root (Docker Desktop running):

```bash
docker compose -f orchestration/compose.yaml up -d --build --wait   # start; UI at http://127.0.0.1:8080
docker compose -f orchestration/compose.yaml exec airflow-scheduler airflow dags unpause stock_nightly
docker compose -f orchestration/compose.yaml exec airflow-scheduler airflow dags trigger stock_nightly
docker compose -f orchestration/compose.yaml down                   # stop; the history stays
```

- `.env` must have `AIRFLOW__API_AUTH__JWT_SECRET` (any long random text). The steps also use
  `STOCK_WRITER_DB_PASSWORD`, and `BREVO_API_KEY`, `WATCHLIST_EMAIL_FROM` and
  `PIPELINE_ALERT_TO` for the alert. Without the Brevo settings, the failure is still logged,
  but no email is sent.
- `STOCK_PIPELINE_TARGET` picks the stock database: `server-writer` by default. For a test
  against the local Docker database, start with `STOCK_PIPELINE_TARGET=` (empty) and
  `STOCK_PIPELINE_DATABASE_URL=postgresql://stock:<password>@host.docker.internal:5432/stock`.
- Airflow keeps its own state in its own PostgreSQL container (`airflow-db` volume), never in
  the `stock` database.
- The image (`orchestration/Dockerfile`) is the official `apache/airflow:3.4.0-python3.12`
  plus this project's dependencies in `/opt/stock-venv`. The two pin different SQLAlchemy
  versions, so the DAG runs `python -m stock_analysis.pipeline …` with the project's
  interpreter rather than importing it. The code is mounted read-only at `/opt/stock`, so a
  change to the DAG or the checks needs no rebuild. A change to `pyproject.toml` or
  `uv.lock` does.
- Every step also runs by hand without Airflow:
  `uv run python -m stock_analysis.pipeline check-prices manual__test` (after `start manual__test`).

Exit codes of `python -m stock_analysis.pipeline`: 0 done, 3 not yet (a sensor tries again),
4 failed (no retry). Anything else is a crash, which Airflow retries.

## Checks

- `tests/test_pipeline.py`: trading days, every check against the local test database, and
  GitHub and Brevo mocked with `respx`.
- The DAG's integrity inside the image:
  `docker compose -f orchestration/compose.yaml exec airflow-scheduler airflow dags list-import-errors`
  ("No data found" means none) and `airflow tasks list stock_nightly`.

## Not done yet

- Airflow triggers the Azure job itself (a deferrable Container Apps Jobs operator). Today it
  waits for the job's own 22:30 schedule.
- The screener and the reports run inside the DAG. That needs them to read from the database,
  so the cloud session only writes the notes.
- Where Airflow runs in production: the PC (now) or Azure Container Apps (cost to measure).
