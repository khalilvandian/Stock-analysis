# The evening run

Every evening at 21:00 Italy time a scheduled Claude session runs these steps on `main`.
Babak approved committing the results straight to `main` (no pull request each night).

1. **Set up:** `uv sync`. Check out `main` and pull.
2. **Numbers first:** `uv run python analysis/watchlist.py --numbers` and
   `uv run python analysis/market.py --numbers` print today's figures.
3. **Update Claude's notes** where the story changed, and set `Updated:` to today:
   - `analyses/<SYMBOL>/notes.md` for each stock in `config/watchlist.toml`: Verdict,
     Summary (4 one-line bullets: cheap, strong, weak, uncertain), Business, Risks, News
     (dated, newest first), What to watch. Search the news for each stock; after an
     earnings report, update the verdict, entry price and, if a quarter's adjusted EPS
     includes a one-off, add an `eps_override` in the config.
   - `analyses/market/notes.md`: Verdict, Summary, What is driving the market, Stocks to
     look at (comment on the screen's names), What to watch.
   - `analyses/summaries/notes.md`: Verdict across the watch list, and Analysis.
   - A new stock on the watch list with no `notes.md` gets a short first analysis.
   Every report keeps the same template: a high-level summary first, then the numbers,
   then the detail. Keep the summaries short and free of detail.
4. **Build:** `uv run python analysis/watchlist.py`. It writes the market report, one PDF
   per stock and the watch list summary, each dated `YYYY-MM-DD_HHMM.pdf`, adds a line to
   each `runs.csv`, rebuilds the dated lists (`analyses/README.md`, `analyses/<SYMBOL>/README.md`)
   and writes the email body to `.cache/watchlist/email.html` (not committed).
5. **Check:** `uv run ruff check . && uv run ruff format --check . && uv run pytest`.
6. **Save:** commit `analyses/` (and any config or notes changes) to `main` and push.
7. **Email:** `uv run python analysis/send_email.py --to <address>` sends the email body
   with every PDF of the run attached, through Resend (resend.com), from Resend's own
   address. The recipient is given in the scheduled task (or `WATCHLIST_EMAIL_TO`) and the
   key in `RESEND_API_KEY`; neither is ever written into this public repository. Babak
   asked for it not to come from their own Gmail.

If a step fails, still commit what was built and say in the email what failed.
