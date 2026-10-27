# Booking Holdings (BKNG): fundamentals and analysis

*Prices intraday on 2026-10-27 (about $151.9); SEC filings through 2026-06-30. Written 2026-10-27.*

## 1. Summary

**Booking is the strongest balance sheet and the biggest cash generator among online travel companies. Its stock is down 29% this year on fears that AI agents will bypass it. It is the cheapest it has been in a decade, earnings are still growing in the mid-teens, and growth in room nights is slowing. View: start a position now and add below about $145. The Q3 report on Nov 3 is the next test.**

- **Cheap:** about 16x clean earnings, against a 10-year norm of about 21–22x. The standard DCF puts fair value 17% above today's price.
- **Strong:** passes every strict debt rule, generates $9.5bn of free cash flow a year, and returns about 10% of its market value to shareholders each year.
- **Weak:** shareholders' equity is negative because of buybacks, and the strongest peer (Trip.com) and the cheapest (Expedia) score better in the weighted screen.
- **Uncertain:** room-night growth fell from 8–9% to a guided 3–5%. AI agents and regulators in the EU and the US are open risks.

## 2. The numbers

Run through this project's process against six online-travel peers.

### Absolute values, latest 12 months

| Group | Value | BKNG |
|---|---|---|
| Price and value | Share price | $151.93 |
| Price and value | Market value | $114.15bn |
| Price and value | DCF fair value (standard) | $183.39 |
| Price and value | Cash flow before growth (DCF base) | $10.02bn |
| Debt and cash | Total debt | $20.69bn |
| Debt and cash | Net debt | $3.48bn |
| Debt and cash | Short-term debt | $2.00bn |
| Debt and cash | Long-term debt | $18.69bn |
| Debt and cash | Cash | $17.21bn |
| Earnings | Revenue | $28.24bn |
| Earnings | EBITDA | $11.11bn |
| Earnings | Net income | $7.21bn |
| Earnings | EPS (GAAP) | $9.02 |
| Earnings | EPS (adjusted, company figure) | $9.61 |
| Earnings | Forward EPS (adjusted, 2027 consensus) | $12.37 |
| Cash flow | Operating cash flow | $9.86bn |
| Cash flow | Capex | $0.32bn |
| Cash flow | Free cash flow | $9.54bn |

About $10bn of the cash is customer prepayments for future stays (deferred merchant bookings). Excluding it, net debt is about $14bn, or 1.2x EBITDA.

### Absolute values by year (SEC)

Per-share figures and market value are adjusted for the 25-for-1 split of 2 April 2026.

| Year | Price | Market value | Revenue | EBITDA | Net income | EPS | Operating CF | Free CF | Net debt | Cash |
|---|---|---|---|---|---|---|---|---|---|---|
| 2025 | $214.21 | $174.8bn | $26.9bn | $9.4bn | $5.4bn | $6.62 | $9.4bn | $9.1bn | $1.5bn | $17.2bn |
| 2024 | $198.74 | $169.2bn | $23.7bn | $8.1bn | $5.9bn | $6.91 | $8.3bn | $7.9bn | $0.4bn | $16.2bn |
| 2023 | $141.89 | $129.6bn | $21.4bn | $6.3bn | $4.3bn | $4.70 | $7.3bn | $7.0bn | $2.1bn | $12.1bn |
| 2022 | $80.61 | $80.7bn | $17.1bn | $5.6bn | $3.1bn | $3.05 | $6.6bn | $6.2bn | $0.3bn | $12.2bn |
| 2021 | $95.97 | $99.2bn | $11.0bn | $2.9bn | $1.2bn | $1.13 | $2.8bn | $2.5bn | −$0.2bn | $11.1bn |
| 2020 | $89.09 | $91.7bn | $6.8bn | −$0.2bn | $0.1bn | $0.06 | $0.1bn | −$0.2bn | $1.5bn | $10.6bn |
| 2019 | $82.15 | $89.4bn | $15.1bn | $5.8bn | $4.9bn | $4.47 | $4.9bn | $4.5bn | $1.3bn | $6.3bn |
| 2018 | $68.90 | $82.7bn | $14.5bn | $5.8bn | $4.0bn | $3.33 | $5.3bn | $4.9bn | $6.0bn | $2.6bn |
| 2017 | $69.51 | $86.8bn | $12.7bn | $4.9bn | $2.3bn | $1.87 | $4.7bn | $4.4bn | $6.3bn | $2.5bn |
| 2016 | $58.64 | $73.4bn | $10.7bn | $3.2bn | $2.1bn | $1.71 | $4.0bn | $3.8bn | $4.1bn | $2.1bn |

Revenue has grown every year except 2020 and 2021 (COVID). Free cash flow has more than doubled since 2016, while the share count fell from 1.25bn to 0.77bn (split-adjusted).

### Method

- `analysis/sector.py`'s `analyse()` provides the latest values and ratios, and `analysis/history.py`'s `sec_history()` provides the yearly history.
- `analysis/screen.py` rules and weights are unchanged. Peers replace the utilities universe, with one peer median for P/E and EV / EBITDA.
- Peers: EXPE, ABNB, TCOM, TRIP, MMYT, TRVG.
- The screen uses GAAP P/E, as for every other company. Adjusted P/E is shown alongside, and section 3 uses it throughout.

### Ratios and screens

**BKNG passes every strict rule. It ranks 3rd of 3 in the weighted screen, behind Trip.com and Expedia: it sits in the middle on debt, profitability and cheapness, and leads on none.**

| Measure | BKNG | Rule or peer median | Result |
|---|---|---|---|
| Net debt / EBITDA | 0.31x | ≤ 4.5x | Pass |
| EBITDA / interest | 10.1x | ≥ 4x | Pass |
| Cash / short-term debt | 8.6x | ≥ 1x | Pass |
| Cash / long-term debt | 92% | ≥ 5% | Pass |
| Revenue growth, average / median year (2023–2025) | 16.5% / 13.4%, 3 of 3 years up | > 0 | Pass |
| EPS growth (GAAP), median year | 47%, 2 of 3 years up | > 0 | Pass |
| Net margin, TTM | 25.5% | | |
| P/E, trailing (GAAP) | 16.8x | Peer median 22.2x | 24% below |
| P/E, trailing (adjusted) | 15.8x | EXPE 14.7x, ABNB 38.3x, MMYT 22.5x, TRIP 9.8x | Middle of the group |
| EV / EBITDA | 10.6x | Peer median 8.9x | 20% above |
| Forward P/E vs trailing | 27% lower | ≥ 15% lower | Getting cheaper |
| Price vs standard DCF fair value | −17% | < 0 | Cheap |

The standard DCF assumes 2.5% growth forever on $10.02bn at a 9.8% WACC. In reverse, today's price implies about 1.2% growth forever, against revenue growth of 8–13% in the last three years.

Strict screen (every debt rule): TCOM, EXPE, BKNG, ABNB pass. TRIP fails interest cover (2.8x), MMYT fails net debt / EBITDA (5.3x), and TRVG is below the $1bn size floor.

Weighted screen (growth required):

| Rank | Company | Total | Debt | Profitability and cash | Cheapness |
|---|---|---|---|---|---|
| 1 | TCOM | 85.1 | 83.3 | 90.5 | 83.3 |
| 2 | EXPE | 63.1 | 66.7 | 52.4 | 66.7 |
| 3 | **BKNG** | **51.8** | **50.0** | **57.1** | **50.0** |

ABNB, TRIP, MMYT and TRVG drop out of the weighted screen because their median EPS growth is negative. Trip.com's lead is flattered by a one-off gain on its MakeMyTrip stake: its TTM net margin of 51% and P/E of 8x are not repeatable.

## 3. Analysis

**BKNG is cheap mostly because of a story, AI disintermediation, not because of its results.** The full write-up is in the project's Claude Doc "Booking Holdings (BKNG) Investment Analysis".

**Valuation against its own history.** Adjusted EPS removes the KAYAK impairment, foreign-exchange swings on euro debt, equity-stake marks, amortization and restructuring. On that basis BKNG trades at 15.8x trailing EPS of $9.61. From 2016 to 2025 (excluding 2020–2021) its yearly average ranged from 18x to 24x, with a median of about 21x.

| Year | Average price | Adjusted EPS | P/E on average price |
|---|---|---|---|
| Now (TTM) | $151.93 | $9.61 | 15.8x |
| 2025 | $208.73 | $9.12 | 22.9x |
| 2024 | $161.59 | $7.48 | 21.6x |
| 2023 | $113.76 | $6.09 | 18.7x |
| 2022 | $82.00 | $3.99 | 20.5x |
| 2021 | $91.31 | $1.83 | 49.9x (COVID) |
| 2020 | $69.15 | $0.19 | n/m (COVID) |
| 2019 | $74.94 | $4.10 | 18.3x |
| 2018 | $79.31 | $3.70 | 21.4x |
| 2017 | $72.58 | $3.08 | 23.6x |
| 2016 | $53.86 | $2.63 | 20.5x |

**Why it fell.** The stock is down 29% this year, most of it since late August:

- the EU General Court upheld the block of the ETraveli deal (Sep 9);
- Meta's Muse agent showed it can book travel directly (Sep 23);
- reports of FTC action over affiliate hotel ads (Oct 7);
- an EU Digital Services Act probe (Oct 21).

Results have not disappointed: Q2 adjusted EPS of $2.54 beat the $2.43 consensus and grew 15%. Room-night growth has slowed, from 8–9% in 2025 to 5% in Q2 and a guided 3–5% in Q3.

**Entry price.** 15x trailing adjusted EPS gives about $144, 5% below today's price. If Q3 EPS meets the $4.49 consensus, it gives about $152. 15x is below the 18.3x decade low, a discount for the AI risk. At 18x the entry is $173 ($182 after Q3).

| P/E | Entry now (EPS $9.61) | After Q3 (EPS ~$10.12) |
|---|---|---|
| 13x | $125 | $132 |
| 14x | $135 | $142 |
| 15x | $144 | $152 |
| 16x | $154 | $162 |
| 18x | $173 | $182 |
| 20x | $192 | $202 |

**What to watch.** The Q3 report on Nov 3: room nights against the 3–5% guide, early 2027 commentary, management's view of AI-agent traffic, any FTC provision, and whether buybacks stay near $4bn a quarter.

## Caveats

- `history.py` multiplies split-adjusted Yahoo prices by pre-split SEC share counts, so its market value for BKNG is 25x too low. The table above corrects this by hand, and EPS is divided by 25.
- SEC "cash" for 2016–2019 excludes short-term investments, which were large then. Net debt in those years is overstated.
- Trip.com and trivago report in CNY and EUR. Trip.com's TTM figures include a large one-off gain.
- The peer group is small and hand-picked, so the percentile scores move a lot with each name.
- Yahoo data is unofficial. Adjusted EPS comes from Booking's earnings releases on SEC EDGAR.

**Reproduce:** `uv run python analysis/peer_screen.py online_travel BKNG EXPE ABNB TCOM TRIP MMYT TRVG`
