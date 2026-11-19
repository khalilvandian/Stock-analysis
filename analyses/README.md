# Watch list analyses

Each stock on the watch list ([config/watchlist.toml](../config/watchlist.toml)) is analysed every evening and saved as a dated PDF in its own folder. Nothing is overwritten: every run, including several in one day, stays in the stock's dated list. Each run also writes one summary PDF of all the stocks to [summaries/](summaries/). Built by `uv run python analysis/watchlist.py`.

| Stock | Latest analysis | Price | Adjusted P/E | 10-yr median | Target | Entry price | vs price | All analyses |
|---|---|---|---|---|---|---|---|---|
| BSX | [2026-11-13 20:53 CET](BSX/2026-11-13_2053.pdf) | $44.40 | 13.9x | 25.2x | 13x | $41.47 | -6.6% | [list](BSX/README.md) |
| BKNG | [2026-11-13 20:53 CET](BKNG/2026-11-13_2053.pdf) | $159.59 | 15.5x | 21.2x | 15x | $154.35 | -3.3% | [list](BKNG/README.md) |
| NFLX | [2026-11-13 20:53 CET](NFLX/2026-11-13_2053.pdf) | $62.24 | 21.3x | 61.3x | 20x | $58.40 | -6.2% | [list](NFLX/README.md) |
| GOOGL | [2026-11-13 20:53 CET](GOOGL/2026-11-13_2053.pdf) | $294.86 | 25.6x | 23.7x | 22x | $255.83 | -13.2% | [list](GOOGL/README.md) |
| UBER | [2026-11-13 20:53 CET](UBER/2026-11-13_2053.pdf) | $69.42 | 22.2x | 22.3x | 20x | $62.40 | -10.1% | [list](UBER/README.md) |

**Market report**, newest first: [2026-11-13_2053](market/2026-11-13_2053.pdf), [2026-11-12_2132](market/2026-11-12_2132.pdf), [2026-11-04_2057](market/2026-11-04_2057.pdf), [2026-11-03_2053](market/2026-11-03_2053.pdf), [2026-11-02_2052](market/2026-11-02_2052.pdf), [2026-10-31_0707](market/2026-10-31_0707.pdf), [2026-10-30_2149](market/2026-10-30_2149.pdf), [2026-10-28_2054](market/2026-10-28_2054.pdf), [2026-10-28_0000](market/2026-10-28_0000.pdf), [2026-10-27_2055](market/2026-10-27_2055.pdf), [2026-10-27_1657](market/2026-10-27_1657.pdf), [2026-10-27_1627](market/2026-10-27_1627.pdf)

**Watch list summary**, newest first: [2026-11-13_2053](summaries/2026-11-13_2053.pdf), [2026-11-12_2132](summaries/2026-11-12_2132.pdf), [2026-11-04_2057](summaries/2026-11-04_2057.pdf), [2026-11-03_2053](summaries/2026-11-03_2053.pdf), [2026-11-02_2052](summaries/2026-11-02_2052.pdf), [2026-10-31_0707](summaries/2026-10-31_0707.pdf), [2026-10-30_2149](summaries/2026-10-30_2149.pdf), [2026-10-28_2054](summaries/2026-10-28_2054.pdf), [2026-10-28_0000](summaries/2026-10-28_0000.pdf), [2026-10-27_2055](summaries/2026-10-27_2055.pdf), [2026-10-27_1657](summaries/2026-10-27_1657.pdf), [2026-10-27_1627](summaries/2026-10-27_1627.pdf)
