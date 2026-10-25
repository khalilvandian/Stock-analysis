# Discounted cash flow: CEG, peers and utilities

*Data as of 2026-09-25 close; guidance from company releases (Q2 2026). Written 2026-09-27.*

Two DCF models were built:
- **Equity DCF** (`analysis/dcf.py`) values the shares directly, from cash flow left after interest.
- **Enterprise DCF** (`analysis/dcf_firm.py`) values the whole company from cash flow before interest, then subtracts net debt. This is the classic DCF and the main one.

## Inputs

| | Starting cash flow (company guidance, 2026) | Source |
|---|---|---|
| CEG | $4.2bn a year 2026–27, about $6.1bn a year 2028–29 | "Free cash flow before growth" of $8.4bn for 2026–27 and $11.5–13bn for 2028–29 |
| VST | $4.33bn | 2026 adjusted guidance, $3.925–4.725bn |
| NRG | $3.05bn | 2026 guidance, $2.8–3.3bn (includes LS Power) |
| TLN | $1.275bn | 2026 adjusted guidance, $1.2–1.35bn (raised, includes Cornerstone) |

"Free cash flow before growth" is operating cash flow after interest and maintenance spending, but before spending on growth projects.

**Common assumptions:**
- **Risk-free rate:** 5.18%, the 10-year Treasury yield on 2026-09-25.
- **Equity risk premium:** 5%.
- **Beta:** each stock's beta adjusted toward 1 (the Blume adjustment).
- **Cost of debt:** the risk-free rate plus a spread for each company's credit rating.
- **Tax rate:** 21%.
- **Growth:** low, mid and high cases grow 0%, 4% or 8% a year for five years, then fade over five years to 2.5% a year forever.

## Enterprise DCF (main model)

The enterprise DCF discounts free cash flow before interest (FCFF) at the WACC, the blended cost of debt and equity.

| | CEG | VST | NRG | TLN |
|---|---|---|---|---|
| **Current price** | **$263.27** | **$138.46** | **$100.37** | **$304.42** |
| FCFF (first year) | $4.82bn | $5.09bn | $3.86bn | $1.67bn |
| WACC | 9.4% | 9.8% | 8.3% | 10.1% |
| Enterprise value (mid case) | $97.2bn | $75.9bn | $72.4bn | $23.6bn |
| Net debt | $24.0bn | $19.5bn | $23.3bn | $9.3bn |
| Fair value per share: low / **mid** / high | $163 / **$207** / $260 | $126 / **$168** / $221 | $166 / **$234** / $318 | $206 / **$298** / $411 |
| Price vs mid fair value | **28% above** | **18% below** | 57% below | 2% above |
| Growth the price assumes | 8.2% a year | 1.3% | −4.9% | 4.3% |

- **NRG's WACC is low because debt is 53% of its financing,** and debt is cheaper than equity. At a 9.4% WACC, NRG's fair value would be about $177; at 10.5%, about $137.
- **CEG adjusted:** subtracting an estimated $2bn a year of growth spending in 2027–28 lowers the mid value to about $202. The guided 2028–29 cash flows include returns from projects whose cost is not in "before growth" cash flow.

**CEG sensitivity: fair value per share by WACC and long-term growth**

| WACC | 1.5% | 2.0% | 2.5% | 3.0% | 3.5% |
|---|---|---|---|---|---|
| 7.5% | $273 | $293 | $316 | $345 | $381 |
| 8.0% | $246 | $262 | $280 | $303 | $330 |
| 8.5% | $222 | $235 | $251 | $269 | $290 |
| 9.0% | $202 | $213 | $225 | $240 | $257 |
| 10.0% | $169 | $176 | $185 | $195 | $206 |

CEG's $263 price is justified only at a WACC of about 8.5% or lower, or with about 8% growth after 2029.

## Equity DCF and dividend model

| | Price | Fair value: low / mid / high | Price vs mid | Growth the price assumes |
|---|---|---|---|---|
| CEG | $263 | $180 / $212 / $251 | 24% above | 9.1% |
| VST | $138 | $126 / $153 / $186 | 10% below | 2.0% |
| NRG | $100 | $155 / $189 / $232 | 47% below | −8.9% |
| TLN | $304 | $241 / $292 / $354 | 4% above | 4.9% |
| NEE (dividends) | $76 | $42 / $46 / $50 | 65% above | 15.3% |
| DUK (dividends) | $113 | $85 / $95 / $103 | 19% above | 9.2% |
| SO (dividends) | $83 | $61 / $69 / $74 | 21% above | 9.4% |

At a 7.5% required return, the utilities' fair values rise: Duke to $106, Southern to $74 and NextEra to $61.

## Why the enterprise DCF does not work for utilities

| | Return on invested capital | WACC | Value if they stopped growing |
|---|---|---|---|
| NEE | 4.9% | 7.4% | about $2 |
| DUK | 5.4% | 6.5% | about $38 |
| SO | 5.7% | 6.7% | about $23 |

The utilities' return on invested capital is below their WACC. In the model, every dollar of growth investment then destroys value, so the results come out near zero or negative. Investors accept regulated returns much as they accept bond yields, so utilities are better valued on dividends and P/E.

## Conclusions

- **The market pays for certainty.** CEG and NextEra, whose revenue is the most contracted or regulated, have the lowest cash yields (3–4.5%). The producers more exposed to power prices have the highest (9–15%).
- **High interest rates are the main pressure.** With the 10-year Treasury at 5.2%, only strong growth justifies CEG at 25x earnings.
- **Vistra** is undervalued on every DCF variant.

Reproduce: `uv run python analysis/dcf_firm.py` and `uv run python analysis/dcf.py`.
