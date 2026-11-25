# Claude's folder

Everything here is how Claude works with the application. Nothing of the application depends on
it: `src/`, `api/`, `orchestration/` and `analysis/` never import it, and the containers don't
contain it (`tests/test_claude_folder.py` checks this).

| Place | What is in it |
|---|---|
| `client.py` | The commands of the web API's operations (`uv run python -m claude app ...`) |
| `tools/` | Reliable scripts Claude answers with, each with a description and a test |
| `instructions/` | What the nightly session follows |
| `scratch/` | One-off scripts, never committed |

`uv run python -m claude` lists every tool; `uv run python -m claude NAME ...` runs one.
Claude Code also needs two things at fixed places: `CLAUDE.md` and `.claude/` (settings, hooks,
skills).

## Two ways Claude works here

- **With Babak** (a session on the PC or in the cloud): full access, also to the code and the
  database. Use a tool when one fits the question, so the same question gets the same answer;
  change the watch list and the recipients with `app`, which checks and logs.
- **The nightly session** Airflow starts: only `app`, with its own key
  (`instructions/nightly_analysis.md`). It can't run SQL that writes, can't read or change the
  recipients through the application, and adds no scripts; it asks for one in its submit note.

## Where a new script goes

1. Used once: `scratch/`.
2. Worth using again: `tools/NAME.py`. It needs a docstring whose first paragraph says what it
   does, a `main(argv=None)`, and a test in `tests/` that names it. It then appears in the list by
   itself.
3. A calculation the PDFs, the site or the nightly numbers also need: `src/stock_analysis/`, and
   the tool calls it. Never a second copy.
4. New data: the ingest (`config/db_items.toml`, a source), never fetched by a tool.

A Python file anywhere else in the repository fails `tests/test_claude_folder.py`, unless it is
added to the list of places there.
