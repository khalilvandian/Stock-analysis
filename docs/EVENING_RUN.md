# The evening run

Every weekday evening (Monday to Friday) at 21:00 Italy time a scheduled Claude session runs these steps on `main`.
Babak approved committing the results straight to `main` (no pull request each night).

Every number comes from the database (`docs/DATABASE.md`), which the ingest job fills every
night after the US close (`docs/INGEST.md`); no step downloads market data. In the cloud
session the scripts reach the database through the web API (`STOCK_API_URL`, with the key the
environment attaches). Prices are therefore the last close the ingest stored (the previous
trading day at 21:00 Italy time), and the PDFs say so.

1. **Set up:** `uv sync`. Check out `main` and pull. `uv run python -c "from stock_analysis.data
   import Data; print(Data.open().status())"` shows the newest price and screener run; if the
   newest price is more than three days old, the ingest has stopped: say so in the email.
2. **Numbers first:** `uv run python analysis/screener.py` refreshes the market screener,
   then `uv run python analysis/watchlist.py --numbers` and
   `uv run python analysis/market.py --numbers` print today's figures (the market one
   includes the screener's top names).
3. **Update Claude's notes** where the story changed, and set `Updated:` to today:
   - `analyses/<SYMBOL>/notes.md` for each stock in `config/watchlist.toml`: Verdict,
     Summary (4 one-line bullets: cheap, strong, weak, uncertain), Business, Risks, News
     (dated, newest first), What to watch. Search the news for each stock; after an
     earnings report, update the verdict, entry price and, if a quarter's adjusted EPS
     includes a one-off, add an `eps_override` in the config.
   - `analyses/market/notes.md`: Verdict, Summary, What is driving the market, Stocks to
     look at (comment on the screener's top names; `uv run python analysis/market.py
     --numbers` lists them after the screener has run), What to watch.
   - `analyses/summaries/notes.md`: Verdict across the watch list, and Analysis.
   - A new stock on the watch list with no `notes.md` gets a short first analysis.
   Every report keeps the same template: a high-level summary first, then the numbers,
   then the detail. Keep the summaries short and free of detail.
4. **Build:** `uv run python analysis/watchlist.py`. It first reruns the market screener
   (`analysis/screener.py`: Stage 1 then Stage 2 on the S&P 500, from the database, a minute
   or two; `--no-screener` skips it after step 2) and saves the run in the database
   (`out_screener_run`, `out_screener_result`; a second run the same day replaces the first).
   The market report
   lists the screener's top 3 cheap or close-to-cheap stocks per sector (if the screener
   fails, it uses the last results and says so). Then it writes one PDF per stock and the
   watch list summary, each dated `YYYY-MM-DD_HHMM.pdf`, records each run in the database
   (`out_watchlist_run`, `out_market_run`), rebuilds the dated lists from them
   (`analyses/README.md`, `analyses/<SYMBOL>/README.md`) and writes the email body to
   `.cache/watchlist/email.html` (not committed). Before that it copies
   `config/watchlist.toml` to the database (the ingest fetches the stocks and peers from
   there) and saves the notes that changed (`out_note`).
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
