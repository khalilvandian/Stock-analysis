"""Point-in-time annual fundamentals from SEC EDGAR company facts.

Every XBRL fact carries the date it was filed. `annual()` only uses facts filed before the
decision date, so a feature for June 30, 2015 never sees a 10-K filed in July 2015 or a
later restatement. When a period was reported more than once before the decision date
(e.g. the prior-year column of the next 10-K), the most recent filing wins: that is what
an investor could read on that day.

Raw company facts are large (3-5 MB per company), so only the tags below are kept, in a
gzipped cache under .cache/predict/sec/.
"""

from __future__ import annotations

import gzip
import json
import time

import httpx
import pandas as pd

from stock_analysis.predict import CACHE
from stock_analysis.predict.universe import SEC_UA

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT", "10-K405", "20-F", "20-F/A", "40-F", "40-F/A"}

# Tags tried in order; for each fiscal year the first tag that has a value wins.
FLOW_TAGS = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "RegulatedAndUnregulatedOperatingRevenue",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RevenuesNetOfInterestExpense",
        "InterestAndDividendIncomeOperating",
        "RegulatedOperatingRevenue",
        "ElectricUtilityRevenue",
    ],
    "gross_profit": ["GrossProfit"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "net_income": [
        "NetIncomeLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "ProfitLoss",
    ],
    "eps": [
        "EarningsPerShareDiluted",
        "EarningsPerShareBasicAndDiluted",
        "EarningsPerShareBasic",
    ],
    "d_and_a": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "Depreciation",
    ],
    "interest": ["InterestExpense", "InterestExpenseDebt", "InterestExpenseLongTermDebt"],
    "operating_cf": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
    ],
    "dividends_paid": ["PaymentsOfDividends", "PaymentsOfDividendsCommonStock"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "rnd": ["ResearchAndDevelopmentExpense"],
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
        "Cash",
    ],
    "short_investments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        "AvailableForSaleSecuritiesCurrent",
    ],
    "lt_debt_noncurrent": [
        "LongTermDebtNoncurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
    ],
    "lt_debt_current": [
        "LongTermDebtCurrent",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
    ],
    "lt_debt_total": [
        "LongTermDebt",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "DebtInstrumentCarryingAmount",
    ],
    "short_borrowings": ["ShortTermBorrowings", "CommercialPaper", "OtherShortTermBorrowings"],
    "debt_current": ["DebtCurrent"],
    "assets": ["Assets"],
    "liabilities": ["Liabilities"],
    "liabilities_and_equity": ["LiabilitiesAndStockholdersEquity"],
    "equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "equity_incl_nci": [
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "StockholdersEquity",
    ],
    "current_assets": ["AssetsCurrent"],
    "current_liabilities": ["LiabilitiesCurrent"],
    "retained_earnings": ["RetainedEarningsAccumulatedDeficit"],
    "goodwill": ["Goodwill"],
}
SHARES_TAGS = ["dei:EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"]

ALL_TAGS = sorted(
    {t for tags in FLOW_TAGS.values() for t in tags}
    | {t for tags in INSTANT_TAGS.values() for t in tags}
    | set(SHARES_TAGS)
)


def _split_tag(tag: str) -> tuple[str, str]:
    return ("dei", tag[4:]) if tag.startswith("dei:") else ("us-gaap", tag)


def trim(raw: dict) -> dict:
    """Keep only the tags we use and the fields we need."""
    out = {"cik": raw.get("cik"), "name": raw.get("entityName"), "facts": {}}
    for tag in ALL_TAGS:
        taxonomy, name = _split_tag(tag)
        node = raw.get("facts", {}).get(taxonomy, {}).get(name)
        if not node:
            continue
        recs = []
        for unit, xs in node["units"].items():
            if unit not in ("USD", "USD/shares", "shares"):
                continue
            for x in xs:
                recs.append([x.get("start"), x["end"], x["val"], x.get("form"), x.get("filed")])
        if recs:
            out["facts"][tag] = recs
    return out


def fetch_facts(cik: int, client: httpx.Client, refresh: bool = False) -> dict | None:
    path = CACHE / "sec" / f"CIK{cik:010d}.json.gz"
    if path.exists() and not refresh:
        return json.loads(gzip.decompress(path.read_bytes()))
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(4):
        r = client.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json", headers=SEC_UA
        )
        time.sleep(0.15)  # SEC fair-access limit is 10 requests per second
        if r.status_code == 200:
            data = trim(r.json())
            path.write_bytes(gzip.compress(json.dumps(data).encode()))
            return data
        if r.status_code == 404:
            path.write_bytes(gzip.compress(json.dumps({"cik": cik, "facts": {}}).encode()))
            return {"cik": cik, "facts": {}}
        time.sleep(1 + 2 * attempt)
    return None


def fetch_profile(cik: int, client: httpx.Client) -> dict:
    """SIC industry code and name from the EDGAR submissions file (cached)."""
    path = CACHE / "sec_profile" / f"CIK{cik:010d}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        if cached.get("sic") is not None or cached.get("missing"):
            return cached
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {"cik": cik, "sic": None, "sic_description": None, "name": None}
    for attempt in range(4):
        r = client.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", headers=SEC_UA)
        time.sleep(0.15)  # SEC fair-access limit is 10 requests per second
        if r.status_code == 200:
            j = r.json()
            out = {
                "cik": cik,
                "sic": int(j["sic"]) if str(j.get("sic") or "").isdigit() else None,
                "sic_description": j.get("sicDescription"),
                "name": j.get("name"),
                "missing": not str(j.get("sic") or "").isdigit(),
            }
            break
        if r.status_code == 404:
            out["missing"] = True
            break
        time.sleep(2 + 3 * attempt)  # throttled: back off, do not cache the failure
    else:
        return out
    path.write_text(json.dumps(out))
    return out


class Facts:
    """Indexed company facts with point-in-time annual lookups."""

    def __init__(self, data: dict):
        self.name = data.get("name")
        self.frames: dict[str, pd.DataFrame] = {}
        for tag, recs in data.get("facts", {}).items():
            df = pd.DataFrame(recs, columns=["start", "end", "val", "form", "filed"])
            df["end"] = pd.to_datetime(df["end"])
            df["start"] = pd.to_datetime(df["start"])
            df["filed"] = pd.to_datetime(df["filed"])
            df["days"] = (df["end"] - df["start"]).dt.days
            self.frames[tag] = df.sort_values("filed")

    def first_annual_filed(self) -> pd.Timestamp | None:
        dates = [df.loc[df.form.isin(ANNUAL_FORMS), "filed"].min() for df in self.frames.values()]
        dates = [d for d in dates if pd.notna(d)]
        return min(dates) if dates else None

    def _annual_tag(self, tag: str, asof: pd.Timestamp, instant: bool) -> pd.DataFrame:
        df = self.frames.get(tag)
        if df is None:
            return pd.DataFrame(columns=["val", "filed"])
        df = df[(df.filed < asof) & df.form.isin(ANNUAL_FORMS)]
        if instant:
            df = df[df.start.isna()]
        else:
            df = df[df.days.between(350, 380)]
        if df.empty:
            return pd.DataFrame(columns=["val", "filed"])
        # sorted by filed, so the last value per period end is the latest filing
        return df.groupby("end")[["val", "filed"]].last()

    def annual(self, tags: list[str], asof, instant: bool, with_filed: bool = False):
        """One value per fiscal period end (ascending), merging tags in priority order.

        With `with_filed`, returns a frame with the value and the filing date it came from.
        """
        asof = pd.Timestamp(asof)
        out = pd.DataFrame(columns=["val", "filed"])
        for tag in tags:
            s = self._annual_tag(tag, asof, instant)
            new = s.index.difference(out.index)
            out = pd.concat([out, s.loc[new]]) if len(out) else s
        out = out.sort_index()
        if with_filed:
            return out
        return out["val"].astype(float)

    def _latest(self, tag: str, asof: pd.Timestamp, max_age_days: int = 400):
        df = self.frames.get(tag)
        if df is None:
            return None
        df = df[(df.filed < asof) & (df.filed >= asof - pd.Timedelta(days=max_age_days))]
        if df.empty:
            return None
        last = df[df.filed == df.filed.max()]
        last = last[last.end == last.end.max()]
        return float(last.val.sum()), last.filed.iloc[0]

    def shares_outstanding(self, asof) -> tuple[float, pd.Timestamp] | None:
        """Shares outstanding known on `asof`, with the filing date it came from.

        First choice is the cover-page count (dei:EntityCommonStockSharesOutstanding; several
        share classes are summed). It is cross-checked against the latest weighted diluted
        share count, because company facts drop the cover count for some multi-class
        companies and a few filings report it in the wrong scale; if the two disagree by
        more than a factor of 1.7, the weighted diluted count is used.
        """
        asof = pd.Timestamp(asof)
        cover = self._latest(SHARES_TAGS[0], asof) or self._latest(SHARES_TAGS[1], asof)
        diluted = None
        for tag in FLOW_TAGS["diluted_shares"]:
            diluted = self._latest(tag, asof)
            if diluted:
                break
        if cover and diluted and cover[0] > 0:
            ratio = diluted[0] / cover[0]
            return cover if 1 / 1.7 <= ratio <= 1.7 else diluted
        return cover or diluted
