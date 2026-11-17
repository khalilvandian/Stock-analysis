"""Full SEC filings through edgartools: the facts SEC's company facts leave out (issue #29).

Company facts (ingest/sec.py) has every fact of the standard taxonomies, but not the facts
split by a dimension. Visa, for example, reports its diluted EPS only per share class. For the
companies with a listed share class in config/companies.toml ([[share_class]]), the ingest
job plans one task per 10-K or 10-Q that reports a missing value (sec_xbrl, keyed by the
accession number). A task reads the filing's XBRL files with edgartools, keeps them as they
came (raw_payload: the six files, with the filing's identity) and stores the mapped facts with
their dimension in raw_sec_xbrl_fact. The build then reads the listed class's value.

edgartools makes its own requests to SEC (about eight per filing), with the same SEC_USER_AGENT.
"""

from __future__ import annotations

import json
import re

import pandas as pd
from sqlalchemy.engine import Connection

from ..db import frame
from ..db.build import ITEMS_CONFIG, load_companies, load_items
from ..db.load_files import finish_fetch, store_changed
from .common import NoData, Outcome, read_payload, sha256, start_fetch
from .sec import user_agent

KINDS = ("schema", "label", "presentation", "calculation", "definition", "instance")
FACT_KEY = ["cik", "accn", "concept", "axis", "member", "unit", "period_start", "period_end"]
FACT_VALUES = ["value", "form", "filed", "label", "statement", "custom"]
STANDARD = ("us-gaap:", "dei:", "srt:", "ifrs-full:")
STATEMENTS = {"IncomeStatement": "IS", "BalanceSheet": "BS", "CashFlowStatement": "CF",
              "StatementOfEquity": "EQ", "ComprehensiveIncome": "CI"}  # fmt: skip
CLASS_AXIS = "us-gaap:StatementClassOfStockAxis"
REQUESTS_PER_FILING = 8


def mapped_concepts(items_config=ITEMS_CONFIG) -> set[str]:
    """The concepts config/db_items.toml reads per share class (sec_class)."""
    _, tags = load_items(items_config)
    return set(tags.loc[tags["taxonomy"] == "sec_class", "tag"])


def share_classes() -> dict[str, str]:
    """Symbol -> the XBRL member of its listed share class (config/companies.toml)."""
    return {s["symbol"]: s["member"] for s in load_companies().get("share_class", [])}


def fetch_files(accession: str) -> dict:
    """The filing's XBRL files, as edgartools downloads them, with the filing's identity."""
    import edgar
    from edgar.xbrl.xbrl import XBRLAttachments

    edgar.set_identity(user_agent())
    filing = edgar.get_by_accession_number(accession)
    if filing is None:
        raise NoData(f"SEC has no filing {accession}")
    files = XBRLAttachments(filing.attachments)
    found = {k: files.content(k) for k in KINDS if files.get(k)}
    if "instance" not in found:
        raise NoData(f"filing {accession} has no XBRL instance")
    return {"accession": accession, "cik": int(filing.cik), "form": filing.form,
            "filed": str(filing.filing_date), "files": found}  # fmt: skip


def parse_files(files: dict):
    """An edgartools XBRL object from the kept files (no request)."""
    from edgar.xbrl import XBRL

    x = XBRL()
    for kind in KINDS:  # in this order, as edgartools reads a filing
        if kind in files:
            method = "parse_labels_content" if kind == "label" else f"parse_{kind}_content"
            getattr(x.parser, method)(files[kind])
    return x


def unit_of(unit_ref: str, currency) -> str:
    """The fact's unit as SEC's company facts names it."""
    ref = str(unit_ref or "").lower()
    if "pershare" in ref or "per_share" in ref:
        return "USD/shares"
    if ref.startswith("share"):
        return "shares"
    return "USD" if (currency == "USD" or ref == "usd") else str(unit_ref)


def facts_frame(payload: dict, keep: set[str]) -> pd.DataFrame:
    """The kept filing's facts of the mapped concepts, without a dimension or with one."""
    cols = FACT_KEY + FACT_VALUES
    df = parse_files(payload["files"]).facts.to_dataframe()
    if df.empty:
        return pd.DataFrame(columns=cols)
    df = df[df["concept"].isin(keep) & df["numeric_value"].notna()]
    for c in ("dimension", "member", "period_start", "period_end", "period_instant"):
        if c not in df:
            df[c] = None
    one_dim = df["dimension"].isna() | ~df["dimension"].astype(str).str.contains(",")
    df = df[one_dim]
    out = pd.DataFrame(
        {
            "cik": payload["cik"],
            "accn": payload["accession"],
            "concept": df["concept"],
            "axis": df["dimension"].fillna("").astype(str),
            "member": df["member"].fillna("").astype(str),
            "unit": [unit_of(u, c) for u, c in zip(df["unit_ref"], df["currency"], strict=True)],
            "period_start": df["period_start"],
            "period_end": df["period_end"].fillna(df["period_instant"]),
            "value": df["numeric_value"].astype(float),
            "form": payload["form"],
            "filed": payload["filed"],
            "label": df["label"],
            "statement": df["statement_type"].map(STATEMENTS) if "statement_type" in df else None,
            "custom": ~df["concept"].str.startswith(STANDARD),
        }
    )
    return out.dropna(subset=["period_end"]).drop_duplicates(FACT_KEY)[cols]


def load_filing(conn: Connection, accession: str, keep: set[str]) -> Outcome:
    """One sec_xbrl task: the filing's XBRL files kept, its mapped facts stored."""
    out = Outcome(requests=REQUESTS_PER_FILING)
    payload = fetch_files(accession)
    body = json.dumps(payload, sort_keys=True).encode()
    url = f"https://www.sec.gov/Archives/edgar/data/{payload['cik']}/{accession.replace('-', '')}/"
    fetch_id = start_fetch(conn, "sec_xbrl", accession, url, sha256(body), payload=body)
    if fetch_id is None:
        return out
    df = facts_frame(payload, keep)
    stored = store_changed(conn, "raw_sec_xbrl_fact", df, FACT_KEY, FACT_VALUES, fetch_id)
    finish_fetch(conn, fetch_id, len(df), stored)
    out.received, out.stored = len(df), stored
    out.fetch_ids.append(fetch_id)
    return out


def reparse(db, keep: set[str] | None = None) -> dict:
    """Read every kept filing again with today's mapping (no request)."""
    keep = keep or mapped_concepts()
    with db.connect() as conn:
        kept = frame(
            conn,
            "SELECT f.fetch_id FROM raw_fetch f JOIN raw_payload p ON p.fetch_id = f.fetch_id "
            "WHERE f.source = 'sec_xbrl'",
        )
    stored = 0
    for fetch_id in kept["fetch_id"]:
        with db.begin() as conn:
            payload = json.loads(read_payload(conn, int(fetch_id)))
            df = facts_frame(payload, keep)
            stored += store_changed(
                conn, "raw_sec_xbrl_fact", df, FACT_KEY, FACT_VALUES, int(fetch_id)
            )
    return {"files": len(kept), "stored": stored}


def filings_for_gaps(conn: Connection, items: list[str]) -> list[dict]:
    """The 10-K or 10-Q that reports each missing value (out_coverage_gap) of these items, for
    the companies with a listed share class: [{symbol, accession}]. A filing's period is the
    latest end of its us-gaap flows in company facts; a fiscal year's gap is matched to the
    10-K ending that year in the fiscal year-end month, a quarter's to the 10-Q ending in that
    month (a 52/53-week quarter may end in the month before)."""
    classes = share_classes()
    if not classes or not items:
        return []
    gaps = frame(
        conn,
        "SELECT symbol, item, period FROM out_coverage_gap WHERE status = 'missing' "
        "AND item = ANY(:items) AND symbol = ANY(:symbols)",
        {"items": items, "symbols": list(classes)},
    )
    if gaps.empty:
        return []
    filings = frame(
        conn,
        "SELECT c.symbol, f.accn, f.form, MAX(f.period_end) AS report_end FROM raw_sec_fact f "
        "JOIN core_company c ON c.cik = f.cik WHERE c.symbol = ANY(:symbols) "
        "AND f.taxonomy = 'us-gaap' AND f.period_start IS NOT NULL "
        "AND f.form IN ('10-K', '10-Q') GROUP BY c.symbol, f.accn, f.form",
        {"symbols": sorted(set(gaps["symbol"]))},
    )
    if filings.empty:
        return []
    filings["ym"] = pd.to_datetime(filings["report_end"]).dt.to_period("M")
    wanted = []
    for g in gaps.itertuples():
        mine = filings[filings["symbol"] == g.symbol]
        if g.period.startswith("FY"):
            hit = mine[(mine["form"] == "10-K") & (mine["ym"].dt.year == int(g.period[2:]))]
        else:
            ym = pd.Period(g.period, "M")
            hit = mine[(mine["form"] == "10-Q") & mine["ym"].isin([ym, ym - 1])]
        if len(hit):
            wanted.append({"symbol": g.symbol, "accession": hit["accn"].iloc[0]})
    return [dict(t) for t in {tuple(w.items()) for w in wanted}]


def accession_ok(accession: str) -> bool:
    return bool(re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession))
