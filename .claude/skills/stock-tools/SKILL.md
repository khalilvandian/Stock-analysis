---
name: stock-tools
description: Reliable scripts for this project. Use when asked about a stock's values or history, comparing peers, screening, metrics, the watch list, who gets the report email, the standing guide or an extra analysis run, and before writing any new script.
---

Run `uv run python -m claude` for the list of tools, then `uv run python -m claude NAME ...`. Use a
tool when one fits instead of writing SQL or a script.

| Asked | Run |
|---|---|
| A stock's numbers (always first) | `absolute TICKERS`, then `absolute --history TICKERS` |
| Compare stocks | `peer_screen NAME TICKERS` |
| Low debt, cheapness | `screen TICKERS [--strict or --balanced]` |
| Metrics, vectors | `metrics list`, `metrics vector TICKERS` |
| Watch list | `app watchlist`, `watchlist-set`, `watchlist-remove`, `watchlist-undo` |
| Report email recipients | `app recipients`, `recipient-add`, `recipient-remove` |
| An analysis run again | `app request analysis --reason "..."` |
| What earlier runs learned | `app guide` |

Change the watch list or the recipients only when Babak asks, with the reason. Never propose a
target P/E. Never write an email address into the repository.

A new script: read `claude/README.md` first, it says where it goes.
