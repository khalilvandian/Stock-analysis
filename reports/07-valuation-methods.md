# Ways to estimate what a stock is worth

*Reference note, 2026-09-27.*

There is no single "actual" price. Each method estimates a fair value from different assumptions. Good practice is to combine three or four methods into a range.

## 1. Intrinsic value: future cash, valued today

| Method | How it works | Best for | Used in this project |
|---|---|---|---|
| DCF on free cash flow to the firm (FCFF) | Cash flow before interest, discounted at the WACC, minus net debt | Comparing companies with different debt | Yes (`dcf_firm.py`) |
| DCF on free cash flow to equity (FCFE) | Cash flow after interest, discounted at the cost of equity | Power producers with cash-flow guidance | Yes (`dcf.py`) |
| Dividend discount model | Present value of future dividends | Utilities and steady dividend payers | Yes (utilities) |
| Gordon growth model | Next year's dividend ÷ (required return − growth) | Mature, stable companies | Inside the dividend model |
| Residual income | Book value plus profits above the required return | Banks and insurers | No |
| Reverse DCF | Solves for the growth the current price assumes | Testing whether expectations are realistic | Yes |
| Sum of the parts | Values each division separately | Conglomerates, e.g. CEG's nuclear, gas and retail | Not yet |

## 2. Relative value: compared with peers

These are ratios:
- **P/E**, trailing and forward
- **PEG** (P/E ÷ expected growth)
- **EV/EBITDA** and EV/EBIT
- **Price/sales** and price/book
- **Price/free cash flow** and free cash flow yield
- **Dividend yield** and earnings yield
- A stock's own historical multiples
- **Precedent transactions**, such as the price paid for Calpine

In this project, EV/EBITDA, trailing P/E and free cash flow yield are used most. Price/book is distorted by share buybacks.

## 3. Asset-based value

- Book value and tangible book value
- Liquidation value
- **Replacement cost (Tobin's Q):** strong for power plants, because a new nuclear plant costs far more per GW than CEG's market value
- Net asset value

## 4. Market signals

Analyst targets, option prices (implied volatility), short interest, insider buying and selling, buybacks, and credit spreads.

## 5. Technical indicators (timing, not value)

Moving averages, RSI, MACD, Bollinger Bands, support and resistance, volume, and beta.

## Not yet built

- Sum-of-the-parts valuation for CEG
- Replacement cost
- Precedent transactions
- Historical multiple bands
- Technical indicators on the dashboard
