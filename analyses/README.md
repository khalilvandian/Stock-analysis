# Watch list analyses

Each stock on the watch list ([config/watchlist.toml](../config/watchlist.toml)) is analysed every evening and saved as a dated PDF in its own folder. Nothing is overwritten: every run, including several in one day, stays in the stock's dated list. Each run also writes one summary PDF of all the stocks to [summaries/](summaries/). Built by `uv run python analysis/watchlist.py`.

| Stock | Latest analysis | Price | Adjusted P/E | 10-yr median | Target | Entry price | vs price | All analyses |
|---|---|---|---|---|---|---|---|---|
| BSX | [2026-10-28 20:54 CET](BSX/2026-10-28_2054.pdf) | $42.35 | 13.3x | 25.2x | 13x | $41.47 | -2.1% | [list](BSX/README.md) |
| BKNG | [2026-10-28 20:54 CET](BKNG/2026-10-28_2054.pdf) | $148.46 | 15.4x | 21.2x | 15x | $144.15 | -2.9% | [list](BKNG/README.md) |
| NFLX | [2026-10-28 20:54 CET](NFLX/2026-10-28_2054.pdf) | $61.91 | 21.2x | 61.3x | 20x | $58.40 | -5.7% | [list](NFLX/README.md) |

**Market report**, newest first: [2026-10-28_2054](market/2026-10-28_2054.pdf), [2026-10-28_0000](market/2026-10-28_0000.pdf), [2026-10-27_2055](market/2026-10-27_2055.pdf), [2026-10-27_1657](market/2026-10-27_1657.pdf), [2026-10-27_1627](market/2026-10-27_1627.pdf)

**Watch list summary**, newest first: [2026-10-28_2054](summaries/2026-10-28_2054.pdf), [2026-10-28_0000](summaries/2026-10-28_0000.pdf), [2026-10-27_2055](summaries/2026-10-27_2055.pdf), [2026-10-27_1657](summaries/2026-10-27_1657.pdf), [2026-10-27_1627](summaries/2026-10-27_1627.pdf)
