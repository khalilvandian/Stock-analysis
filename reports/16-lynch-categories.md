# Quantifying Peter Lynch's six categories

*Data as of 2026-10-28 (Stage 1 rerun on the S&P 500, 497 companies, TradingView yearly
history). Written 2026-10-28 for Babak's question: "How can we quantify each category to be
able to recognise each stock and know which category it is? Is there a quantification
method?" Tool: `analysis/lynch_compare.py`. Stage 1 itself is not changed by this report.*

## 1. Summary

- **Lynch gave numbers for only three of his six categories**, all about earnings growth:
  slow growers 2-4% a year (about the economy), stalwarts 10-12%, fast growers 20-25% and up.
  Cyclicals, turnarounds and asset plays he described in words and examples only.
- **Published quant versions do the same.** Validea's Lynch model, the best-known one, sorts
  stocks only into the three growth groups (under 10%, 10-19%, 20-50% EPS growth, averaged
  over 3, 4 and 5 years) and leaves the other three out. AAII's Lynch screen doesn't classify
  at all. We found no published screen that turns cyclicals, turnarounds or asset plays into
  numbers, so ours (industry list, EPS falls, EPS against its peak, price/book, net cash)
  are our own translations of his words.
- **Our current rules are a reasonable translation, with two clear gaps and one big
  sensitivity.** The gaps: Micron, Western Digital and Qualcomm count as fast growers
  because a rebound year inflates the median growth, and banks' deposits count as
  "net cash" for the asset-play test (Northern Trust). The sensitivity: with GAAP EPS, the
  growth number depends heavily on how it is measured. Switching to Validea's measure moves
  159 of 497 companies to another category, and 147 of the 341 growth names sit near a
  cut-off.
- **Proposal** (section 3): Validea's growth measure with 10% and 20% cut-offs; a fast
  grower must also grow revenue at least 10% a year; a cyclical is a company whose EPS
  *and* revenue fell together in 2 or more of 10 years; no net-cash asset play for
  financials; and a "borderline" flag where the category isn't clear. It changes the Stage 1
  result for 30 companies (15 in, 15 out). BKNG, NFLX (fast growers, pass) and BSX (fast
  grower, fails on cash against short-term debt) are unchanged.
- **Babak's call:** whether to adopt the proposal, all of it or in parts. Nothing in the
  nightly run changes until then.

## 2. The numbers

### 2.1 Lynch's own definitions (One Up on Wall Street, chapter 7)

| Category | What Lynch says | Numbers Lynch gives |
|---|---|---|
| Slow growers | "Large and aging companies" growing "slightly faster than the gross national product"; "a sure sign of a slow grower is that it pays a generous and regular dividend"; electric utilities are his main example | Earnings growth about 2-4% a year |
| Stalwarts | Big companies (Coca-Cola, Bristol-Myers, Procter & Gamble) "not exactly agile climbers"; give "pretty good protection during recessions" | Earnings growth 10-12% a year; he buys them "for a 30 to 50 percent gain" |
| Fast growers | "Small, aggressive new enterprises"; can't keep up double-digit growth forever and "settle down into the comfortable single digits of sluggards and stalwarts" | 20-25% a year (some editions and summaries: 20-30% or more) |
| Cyclicals | "Sales and profits rise and fall in a regular if not completely predictable fashion"; autos, airlines, tyres, steel, chemicals; "the most misunderstood" because big cyclicals look like stalwarts | None |
| Turnarounds | "Battered, depressed" companies with no growth that may recover; the "bail-us-out-or-else" kind (Chrysler, Lockheed) among several kinds | None |
| Asset plays | A company "sitting on something valuable that you know about, but that the Wall Street crowd has overlooked": cash, real estate, natural resources, patents, tax-loss carry-forwards | None |

Between slow growers (2-4%) and stalwarts (10-12%), and between stalwarts and fast growers
(12-20%), Lynch gives no number: any quant version has to choose where the lines go.

### 2.2 Published quant versions

| Source | How it classifies | Growth measure | Cut-offs |
|---|---|---|---|
| Validea, "Peter Lynch P/E/Growth Investor" | Fast grower, stalwart, slow grower only; non-financial companies; financials judged on equity/assets (5%+) and return on assets (1%+) | Average of the 3-, 4- and 5-year EPS growth rates | Slow under 10%; stalwart 10-19% with sales of at least $1.9bn; fast 20-50% (above 50% is treated as unsustainable) |
| AAII, "Lynch" screen | No classification: one screen for all | EPS growth | Dividend-adjusted PEG (P/E / (growth + yield)) of 0.5 or less; P/E below the industry median and its own 5-year average; financials excluded |
| Dickinson 2011, *The Accounting Review* (academic, not Lynch) | Life-cycle stage from the signs of operating, investing and financing cash flow: introduction, growth, mature, shake-out, decline | Cash-flow signs, not growth rates | Closest academic idea to Lynch's growth groups; a possible cross-check, not used |

Validea's other Lynch rules for every category: debt/equity under 80% (not for financials
and utilities), inventory not rising much faster than sales; bonus for free cash flow yield
and net cash per share.

### 2.3 Our current rules (Stage 1, `config/screeners.toml` `[lynch]`)

Tested in this order; the first that fits wins.

| Order | Category | Test now |
|---|---|---|
| 1 | no profit (not Lynch's) | No positive EPS in any of the last 5 fiscal years |
| 2 | cyclical | Industry in a list of 23 (autos, airlines, steel, metals, chemicals, oil, shipping, homebuilding, chip equipment, machinery, paper, hotels and cruises) |
| 3 | turnaround | A loss now, or EPS more than 50% below its 5-year peak |
| 4 | cyclical | EPS fell more than 30% in 3 or more of the last 10 years, unless median growth is 20%+ |
| 5 | asset play | Price below book value, or net cash above 30% of market value |
| 6 | fast grower | Median yearly EPS growth over 5 years of 20% or more |
| 7 | stalwart | 8% to under 20% |
| 8 | slow grower | Under 8% |

Today's S&P 500 run: slow growers 113, stalwarts 104, cyclicals 94, fast growers 93,
turnarounds 68, asset plays 8, no profit 1, too little history 16.

### 2.4 How sensitive the growth groups are

The same 5 years of GAAP EPS, measured two ways (median yearly growth, as now; Validea's
average of the 3-, 4- and 5-year compound rates):

| Company | Now: median yearly | Validea 3/4/5-yr | 5-yr revenue growth | Now | With Validea's measure |
|---|---|---|---|---|---|
| Eli Lilly | 12.8% | 38.7% | 21.6% | stalwart | fast grower |
| Johnson & Johnson | 4.6% | 13.9% | 2.7% | slow grower | stalwart |
| JPMorgan | 21.7% | 14.3% | 17.3% | fast grower | stalwart |
| Oracle | 20.6% | 17.8% | 10.7% | fast grower | stalwart |
| Altria | 43.2% | 17.6% | -0.7% | fast grower | stalwart |
| IBM | 1.8% | 37.1% | 4.1% | cyclical | stalwart |
| T-Mobile US | 0.6% | 46.3% | 5.2% | slow grower | stalwart |
| Duke Energy | 11.1% | 20.6% | 6.2% | stalwart | stalwart (borderline) |
| Apple | 8.9% | 10.7% | 8.7% | stalwart | stalwart (borderline) |
| Microsoft | 19.8% | 19.0% | 14.6% | stalwart | stalwart (borderline) |
| Netflix | 27.5% | 30.6% | 12.6% | fast grower | fast grower |
| Booking | 53.8% | 81.2% | 31.7% | fast grower | fast grower |

The gaps come from one-off years in GAAP EPS: charges (IBM's 2022 pension charge, T-Mobile's
Sprint merger costs), gains (J&J's 2023 Kenvue separation), and recent acceleration that a
median plays down (Lilly's weight-loss drugs). A single growth number on GAAP EPS can't
separate a real 12% grower from a 4% grower with one odd year.

### 2.5 Current against proposed, every company

| Now ↓ / Proposed → | blank | asset play | cyclical | fast grower | no profit | slow grower | stalwart | turnaround | Total |
|---|---|---|---|---|---|---|---|---|---|
| blank | 16 | | | | | | | | 16 |
| asset play | | 2 | | 1 | | 2 | 3 | | 8 |
| cyclical | 3 | 1 | 60 | | | 21 | 9 | | 94 |
| fast grower | | | 4 | 37 | | 9 | 43 | | 93 |
| no profit | | | | | 1 | | | | 1 |
| slow grower | | | | 1 | | 96 | 16 | | 113 |
| stalwart | | | 1 | 8 | | 37 | 58 | | 104 |
| turnaround | | | | | | | | 68 | 68 |
| **Total** | 19 | 3 | 65 | 47 | 1 | 165 | 129 | 68 | 497 |

**Stage 1 result:** 169 pass now, 170 with the proposal; 15 move from pass to fail (among
them Eli Lilly, Dell, Lam Research, Bristol-Myers, Adobe, Regeneron, Howmet) and 15 from
fail or incomplete to pass (among them Micron, J&J, Qualcomm, Western Digital, Moody's,
Grainger). Every company: `uv run python analysis/lynch_compare.py --csv PATH`.

## 3. Claude's analysis

### 3.1 Is there a quantification method?

Yes for the growth groups, no for the rest. Lynch's numbers (2-4%, 10-12%, 20-25%) are for
earnings growth and are the base of every quant version. Validea fills his gaps with
10% and 20% cut-offs and a 3/4/5-year average. For cyclicals, turnarounds and asset plays
there is no standard; each has to be translated from what Lynch describes:

| Category | What can be measured | Our test | Proposed |
|---|---|---|---|
| Slow grower | EPS growth under the stalwart line; a steady dividend is the "sure sign" | Under 8% | Under 10% (Validea); dividend record shown, not used to classify |
| Stalwart | EPS growth in the middle band; big company | 8-20% | 10-20% (Lynch 10-12%, Validea 10-19%) |
| Fast grower | EPS growth 20%+ *and* the business expanding | Median yearly EPS growth 20%+ | Validea growth 20%+ and revenue 10%+ a year |
| Cyclical | Industry; sales and profits falling together in downturns | Industry list, or EPS fell 30%+ in 3 of 10 years unless a fast grower | Industry list, or EPS fell 30%+ in a year revenue fell 5%+, in 2 of 10 years, whatever the growth |
| Turnaround | Losing money, or earnings far below their past level, after a profitable history | Loss now, or EPS 50%+ below the 5-year peak | No change |
| Asset play | Assets worth more than the price after debt: price below book, lots of net cash | P/B under 1, or net cash over 30% of market value | P/B under 1 only with debt/equity at most 1; no net-cash test for the Finance sector |

### 3.2 Where our rules differ, and why the proposal

1. **Growth measure.** The median of yearly changes ignores the size of the bad years, so a
   rebound year counts as much as a steady one (Micron's median is 465%). Validea's average
   of three compound rates is a published reading of Lynch and uses the whole period.
   Neither fixes one-off charges in GAAP EPS; the real fix is adjusted EPS, which Stage 2
   already takes from Yahoo for the last few years only. A longer adjusted-EPS history needs
   a paid source.
2. **Cut-off at 10%, not 8%.** Lynch's stalwarts start at 10%, Validea's too. 8% was our
   judgement call for the 4-10% gap; it puts more companies into stalwarts than Lynch would.
3. **Fast growers must grow sales.** Lynch's fast growers are expanding businesses ("small,
   aggressive new enterprises"). Without the revenue test, Altria (revenue -0.7% a year),
   Dell and Lam Research count as fast growers because of buybacks, margins or a low base.
   10% is our judgement.
4. **Cyclicals by history.** Lynch's cyclicals are companies whose *sales and profits* rise
   and fall with the economy. Counting EPS falls alone catches write-downs (IBM,
   Bristol-Myers, Mondelez, CVS); counting only years when revenue fell too keeps the real
   cycles (Micron, Western Digital, Qualcomm) and drops the write-downs. Dropping the
   fast-grower exemption stops a memory-chip rebound from passing as growth. The count
   goes from 87 cyclicals by history to 47.
5. **Asset plays.** A bank's or broker's cash is its customers' money, so the net-cash test
   makes no sense there (Northern Trust, Interactive Brokers). And Lynch says debt
   "detracts" from the assets, so cable companies trading below book with heavy debt
   (Charter) shouldn't count. Asset plays are the category statements catch worst: Lynch's
   examples are assets carried at old cost (land, timber, oil) or not on the balance sheet
   at all (brands, tax losses). The test can only flag candidates.
6. **Borderline flag.** Lynch says companies move between categories over time and some fit
   two. 147 of 341 growth names (43%) are within 2 points of a cut-off or put in different
   groups by the two growth measures. The proposal marks them "borderline" rather than
   pretending to precision; Claude's per-stock notes can then say which category fits.

### 3.3 Caveats

- One day's data, S&P 500 only, GAAP diluted EPS from TradingView.
- The proposal's own thresholds (10% revenue growth, 5% revenue fall, 2 of 10 years, debt/
  equity 1) are judgement calls, not Lynch's or Validea's numbers.
- No back-test: there is no labelled set of "true" Lynch categories to test against. The
  check here is whether well-known companies land where Lynch would put them.
- The classification also decides which Stage 1 rules apply, so it moves 30 pass/fail
  results; the two-stage design and Stage 2 are unaffected.

### 3.4 Sources

- Peter Lynch with John Rothchild, *One Up on Wall Street* (1989), chapter 7 "Six Categories
  of Stocks". Quotes checked against reader highlights:
  [Goodreads notes](https://www.goodreads.com/notes/19209522-one-up-on-wall-street/50875428-tommy-carstensen?page=1)
  and summaries ([Value Research](https://www.valueresearchonline.com/stories/51021/peter-lynch-s-six-stock-categories/),
  [Manas Saloi](https://www.manassaloi.com/booksummaries/2016/03/04/one-up-on-wallstreet-lynch.html)).
- Validea's Lynch model: [Validea, "The Investment Strategy of Peter Lynch"](https://blog.validea.com/?p=32501),
  [Validea, "The Lynch Approach: GARP, PEGs, and Profits"](https://blog.validea.com/?p=7627),
  [Validea's Top 10 Peter Lynch Stocks, July 2024](https://blog.validea.com/32776-2/),
  [MoneyShow (John Reese, Validea)](https://moneyshow.com/articles/guru-31878).
- AAII: [Former Wall Street Investment Manager's Screening Strategy](https://www.aaii.com/stockideas/article/190534-former-wall-street-investment-managers-screening-strategy),
  [The Peter Lynch Approach](https://www.aaii.com/journal/article/the-peter-lynch-approach-investing-in-understandable-stocks).
- Victoria Dickinson, "Cash Flow Patterns as a Proxy for Firm Life Cycle", *The Accounting
  Review* 86(6), 2011, pp. 1969-1994, doi:10.2308/accr-10130.

### 3.5 Reproduce

```
uv run python analysis/stage1.py          # today's data, writes .cache/screener/stage1_full.pkl
uv run python analysis/lynch_compare.py   # current against proposed; --csv PATH for every company
```
