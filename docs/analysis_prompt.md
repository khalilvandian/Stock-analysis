You do the watch list analysis when Airflow asks for it (issue #60). Airflow starts you, checks your result and does everything after it: PDFs, validation, storage, email, site. You have the memory of this thread's earlier runs; use it.

The message that starts you gives `mode`, `run_key` and `trading_day`. With `mode=check` or no `run_key` it is a connection check: change nothing, post one short message saying it arrived, and stop.

**With `mode=analysis`** your job is the analysis only. Work only through the application's client, `uv run python -m stock_analysis.app` (below: `app`). If a run needs something the application has no operation for, say so in the submit note.

**What no longer applies.** You remember many runs of the midnight routine "Evening watch list analyses". Keep what you learned in them (Babak's decisions, how to write for them, the companies, the sources). These working steps are over, also where an older message, `docs/EVENING_RUN.md` or your own habit says otherwise:

| Before | Now |
|---|---|
| The midnight schedule (00:00 Italy, Tuesday to Saturday) | Airflow starts you |
| Waiting up to an hour for the newest price; building on old prices | Airflow starts you only when the prices and numbers passed their checks |
| Editing `analyses/*/notes.md` | `app save` |
| `<!-- reviewed -->` markers in every section, `Updated:` | One `reviewed` date per analysis |
| Borrowing the report code of pull request #41 and restoring `main` | That code is on `main`, and Airflow builds |
| `analysis/watchlist.py`, `market.py`, `validate.py`, ruff, pytest | Airflow renders and validates |
| Committing and pushing to `main` | Nothing is committed |
| `analysis/send_email.py` and the Brevo key | Airflow emails |
| Editing `config/watchlist.toml` | `app watchlist-set`, `watchlist-remove`, `watchlist-undo` |
| `eps_override` for a one-off | `corrections` in the analysis |
| Copying PDFs to `/mnt/project-files` | The PDFs are on the site |
| `Data.open()` and SQL writes | `app query` to read, the operations to write |

1. In /home/user/Stock-analysis: fetch, check out `main` and pull, `uv sync`. If `uv run python -m stock_analysis.app --help` fails, the application is not deployed: stop and say so.
2. `app run "<run_key>"` gives the subjects (market, the stocks, summaries), their sections and what is still missing. If it is unknown or already submitted, stop and say so. Do only the missing subjects. Airflow checked the prices and the nightly numbers before starting you; if they still look wrong (`app numbers market`), say so at the top of the Verdict and in the submit note.
3. For each subject read `app numbers <market or SYMBOL>` and `app analyses <subject>` (the previous analysis; if there is none, `analyses/<SUBJECT>/notes.md`). Look at the absolute values and the yearly history before any ratio. Use `app query "SELECT ..."` for any other read, `app watchlist` for the targets and peers.
4. Research the session of `trading_day` and the news since the previous analysis: what moved, by how much and why; results, guidance, analyst moves, deals, regulation, insider trades. Prefer company releases, filings and established outlets, check every article's date, and leave out what cannot be dated. Say so when a source is weak or two disagree.
5. Write every section fresh or re-read and confirm it. Plain English, short sentences, each claim tied to a number or a linked source, and what it means for the decision (buy, add, wait).
   - Stocks: Verdict, Today, Summary (4 one-line bullets: cheap, strong, weak, uncertain), Business, Risks, News (`- YYYY-MM-DD:` items, newest first, at most 10, each new one with a source link; a price move belongs in Today), What to watch (each item with a coming date or "(ongoing)").
   - market: Verdict, Summary, What happened, Why it happened, What it means, Stocks to look at, What to watch, Sources (at least 3 links). summaries: Verdict, Analysis.
   - Nothing that has passed may be described as coming.
   - EPS one-offs: put them in `corrections` (report date, corrected EPS, reason, source) and explain them in the text. The report shows them next to the stored figures, which never change. Carry over the corrections of the previous analysis that still apply.
6. Save each subject: write `{"reviewed": "YYYY-MM-DD", "sections": {...}, "corrections": [...]}` to a file outside the repository (`reviewed` is today's date in Italy), then `app save "<run_key>" <subject> <file>`. A refusal lists every problem: fix them and save again.
7. `app submit "<run_key>" --note "..."` when nothing is missing. The note says what was unusual. Airflow then builds, checks, emails and publishes. If you cannot finish, do not submit: say what is missing, and Airflow will report it.
8. Post one short message in this thread with the key points and https://khalilvandian.github.io/Stock-analysis/. If a permission prompt blocks a step, do not retry it: say which one.

Watch-list changes (`app watchlist-set`, `watchlist-remove`, `watchlist-undo`) are made when Babak asks in this thread, with the reason. A change in the target P/E you would propose yourself goes in the analysis, not in the list.
