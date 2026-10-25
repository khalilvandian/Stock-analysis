# Screening the sector: low debt, cheapness, growth and quality

*Data as of 2026-09-28. Written 2026-09-28. Tool: `analysis/screen.py`.*

The screen was refined in seven rounds. Each round below gives the rules and the result. Round 7 is the current method.

## Round 1: low debt and cheap (first pass)

**Rules:**
- **Low debt:** net debt / EBITDA ≤ 3.5x and EBITDA / interest ≥ 4x.
- **Cheap score, 0–3:** one point each for trailing P/E below its sub-industry median, EV/EBITDA below its sub-industry median, and price below DCF fair value.
- **Getting cheaper:** forward P/E at least 15% below trailing P/E.

**Result:** Vistra (3/3, P/E expected to fall 43%), MGE Energy and California Water stood out.

## Round 2: nine strict pass/fail rules

The rules: market value ≥ $1bn, US-dollar data, profitable, net debt/EBITDA ≤ 4.5x, interest cover ≥ 4x, price below fair value, P/E at or below its group, EV/EBITDA at or below its group, and earnings expected to rise.

**Companies left after each rule:** 77 → 68 → 61 → 18 → 17 → 6 → 4 → 4 → **3**.

**Passed all nine:** **Vistra, UGI, California Water.** Edison passed eight but has earnings expected to fall and wildfire liability. Near misses: MGE Energy and OGE.

## Round 3: debt redefined around cash

The user's definition of debt health: how much cash a company holds, whether that cash covers debt due within a year, and how cash compares with long-term debt.

- **Sector medians:** cash covers 54% of debt due within a year and 3% of long-term debt. Utilities refinance maturing debt rather than paying it from cash.
- **With "cash ≥ short-term debt" required:** only 11 of 61 companies pass, and only **UGI** is also cheap on every test.

## Round 4: strict on debt, including long term

**Rules:**
- Cash ≥ short-term debt.
- Cash ≥ 5% of long-term debt.
- Net debt/EBITDA ≤ 4.5x.
- EBITDA/interest ≥ 4x.
- Cheapness ranks the survivors but is not required.

**Result:** 6 companies pass.

| Rank | Company | Cash / debt due in a year | Cash / long-term debt | Net debt / EBITDA | Price vs fair value |
|---|---|---|---|---|---|
| 1 | UGI | 1.3x | 7.1% | 3.7x | −16% |
| 2 | Hawaiian Electric | 1.9x | 8.5% | 3.5x | no DCF |
| 3 | Con Edison | 1.3x | 5.4% | 4.1x | +10% |
| 4 | SOLV Energy | 15.9x | net cash | net cash | +25% |
| 5 | Atmos Energy | 1.0x | 5.3% | 3.7x | +69% |

**Finding:** the strongest balance sheets already trade at a premium. Only UGI is both safe and cheap.

## Round 5: weighted balance, debt 65% and cheapness 35%

**How the score works:** each measure is ranked as a percentile (0–100) across the 60 companies that are profitable, worth at least $1bn and report in US dollars.
- **Debt (4 measures):** cash vs short-term debt, cash vs long-term debt, net debt/EBITDA, interest cover.
- **Cheapness (4 measures):** price vs fair value, P/E vs its group, EV/EBITDA vs its group, expected P/E change.

**Top 5:** Hawaiian Electric, SOLV Energy, Vistra, Con Edison, UGI. The same five hold at debt weights from 60% to 70%.

## Round 6: growth must be positive

Revenue and EPS growth were calculated year by year (2023, 2024, 2025). Both the **average and the median** of those yearly rates must be above 0.

**Companies left after each rule:** 61 → 45 → 36 → 32 → **26**. UGI, Hawaiian Electric, SOLV Energy and Southwest Gas drop out because their revenue shrank.

**Top 5:** Vistra, Con Edison, CEG, Atmos Energy, Exelon.

## Round 7 (current): debt 50%, profitability and cash 25%, cheapness 25%

**The profitability-and-cash score** combines:
- Net margin (counted double)
- Margin change per year, average and median
- Operating cash flow growth, average and median
- Cash balance growth, average and median (counted half, because cash swings a lot)

Positive revenue and EPS growth is still required.

| Rank | Company | Total | Debt | Profit & cash | Cheap | Net margin | Cash flow growth (avg / median) | Price → fair value |
|---|---|---|---|---|---|---|---|---|
| **1** | **Vistra (VST)** | 74 | 77 | 58 | 85 | 11.6% | +332% / −11% | $138 → $168 |
| **2** | **Atmos Energy (ATO)** | 71 | 91 | 81 | 20 | 28.5% | +74% / +18% | $157 → $93 |
| **3** | **Con Edison (ED)** | 69 | 87 | 44 | 60 | 12.5% | +18% / +33% | $103 → $94 |
| **4** | **Constellation (CEG)** | 69 | 82 | 61 | 50 | 11.1% | not measurable | $263 → $207 |
| **5** | **American States Water (AWR)** | 65 | 78 | 67 | 37 | 20.5% | +56% / +16% | $83 → $81 |

The same five appear at every weight mix tested (debt 45–60%, profitability 20–30%). Exelon ranks 11th because its net margin has been flat at about 11% for four years.

**Watch-outs:**
- **Vistra:** operating cash flow fell in 2024 and 2025, and the +332% average comes from a single rebound year.
- **Atmos:** the best business on the list, but 69% above fair value.
- **CEG:** cash flow growth can't be measured, because its operating cash flow was negative in 2021–2024 (receivables accounting).

## Caveats

- Three to four years of history is short. Prefer medians over averages.
- Power producers' EPS swings with hedge accounting.
- Hawaiian Electric (Maui) and Edison (Eaton) carry wildfire liabilities that the numbers don't capture.
- This is a research screen, not investment advice.

**Reproduce:**
- `uv run python analysis/screen.py --balanced --debt-weight 0.5 --quality-weight 0.25` (current method)
- `uv run python analysis/screen.py --strict` (round 4 debt rules)
