# CEG vs peers: debt, growth, leverage and valuation

*Data as of 2026-09-25 close; balance sheets at 2026-06-30. Written 2026-09-27.*

**Peers:**
- Independent power producers: Vistra (VST), NRG Energy (NRG), Talen (TLN).
- Regulated utilities as the sector benchmark: NextEra (NEE), Duke (DUK), Southern (SO).

## Absolute values

| | CEG | VST | NRG | TLN | NEE | DUK | SO |
|---|---|---|---|---|---|---|---|
| Market value | $93bn | $46bn | $21bn | $15bn | $159bn | $88bn | $95bn |
| Total debt | $24.7bn | $19.9bn | $23.5bn | $9.6bn | $110bn | $92bn | $77bn |
| Free cash flow, 12m | $0.31bn | $2.25bn | $0.32bn | $0.44bn | $3.05bn | −$4.27bn | −$3.27bn |
| Revenue, FY2025 | $25.5bn | $17.7bn | $30.7bn | $2.6bn | $27.4bn | $32.2bn | $29.6bn |

## Debt

| | CEG | VST | NRG | TLN | NEE | DUK | SO |
|---|---|---|---|---|---|---|---|
| Net debt / EBITDA | 2.9x | 3.0x | 6.2x | 12.1x | 6.1x | 5.2x | 5.0x |
| EBITDA / interest | 10.5x | 6.8x | 3.6x | 1.5x | 5.0x | 4.7x | 4.6x |
| Debt change, 1 year | +197% | +10% | +111% | +213% | +18% | +4% | +9% |

### Net debt / EBITDA history

| | 2022 | 2023 | 2024 | 2025 | Latest 12m |
|---|---|---|---|---|---|
| CEG | 3.4x | 1.9x | 0.8x | 0.9x | 2.9x |
| VST | 12.3x | 2.4x | 2.3x | 3.8x | 3.0x |
| NRG | 2.8x | 6.0x | 2.9x | 3.6x | 6.2x |
| TLN | – | – | 1.5x | 12.0x | 12.1x |
| NEE | 6.9x | 4.2x | 5.8x | 5.8x | 6.1x |
| DUK | 6.0x | 5.8x | 5.7x | 5.3x | 5.2x |
| SO | 5.6x | 5.3x | 4.9x | 5.1x | 5.0x |

**Reading the debt numbers:**
- CEG's leverage jumped in a single step with Calpine.
- CEG's 2.9x is overstated: EBITDA includes only six months of Calpine while debt includes all of it. On a full-year basis it is about 2.5x (assuming roughly $3bn a year of Calpine EBITDA, an estimate).
- NRG and Talen also borrowed for acquisitions (the LS Power portfolio and the Cornerstone assets).
- Regulated utilities normally run at 5–6x, because their revenue is set by regulators.

## Growth

| | CEG | VST | NRG | TLN | NEE | DUK | SO |
|---|---|---|---|---|---|---|---|
| Revenue growth, 2022–25 compound | 1% | 9% | −1% | 10% | 9% | 4% | 0% |
| Latest quarter revenue vs a year earlier | +23% | −6% | +11% | +111% | +12% | +1% | 0% |
| Share price, 1 year | −19% | −31% | −38% | −26% | +5% | −4% | −9% |
| Share price, 3 years | +139% | +322% | +171% | +460% | +23% | +36% | +33% |

## Valuation

| | CEG | VST | NRG | TLN | NEE | DUK | SO |
|---|---|---|---|---|---|---|---|
| **Trailing P/E** | 25.7 | 23.3 | 26.1 | loss | 17.1 | 17.1 | 20.0 |
| Forward P/E | 19.8 | 13.4 | 9.0 | 9.9 | 17.3 | 15.8 | 16.8 |
| EV / EBITDA, 12m | 14.3 | 10.1 | 11.9 | 31.1 | 15.0 | 10.2 | 11.4 |
| FCF yield | 0.3% | 4.8% | 1.5% | 3.0% | 1.9% | −4.8% | −3.4% |
| Dividend yield | 0.7% | 0.7% | 1.9% | – | 3.3% | 3.8% | 3.7% |
| Below 52-week high | −36% | −36% | −47% | −33% | −23% | −16% | −18% |
| Analyst target upside | +32% | +57% | +88% | +51% | +30% | +21% | +20% |

## Conclusions

- **CEG** has the strongest balance sheet among the power producers and the best interest cover. On EV/EBITDA and forward P/E it is the most expensive of them. On trailing P/E it is level with NRG (25.7 vs 26.1) and above Vistra.
- **Vistra** is the cheapest good-quality name. It has similar leverage to CEG and the best free cash flow, but its earnings depend more on power prices.
- **NRG and Talen** look cheap on forward earnings but are highly indebted.
- **Regulated utilities** are fairly valued, with 3–4% dividends and low volatility.

**Caveat:** EBITDA and EPS are GAAP figures, so hedge accounting moves them a lot. Single-year P/E and EBITDA ratios can mislead.

Reproduce: `analysis/compare.py`, `analysis/debt_to_ebitda.py`, `analysis/valuation.py`.
