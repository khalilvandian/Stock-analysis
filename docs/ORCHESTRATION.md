# The nightly pipeline (orchestration)

Issue #30. Apache Airflow 3 runs every timed piece of the project as a task: it starts each
Azure job run, checks what the run stored, logs every step in the database, and emails an
alert when a step fails or never happens. Before this, each piece ran on its own clock and
nothing noticed when one stopped. In November 2026 the evening routine was switched off for
three weekdays without anyone noticing.

Two things stay outside Airflow on purpose:
- The **Claude session**, which reads the data and writes the notes, keeps its own schedule.
  Airflow checks that it committed and that the site published it.
- The **audit** (`pipeline-watch.yml`) has to work when Airflow is down.

The diagrams are in [`pipeline.html`](pipeline.html), section "The nightly pipeline, in
UML": the night and the hourly quotes as activity diagrams, the state machine of a run, and
the deployment on Azure.

## The DAGs

### `stock_nightly`: weekdays from 22:30 UTC

```
start → fetch → check_fetch → build → check_build, then in parallel:
    quality                                         ─┐
    coverage ─────────────────────┐                  ├→ finish
    nightly → check_nightly ──────┴→ publish_site    ─┤
    check_prices → mark_ready → wait_for_evening     ─┘
```

| Task | Runs | Passes when | Fails when |
|---|---|---|---|
| `start` | Opens the run log: a row in `ops_pipeline_run` (status `running`) | The row exists | The database can't be reached (retried) |
| `fetch` | A run of the Azure job `stock-ingest`: `db ingest --no-build --no-site` (the sources into the raw layer) | The run succeeds | The run fails (retried once as a new run) |
| `check_fetch` | SQL: the newest row in `ops_run` since the start | `ok` or `partial` | None, or `failed` |
| `build` | A run of `stock-ingest`: `db build` (the core layer, from what changed) | The run succeeds | The run fails (retried once) |
| `check_build` | SQL: the newest row in `core_build` since the start | `ok` | None, or `failed` (with the error) |
| `quality` | A run of `stock-ingest`: `db check` | No FAIL | Any FAIL (the database's own checks) |
| `coverage` | A run of `stock-ingest`: `db coverage` (the Data page's snapshot) | The run succeeds | The run fails |
| `nightly` | A run of `stock-ingest`: `db nightly` (the screener, each watch-list stock's numbers, the market numbers) | Every part succeeds | Any part fails: the command exits 1 |
| `check_nightly` | SQL: a screener run, the market numbers, and numbers for every watch-list stock stored since the start | All there | Something missing (named) |
| `publish_site` | GitHub's API: start the Pages workflow | GitHub accepts it | No `GITHUB_DISPATCH_TOKEN`, or GitHub refuses |
| `check_prices` | SQL: each current S&P 500 member's newest price in `core_price_daily` | At least 95% have the last US close | Fewer: the prices are stale |
| `mark_ready` | Sets the run to `ready`: the marker | Always | The database can't be reached |
| `wait_for_evening` | In the triggerer, every 10 minutes: a `Watch list analyses …` commit on `main` since the start, then a successful Pages run for it | Both found | No commit 5 hours after the start, or the Pages run failed |
| `finish` | Sets the run to `ok` (a run already `failed` stays `failed`) | Every branch passed | — |

### `stock_quotes`: 5 minutes past every hour, Monday to Friday

`start → quotes → check_quotes → finish`. `quotes` is a run of the Azure job `stock-quotes`
(`db quotes`). `check_quotes` passes when the run stored its quotes, or found the same
prices as last time (the market is closed), and fails on an error.

### Rules for every task

- **Job runs:** a task starts one run through Azure Resource Manager's API, with its own
  command (the job's image, environment and secrets stay as configured), then waits in the
  triggerer (deferred), so no task slot is held while it waits. A failed run fails the task;
  a retry is a new run. The jobs have **no schedule of their own**, and there is **no
  fallback**: a failure should show.
- **Checks** are a few milliseconds of SQL inside Airflow (`stock_analysis.pipeline`, which
  needs only psycopg and httpx). A failed check fails at once, with no retry.
- **Any failure** marks the run `failed`, writes the step's row, and emails
  `PIPELINE_ALERT_TO` (else `WATCHLIST_EMAIL_TO`) through Brevo, with a link to the step's
  log. Alerts go straight from Airflow, so they still go out when Azure is the thing failing.
- **The database firewall:** every command a job runs opens its own rule for its run
  (`ingest-job`, `build-job`, `coverage-job`, `check-job`, `nightly-job`, `quotes-job`), so
  runs going at the same time never remove each other's access.

## The audit

`pipeline-watch.yml` runs on GitHub Actions every 3 hours (at :20) and reads the run log
through the web API: `python -m stock_analysis.pipeline audit`. It checks:
- the last trading day's `stock_nightly` run finished `ok`, once it should be over (8 hours
  after the close);
- on weekdays, an `ok` `stock_quotes` run in the last 2 hours.

A failed check fails the workflow, and GitHub emails the repository owner.

## The run log

Two tables (migration `011`, [`DATABASE.md`](DATABASE.md)):

- `ops_pipeline_run`: one row per DAG run: `pipeline` (`stock_nightly`, `stock_quotes`),
  `run_key` (Airflow's run id), `run_date` (the trading day), `started_at`, `ready_at`,
  `finished_at`, `status` (`running` → `ready` → `ok`, or `failed`), `host`.
- `ops_pipeline_step`: one row per step and run: `status` (`ok`, `waiting`, `failed`), the
  time and a JSON `detail` (what the check found, which job run).

```sql
SELECT r.pipeline, r.run_date, r.status, s.step, s.status, s.at, s.detail
FROM ops_pipeline_run r JOIN ops_pipeline_step s USING (run_id)
ORDER BY r.run_id DESC, s.at;
```

## The Claude session

It keeps its own schedule: 00:00 Italy time, Tuesday to Saturday. It waits up to an hour for
the newest price. The marker tells it more:

```bash
uv run python -m stock_analysis.pipeline marker   # exit 0 = ready; 3 = not yet; 4 = the run failed
```

A failed run goes at the top of its email ([`EVENING_RUN.md`](EVENING_RUN.md), step 1). In
summer 00:00 Italy time is 22:00 UTC, before the night starts at 22:30 UTC; the session's own
wait for the price is what covers that.

## Where it runs

Developed and tested locally in Docker; production on Azure (decided 2026-11-19,
[`DECISIONS.md`](DECISIONS.md)). Only the parts that must always run are on the VM.

| Part | Production | Cost |
|---|---|---|
| Scheduler (LocalExecutor, 4 task slots), DAG processor, triggerer, `api-server --apps execution` (the API tasks report to) | A free **B2ats v2** Linux VM (2 vCPU, 1 GiB; 750 free hours a month), in Docker | $0 |
| The UI and REST API: `api-server --apps core` | A **Container App that scales to zero**, open only to your IP | about $0 |
| Airflow's own database | An `airflow` database on `stock-db-bk`, with small connection pools (the server allows 50 connections in all) | $0 |
| Task logs | Blob storage (Airflow's remote logging), so the UI can read what the VM wrote | cents |
| The work | The existing Container Apps Jobs `stock-ingest` and `stock-quotes`, started by Airflow | per second, mostly inside the free allowance |
| Starting the jobs | The VM's managed identity, allowed to start only those two jobs | — |

The image (`orchestration/Dockerfile`) is the official `apache/airflow:3.4.0-python3.12` with
the DAGs, the plugin `stock_orch` and `stock_analysis.pipeline` copied in. It doesn't need
the project's own dependencies: those stay in the jobs' image.

## Running it locally

From the repository root, with Docker Desktop running. The compose file has the same layout
as Azure, plus a local metadata PostgreSQL:

```bash
docker compose -f orchestration/compose.yaml up -d --build --wait   # UI at http://127.0.0.1:8080
docker compose -f orchestration/compose.yaml exec airflow-scheduler airflow dags list-import-errors
docker compose -f orchestration/compose.yaml down                   # stop; the history stays
```

- `.env` settings:
  - `AIRFLOW__API_AUTH__JWT_SECRET` (any long random text);
  - `STOCK_WRITER_DB_PASSWORD`, or `STOCK_PIPELINE_DB_URL` for another database;
  - `BREVO_API_KEY`, `WATCHLIST_EMAIL_FROM` and `PIPELINE_ALERT_TO` for the alert;
  - `GITHUB_DISPATCH_TOKEN`: a fine-grained token for this repository with "Actions: write";
  - `AZURE_SUBSCRIPTION_ID`.
- Starting the real Azure jobs from the PC needs a short-lived token:
  `AZURE_ARM_TOKEN=$(az account get-access-token --query accessToken -o tsv)`, given to
  `docker compose up`. On the VM the managed identity replaces it.
- Every check also runs by hand: `uv run python -m stock_analysis.pipeline check-prices
  RUN_KEY` (after `start RUN_KEY`).

## Checks

- `tests/test_pipeline.py` (the usual `uv run pytest`): trading days, every check against the
  local test database, GitHub and Brevo mocked with `respx`, and a test that the module
  imports without pandas or SQLAlchemy.
- `orchestration/tests/` runs in the Airflow image: the job operator and its trigger, the
  evening trigger, the UI's firewall rule, and the DAGs' task order.

  ```bash
  docker compose -f orchestration/compose.yaml run --rm --no-deps --entrypoint bash airflow-scheduler \
      -c "pip install -q pytest respx && cd /opt/stock/orchestration/plugins && \
          python -m pytest -q -p no:cacheprovider /opt/stock/orchestration/tests"
  ```
- Checked against Azure from local Airflow (2026-11-19):
  - a `stock_quotes` run started by Airflow ran on Azure and stored 514 quotes on the server;
  - two `stock-ingest` runs started at the same time both succeeded, so the parallel
    quality, coverage and nightly steps work.

## Memory on the VM

Measured at rest in this layout (2026-11-19): scheduler 261 MiB, execution API 251 MiB,
triggerer 224 MiB, DAG processor 194 MiB, about 930 MiB together. Ubuntu needs about 200 MiB
more, so the free 1 GiB VM gets a 3 GiB swap file at first boot
(`deploy/airflow/cloud-init.yaml`). The execution API and the triggerer sit idle most of the
day and can swap out. If the VM is slow or a process is killed for memory, resize it to B1ms
(2 GiB, about $18 a month), with nothing to reinstall: `az vm resize -g stock-rg -n airflow-vm
--size Standard_B1ms`.

## Going live

All after the merge to `main`, in this order. The jobs' cron and Airflow change hands in one
evening: never before (nothing would run) and never after (everything would run twice).

1. The workflows build `stock-analysis-ingest` (with `--no-nightly`, `--no-site` and the
   firewall rule per command) and `stock-airflow`. Make the `stock-airflow` package public
   (GitHub, Packages, its settings), as the ingest image is.
2. Add `GITHUB_DISPATCH_TOKEN` to `.env`: a fine-grained token for this repository with
   "Actions: write".
3. `powershell -ExecutionPolicy Bypass -File deploy\ingest-job.ps1`, then
   `deploy\quotes-job.ps1`: both jobs are recreated with trigger Manual (no schedule).
4. `powershell -ExecutionPolicy Bypass -File deploy\airflow.ps1`. It creates Airflow's
   database (and applies migration `011`), Blob logging, the UI app, and the VM with Airflow
   running, then unpauses both DAGs. To use a VM made on Azure's "Free account virtual
   machine" page instead, create it first as `airflow-vm`; the script then skips that step.
5. Open the UI (the script prints its address), trigger `stock_quotes` once, and watch the
   first night. The audit checks it from the next 3-hour slot on.

## Not done yet

Follow-ups (a separate issue): housekeeping (`airflow db clean`, log retention), warnings
before credentials expire, manual DAGs for `db reparse`, and the bulk SEC files. A stricter
hourly check (the quotes must come from the current US session) is optional.
