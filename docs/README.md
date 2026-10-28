# Documentation

This folder describes how the project is built, what its parts are, how to run it and why
it is the way it is. The project rules every Claude session follows are in
[`CLAUDE.md`](../CLAUDE.md); the analyses themselves are in [`reports/`](../reports/README.md).

## Start here

1. Read [`CLAUDE.md`](../CLAUDE.md): absolute values first, the evening run, the report rules.
2. Set up the environment with [`SETUP.md`](SETUP.md), then run `uv sync` and `uv run pytest`.
3. Read [`ARCHITECTURE.md`](ARCHITECTURE.md) for the layers and where every file fits.
4. Read [`ENTITIES.md`](ENTITIES.md) for the data sources, the watch list and the file formats.
5. To analyse one stock, follow "Single-stock analysis" in [`PROCESSES.md`](PROCESSES.md).
6. To screen the market, run `uv run python analysis/screener.py` and read [`SCREENER.md`](SCREENER.md).
7. The evening run is [`EVENING_RUN.md`](EVENING_RUN.md); its parts are explained in `PROCESSES.md`.
8. Before changing a rule or a default, check [`DECISIONS.md`](DECISIONS.md) for why it is set that way.
9. When something breaks, start with the troubleshooting table in [`OPERATIONS.md`](OPERATIONS.md).
10. Before every commit: `uv run ruff check . && uv run ruff format --check . && uv run pytest`.

## Index

| Document | What it covers |
|---|---|
| [`README.md`](README.md) | This index and the start-here list |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | The design: layers, module map, data flow, where state lives, design principles |
| [`ENTITIES.md`](ENTITIES.md) | Data sources, absolute values, metrics, watch list, Lynch categories, screener types, reports, dated analyses, site, email, schedule, file formats |
| [`PROCESSES.md`](PROCESSES.md) | Every process step by step with the exact commands |
| [`SCREENER.md`](SCREENER.md) | Full reference of the two-stage market screener: every rule, threshold and source |
| [`DECISIONS.md`](DECISIONS.md) | Dated decision log: what was decided, by whom and why |
| [`OPERATIONS.md`](OPERATIONS.md) | Running and changing things, troubleshooting, test policy, the pre-commit check |
| [`SETUP.md`](SETUP.md) | Setting up a Claude Code on the web workspace for this repository |
| [`EVENING_RUN.md`](EVENING_RUN.md) | The steps the scheduled 21:00 session follows every evening |
| [`METRICS.md`](METRICS.md) | The metrics dictionary, generated from `config/metrics.toml` (do not edit by hand) |
| [`PREDICT.md`](PREDICT.md) | Predictive analysis: the point-in-time S&P 500 dataset, the "goodness" labels, features, walk-forward experiments and survivorship handling (report 15) |

Nothing in this repository is investment advice.
