"""Yearly history of the absolute values for every company, back to 2016 where filed.

Primary source: SEC EDGAR XBRL "company facts" (annual 10-K / 20-F / 40-F figures).
Gaps are filled from Yahoo Finance annual statements (data/sector/history_yahoo.csv,
written by analysis/sector.py). Year-end share prices come from Yahoo price history.
Every value records its source.

Writes data/sector/history.csv (long format: symbol, fiscal_year_end, column, value, source).
Raw SEC files are cached in .cache/sec/ (not committed).

Usage: uv run python analysis/history.py [--refresh]
"""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache/sec"
OUT = ROOT / "data/sector"
UA = {"User-Agent": "stock-analysis research b.khalilvandian@gmail.com"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A", "10-KT"}
FIRST_YEAR = 2016
TAX = 0.21

# Tags tried in order; the first one reported for a given year wins.
FLOW_TAGS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RegulatedAndUnregulatedOperatingRevenue",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
        # partial revenue lines, used only when no total is reported
        "RegulatedOperatingRevenue",
        "ElectricUtilityRevenue",
        "UtilityRevenue",
        "ifrs:Revenue",
    ],
    "net_income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
        "ifrs:ProfitLossAttributableToOwnersOfParent",
        "ifrs:ProfitLoss",
    ],
    "eps": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
        "EarningsPerShareBasic",
        "ifrs:DilutedEarningsLossPerShare",
        "ifrs:BasicEarningsLossPerShare",
    ],
    "operating_income": ["OperatingIncomeLoss", "ifrs:ProfitLossFromOperatingActivities"],
    "d_and_a": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "UtilitiesOperatingExpenseDepreciationAndAmortization",
        "Depreciation",
        "ifrs:AdjustmentsForDepreciationAndAmortisationExpense",
        "ifrs:DepreciationAndAmortisationExpense",
        "ifrs:DepreciationExpense",
    ],
    "interest": [
        "InterestExpense",
        "InterestExpenseDebt",
        "InterestExpenseLongTermDebt",
        "ifrs:InterestExpenseOnBorrowings",
        "ifrs:InterestExpense",
    ],
    "operating_cf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "ifrs:CashFlowsFromUsedInOperatingActivities",
    ],
    "capex_paid": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
        "ifrs:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
    ],
    "diluted_shares": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfShareOutstandingBasicAndDiluted",
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
}
INSTANT_TAGS = {
    "cash": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "ifrs:CashAndCashEquivalents",
    ],
    "lt_debt_noncurrent": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "OtherLongTermDebtNoncurrent",
        "ifrs:LongtermBorrowings",
        "ifrs:NoncurrentPortionOfNoncurrentBorrowings",
    ],
    "lt_debt_current": [
        "LongTermDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "ifrs:CurrentPortionOfLongtermBorrowings",
    ],
    "lt_debt_total": [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
    ],
    "short_borrowings": [
        "ShortTermBorrowings",
        "CommercialPaper",
        "NotesPayableCurrent",
        "OtherShortTermBorrowings",
        "ShortTermBankLoansAndNotesPayable",
        "ifrs:ShorttermBorrowings",
    ],
    "debt_current": [
        "DebtCurrent",
        "ifrs:CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    ],
}


def ticker_ciks() -> dict[str, int]:
    tk = requests.get(
        "https://www.sec.gov/files/company_tickers.json", headers=UA, timeout=30
    ).json()
    return {v["ticker"].replace("-", "."): v["cik_str"] for v in tk.values()}


def company_facts(symbol: str, cik: int, refresh: bool) -> dict | None:
    path = CACHE / f"{symbol}.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    for attempt in range(4):
        r = requests.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=UA, timeout=60
        )
        if r.status_code == 200:
            path.write_text(r.text)
            return r.json()
        if r.status_code == 404:
            return None
        time.sleep(1 + attempt)
    return None


def _facts(facts: dict, tag: str) -> list[tuple[str, dict]]:
    taxonomy, name = ("ifrs-full", tag[5:]) if tag.startswith("ifrs:") else ("us-gaap", tag)
    node = facts.get("facts", {}).get(taxonomy, {}).get(name)
    if not node:
        return []
    return [(unit, x) for unit, xs in node["units"].items() for x in xs]


_fx: dict[str, float] = {"USD": 1.0}


def fx_to_usd(currency: str) -> float:
    if currency not in _fx:
        hist = yf.Ticker(f"{currency}USD=X").history(period="5d")
        _fx[currency] = float(hist["Close"].iloc[-1]) if not hist.empty else np.nan
    return _fx[currency]


def _currency(unit: str) -> str | None:
    """'USD' -> USD, 'BRL/shares' -> BRL, 'shares' -> None."""
    code = unit.split("/")[0]
    return code if len(code) == 3 and code.isupper() else None


def annual_values(facts: dict, tag: str, instant: bool) -> pd.Series:
    """One value per fiscal-year end date in USD (or raw for share counts).

    Latest filing wins, which captures restatements. Amounts are converted from the
    currency they were reported in at today's exchange rate.
    """
    best: dict[str, tuple[str, float, str]] = {}
    for unit, x in _facts(facts, tag):
        if x.get("form") not in ANNUAL_FORMS:
            continue
        if instant:
            if "start" in x:
                continue
        else:
            if "start" not in x:
                continue
            days = (date.fromisoformat(x["end"]) - date.fromisoformat(x["start"])).days
            if not 350 <= days <= 380:
                continue
        end = x["end"]
        if int(end[:4]) < FIRST_YEAR:
            continue
        if end not in best or x.get("filed", "") > best[end][0]:
            best[end] = (x.get("filed", ""), float(x["val"]), unit)
    out = {}
    for end, (_, val, unit) in best.items():
        cur = _currency(unit)
        out[pd.Timestamp(end)] = val * fx_to_usd(cur) if cur else val
    return pd.Series(out, dtype=float).sort_index()


def first_available(facts: dict, tags: list[str], instant: bool) -> tuple[pd.Series, pd.Series]:
    """Merge tags in priority order; returns values and the tag used for each date."""
    values, used = pd.Series(dtype=float), pd.Series(dtype=object)
    for tag in tags:
        s = annual_values(facts, tag, instant)
        new = s.index.difference(values.index)
        values = pd.concat([values, s[new]]).sort_index()
        used = pd.concat([used, pd.Series(tag, index=new)]).sort_index()
    return values, used


def fiscal_year_ends(flows: dict[str, pd.Series]) -> pd.DatetimeIndex:
    ends = set()
    for key in ("net_income", "revenue", "operating_cf"):
        ends |= set(flows[key].index)
    return pd.DatetimeIndex(sorted(ends))


def align(s: pd.Series, ends: pd.DatetimeIndex) -> pd.Series:
    """Match balance-sheet dates to fiscal year ends (within a week)."""
    out = {}
    if s.empty:
        return pd.Series(out, dtype=float)
    s.index = pd.DatetimeIndex(s.index)
    for e in ends:
        near = s[(s.index >= e - pd.Timedelta(days=7)) & (s.index <= e + pd.Timedelta(days=7))]
        if len(near):
            out[e] = near.iloc[-1]
    return pd.Series(out, dtype=float)


def sec_history(symbol: str, facts: dict) -> pd.DataFrame:
    flows = {k: first_available(facts, tags, instant=False)[0] for k, tags in FLOW_TAGS.items()}
    # a partial revenue line can never exceed the total, so take the largest per year
    rev = pd.concat([annual_values(facts, t, False) for t in FLOW_TAGS["revenue"]], axis=1)
    flows["revenue"] = rev.max(axis=1) if not rev.empty else pd.Series(dtype=float)
    ends = fiscal_year_ends(flows)
    inst = {
        k: align(first_available(facts, t, instant=True)[0], ends) for k, t in INSTANT_TAGS.items()
    }

    usd = lambda s: s / 1e9  # noqa: E731 - values are already USD
    lt_cur = inst["lt_debt_current"]
    lt_non = inst["lt_debt_noncurrent"].combine_first(inst["lt_debt_total"] - lt_cur)
    short = inst["debt_current"].combine_first(lt_cur.add(inst["short_borrowings"], fill_value=0))
    short = short.combine_first(inst["short_borrowings"])
    ebitda = flows["operating_income"] + flows["d_and_a"]
    capex = -flows["capex_paid"].abs()
    rows = {
        "revenue": usd(flows["revenue"]),
        "ebitda": usd(ebitda),
        "net_income": usd(flows["net_income"]),
        "eps": flows["eps"],
        "operating_cf": usd(flows["operating_cf"]),
        "capex": usd(capex),
        "free_cf": usd(flows["operating_cf"] + capex),
        "fcff_before_growth": usd(
            flows["operating_cf"]
            - flows["d_and_a"]
            + flows["interest"].abs().reindex(ends).fillna(0) * (1 - TAX)
        ),
        "cash": usd(inst["cash"]),
        "long_term_debt": usd(lt_non),
        "short_term_debt": usd(short),
        "total_debt": usd(lt_non.add(short, fill_value=0).where(lt_non.notna())),
    }
    rows["net_debt"] = rows["total_debt"] - rows["cash"]
    rows["_shares"] = flows["diluted_shares"]
    out = []
    for col, s in rows.items():
        for end, v in s.dropna().items():
            if end in ends:
                out.append(
                    {
                        "symbol": symbol,
                        "fiscal_year_end": end,
                        "column": col,
                        "value": v,
                        "source": "SEC",
                    }
                )
    return pd.DataFrame(out)


def add_prices(hist: pd.DataFrame, symbol: str, financial_currency: str | None) -> pd.DataFrame:
    """Year-end share price (Yahoo) and market value (price x diluted shares).

    Market value is only computed for companies reporting in US dollars: foreign filers'
    share counts are ordinary shares while the US price is per ADR.
    """
    ends = sorted(hist.loc[hist["column"] != "_shares", "fiscal_year_end"].unique())
    if not ends:
        return hist
    try:
        px = yf.Ticker(symbol).history(start=f"{FIRST_YEAR - 1}-12-01", auto_adjust=False)["Close"]
    except Exception:  # noqa: BLE001
        return hist
    if px.empty:
        return hist
    px.index = px.index.tz_localize(None)
    extra = []
    shares = hist[hist["column"] == "_shares"].set_index("fiscal_year_end")["value"]
    for e in ends:
        before = px[px.index <= e]
        if before.empty:
            continue
        price = float(before.iloc[-1])
        extra.append(
            {
                "symbol": symbol,
                "fiscal_year_end": e,
                "column": "price",
                "value": price,
                "source": "Yahoo",
            }
        )
        if (financial_currency or "USD") == "USD" and e in shares.index:
            extra.append(
                {
                    "symbol": symbol,
                    "fiscal_year_end": e,
                    "column": "market_cap",
                    "value": price * shares[e] / 1e9,
                    "source": "Yahoo price x SEC shares",
                }
            )
    return pd.concat([hist, pd.DataFrame(extra)], ignore_index=True)


def fill_from_yahoo(hist: pd.DataFrame, yahoo: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """Add Yahoo annual values for (column, year) pairs the SEC data doesn't cover."""
    y = yahoo[yahoo["symbol"] == symbol].copy()
    if y.empty:
        return hist
    y["fiscal_year_end"] = pd.to_datetime(y["period_end"])
    y = y[~y["column"].isin(["price", "market_cap"])]
    have = set()
    if not hist.empty:
        have = {(c, d.year) for c, d in zip(hist["column"], hist["fiscal_year_end"], strict=True)}
    add = y[
        [(c, d.year) not in have for c, d in zip(y["column"], y["fiscal_year_end"], strict=True)]
    ]
    add = add.assign(source="Yahoo")[["symbol", "fiscal_year_end", "column", "value", "source"]]
    return pd.concat([hist, add], ignore_index=True)


def reporting_currency(facts: dict) -> str:
    """The currency most amounts are reported in."""
    counts: dict[str, int] = {}
    for taxonomy in ("us-gaap", "ifrs-full"):
        for node in facts.get("facts", {}).get(taxonomy, {}).values():
            for unit in node["units"]:
                cur = _currency(unit)
                if cur and "/" not in unit:
                    counts[cur] = counts.get(cur, 0) + 1
    return max(counts, key=counts.get) if counts else "USD"


def build(refresh: bool = False) -> pd.DataFrame:
    CACHE.mkdir(parents=True, exist_ok=True)
    sector = pd.read_csv(OUT / "utilities.csv", index_col=0)
    yahoo = pd.read_csv(OUT / "history_yahoo.csv")
    ciks = ticker_ciks()

    def one(symbol: str) -> pd.DataFrame:
        cik = ciks.get(symbol.replace("-", "."))
        facts = company_facts(symbol, cik, refresh) if cik else None
        hist = sec_history(symbol, facts) if facts else pd.DataFrame()
        hist = fill_from_yahoo(hist, yahoo, symbol)
        currency = reporting_currency(facts) if facts else sector.loc[symbol, "currency"]
        hist = add_prices(hist, symbol, currency if isinstance(currency, str) else "USD")
        return hist[hist["column"] != "_shares"] if not hist.empty else hist

    with ThreadPoolExecutor(max_workers=4) as pool:
        parts = list(pool.map(one, sector.index))
    out = pd.concat([p for p in parts if not p.empty], ignore_index=True)
    out["fiscal_year_end"] = pd.to_datetime(out["fiscal_year_end"]).dt.date
    out = out.sort_values(["symbol", "column", "fiscal_year_end"])
    out.to_csv(OUT / "history.csv", index=False)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download SEC company facts")
    h = build(ap.parse_args().refresh)
    years = pd.to_datetime(h["fiscal_year_end"]).dt.year
    print(
        f"{len(h)} values for {h['symbol'].nunique()} companies, "
        f"fiscal years {years.min()}-{years.max()}"
    )
    print(h["source"].value_counts().to_string())
