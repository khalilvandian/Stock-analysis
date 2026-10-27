# Watch list analyses

Each stock on the watch list ([config/watchlist.toml](../config/watchlist.toml)) is analysed every evening and saved as a dated PDF in its own folder. Nothing is overwritten: every run, including several in one day, stays in the stock's dated list. Each run also writes one summary PDF of all the stocks to [summaries/](summaries/). Built by `uv run python analysis/watchlist.py`.

| Stock | Latest analysis | Price | Adjusted P/E | 10-yr median | Target | Entry price | vs price | All analyses |
|---|---|---|---|---|---|---|---|---|
| BSX | [2026-10-27 20:55 CET](BSX/2026-10-27_2055.pdf) | $45.02 | 14.0x | 25.2x | 13x | $41.73 | -7.3% | [list](BSX/README.md) |
| BKNG | [2026-10-27 20:55 CET](BKNG/2026-10-27_2055.pdf) | $150.33 | 15.6x | 21.2x | 15x | $144.15 | -4.1% | [list](BKNG/README.md) |
| NFLX | [2026-10-27 20:55 CET](NFLX/2026-10-27_2055.pdf) | $62.58 | 21.4x | 61.3x | 20x | $58.40 | -6.7% | [list](NFLX/README.md) |

**Market report**, newest first: [2026-10-27_2055](market/2026-10-27_2055.pdf), [2026-10-27_1657](market/2026-10-27_1657.pdf), [2026-10-27_1627](market/2026-10-27_1627.pdf)

**Watch list summary**, newest first: [2026-10-27_2055](summaries/2026-10-27_2055.pdf), [2026-10-27_1657](summaries/2026-10-27_1657.pdf), [2026-10-27_1627](summaries/2026-10-27_1627.pdf)
