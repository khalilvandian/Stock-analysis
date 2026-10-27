# 14. Metrics dictionary: the fundamentals we use, defined once

Issue #8, "Quantification". Data date: 2026-10-26 (Yahoo) and 2026-10-27 (TradingView,
watch list) for the worked examples.

## 1. Summary

Every fundamental metric the project has used so far, 81 of them, is now defined in one
place, `config/metrics.toml`, with its definition, formula, data source and a worked example
on Boston Scientific. A small module, `stock_analysis.metrics`, picks any set of them and
builds each stock's vector. The point of this issue is for Babak to choose the set we go on
with; a draft of 16 is proposed below as a starting point.

- **Where they come from:** the absolute-values screen, the strict and weighted screens, the
  standard DCF, the watch-list run (adjusted P/E against own history) and the Stage 1 and
  Stage 2 market screener (PR #7: Lynch categories, Piotroski, Altman).
- **Groups:** size and price (3), balance sheet (6), income statement (8), cash flow (4),
  debt and liquidity ratios (9), profitability (5), growth (13), earnings history for the
  Lynch categories (9), quality scores (6), valuation (18).
- **Draft status:** 16 core, 44 candidate, 11 context (absolute amounts needed to read the
  others), 10 derived (depend on a peer group or a model, not the stock alone).
- **Left out on purpose:** technicals, analyst targets and ratings, market data. None comes
  from the financial statements.

The full list and one entry per metric are in [docs/METRICS.md](../docs/METRICS.md),
generated from the TOML.

## 2. The numbers

### Absolute values first: the worked-example stock

Boston Scientific, last 12 months to 2026-09-30, Yahoo (price as of the 2026-10-26 close).

| Group | Value | BSX |
|---|---|---|
| Price and value | Share price | $45.58 |
| | Market value | $66.06bn |
| | DCF fair value | $34.09 |
| | Cash flow before growth (DCF base) | $3.40bn |
| Debt and cash | Total debt | $12.62bn |
| | Net debt | $12.09bn |
| | Short-term debt | $1.71bn |
| | Long-term debt | $10.92bn |
| | Cash | $0.54bn |
| Earnings | Revenue | $21.00bn |
| | EBITDA | $5.64bn |
| | Net income | $3.68bn |
| | EPS, GAAP | $2.47 |
| | EPS, adjusted | $3.21 |
| | Forward EPS | $3.38 |
| Cash flow | Operating cash flow | $4.53bn |
| | Capex | -$2.72bn (Yahoo; -$0.90bn on TradingView and SEC) |
| | Free cash flow | $1.81bn |

### The proposed first vector (16 metrics)

Chosen to cover each thing Babak's method checks, with one measure each where several say
the same thing, and to be comparable across companies of any size (ratios, not dollars).

| Metric | What it checks | BSX |
|---|---|---|
| Cash / short-term debt | Babak's must-have 1: this year's debt covered by cash | 0.32x (fails) |
| Cash / long-term debt | Babak's must-have 2: a cash cushion | 4.9% (just fails) |
| Net debt / EBITDA | Leverage | 2.14x |
| Interest cover | Can it pay its lenders | 15.5x |
| Net margin | Profitability | 17.5% |
| Revenue growth, median year | Growth, typical year | 17.6% |
| EPS growth, median year | Growth; sorts Lynch's growers | 35.9% (5 yrs) |
| OCF growth, median year | Cash growth | 37.2% |
| Piotroski F-score | Nine-point financial strength | 8 |
| Altman Z-score | Distress risk | 2.93 (grey zone) |
| Lynch category | Which rules apply | fast grower |
| EPS, adjusted | Babak's "true" EPS | $3.21 |
| P/E, adjusted | Babak's "true" P/E | 14.0x |
| P/E against own 10-year median | Cheap against its own history | -44% |
| FCF yield | Cash return at today's price | 2.7% |
| Price against own cheap price | Stage 2's ranking measure | (BSX fails Stage 1) |

The named sets `absolute_values`, `strict_screen`, `weighted_screen`, `stage1` and
`watchlist` in the TOML reproduce the inputs of each existing screen, so any of them can be
used as a vector as well.

## 3. Method and open choices

**How it is built.** Each metric records where it lives in each of our tables: `sector`
(Yahoo, `analysis/sector.py`), `stage1` (TradingView, `analysis/stage1.py`), `stage2` and
`watchlist`. `build_vectors()` takes any of those tables and returns one row per stock and one
column per chosen metric, in the dictionary's units (TradingView's percentages are rescaled),
with metrics worked out from others where the formula allows, booleans as 0/1 and the Lynch
category as six 0/1 columns. A metric the table doesn't have is a blank column, so every
vector has the same shape. `standardize()` turns a group of vectors into 0-100 percentiles
(or z-scores) with lower-is-better metrics reversed, so 100 is always best.

**Open choices for Babak** (Claude's suggestion in brackets):

1. **The set.** Cut or extend the 16 above. [Start with them; add ROIC later.]
2. **Fundamentals only, or valuation too?** Babak's method keeps them apart: Stage 1 is the
   statements, Stage 2 is the price. The vector could follow that with a "quality" vector and
   a separate "price" vector. [Two vectors.]
3. **Which growth window.** Yahoo gives 3-4 years, TradingView 5-10, SEC back to 2016.
   [5 years from TradingView or SEC, since 3 years is one cycle at most.]
4. **GAAP or adjusted EPS** for the growth and Lynch measures. Adjusted is Babak's "true"
   EPS but is only fetched for the watch list and Stage 2's top stocks. [Adjusted where we
   have it.]
5. **Which first must-have.** Cash / short-term debt fails companies that keep little cash
   but generate a lot (BSX: 0.32x, but 2.97x counting a year's operating cash flow).
   [Keep the strict one, add the cash-plus-OCF one as a candidate.]
6. **Net cash.** Net debt / EBITDA goes negative with net cash, and cover ratios are infinite
   without debt. [Clip at 0 and at a ceiling (e.g. 50x) before standardizing.]
7. **Lynch category in the vector, or as a split.** As six 0/1 columns, or compare stocks
   only within their category. [Within category: a fast grower and a slow grower should not
   be judged on one scale.]
8. **Recompute Piotroski and Altman ourselves** from SEC filings rather than trusting
   TradingView's. [Later, for the stocks we hold or watch.]
9. **Drop cash-balance growth.** It jumps with deals and debt raises (BSX +375% in 2025).
   [Drop.]

**Defaults taken until Babak answers (2026-10-27).** Babak asked for the work to be
finished without waiting, so Claude's suggestions above are the working defaults. Each one
is a setting, not a rewrite, and can be changed after review:

| # | Default in use | Where |
|---|---|---|
| 1 | The 16 metrics of the `proposed` set | `config/metrics.toml` `[sets]` |
| 2 | Two vectors (quality, price) suggested; nothing builds one yet | report only |
| 3 | 5-year growth window | `growth_years` in the screener and metrics |
| 4 | Adjusted EPS where we have it (watch list, Stage 2's closest names) | `analysis/stage2.py`, `watchlist.py` |
| 5 | Strict cash / short-term debt stays a must-have; cash plus OCF is a candidate | `config/metrics.toml` |
| 6 | **Built:** net debt / EBITDA clipped at 0, cover ratios capped at 50x before standardizing (`clip=False` turns it off) | `clip` in `config/metrics.toml`, `build_vectors()` |
| 7 | Compare within Lynch category (suggested); the vector still carries six 0/1 columns | report only |
| 8 | Keep TradingView's Piotroski and Altman for now | report only |
| 9 | **Built:** cash-balance growth is "context", not in the proposed set | `config/metrics.toml` |

## Caveats

- Sources disagree. Yahoo and TradingView count cash, EBITDA and capex differently (BSX
  EBITDA $5.64bn vs $5.99bn; capex $2.72bn vs $0.90bn). Each metric records its source.
- Worked examples are as of their dates and will drift; the formulas don't.
- Peer-relative metrics (P/E against industry, the weighted scores) change with the peer
  group, so they are marked "derived" and not proposed for the vector.

## Reproduce

```
uv run python -m stock_analysis.metrics list --set proposed
uv run python -m stock_analysis.metrics doc            # rewrite docs/METRICS.md
uv run python -m stock_analysis.metrics vector data/peers/medtech.csv --source sector BSX
uv run python -m stock_analysis.metrics vector data/screener/stage1.csv --source stage1 \
    --set stage1 --standardize percentile BSX
```
