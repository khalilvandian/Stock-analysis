# Alphabet (GOOGL): fundamentals and an AI-adjusted P/E

*Prices on 2026-10-29 (GOOGL $286.55, SpaceX $143.99); 12-month figures to 2026-09-30 from
Alphabet's Q4 2025 to Q3 2026 earnings releases and the Q3 2026 10-Q (filed 2026-10-29).
Written 2026-10-29.*

## 1. Summary

**The business is the strongest it has been in years, but the stock is not cheap. The
GAAP P/E of 15x is an illusion: 43% of the last year's earnings are paper gains on the
Anthropic and SpaceX stakes. On operating earnings Alphabet trades at about 26x, or 24.5x
once the stakes are taken out of the price, in line with its 10-year median of 24.8x.
View: wait, and buy below about $259 (22x). The circular AI deals are a real risk, but it
sits in the backlog and the guarantees, not in today's earnings.**

- **Doing well:** Q3 revenue +25%, Google Cloud +103%, operating income +30%.
- **Not cheap:** 25.8x core EPS of $11.09; core EPS grew about 23%, so the PEG is about 1.1.
- **Weak:** free cash flow fell to $19.7bn over 12 months (negative in Q2 and Q3) as capex
  reached $160bn. No buybacks in 2026; $62bn of new equity and $85bn of new debt.
- **AI-adjusted P/E:** marks out of E, after-tax stakes ($14.93 a share) out of P, and a
  check of how much revenue Alphabet funds itself (section 3).

## 2. The numbers

Run through this project's process against five megacap peers.

### Absolute values, latest 12 months

| Group | Value | GOOGL |
|---|---|---|
| Price and value | Share price | $286.55 |
| Price and value | Market value (12.29bn shares) | $3,523bn |
| Price and value | DCF fair value (standard) | $161.01 |
| Price and value | Cash flow before growth (DCF base) | $162.2bn |
| Debt and cash | Total debt | about $126bn |
| Debt and cash | Short-term debt | about $1bn (June) |
| Debt and cash | Long-term debt | $125.1bn |
| Debt and cash | Cash and bonds (excluding equity stakes) | $174.7bn |
| Debt and cash | Net debt | −$49.6bn (net cash) |
| Earnings | Revenue | $471.1bn |
| Earnings | EBITDA (operating income + depreciation) | $185.0bn |
| Earnings | Net income (GAAP) | $235.7bn |
| Earnings | EPS (GAAP) | $19.16 |
| Earnings | EPS (core: without stake marks and one-offs) | $11.09 |
| Earnings | Forward EPS (consensus, next year) | $15.31 |
| Cash flow | Operating cash flow | $179.6bn |
| Cash flow | Capex | $159.8bn |
| Cash flow | Free cash flow | $19.7bn |

Net income is 1.3 times operating cash flow because $129.6bn of it is gains on equity
stakes. Capex is 5.7 times depreciation. The peer tool's EBITDA for GOOGL ($326.8bn, Yahoo,
June) includes the stake gains, so the table uses operating income plus depreciation.

### Absolute values by year (SEC)

Per-share figures adjusted for the 20-for-1 split of July 2022. Market value is
approximate (diluted shares × year-end price).

| Year | Price (year end) | Market value | Revenue | Operating income | Net income | EPS | Operating CF | Capex | Free CF | Cash (excl. bonds) |
|---|---|---|---|---|---|---|---|---|---|---|
| 2025 | $313.00 | $3,828bn | $402.8bn | $129.0bn | $132.2bn | $10.81 | $164.7bn | $91.4bn | $73.3bn | $30.7bn |
| 2024 | $189.30 | $2,356bn | $350.0bn | $112.4bn | $100.1bn | $8.04 | $125.3bn | $52.5bn | $72.8bn | $23.5bn |
| 2023 | $139.69 | $1,777bn | $307.4bn | $84.3bn | $73.8bn | $5.80 | $101.7bn | $32.3bn | $69.5bn | $24.0bn |
| 2022 | $88.23 | $1,160bn | $282.8bn | $74.8bn | $60.0bn | $4.56 | $91.5bn | $31.5bn | $60.0bn | $21.9bn |
| 2021 | $144.85 | $1,963bn | $257.6bn | $78.7bn | $76.0bn | $5.61 | $91.7bn | $24.6bn | $67.0bn | $20.9bn |
| 2020 | $87.63 | $1,204bn | $182.5bn | $41.2bn | $40.3bn | $2.93 | $65.1bn | $22.3bn | $42.8bn | $26.5bn |
| 2019 | $66.97 | $936bn | $161.9bn | $34.2bn | $34.3bn | $2.46 | $54.5bn | $23.5bn | $31.0bn | $18.5bn |
| 2018 | $52.25 | $735bn | $136.8bn | $27.5bn | $30.7bn | $2.19 | $48.0bn | $25.1bn | $22.8bn | $16.7bn |
| 2017 | $52.67 | $741bn | $110.9bn | $26.2bn | $12.7bn | $0.90 | $37.1bn | $13.2bn | $23.9bn | $10.7bn |
| 2016 | $39.62 | $554bn | $90.3bn | $23.7bn | $19.5bn | $1.39 | $36.0bn | $10.2bn | $25.8bn | $12.9bn |

Revenue grew every year. Free cash flow was $60–73bn a year from 2021 to 2025; 2026 is the
first year it falls sharply. Long-term debt went from $11bn (2024) to $125bn (Sep 2026).

### Method

- Peers: META, MSFT, AMZN, AAPL, ORCL (`data/peers/megacap_tech.csv`), with the usual
  `analysis/screen.py` rules and weights. The peer table is Yahoo's, which still showed
  GOOGL's June figures on 2026-10-29.
- The screen uses GAAP P/E, as for every company; it was rerun with GOOGL's core figures.

### Ratios and screens

| Measure | GOOGL | Rule or peers | Result |
|---|---|---|---|
| Net debt / EBITDA | net cash | ≤ 4.5x | Pass |
| EBITDA / interest | 145x | ≥ 4x | Pass |
| Cash / short-term debt | 242x | ≥ 1x | Pass |
| Cash / long-term debt | 215% | ≥ 5% | Pass |
| Revenue growth, 2023–2025 | +8.7%, +13.9%, +15.1% | > 0 | Pass |
| EPS growth (GAAP), 2023–2025 | +27%, +39%, +35% | > 0 | Pass |
| P/E, trailing (GAAP) | 15.0x | META 21.3x, MSFT 29.3x, AMZN 19.8x, AAPL 40.2x, ORCL 21.8x | Looks cheapest |
| P/E, core ex-stakes | 24.5x | same peers (GAAP) | Middle |
| Forward P/E | 18.7x | META 17.5x, MSFT 22.2x, AMZN 23.5x | Middle |
| Price vs standard DCF | +78% above $161 | < 0 | Expensive |

The standard DCF assumes 2.5% growth forever on $162bn at a 10.7% WACC; today's price
implies about 5.9%. Its base (operating cash flow minus depreciation) ignores that capex is
now five times depreciation.

Strict screen: all six pass. Weighted screen:

| Rank | Company | Total | Debt | Profitability and cash | Cheapness |
|---|---|---|---|---|---|
| 1 | **GOOGL** | **81.4** | **91.7** | **71.4** | **70.8** |
| 2 | MSFT | 64.3 | 75.0 | 57.1 | 50.0 |
| 3 | AMZN | 62.5 | 66.7 | 66.7 | 50.0 |
| 4 | META | 58.6 | 45.8 | 76.2 | 66.7 |
| 5 | ORCL | 42.9 | 20.8 | 46.4 | 83.3 |
| 6 | AAPL | 40.3 | 50.0 | 32.1 | 29.2 |

With GOOGL's core figures (P/E 25.8x, EBITDA $185bn, net income $136bn) it stays 1st
(75.9) on its balance sheet, but cheapness falls to 58.3 and profitability to 61.9.
Amazon's GAAP earnings also carry Anthropic gains.

## 3. Analysis

### The AI-adjusted P/E

**Recommended measure: core P/E ex-stakes = (price − after-tax value of equity stakes per
share) / (GAAP EPS − after-tax marks on equity stakes + one-offs).** It moves Alphabet from
15.0x to 24.5x. Almost all of the move comes from the stake marks, not from circular
revenue.

**The circle, from the filings.** Alphabet put $20bn into Anthropic in 2026 (March and May)
and can add $20bn more through 2030; it owned about 14% before. Anthropic committed in
March 2026 to spend at least $114.5bn with Google from April 2026 to July 2033, and expects
$125–150bn more of TPU compute in 2028–2031. Alphabet owns about 498 million SpaceX
shares; SpaceX's AI unit has agreed to sell Anthropic up to $120.5bn of GPU compute. Each
funding round sets a higher price for Anthropic and Alphabet marks its whole stake up to
it: $129.6bn of equity-stake gains in the last 12 months.

**What is discounted, and why.**

| Step | What changes | Amount | Why |
|---|---|---|---|
| 1. Marks out of E | EPS minus the after-tax gains and losses on equity stakes (Alphabet's own per-quarter figures) | −$8.21 a share (Q4 2025 +0.15, Q1 2026 +2.35, Q2 2026 +6.26, Q3 2026 −0.55) | Revaluations, not cash earned; often set by rounds Alphabet joins, and they reverse |
| 1b. One-offs out of E | Waymo compensation charge, Q4 2025 | +$0.14 a share | One-off |
| 2. Stakes out of P | Price minus after-tax stakes | −$14.93 a share | Once the gains leave E the price must not pay for the stakes; Lynch's cash-per-share rule applied to investments |
| 3. Circular revenue | Cloud revenue paid with Alphabet's own money | −$0.04 to −$0.11 a share | Too small to deduct; tracked as a risk |

Stakes at 30 September 2026: private companies at last-round price, mostly Anthropic,
$128.2bn; SpaceX 498m shares at $143.99, $71.8bn; other listed stakes $15.2bn; less 21% tax
on about $150bn of unrealized gains, −$31.6bn. After tax: $183.5bn, $14.93 a share.

| Measure | Price | EPS | P/E |
|---|---|---|---|
| GAAP | $286.55 | $19.16 | 15.0x |
| Without marks | $286.55 | $10.95 | 26.2x |
| Core (marks and one-offs out) | $286.55 | $11.09 | 25.8x |
| **Core ex-stakes** | **$271.62** | **$11.09** | **24.5x** |

Stake worth nothing → 25.8x. Anthropic lists well above its last round → below 24.5x.

**Circular revenue.** In H1 2026 Anthropic took in $16.3bn of revenue and $110.8bn of
financing; Alphabet's $20bn was about 16% of it. So about 16% of what Anthropic pays Google
is Google's own money. Alphabet does not disclose that amount; at $10–30bn a year the
self-funded part is $1.6–4.7bn of revenue and $0.04–0.11 of EPS (36% Cloud margin, 21% tax).

**Where the circular risk sits.** Cloud backlog $561bn, of which Anthropic's minimum is
about a fifth and Crux AI (a joint venture Alphabet partly owns) $16.8bn. $75.7bn of
data-centre backstops and $22.8bn of financial guarantees; TPU buyers' options to sell
the chips back; $21.1bn of milestone-based forward funding for one strategic investment.

### Core P/E against its own history

Core EPS removes stake marks, the EU fines (2017, 2018, 2019, 2025), the 2017 tax-reform
charge and the 2025 Waymo charge (gains taxed at 21%).

| Year | Average price | GAAP EPS | Core EPS | Core P/E |
|---|---|---|---|---|
| Now (12 months to Sep 2026) | $286.55 | $19.16 | $11.09 | 25.8x (24.5x ex-stakes) |
| 2025 | $216.50 | $10.81 | $9.67 | 22.4x |
| 2024 | $164.75 | $8.04 | $7.80 | 21.1x |
| 2023 | $119.88 | $5.80 | $5.78 | 20.8x |
| 2022 | $112.52 | $4.56 | $4.77 | 23.6x |
| 2021 | $125.09 | $5.61 | $4.89 | 25.6x |
| 2020 | $74.33 | $2.93 | $2.61 | 28.5x |
| 2019 | $59.79 | $2.46 | $2.43 | 24.6x |
| 2018 | $56.18 | $2.19 | $2.24 | 25.1x |
| 2017 | $47.30 | $0.90 | $1.82 | 26.1x |
| 2016 | $38.19 | $1.39 | $1.39 | 27.4x |

Median 24.8x, range 20.8–28.5x. Core EPS grew about 24% a year since 2016 and about 23% in
the last 12 months, so the Lynch PEG is about 1.1: fair, not a bargain.

### Entry price

Entry = target core P/E × $11.09 + $14.93.

| Core P/E | Entry price | vs today |
|---|---|---|
| 18x | $214 | −25% |
| 20x | $237 | −17% |
| **22x** | **$259** | **−10%** |
| 24x | $281 | −2% |
| 25x (10-year median) | $292 | +2% |

Proposed: 22x ≈ $259, the 2023–2025 level, with a discount for the capex and the dilution.

### Business, cash flow and risks

- Q3 2026: revenue $127.6bn (+25%); Services $96.3bn (+11%), Search +12%, YouTube ads +9%;
  Cloud $30.7bn (+103%) with TPU system sales, 36% margin; Other Bets −$2.0bn.
- The stock fell 12% on 2026-10-29: core EPS $2.67 vs about $3.02 expected, Search missed,
  free cash flow −$9.1bn, 2027 capex to "increase significantly" from $195–205bn.
- Funding: no buybacks in 2026 ($69.5bn authorization unused), $42.9bn of new shares,
  $19.1bn of mandatory convertible preferred and $85.2bn of new debt; shares outstanding up
  1.7%. Purchase commitments $924bn; data-centre leases not yet started $130.5bn.
- Risks: return on the build-out; customer concentration in AI labs; reported EPS swinging
  with Anthropic's share price after its IPO; Search slowing from 17–19% to 12%.
- Watch: Anthropic's IPO price and lock-up, 2027 capex (Q4 report, early February), Cloud
  margin in Q4, return of buybacks.

## Caveats

- What Anthropic pays Alphabet is not disclosed; the circular-revenue figure is a range.
- Private stakes are carried at the last funding-round price, not a market price.
- The peer table, short-term debt and the DCF base are Yahoo's June figures.
- Pre-2022 EPS and market values are split-adjusted by hand; 2016–2019 core EPS uses
  approximate fine and tax-charge amounts.
- This report was written by Claude, which is made by Anthropic. Every Anthropic figure
  comes from its S-1 or Alphabet's filings.

**Reproduce:** `uv run python analysis/peer_screen.py megacap_tech GOOGL META MSFT AMZN AAPL ORCL`;
the adjustments use the Q3 2026 8-K and 10-Q (`sec.gov`, CIK 1652044) and the Anthropic S-1
(CIK 2130357). Metrics `eps_core_ex_marks`, `stakes_after_tax_per_share` and
`pe_core_ex_stakes` are defined in `config/metrics.toml`.
