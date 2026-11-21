# The evening run

Every weekday evening (Monday to Friday) at 21:00 Italy time a scheduled Claude session runs these steps on `main`.
Babak approved committing the results straight to `main` (no pull request each night).

The session does only what needs judgement: reading the numbers, writing Claude's notes and
the email. Every number is already computed on the server (`docs/INGEST.md`): after each
night's ingest the job runs the nightly analyses (`stock_analysis.nightly`) and stores the
market screener's run, each watch-list stock's numbers (its row, yearly history, prices,
adjusted EPS, peers, next report) and the market report's numbers. No step downloads market
data or recomputes what the server stored. In the cloud session the scripts reach the
database through the web API (`STOCK_API_URL`, with the key the environment attaches). Prices
are the last close the ingest stored (the previous trading day), and the PDFs say so.

1. **Set up:** `uv sync`. Check out `main` and pull. `uv run python -c "from stock_analysis.data
   import Data; print(Data.open().status())"` shows the newest price and screener run; if the
   newest price is more than three days old, the ingest has stopped: say so in the email.
   `uv run python -m stock_analysis.pipeline marker` reads the orchestrator's marker
   ([`ORCHESTRATION.md`](ORCHESTRATION.md)): exit 0 when the night's checks passed, 3 while
   they are still running, 4 when one failed (Airflow has emailed which). A failed run goes
   at the top of the email; the session still builds from what is stored.
2. **Read the numbers:** `uv run python analysis/watchlist.py --numbers` and
   `uv run python analysis/market.py --numbers` print the stored figures (the market one
   includes the screener's top names). "Stored numbers (computed on the server)" lists the
   stocks read as stored; a stock computed now had none since the last build, or its
   watch-list settings changed since (a new target, peer or EPS correction).
3. **Research and write Claude's notes.** The numbers come from the server; the words are
   Claude's, and they are only worth reading if they are deep, current and sourced. Write for
   Babak: plain English, short sentences, every claim tied to a number or a linked source,
   and always say what it means for the decision (buy, add, wait), not just what happened.
   - **Research first.** Search the news for the market's last session(s) since the previous
     run (what moved, by how much, and why) and for each stock in `config/watchlist.toml`
     (results, guidance, analyst moves, deals, regulation, insider trades). Open the article
     when the snippet is unclear, prefer primary sources (company releases, filings) and
     established outlets, check the article's date, and leave out anything that cannot be
     dated to the period or that does not bear on the investment case. Say so when a source
     is weak or two sources disagree.
   - `analyses/<SYMBOL>/notes.md` for each stock: **Verdict** (the decision in 3-4
     sentences, with price, P/E and entry), **Today** (what the stock did since the last run,
     why, and *What it means for you*), **Summary** (4 one-line bullets: cheap, strong, weak,
     uncertain), **Business**, **Risks**, **News** (dated `- YYYY-MM-DD:` items, newest first,
     at most 10, each new item with a source link; a price move is not news, it goes in
     Today), **What to watch** (each item with a coming date, or marked "(ongoing)"). After
     an earnings report, update the verdict, entry price and, if a quarter's adjusted EPS
     includes a one-off, add an `eps_override` in the config.
   - `analyses/market/notes.md`: **Verdict**, **Summary**, **What happened** (the
     sessions since the last run, with index levels and moves), **Why it happened** (the
     causes, each with its source), **What it means** (the interpretation for a long-term,
     Lynch-style investor), **Stocks to look at** (comment on the screener's top names from
     step 2), **What to watch** (coming events with dates), **Sources** (at least 3 links).
   - `analyses/summaries/notes.md`: **Verdict** across the watch list, and **Analysis**
     (what changed across the list, where to act, where to wait).
   - A new stock on the watch list with no `notes.md` gets a short first analysis.
   - **Review every section, every run.** Each section starts with
     `<!-- reviewed YYYY-MM-DD -->` (the run's date, Italy time), added only after the
     section was re-read and rewritten or confirmed as still true, and `Updated:` is the run's
     date. Remove events that have passed (an election, a meeting, a report already out);
     keep Business and Risks unless something changed, but re-read them.
   - `stock_analysis.notes_check` enforces this: a section not reviewed for the run, news
     without a date or a source, a "what to watch" item with no date or a past one, or a
     sentence describing a past date as still to come. `analysis/watchlist.py` refuses to
     build until the notes pass (`--allow-stale-notes` overrides it; then say so in the
     email), and `analysis/validate.py` reports the same checks.
4. **Build:** `uv run python analysis/watchlist.py`. It copies `config/watchlist.toml` to the
   database if it changed (the ingest and the nightly analyses read the stocks and peers
   from there) and saves the notes that changed (`out_note`). Then it renders the market
   report and one PDF per stock and the watch list summary, each dated `YYYY-MM-DD_HHMM.pdf`,
   from the stored numbers and the notes; records each run in the database
   (`out_watchlist_run`, `out_market_run`); rebuilds the dated lists from them
   (`analyses/README.md`, `analyses/<SYMBOL>/README.md`); and writes the email body to
   `.cache/watchlist/email.html` (not committed). A stock or the market report that fails is
   left out and named at the top of the email; the rest is still built. `--screener` reruns
   the market screener first (only if the night's run failed), `--recompute` computes every
   stock now instead of reading the stored numbers.
5. **Check:** `uv run python analysis/validate.py` (the run's outputs are complete and
   consistent; a FAIL goes in the email) and
   `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
6. **Save:** commit `analyses/` (and any config or notes changes) to `main` and push. The
   push publishes the site; its Screener page and run lists read the database.
7. **Email:** `uv run python analysis/send_email.py --to <addresses>` sends one email
   through Brevo (brevo.com, free, 300 a day) with the run's HTML body and every PDF of the
   run attached. It needs `BREVO_API_KEY` and the verified sender in `WATCHLIST_EMAIL_FROM`
   in the cloud environment settings. Up to 5 recipients, comma separated, from the
   scheduled task or `WATCHLIST_EMAIL_TO`. Keys and addresses are never written into this
   public repository. The email never goes through Babak's own Gmail. If Brevo is missing a
   setting or refuses, no email is sent: say in the thread what failed.

If a step fails, still commit what was built and say in the email what failed.
