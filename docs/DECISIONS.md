# Decision log

The decisions that shape the project, newest last within each day. Each says who decided,
what, and why. "Babak" means Babak decided or approved it; "Claude, pending Babak" means
Claude took a default that Babak has not yet confirmed. Add new decisions at the end with
their date.

## 2026-10-25

### Yahoo Finance and SEC EDGAR are the primary sources, not FMP

- **Who:** Babak, on Claude's test results (report 01).
- **Decision:** Yahoo Finance supplies current figures and prices; SEC EDGAR supplies the
  history. Financial Modeling Prep is kept only as a client (`FMPClient`).
- **Why:** FMP's free plan returned HTTP 402 for most symbols (every CEG endpoint but the
  profile), and by 2026-10-27 the key in use was invalid. The project works on free sources
  without any key.

### SEC is primary for the yearly history; Yahoo fills the gaps

- **Who:** Babak, on Claude's proposal (in use since 2026-09-28, recorded in reports 01 and 10).
- **Decision:** `history.py` takes annual 10-K, 20-F and 40-F figures from SEC company facts
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
- **Decision:** The evening run commits `analyses/` (and, since this evening, the screener's
  `data/screener/` files) to `main` and pushes, with no pull request each night.
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
  close-to-cheap stocks per sector from `data/screener/top.csv`, with Stage 1's pass counts.
  The site gets a Screener page, and the email's market section lists the names.
  `data/screener/` (`top.csv`, `stage1.csv` and the dated CSV) is committed each evening with
  the analyses.
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

### No API for now: scripts and Claude connect straight to the database

- **Who:** Babak.
- **Decision:** Analyses, scripts and Claude read and write the PostgreSQL database directly,
  with two working users: `stock_reader` (read only) and `stock_writer` (data, not schema). Claude's
  cloud environment gets their passwords as environment variables. The API planned earlier is
  dropped until an interface needs it. The existing files stay as they are, so Claude can still use
  them.
- **Why:** an API is extra code, hosting and upkeep, which isn't needed while every user of the data is
  a script or Claude that can hold a database password.
- **Open point:** whether cloud sessions can reach PostgreSQL through Anthropic's proxy has to
  be tested (docs/SETUP.md). If they can't, a self-hosted Claude environment or a small HTTPS
  layer is the fallback.
