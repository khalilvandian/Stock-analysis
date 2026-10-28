"""Historical S&P 500 membership and the SEC/Yahoo identity of every past member.

The current S&P 500 list is survivorship-biased: it only holds companies that did well
enough to still be in the index today. We instead use each year's actual members,
including companies that were later removed, renamed or acquired.

`resolve()` gives every historical ticker an SEC CIK (for fundamentals) and a Yahoo symbol
(for prices):

1. `sec_current`: the ticker is in SEC's current ticker list.
2. `rename`: the ticker disappeared from the index on the same day a ticker that SEC knows
   appeared, with no index change recorded on Wikipedia (e.g. FB -> META). Prices and
   filings continue under the new ticker and the same CIK.
3. `name_search`: the company is gone (usually acquired). The CIK is found by searching
   EDGAR for the name Wikipedia gives for the removed company. Fundamentals exist,
   but Yahoo has no prices for delisted stocks, so no label can be computed.
4. `unresolved`: nothing found.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, timedelta

import httpx
import pandas as pd

from stock_analysis.predict import ROOT

SEC_UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "stock-analysis research project")}


def load_membership(path=None) -> pd.DataFrame:
    path = path or ROOT / "data/predict/sp500_ticker_start_end.csv"
    m = pd.read_csv(path, parse_dates=["start_date", "end_date"])
    return m.rename(columns={"start_date": "start", "end_date": "end"})


def members_on(membership: pd.DataFrame, day) -> list[str]:
    """Tickers in the index on `day` (start <= day < end)."""
    day = pd.Timestamp(day)
    inside = (membership.start <= day) & (membership.end.isna() | (membership.end > day))
    return sorted(membership.loc[inside, "ticker"].unique())


def decision_dates(cfg: dict) -> list[pd.Timestamp]:
    d = cfg["dates"]
    return [
        pd.Timestamp(f"{y}-{d['month_day']}") for y in range(d["first_year"], d["last_year"] + 1)
    ]


def sec_tickers(client: httpx.Client) -> dict[str, tuple[int, str]]:
    """Current SEC ticker list: ticker (with '.' for share classes) -> (cik, name)."""
    r = client.get("https://www.sec.gov/files/company_tickers.json", headers=SEC_UA)
    r.raise_for_status()
    return {
        v["ticker"].upper().replace("-", "."): (int(v["cik_str"]), v["title"])
        for v in r.json().values()
    }


def edgar_name_search(client: httpx.Client, name: str) -> tuple[int, str] | None:
    """First EDGAR company whose name matches `name` (best effort)."""
    clean = re.sub(r"[.,]|\b(Inc|Corp|Corporation|Co|Company|Ltd|plc|The)\b", " ", name)
    clean = " ".join(clean.split())
    if not clean:
        return None
    r = client.get(
        "https://www.sec.gov/cgi-bin/browse-edgar",
        params={
            "company": clean,
            "owner": "exclude",
            "action": "getcompany",
            "type": "10-K",
            "output": "atom",
        },
        headers=SEC_UA,
    )
    time.sleep(0.15)  # SEC fair-access limit is 10 requests per second
    if r.status_code != 200:
        return None
    ciks = re.findall(r"<cik>0*(\d+)</cik>", r.text)
    names = re.findall(r"<conformed-name>([^<]*)</conformed-name>", r.text) or re.findall(
        r"<name>([^<]*)</name>", r.text
    )
    names = [n for n in names if n != "Webmaster"]
    if not ciks:
        return None
    return int(ciks[0]), (names[0] if names else clean)


GENERIC_WORDS = {
    "inc",
    "corp",
    "corporation",
    "co",
    "company",
    "companies",
    "group",
    "holdings",
    "holding",
    "the",
    "ltd",
    "plc",
    "international",
    "energy",
    "financial",
    "petroleum",
    "resources",
    "technologies",
    "technology",
    "systems",
    "pharmaceuticals",
    "bank",
    "bancorp",
    "trust",
    "and",
    "of",
    "new",
    "american",
    "national",
    "services",
    "industries",
    "brands",
    "de",
}


def _words(name) -> set[str]:
    if not isinstance(name, str):
        return set()
    words = re.findall(r"[a-z0-9]+", name.lower().replace("&", " "))
    return {w for w in words if len(w) >= 3 and w not in GENERIC_WORDS}


def same_company(a, b) -> bool:
    """Loose name match ("Anadarko Petroleum" vs "ARKO Petroleum Corp." -> False)."""
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return True  # nothing to compare: assume the same
    if wa & wb:
        return True
    # abbreviations: "TECO" vs "Tampa Electric", "SunTrust" vs "SUNTRUST BANKS"
    return any(x.startswith(y) or y.startswith(x) for x in wa for y in wb)


def _wiki_removals(changes: pd.DataFrame) -> dict[str, list[tuple[date, str, str]]]:
    out: dict[str, list[tuple[date, str, str]]] = {}
    for row in changes.dropna(subset=["removed_ticker"]).itertuples():
        out.setdefault(row.removed_ticker, []).append(
            (pd.Timestamp(row.date).date(), row.removed_name, str(row.reason))
        )
    return out


def resolve(
    membership: pd.DataFrame,
    changes: pd.DataFrame,
    tickers: list[str],
    client: httpx.Client,
    first_annual_filed=None,
    overrides: pd.DataFrame | None = None,
    rename_window_days: int = 1,
) -> pd.DataFrame:
    """One row per historical ticker: cik, yahoo symbol, name, method, exit date and reason.

    `first_annual_filed(cik)` returns the date of a company's first 10-K in EDGAR; a rename
    is only accepted when the new ticker's company filed 10-Ks at least a year before the
    switch (a new spin-off on the same day is an index change, not a rename).
    `overrides` (columns ticker, cik, yahoo, note) are reviewed by hand and win.
    """
    sec = sec_tickers(client)
    by_cik: dict[int, str] = {}
    for t, (cik, _) in sec.items():
        # prefer the common stock: no class/warrant suffix, then the shortest ticker
        old = by_cik.get(cik)
        if old is None or ("." in old, len(old)) > ("." in t, len(t)):
            by_cik[cik] = t
    removals = _wiki_removals(changes)
    wiki_adds = changes.dropna(subset=["added_ticker"])
    wiki_add_dates = {r.added_ticker: pd.Timestamp(r.date).date() for r in wiki_adds.itertuples()}
    rows = []
    for t in tickers:
        spans = membership[membership.ticker == t]
        end = spans.end.max() if spans.end.notna().all() else pd.NaT
        exit_info = None
        if pd.notna(end):
            near = [x for x in removals.get(t, []) if abs((x[0] - end.date()).days) <= 5]
            exit_info = near[0] if near else None
        row = {
            "ticker": t,
            "left_index": end.date() if pd.notna(end) else None,
            "exit_reason": exit_info[2] if exit_info else None,
        }
        reused = t in sec and exit_info is not None and not same_company(exit_info[1], sec[t][1])
        if t in sec and not reused:
            cik, name = sec[t]
            rows.append(
                {
                    **row,
                    "cik": cik,
                    "yahoo": t.replace(".", "-"),
                    "name": name,
                    "method": "sec_current",
                }
            )
            continue
        if pd.notna(end) and exit_info is None:
            lo = end - timedelta(days=rename_window_days)
            hi = end + timedelta(days=rename_window_days)
            starts = membership[(membership.start >= lo) & (membership.start <= hi)]
            cands = []
            for s in starts.ticker:
                if s not in sec or s == t:
                    continue
                added = wiki_add_dates.get(s)
                if added and abs((added - end.date()).days) <= 5:
                    continue  # a real index addition, not a new name
                cik = sec[s][0]
                first = first_annual_filed(cik) if first_annual_filed else None
                if first is not None and first > end - pd.Timedelta(days=365):
                    continue  # the new company did not exist before: spin-off, not rename
                cands.append(s)
            if len(cands) == 1:
                new = cands[0]
                cik, name = sec[new]
                rows.append(
                    {
                        **row,
                        "cik": cik,
                        "yahoo": new.replace(".", "-"),
                        "name": name,
                        "method": f"rename:{new}",
                    }
                )
                continue
        old_name = exit_info[1] if exit_info else None
        found = edgar_name_search(client, old_name) if old_name else None
        if found and found[0] in by_cik:
            # same legal entity still files and trades under a new ticker
            new = by_cik[found[0]]
            rows.append(
                {
                    **row,
                    "cik": found[0],
                    "yahoo": new.replace(".", "-"),
                    "name": found[1],
                    "method": f"cik_current:{new}",
                }
            )
        elif found:
            rows.append(
                {**row, "cik": found[0], "yahoo": None, "name": found[1], "method": "name_search"}
            )
        else:
            rows.append(
                {**row, "cik": None, "yahoo": None, "name": old_name, "method": "unresolved"}
            )
    out = pd.DataFrame(rows)
    if overrides is not None and len(overrides):
        out = out.set_index("ticker")
        for o in overrides.itertuples():
            out.loc[o.ticker, ["cik", "yahoo", "method"]] = [
                o.cik if pd.notna(o.cik) else None,
                o.yahoo if isinstance(o.yahoo, str) and o.yahoo else None,
                f"override: {o.note}",
            ]
        out = out.reset_index()
    out["cik"] = pd.to_numeric(out["cik"]).astype("Int64")
    return out
