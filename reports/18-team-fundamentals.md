# Atlassian (TEAM): fundamentals and analysis

*Prices at the close on 2026-10-30 ($191.72); SEC filings through the 10-K for the year to 2026-06-30. Written 2026-10-31. Not on the watch list.*

## 1. Summary

**Atlassian (Nasdaq: TEAM; Jira, Confluence, Loom, Rovo) is a high-quality software business: 89% gross margin, revenue up 26% last year, no net debt and $1.3bn of free cash flow. The stock is not cheap after more than tripling from its April low. At about 33x adjusted earnings it is well above its peers (median about 18x forward), and those earnings leave out stock-based pay of $1.6bn a year, more than the whole adjusted profit. Atlassian guides FY2027 to slower growth (13%) and a lower margin, so adjusted EPS should be about flat. View: a good company at a full price. Wait for the Q1 report on Nov 5; about $146 (25x adjusted EPS) is a sensible entry.**

- **Cheap:** no. 33x adjusted EPS of $5.85, 7.4x sales, and a 2.7% free cash flow yield, all above the peer group.
- **Strong:** subscription ARR of $6.6bn, up 23%; remaining contract value up 44% to $4.8bn; cloud up 31% in Q4; net cash.
- **Weak:** stock-based pay is 24.5% of revenue. Free cash flow minus stock-based pay was −$0.3bn in FY2026, and GAAP has shown a loss every year since FY2017.
- **Uncertain:** whether AI agents cut the number of paid seats (the early-2026 "SaaSpocalypse" fear), and how much of FY2026 was pulled forward by the Data Center end-of-life.

## 2. The numbers

Run through this project's process against ten software peers.

### Absolute values, latest 12 months (= FY2026, year to June 30)

| Group | Value | TEAM |
|---|---|---|
| Price and value | Share price | $191.72 |
| Price and value | Market value | $48.53bn |
| Price and value | DCF fair value (standard) | $61.09 |
| Price and value | Cash flow before growth (DCF base) | $1.25bn |
| Debt and cash | Total debt | $1.23bn |
| Debt and cash | Net debt | −$0.01bn |
| Debt and cash | Short-term debt | $0.05bn |
| Debt and cash | Long-term debt | $1.18bn |
| Debt and cash | Cash | $1.24bn |
| Earnings | Revenue | $6.57bn |
| Earnings | EBITDA | $0.21bn |
| Earnings | Net income | −$0.05bn |
| Earnings | EPS (GAAP) | −$0.21 |
| Earnings | EPS (adjusted, company figure) | $5.85 |
| Earnings | Forward EPS (Yahoo) | $6.74 |
| Cash flow | Operating cash flow | $1.35bn |
| Cash flow | Capex | $0.03bn |
| Cash flow | Free cash flow | $1.32bn |
| Not in the config | Stock-based compensation (SEC) | $1.61bn |

Debt is mainly about $1bn of senior notes; Yahoo's total adds leases. Cash halved from $2.5bn in a year: $1.8bn of buybacks and $1.23bn of acquisitions (mainly DX), against $1.32bn of free cash flow. Customer prepayments (deferred revenue) are $2.5bn, so cash is lower than the balance sheet makes it look.

### Absolute values by year (SEC, fiscal years to June 30, $bn except per share)

| Year | Price | Market value | Revenue | EBITDA | Net income | EPS | Operating CF | Free CF | Stock-based pay | Net debt | Cash |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026 | $77.79 | 20.2 | 6.57 | 0.15 | −0.05 | −$0.21 | 1.35 | 1.32 | 1.61 | −0.25 | 1.24 |
| 2025 | $203.09 | 53.2 | 5.22 | −0.04 | −0.26 | −$0.98 | 1.46 | 1.42 | 1.36 | −1.53 | 2.51 |
| 2024 | $176.88 | 45.8 | 4.36 | −0.04 | −0.30 | −$1.16 | 1.45 | 1.42 | 1.08 | −1.19 | 2.18 |
| 2023 | $167.81 | 43.0 | 3.53 | −0.28 | −0.49 | −$1.90 | 0.87 | 0.84 | 0.95 | −1.10 | 2.10 |
| 2022 | $187.40 | 47.5 | 2.80 | 0.12 | −0.52 | −$2.05 | 0.82 | 0.75 | 0.53 | −0.39 | 1.39 |
| 2021 | $256.86 | 64.1 | 2.09 | 0.20 | −0.58 | −$2.32 | 0.79 | 0.76 | 0.34 | −0.57 | 0.92 |
| 2020 | $180.27 | – | – | 0.08 | −0.35 | −$1.43 | 0.57 | 0.54 | – | – | 1.49 |
| 2019 | $130.84 | – | – | 0.01 | −0.64 | −$2.67 | 0.47 | 0.42 | – | −0.42 | 1.27 |
| 2018 | $62.52 | – | 0.87 | 0.03 | −0.11 | −$0.49 | 0.31 | 0.28 | – | −0.59 | 1.41 |
| 2017 | $35.18 | – | 0.62 | 0.01 | −0.04 | −$0.17 | 0.20 | 0.20 | – | −0.24 | 0.24 |
| 2016 | $25.90 | – | 0.46 | 0.02 | 0.00 | $0.02 | 0.13 | 0.10 | – | – | 0.26 |

The June 30, 2026 price ($77.79) is real: the stock fell from about $162 at the end of 2025 to $57 on April 10, then more than tripled to about $228 in mid-October. Revenue has grown every year, by 20–41%, and free cash flow has grown from $0.1bn to $1.3bn. Stock-based pay has grown faster than free cash flow, from $0.34bn in FY2021 to $1.61bn. The diluted share count still rose, from 250m in FY2021 to 262m in FY2025, and fell only to 260m in FY2026: buybacks of $3.0bn over three years went mostly to offset new shares.

### Method

- `analysis/sector.py`'s `analyse()` for the latest values and ratios, `analysis/watchlist.py`'s `sec_years()` for the yearly history (SEC first, Yahoo prices), and the SEC company facts in `.cache/sec/TEAM.json` for stock-based pay, buybacks and acquisitions.
- Peers (collaboration and business software): NOW, CRM, WDAY, HUBS, MNDY, ASAN, GTLB, DDOG, ZM, BOX. `analysis/screen.py` rules and weights unchanged.
- Adjusted EPS is Atlassian's non-GAAP EPS from its earnings releases (Yahoo's reported quarterly EPS: $1.04, $1.22, $1.75 and $1.87 for the four quarters of FY2026; the company's full-year figure is $5.85). It excludes stock-based pay, amortization of acquired intangibles and the $285m restructuring.

### Ratios and screens

**TEAM is out of both screens because GAAP EPS is negative.** On debt it would pass every strict rule: net debt / EBITDA −0.03x, EBITDA / interest 4.3x (rule ≥ 4x), cash / short-term debt 25.6x, cash / long-term debt 105%.

| Measure | TEAM | Peer median | Note |
|---|---|---|---|
| Revenue growth, latest year | 27.6% | 16.3% | FY2027 guided at about 13% |
| Revenue growth, 3-year average | 23.0% | | 3 of 3 years up |
| Net margin (GAAP) | −0.8% | | Up from −13.8% in FY2023 |
| P/E, trailing (adjusted) | 32.8x | | On $5.85 |
| P/E, forward (Yahoo) | 28.4x | 18.4x | Yahoo's $6.74 looks high against guidance (below) |
| Price / sales | 7.4x | 4.8x | |
| Free cash flow yield | 2.7% | 5.7% | Negative after stock-based pay |
| EV / EBITDA (GAAP) | 229x | 31x | Not meaningful: GAAP EBITDA is after stock-based pay |
| Price vs standard DCF fair value | +214% | | The standard DCF does not fit (below) |

Strict screen (every debt rule): CRM, WDAY, HUBS, BOX, NOW, DDOG pass. Weighted screen (growth required): ZM 74.3, DDOG 60.0, BOX 56.4, CRM 52.1, NOW 51.0.

### DCF

The standard DCF ($61) assumes 2.5% growth forever on $1.25bn, which does not suit a business growing 20%+. A two-stage DCF (10 years of growth, then 3%, at the 10.8% WACC) gives:

| Free cash flow base | 10% a year | 15% | 20% | 25% |
|---|---|---|---|---|
| As reported ($1.32bn; stock-based pay treated as free) | $114 | $164 | $236 | $337 |
| Less half of stock-based pay ($0.52bn) | $45 | $64 | $92 | $132 |

Today's price implies free cash flow growing about 17% a year for ten years if stock-based pay costs nothing, or about 30% a year if half of it is counted as a cost.

### P/E against its own history

| Year | Average price | Adjusted EPS | P/E on average price |
|---|---|---|---|
| Now (TTM) | $191.72 | $5.88 | 32.6x |
| 2025 | $201.46 | $4.21 | 47.9x |
| 2024 | $197.39 | $3.28 | 60.2x |
| 2023 | $176.59 | $2.49 | 70.9x |
| 2022 | $226.03 | $1.55 | 145.8x |
| 2021 | $301.71 | $1.68 | 179.6x |
| 2020 | $174.21 | $1.17 | 148.9x |
| 2016–2019 | | | 76x–114x |

Calendar years, on trailing adjusted EPS. The 10-year median (about 93x) reflects hyper-growth years and is no guide to a fair price now. The multiple has fallen every year since 2021 while EPS rose about 3.5x.

## 3. Analysis

**The business is good; the price already assumes it stays that way.**

**What it does.** Atlassian sells team software by subscription: Jira (project and issue tracking), Confluence (documents and wikis), Jira Service Management, Loom, and Rovo, its AI assistant and agents. More than 350,000 organizations use it; over 700 pay more than $1m a year. Its own servers ("Data Center") reach end of life in March 2029, and customers are moving to cloud.

**FY2026 results (to June 30).** Revenue $6.57bn, up 26%; Q4 revenue $1.77bn, up 28%, with cloud up 31% to $1.21bn. Q4 non-GAAP EPS $1.87 against $0.98 a year earlier and a $1.50 consensus; the stock rose about 35% on the report (Aug 6). In March Atlassian cut about 1,600 jobs (10%) to fund AI and enterprise sales, at a cost of $225–236m.

**Why adjusted EPS jumped, and why it should not keep jumping.**
- Data Center end-of-life brings term-licence revenue forward: Atlassian says this added about 4 points to the FY2026 non-GAAP operating margin.
- FY2027 guidance: revenue up about 13%, Data Center revenue down about 17%, non-GAAP operating margin about 25% (about 3 points of that from paying more in cash and less in shares), and a flat share count.
- Claude's estimate: FY2027 non-GAAP operating income about flat on FY2026 (revenue about $7.4bn x 25% against about $1.9bn), so non-GAAP EPS of about $5.6–5.9, not the $6.74 Yahoo shows. The FY2027 consensus figures found online were stale or mixed GAAP and non-GAAP numbers.

**Stock-based pay is the main issue for the valuation.** It was $1.61bn in FY2026, $6.35 a share, more than the $5.85 of adjusted EPS. It is a real cost: Atlassian spent $1.8bn on buybacks last year and the share count fell only slightly. Moving pay toward cash in FY2027 will make the reported numbers more honest but lower. Counted in full, the business earned about nothing in FY2026 on a GAAP basis (−$0.05bn, including $0.29bn of restructuring).

**Why it fell and recovered.** The stock lost about 75% from its peak by April 10, 2026 (and about 58% from the 2021 high of $458), during the early-2026 software sell-off on fears that AI agents reduce paid seats. Strong Q3 and Q4 results, Rovo adoption (over 80% of the Fortune 500) and the rotation back into software then took it from $57 to about $228. It fell 7.3% and 6.1% on Oct 29–30 in the tech sell-off, to $191.72.

**Entry price.** On FY2026 adjusted EPS of $5.85:

| P/E | Entry price | vs. today |
|---|---|---|
| 20x | $117 | −39% |
| 22x | $129 | −33% |
| 25x | $146 | −24% |
| 28x | $164 | −15% |
| 30x | $176 | −8% |

25x is a premium to the peer median (about 18x forward) for growth about twice theirs, and a discount to TEAM's own falling multiple (48x in 2025) for the flat FY2027 and the stock-based pay.

**What to watch.** The Q1 FY2027 report on Nov 5 (after the close; revenue guided at $1.705–1.715bn): cloud growth against the 25.5% FY2027 guide, ARR growth against 18%, Data Center decline, seat counts and any sign of seat compression from AI, and whether the 25% margin guide holds.

## Caveats

- Fiscal years end June 30, so "2026" in the SEC table is July 2025 to June 2026; the P/E history uses calendar years.
- SEC data for FY2016–FY2020 comes from 20-F filings and has gaps (revenue for FY2019–FY2020, market value before FY2021, stock-based pay before FY2021 not shown).
- Adjusted EPS is company-defined and excludes stock-based pay, so it is not comparable with GAAP EPS or with peers that pay less in shares.
- The FY2027 EPS is Claude's estimate from Atlassian's guidance, not a consensus figure.
- The peer group is hand-picked; several peers are also loss-making or barely profitable on GAAP.
- Yahoo data is unofficial. The FY2026 figures and guidance come from Atlassian's Q4 FY2026 shareholder letter on SEC EDGAR.

**Reproduce:** `uv run python analysis/peer_screen.py collaboration_software TEAM NOW CRM WDAY HUBS MNDY ASAN GTLB DDOG ZM BOX`
