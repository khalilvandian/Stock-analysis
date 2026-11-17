"""SEC EDGAR: the ticker-to-CIK file and each company's XBRL "company facts" (every value
filed in 10-K, 10-Q, 20-F and 40-F filings, with its filing date). Free; SEC asks for at
most 10 requests a second and a User-Agent naming the client (SEC_USER_AGENT).

Only the facts whose tags config/db_items.toml maps to an item are stored, so raw_sec_fact
stays small. A tag added to db_items.toml later needs the companies fetched again
(`ingest --due-now sec_companyfacts`).
"""

from __future__ import annotations

import json
import os

import httpx
import pandas as pd
from sqlalchemy.engine import Connection

from ..db import frame, insert_df
from ..db.build import ITEMS_CONFIG, load_items
from ..db.load_files import finish_fetch, store_changed
from .common import NoData, Outcome, RateLimited, sha256, start_fetch

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FACT_KEY = ["cik", "taxonomy", "tag", "unit", "period_start", "period_end", "accn"]
FACT_VALUES = ["value", "fy", "fp", "form", "filed"]


def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT") or "stock-analysis research project"


def client() -> httpx.Client:
    return httpx.Client(
        timeout=120, headers={"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    )


def get(http: httpx.Client, url: str) -> httpx.Response:
    r = http.get(url)
    if r.status_code == 429:
        raise RateLimited(f"SEC 429 for {url}")
    if r.status_code == 403:  # SEC refuses clients that don't name themselves
        raise RateLimited(
            f"SEC 403 for {url}: set SEC_USER_AGENT to '<project> <contact email>' "
            f"(now {user_agent()!r}), and keep under 10 requests a second"
        )
    if r.status_code == 404:
        raise NoData(f"SEC has nothing at {url}")
    r.raise_for_status()
    return r


def mapped_tags(items_config=ITEMS_CONFIG) -> set[tuple[str, str]]:
    """(taxonomy, tag) pairs that config/db_items.toml maps to an item."""
    _, tags = load_items(items_config)
    sec = tags[~tags["taxonomy"].isin(["history", "yahoo"])]
    return set(zip(sec["taxonomy"], sec["tag"], strict=True))


# ---------------------------------------------------------------- tickers


def load_tickers(conn: Connection, http: httpx.Client) -> Outcome:
    r = get(http, TICKERS_URL)
    out = Outcome(requests=1)
    fetch_id = start_fetch(conn, "sec_tickers", "all", TICKERS_URL, sha256(r.content))
    if fetch_id is None:
        return out  # same file as last time
    rows = pd.DataFrame(r.json().values())
    df = pd.DataFrame(
        {"ticker": rows["ticker"], "cik": rows["cik_str"].astype("int64"), "title": rows["title"]}
    ).drop_duplicates("ticker")
    df.insert(0, "fetch_id", fetch_id)
    insert_df(conn, "raw_sec_ticker", df)
    finish_fetch(conn, fetch_id, len(df), len(df))
    out.received = out.stored = len(df)
    out.fetch_ids.append(fetch_id)
    return out


def ciks(conn: Connection) -> dict[str, int]:
    """Symbol (TradingView style, BRK.B) -> CIK, from the newest ticker file."""
    t = frame(
        conn,
        "SELECT ticker, cik FROM raw_sec_ticker "
        "WHERE fetch_id = (SELECT MAX(fetch_id) FROM raw_sec_ticker)",
    )
    return {k.replace("-", "."): int(v) for k, v in zip(t["ticker"], t["cik"], strict=True)}


# ---------------------------------------------------------------- company facts


def facts_frame(payload: dict, cik: int, keep: set[tuple[str, str]]) -> pd.DataFrame:
    """The kept facts of a companyfacts document, one row per fact."""
    rows = []
    for taxonomy, tags in (payload.get("facts") or {}).items():
        for tag, node in tags.items():
            if (taxonomy, tag) not in keep:
                continue
            for unit, facts in (node.get("units") or {}).items():
                for x in facts:
                    if x.get("val") is None or not x.get("end") or not x.get("filed"):
                        continue
                    rows.append(
                        {
                            "cik": cik,
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "unit": unit,
                            "period_start": x.get("start"),
                            "period_end": x["end"],
                            "accn": x.get("accn") or "",
                            "value": float(x["val"]),
                            "fy": x.get("fy"),
                            "fp": x.get("fp"),
                            "form": x.get("form"),
                            "filed": x["filed"],
                        }
                    )
    df = pd.DataFrame(rows, columns=FACT_KEY + FACT_VALUES)
    df["fy"] = pd.to_numeric(df["fy"]).astype("Int64")
    return df.drop_duplicates(FACT_KEY, keep="last")


def load_companyfacts(
    conn: Connection, http: httpx.Client, cik: int, keep: set[tuple[str, str]]
) -> Outcome:
    url = FACTS_URL.format(cik=cik)
    r = get(http, url)
    out = Outcome(requests=1)
    fetch_id = start_fetch(conn, "sec_companyfacts", str(cik), url, sha256(r.content))
    if fetch_id is None:
        return out
    df = facts_frame(json.loads(r.content), cik, keep)
    stored = store_changed(conn, "raw_sec_fact", df, FACT_KEY, FACT_VALUES, fetch_id)
    finish_fetch(conn, fetch_id, len(df), stored)
    out.received, out.stored = len(df), stored
    out.fetch_ids.append(fetch_id)
    return out
