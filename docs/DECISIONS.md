# Decision log

The decisions that shape the project, newest last within each day. Each says who decided,
what, and why. "Babak" means Babak decided or approved it; "Claude, pending Babak" means
Claude took a default that Babak has not yet confirmed. Add new decisions at the end with
their date.

## 2026-10-25

### Yahoo Finance and SEC EDGAR are the primary sources, not FMP

- **Who:** Babak, on Claude's test results (report 01).
- **Decision:** Yahoo Finance supplies current figures and prices; SEC EDGAR supplies the
  history. Financial Modeling Prep was kept only as a client (`FMPClient`), removed in
  issue #33 with the other unused code.
- **Why:** FMP's free plan returned HTTP 402 for most symbols (every CEG endpoint but the
  profile), and by 2026-10-27 the key in use was invalid. The project works on free sources
  without any key.

### SEC is primary for the yearly history; Yahoo fills the gaps

- **Who:** Babak, on Claude's proposal (in use since 2026-09-28, recorded in reports 01 and 10).
- **Decision:** (`history.py` was retired in issue #33; the database's build follows the same
  rule.) `history.py` takes annual 10-K, 20-F and 40-F figures from SEC company facts
  back to 2016; Yahoo's annual statements fill only what SEC lacks. Every value records its
  source.
- **Why:** Yahoo gives only about four years of annual statements. SEC filings are the
  official record and go back far enough for a 5-10 year history; checks against Yahoo for
  2022-2025 agree within 5% in 93-98% of cases.

### The panic-sell screen was a one-off

- **Who:** Babak and Claude.
- **Decision:** The 2026-10-25 panic-sell screen (S&P 500 stocks at least 25% below their
  52-week high with growing adjusted earnings, ranked by P/E against their own median) was a
  one-off look at a sell-off. It later fed the market report's "stocks to look at" until it
  was replaced on 2026-10-27 (below).
- **Why:** A sell-off is a moment, not a method. Babak's method is good statements first, then
  price against the stock's own cheap price.

## 2026-10-27

### Adjusted EPS is Yahoo's reported quarterly EPS, split-adjusted

- **Who:** Babak, on Claude's proposal.
- **Decision:** "Adjusted" or "true" EPS for valuation is the sum of the last four quarters of
  Yahoo's reported EPS (the figure analysts' estimates use, without amortization and
  one-offs), split-adjusted. One-offs Yahoo still includes are corrected by hand with
  `eps_override` in `config/watchlist.toml`, each with its reason.
- **Why:** GAAP EPS is distorted by amortization, write-downs and deal costs (BSX, BKNG).
  Yahoo's series is split-adjusted and goes back decades, so no hand-kept table is needed.

### Valuation against the stock's own history

- **Who:** Babak.
- **Decision:** A stock is judged cheap against its own adjusted P/E history: each year's
  average price over that year's adjusted EPS, over 10 years (with the 5-year median shown
  next to it). The entry price is a target multiple times trailing adjusted EPS; Claude
  proposes the target and marks it "not yet confirmed by Babak" until they confirm it.
  The target is optional: on 2026-11-12 Babak chose not to set one for Netflix ("I don't
  know how to set the target"), so new analyses show the price at the stock's own P/E
  levels (lows and medians) instead of proposing an entry price, unless Babak asks for one.
- **Why:** Peer multiples depend on a hand-picked group; a company's own history shows what
  the market has been willing to pay for that business. Used in reports 11 and 12, the watch
  list and Stage 2.

### Every report has three parts: summary, Babak's numbers, Claude's analysis

- **Who:** Babak.
- **Decision:** Reports, watch-list PDFs and the market report follow one template:
  1. Summary (the verdict and four short points: cheap, strong, weak, uncertain),
  2. the numbers Babak asks for (absolute values first, history, ratios, screens, DCF),
  3. Claude's analysis. Summaries stay short and free of detail.
- **Why:** Babak reads the verdict first, checks the numbers they rely on, and then reads the
  reasoning. Applied first to report 11 (BSX) and then everywhere.

### The watch list: BKNG, BSX, NFLX, GOOGL and UBER, every evening at 21:00 Europe/Rome

- **Who:** Babak.
- **Decision:** `config/watchlist.toml` lists BSX, BKNG and NFLX, and since 2026-10-29
  GOOGL and UBER. A scheduled Claude session
  analyses them every evening at 21:00 Italy time and saves dated PDFs.
- **Why:** A daily, dated record of each stock against its entry price, without asking for it.

### Evening results are committed straight to `main`

- **Who:** Babak.
- **Decision:** The evening run commits `analyses/` to `main` and pushes, with no pull
  request each night. (Until issue #33 it also committed the screener's `data/screener/`
  files; the screener's runs are in the database now.)
- **Why:** A nightly pull request would need a nightly review for generated files.

### "A list of dated analyses", not "an archive"

- **Who:** Babak.
- **Decision:** The dated PDFs are called a list of dated analyses, in docs, pages and
  messages.
- **Why:** Every run is kept and listed by date for reading and comparison; nothing is put
  away out of sight, which is what "archive" suggests.

### A public GitHub Pages site for the dated analyses

- **Who:** Babak.
- **Decision:** https://khalilvandian.github.io/Stock-analysis/, built by `analysis/site.py`
  and published by GitHub Actions on pushes to `main`.
- **Why:** The analyses can be read on any device, and links in the email work without
  signing in. The repository is public anyway, which is also why no secret may be in it.

### Email only through Brevo, never through Babak's Gmail, only to Babak

- **Who:** Babak.
- **Decision:** `analysis/send_email.py` sends one email per run through Brevo's API, from a
  sender verified in Brevo, with every PDF attached. It never goes through Babak's own Gmail
  account. The recipient is Babak. Keys and addresses live in the cloud environment
  (`BREVO_API_KEY`, `WATCHLIST_EMAIL_FROM`, `WATCHLIST_EMAIL_TO`). If Brevo fails, no email is
  sent and the session says so.
- **Why:** The earlier routes were dropped the same day: Resend first, then a Gmail connector
  fallback, which sent from Babak's own account and could only send light copies or links
  instead of the real PDFs. Brevo is free (300 emails a day),
  works over HTTPS (SMTP ports are blocked in the cloud environment) and delivers to any
  address once the sender is verified.

### The market screener's design

- **Who:** Babak, with Claude's proposals for the thresholds (report 13, methods doc).
- **Decisions:**
  1. **Two stages.** Stage 1 keeps companies with good financial statements; Stage 2 ranks
     only those by price. Statements first, price second.
  2. **Separate modules.** `stage1.py` and `stage2.py` share nothing but Stage 1's output file;
     Stage 2 checks it has every column it needs. Either can change without the other.
  3. **Lynch categories.** Each company is judged by the rules for its Peter Lynch category;
     banks, insurers and REITs by their kind of business.
  4. **No fear signal.** A sell-off, drawdown or VIX level is not part of the screen.
  5. **Fundamentals plus technicals.** Fundamentals decide what is listed and in what order;
     technicals (trend, RSI, 52-week range, rating) are shown for timing only.
  6. **Free sources only.** TradingView's screener, Yahoo, SEC EDGAR, the ECB.
  7. **US and Europe capability, S&P 500 focus for now.** The code covers the US and 17
     European markets above $1bn; Babak: "for now, we're focusing on the S&P 500"
     (`[universe] index = "SP:SPX"`).
  8. **Top 3 per sector**, cheap or within 15% of the stock's own cheap price.
- **Why:** This is Babak's method made mechanical: find good businesses first, then wait for a
  price that is cheap for that business. Lynch's categories stop a utility and a software
  company being judged by one set of rules.

### The screener's top 3 per sector replaces the panic-sell table in the market report

- **Who:** Babak.
- **Decision:** The evening run first runs the market screener (Stage 1 then Stage 2 on the
  S&P 500). The market report's "stocks to look at" is the screener's top 3 cheap or
  close-to-cheap stocks per sector, with Stage 1's pass counts. The site gets a Screener
  page, and the email's market section lists the names. (Read from the database's screener
  run since issue #33.)
- **Why:** The panic-sell screen was a one-off; the screener is the method.

### Metrics dictionary: Claude's defaults taken, pending Babak's review

- **Who:** Claude, pending Babak (report 14, issue #8).
- **Decision:** Until Babak chooses, the open choices in report 14 take Claude's recommended
  defaults:
  1. **The set:** start with the 16 proposed metrics; add ROIC later.
  2. **Two vectors:** a "quality" vector from the statements and a separate "price" vector,
     following the two screener stages.
  3. **Growth window:** 5 years, from TradingView or SEC (3 years is one cycle at most).
  4. **EPS:** adjusted where we have it, GAAP otherwise.
  5. **First must-have:** keep the strict cash / short-term debt rule; keep (cash + operating
     cash flow) / short-term debt as a candidate.
  6. **Net cash and cover ratios:** clip net debt ratios at 0 and cover ratios at a ceiling
     (50x) before standardizing (built into `build_vectors()` through a `clip` entry
     in the dictionary).
  7. **Lynch category:** compare stocks within their category rather than as six 0/1
     columns on one scale.
  8. **Piotroski and Altman:** use TradingView's for now; recompute from SEC filings later for
     the stocks held or watched.
  9. **Cash-balance growth:** drop it (it jumps with deals and debt raises).
- **Why:** The vector work can go on while Babak reviews; each default is the one Claude
  recommended in report 14 and can be changed in `config/metrics.toml`.

## 2026-11-16

### One database behind an API; the apps are added only when they are built

- **Who:** Babak, on Claude's proposal (issue #16).
- **Decision:** The project's purpose is an analysis interface that shows each company's
  fundamental and technical analysis, built from data gathered from several sources and
  stored in one database, to help with investment decisions. The target layout:
  - **db:** PostgreSQL. It is the single place the data lives, and it is never exposed
    to the internet.
  - **worker:** the loaders, the build and the analyses, run on a schedule. It writes
    to the database.
  - **api:** the only way in for every interface, served over HTTPS with a token.
  - **ui:** the analysis interface. It reads through the API, as can the GitHub Pages
    site and the evening run.

  They will run as Docker Compose services on one Oracle Cloud machine, set up by us,
  with the same Compose file used locally. `src/stock_analysis` stays the one shared
  library that the worker and the API are thin layers over.
- **Kept minimal on purpose:** the design is still being explored, so a folder, service or
  file appears only when there is code for it. Today there is the database package
  (`stock_analysis.db`), its migrations and `check`. No `apps/`, Compose file or API code
  exists yet. The order when they come:
  1. local Compose with PostgreSQL, with the loaders and build on SQLAlchemy
  2. the API
  3. the worker with the API loaders
  4. the Oracle Cloud server
  5. the evening run and the site reading the API
  6. the UI
- **Why:**
  - Several interfaces will share the data, so one entry point (the API) keeps the
    schema free to change and access control in one place.
  - A private database removes the open question of whether the cloud session can reach
    port 5432, because it calls the API over HTTPS instead.
  - Compose gives the same setup on the PC and the server, and Kubernetes isn't needed
    at this size.

### PostgreSQL only; SQLite dropped

- **Who:** Babak.
- **Decision:** The database is PostgreSQL 16 only: in Docker on this machine now (target
  `local`), and on the Oracle Cloud server later (`server`). The SQLite file and code path
  are removed.
- **Why:** PostgreSQL is what the server will run, and keeping two engines meant writing for
  the common subset of both. On 2026-11-16, both engines were built from the same files and
  gave identical tables, so nothing is lost.
- **Consequence:** the database tests need PostgreSQL. They use the `stock_test` database in
  the local container and are skipped where none is running (for example the cloud
  sessions), while the rest of the suite still runs.

### The server is Azure Database for PostgreSQL (Azure for Students), not Oracle Cloud

- **Who:** Babak.
- **Decision:** The project's PostgreSQL server is **Azure Database for PostgreSQL – Flexible
  Server** `stock-db-bk` (Italy North, Burstable B1ms, 32 GiB, PostgreSQL 16) on the **Azure
  for Students** subscription, opened with the university account.
- **Why:**
  - Oracle Cloud's free ARM machine (A1) in Milan, the home region and the only one free
    resources can use, was "out of capacity" for every size tried.
  - Upgrading to Pay As You Go needed a temporary hold of about €93 on the card, which
    Babak declined for a project this size.
  - Azure for Students needs no card, and its free services cover a B1ms PostgreSQL server
    with 32 GB for 12 months.
  - The server is managed, so Azure handles updates and backups. That's less work than
    running PostgreSQL ourselves.
- **Weekly cadence:** the data is gathered and cleaned **weekly** (Saturday), not daily. The
  worker that does this (a small VM or GitHub Actions) is still to be set up.
- **Access:** firewall rules for listed IPs only; `allow-my-ip` updates the home rule when the
  IP changes. Later, only the worker's address.
- **Later:** after 12 months the free services end and the server would use the student
  credit (about $19 a month at list price). Decide then whether to keep, shrink or move it;
  a `pg_dump` moves it anywhere.

### Scripts connect straight to the database; cloud sessions go through a small, general API

- **Who:** Babak.
- **Decision:** On a PC, scripts and Claude read and write PostgreSQL directly with two working
  users: `stock_reader` (read only) and `stock_writer` (data, not schema). Claude's cloud
  sessions use a small web API on Azure (`api/app.py`, App Service `stock-api-bk`, free F1)
  with two general routes instead of one per question: `/query` (any single read-only
  statement, as `stock_reader`) and `/execute` (write steps in one transaction, as
  `stock_writer`). `Data.open()` picks the backend, so scripts are the same everywhere. The key
  reaches cloud sessions as a network secret, never as a variable. (The files that stayed
  then were retired in issue #33.)
- **Why:** tested 2026-11-16: cloud sessions can't reach PostgreSQL in any way (direct
  connections are refused; the proxy's CONNECT tunnel passes only web traffic), while HTTPS
  works. Considered and rejected: a copy of the database per session (not the live database),
  a remote MCP server (tools don't suit scripts that pull thousands of rows), moving to a
  provider with an HTTP driver (Neon; unofficial Python drivers), a WebSocket tunnel
  (unproven), self-hosted cloud environments (Team and Enterprise plans only). An API per
  use case was rejected too: every new analysis would need a new route.
- **Safety:** the key, HTTPS only, one statement per request, a read-only transaction for
  `/query`, and the database users' rights (the writer can't change the schema or
  `schema_version`, or change or delete raw data). The database firewall admits only the
  API's addresses and the home PC.

## 2026-11-17

### The ingest job: a backfill to the request limits, then maintenance (issue #18)

- **Who:** Babak asked for it; the settings below are Claude's proposal, to review.
- **Decision:** One job, `python -m stock_analysis.db ingest`, fills the database from
  TradingView, SEC EDGAR, Yahoo and the ECB. Each run works through a to-do list (`ops_task`,
  one task per source and company), never-fetched tasks first, until each source's budget,
  its rate limit or the run's time limit. It backfills until the S&P 500 is complete, then
  maintains it with fewer calls. Details: `docs/INGEST.md`.
- **What "complete" means** (`config/coverage.toml`, `docs/COVERAGE.md`):
  - 2016 onwards (or since listing), every required item for each fiscal year and for the
    last 8 quarters
  - daily prices on 98% of trading days, current
  - Yahoo's reported EPS for the last 8 reports
  - interest and the three debt lines optional
  - operating income, EBITDA, D&A and capex not required for banks, insurers and asset
    managers; operating income and EBITDA not required for REITs
  - backfill ends when every task has been fetched once and 90% of the required values are
    in (first full backfill, 2026-11-17: 95%); the gaps left are mapping work, not fetching
- **Build:** SEC facts are now in the build, first-ranked, with their real filing dates.
  - The fourth quarter is the year less three quarters.
  - Every period is dated at its nearest month end, so SEC's 52/53-week dates and Yahoo's
    month ends are the same period.
  - SEC values start in 2015, because the splits before the price history are unknown.
- **Why:** the free sources limit requests, not data. Yahoo throttles when called too often,
  and SEC allows 10 requests a second. A queue that resumes where it stopped fills the
  database over a few nights and then needs little.

### The ingest job runs as an Azure Container Apps Job

- **Who:** Babak, after comparing the options with Claude.
- **Decision:** An Azure Container Apps **Job** (`stock-ingest`, Consumption environment
  `stock-jobs-env`, schedule `30 22 * * *` UTC, 1.5 vCPU, 3 GiB: the full build peaks at 1.7 GiB). Its image is built from this
  repository by GitHub Actions and kept on GitHub Container Registry. Each run lets itself
  through the database firewall with its managed identity (rule `ingest-job`, deleted at the
  end), so *Allow Azure services* stays off. When a run ends it starts the Pages workflow, so
  the Data page updates within minutes; a daily schedule is the fallback.
- **Why:** the job starts, runs for one to two hours and stops. A Container Apps Job is
  billed per second while running and the free monthly grant covers it.
- **Rejected:**
  - **The API's App Service F1:** it only runs during requests, cuts each one off at 230
    seconds, allows 60 CPU minutes a day shared with the API, and can't run scheduled jobs
    without Always On (B1, paid).
  - **Azure Functions:** the Consumption plan caps a run at 10 minutes, and Flex Consumption
    would mean repackaging the code as a function app.
  - **Azure Container Registry:** about $5 a month, while GitHub's registry is free for a
    public repository.
  - **Opening the firewall to all of Azure:** the database stays limited to listed
    addresses.

### The site gets grouped menus, and the pipeline diagram is one of its pages

Seven pages no longer fit one row of tabs, least of all on a phone, so the top bar has three
menus: Analyses, Markets and Project. They are plain `<details>` elements, so they work
without JavaScript; a few lines of script only close the other menus. The pipeline diagram
lives in one file, `docs/pipeline.html`, which is both the Claude artifact and the site's
Pipeline page: its styles are scoped under `.pipeline` with `--p-` tokens, so the site can
include it unchanged, and a push that edits it republishes the site.

### The scripts work on the database alone, and what they don't use is removed (issue #33)

- **Who:** Babak, 2026-11-18: "all the scripts now should be working on the server ... remove
  after the switch all the redundant material"; the test is that the scheduled evening run
  succeeds for the watch list; any script the scheduled run doesn't use is redundant.
- **Decision:**
  - Only the ingest job calls the sources. Every script reads the database through
    `stock_analysis.data` and `stock_analysis.stocks` (a stock's row: absolute values in $bn,
    ratios, growth, standard DCF; its fiscal-year history; prices; earnings dates; the latest
    screener run) and records its results there: the screener's runs (`out_screener_*`), the
    watch list's and the market report's runs, Claude's notes, the watch list itself.
  - The ingest gained what the scripts needed: every TradingView screener field with each
    snapshot (`extra_json`), a snapshot of the watch list's symbols outside the index, the
    watch list's stocks and peers (and `extra_symbols`) fetched like members, the market
    report's instruments (`config/market.toml`, `core_market_daily`), and earnings dates due
    again on every run in the four days after a report.
  - Removed: `data/` (every file), `analyses/*/runs.csv`, `config/market_universe.csv`, the
    `db load-files` command, and the scripts the evening run and the site don't use:
    `sector.py`, `history.py`, `compare.py`, `valuation.py`, `debt.py`, `debt_to_ebitda.py`,
    `dcf.py`, `dcf_firm.py`, `dashboard/`, `stock_analysis.fetch`, `stock_analysis.fmp`,
    `ecb.usd_per_unit`. Then (Babak, 2026-11-19: "they don't serve anything anymore ...
    they were just initial experimentation") reports 01-14 too, which read those files and
    scripts; `reports/README.md` lists them and the commit to read them from, and the docs
    still cite them by number where a decision came from one.
  - The site reads the runs, the screener, the coverage and the explorer from the database
    through the web API at build time.
- **Consequences:**
  - Prices are the last close the ingest stored (after the US close), not a live quote at
    21:00 Italy time; the PDFs say so.
  - The utilities "sector" is the database's (the S&P 500's utilities and any added
    symbols), not Yahoo's 102 US-listed utilities.
  - Forward EPS, beta, the analysts' target and rating come from TradingView instead of
    Yahoo's `info`; the growth measures use the database's last four fiscal years.
  - The screener's universe is the ingest's (`SP:SPX`): `[universe] index = ""` (whole
    markets) is refused until the ingest snapshots whole markets.
- **Rejected:** keeping the files as a fallback (two sources of truth, and the scripts
  drifted apart); porting the per-ticker scripts (they were ported first, then removed as
  unused by the scheduled run).

### The server computes; the scheduled Claude session only interprets (issue #33)

- **Who:** Babak, 2026-11-18: "we should minimalize the task that the Claude schedule does ...
  on a schedule we already execute them ... the Claude schedule only checks those ready-made
  data and does its interpretation and analysis on top of them, and creates its own analysis
  and PDFs."
- **Decision:** after each night's ingest the job runs the nightly analyses
  (`stock_analysis.nightly`): the market screener, each watch-list stock's numbers and the
  market report's numbers, stored in `out_screener_*`, `out_stock_numbers` and
  `out_market_numbers` (migration `015`). The evening session reads them, writes the notes
  and renders the PDFs. Its scripts compute on the spot only what is missing: a stock whose
  numbers are older than the last build, or whose watch-list settings (target, peers, EPS
  corrections) changed since, and the market numbers when none were stored. The screener
  and the computations moved into the package (`stock_analysis.screener`,
  `stock_analysis.nightly`) so the job's image has them.
- **Why:** the session's time and tokens go to judgement, not to arithmetic a schedule can
  do; the numbers are ready before the session starts and the same for every reader.
- **Rejected:** rendering the PDFs on the server too: they carry Claude's notes of the same
  evening, so they are built after the notes.

### One orchestrated, logged and watched nightly pipeline (issue #30)

- **Who:** Babak, after the evening routine had been switched off for three weekdays without
  any warning.
- **Decision:** Apache Airflow 3 (3.4.0) on the PC first: Docker Compose with the
  LocalExecutor and its own metadata PostgreSQL (`orchestration/`). One DAG, `stock_nightly`,
  at 22:35 UTC on weekdays, checks every scheduled piece: the Azure ingest run, the nightly
  analyses in its summary, the prices (the last close for at least 95% of the members), the
  hourly quotes job, and then the scheduled Claude session's commit and its published site.
  It sets a **ready marker** and logs every step in `ops_pipeline_run` and
  `ops_pipeline_step`. A failure emails an alert. A GitHub workflow audits each morning that
  the last trading day has a finished run, so a night when Airflow didn't run is caught too.
- **The Claude step:** a ready marker, chosen over Airflow starting the routine or running
  `claude -p` headless. The session keeps its own schedule (00:00 Italy time, Tuesday to
  Saturday, since 2026-11-19) and its own wait for the newest price. The marker tells it
  whether the night's checks passed, and Airflow checks that it committed.
- **Side checks:** the nightly analyses and the quotes job alert without holding back the
  marker, because the evening session computes missing numbers on the spot.
- **Why:** Airflow is the community standard (career value, issue #30). The checks live in
  `stock_analysis.pipeline`, so they're tested without Airflow and run by hand, and the DAG
  only orders them. Airflow and the project pin different SQLAlchemy versions, so the
  project runs in its own environment inside the image.
- **Rejected:** keeping separate clocks with no checks (the failure that started this);
  putting the run log only in Airflow's metadata database, which the cloud session and
  GitHub can't read.

## 2026-11-19

### Airflow owns every scheduled piece, and runs on Azure (issue #30)

- **Who:** Babak: "the point of orchestration was to take everything under control ... define
  them as tasks, make them repeatable"; "we are locally working on Airflow, but we will
  implement Airflow on Azure."
- **Decision:** Airflow starts each piece as a task instead of watching it: the ingest, the
  nightly analyses (split out of the ingest run), the hourly quotes and the site rebuild.
  The Azure jobs lose their own cron, with no fallback schedule: a failure should show, not
  be covered. Two things stay outside: the Claude session that reads the data keeps its own
  schedule for now (Airflow checks its commit), and the morning audit, which must work when
  Airflow is down. Airflow is
  developed and tested locally in Docker; production Airflow runs on Azure, never on the PC.
- **Why:** a schedule nobody controls is what failed in November. Tasks can be retried and
  rerun for any date. Hosting on the PC would stop every job when the PC is off.
- **Supersedes:** the watcher design of 2026-11-18 (above), where the jobs kept their own
  schedules and Airflow only checked them.

