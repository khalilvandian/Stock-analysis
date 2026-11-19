"""Files downloaded or found by hand, loaded into the raw layer as if their source had returned
them (issue #29).

    python -m stock_analysis.db import inbox/sec_companyfacts/companyfacts.zip
    python -m stock_analysis.db import FILE --target server --symbols COST,KR

A file goes through the same parser as its API source, into the same raw tables: one
raw_fetch row per payload (url file:<name>), the payload kept in raw_payload, and a payload
seen before is skipped. Then the source's tasks for what the file covered are marked fetched
(ops_task), so the ingest job, on this PC or on the server, doesn't download it again. Run
it with --target server and the server's database receives the data directly from this PC:
the cloud job never needs the file.

Kinds (the folder name under inbox/, or --kind):

    sec_companyfacts   SEC's companyfacts.zip (every company, rebuilt nightly) or one
                       CIK##########.json from the company-facts API. Only the companies the
                       database follows (the universe, their predecessors) are loaded.
    sec_fsds           A quarter of SEC's Financial Statement Data Sets (2026q3.zip: every
                       filing's numbers). For the followed companies' 10-K and 10-Q, the
                       facts company facts leaves out go into raw_sec_xbrl_fact: the
                       companies' own tags, and the values per share class of the concepts
                       read per class. A subsidiary's values (co-registrants) are left out.

A payload larger than PAYLOAD_MAX_BYTES (a quarter's data set, about 80 MB) is not copied
into the database: the file stays in inbox/ and raw_fetch.url names it.
"""

from __future__ import annotations

import hashlib
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from ..db import Database, frame, run
from ..db.build import load_companies
from ..db.raw import finish_fetch, store_changed
from . import xbrl
from .common import sha256, start_fetch
from .job import load_config
from .sec import mapped_tags, parse_companyfacts

CIK_FILE = re.compile(r"CIK(\d{10})\.json$")
PAYLOAD_MAX_BYTES = 50_000_000
FSDS_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A"}


def followed_ciks(conn, symbols: list[str] | None = None) -> dict[int, list[str]]:
    """CIK -> the task keys it fills: the symbols of the companies the database follows
    (core_company, or the ticker file for a company not built yet) and predecessor CIKs."""
    rows = frame(
        conn,
        "SELECT symbol, cik FROM core_company WHERE cik IS NOT NULL "
        "UNION SELECT REPLACE(t.ticker, '-', '.'), t.cik FROM raw_sec_ticker t "
        "JOIN ops_task o ON o.request_key = REPLACE(t.ticker, '-', '.') "
        "AND o.source = 'sec_companyfacts' "
        "WHERE t.fetch_id = (SELECT MAX(fetch_id) FROM raw_sec_ticker)",
    )
    out: dict[int, list[str]] = {}
    for sym, cik in zip(rows["symbol"], rows["cik"], strict=True):
        if symbols is None or sym in symbols:
            out.setdefault(int(cik), []).append(sym)
    for p in load_companies().get("predecessor", []):
        if symbols is None or p["symbol"] in symbols:
            out.setdefault(int(p["cik"]), []).append(f"CIK{int(p['cik'])}")
    return out


def mark_fetched(conn, source: str, keys: list[str], when: datetime, fetch_id) -> None:
    """The tasks a file covered count as fetched on the file's date: due again after the
    source's refresh interval, as if the job had fetched them then."""
    days = float(load_config()["sources"][source]["refresh_days"]["maintain"])
    run(
        conn,
        "UPDATE ops_task SET status = 'ok', attempts = 0, last_attempt_at = :t, "
        "last_success_at = :t, next_due_at = :due, last_error = NULL, "
        "last_fetch_id = COALESCE(:id, last_fetch_id) "
        "WHERE source = :source AND request_key = ANY(:keys)",
        {"t": when.strftime("%Y-%m-%dT%H:%M:%S"),
         "due": (when + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S"),
         "id": fetch_id, "source": source, "keys": keys},
    )  # fmt: skip


def import_companyfacts(db: Database, path: Path, symbols: list[str] | None = None) -> dict:
    """companyfacts.zip, or a single CIK##########.json."""
    keep = mapped_tags()
    with db.connect() as conn:
        follow = followed_ciks(conn, symbols)
    when = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(tzinfo=None)
    done = {"files": 0, "new": 0, "stored": 0, "skipped_not_followed": 0}

    def one(name: str, content: bytes) -> None:
        m = CIK_FILE.search(name)
        cik = int(m.group(1)) if m else None
        if cik not in follow:
            done["skipped_not_followed"] += 1
            return
        url = f"file:{path.name}#{name}" if name != path.name else f"file:{path.name}"
        with db.begin() as conn:
            fetch_id = start_fetch(
                conn, "sec_companyfacts", str(cik), url, sha256(content), when, payload=content
            )
            if fetch_id is not None:
                stored, received = parse_companyfacts(conn, content, cik, keep, fetch_id)
                finish_fetch(conn, fetch_id, received, stored)
                done["new"] += 1
                done["stored"] += stored
            mark_fetched(conn, "sec_companyfacts", follow[cik], when, fetch_id)
        done["files"] += 1

    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            wanted = [n for n in z.namelist() if (m := CIK_FILE.search(n)) and
                      int(m.group(1)) in follow]  # fmt: skip
            done["skipped_not_followed"] = len(z.namelist()) - len(wanted)
            for name in wanted:
                one(name, z.read(name))
    else:
        one(path.name, path.read_bytes())
    return done


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fsds_frame(
    path: Path, ciks: set[int], class_concepts: set[str], standard: set[str] | None = None
) -> pd.DataFrame:
    """The kept rows of one quarter's data set, in raw_sec_xbrl_fact's columns: the
    companies' own tags, the values per share class of `class_concepts`, and the `standard`
    concepts (the tags mapped in config/db_items.toml, 'us-gaap:Revenues')."""
    cols = xbrl.FACT_KEY + xbrl.FACT_VALUES
    with zipfile.ZipFile(path) as z:
        sub = pd.read_csv(
            z.open("sub.txt"), sep="\t", dtype=str, usecols=["adsh", "cik", "form", "filed"]
        )
        sub = sub[sub["form"].isin(FSDS_FORMS) & sub["cik"].astype(int).isin(ciks)]
        num = pd.concat(
            c[c["adsh"].isin(sub["adsh"])]
            for c in pd.read_csv(z.open("num.txt"), sep="\t", dtype=str, chunksize=500_000)
        )
        pre = pd.concat(
            c[c["adsh"].isin(sub["adsh"])]
            for c in pd.read_csv(z.open("pre.txt"), sep="\t", dtype=str, chunksize=500_000,
                                 usecols=["adsh", "stmt", "tag", "version", "plabel"])
        )  # fmt: skip
    if num.empty:
        return pd.DataFrame(columns=cols)
    num = num[num["coreg"].isna()]  # the filer's own values, not a subsidiary's
    custom = num["version"] == num["adsh"]
    seg = num["segments"].fillna("")
    prefix = num["version"].str.split("/").str[0]
    one_class = seg.str.fullmatch(r"ClassOfStock=[^;=]+;")
    by_class = one_class & ("us-gaap:" + num["tag"]).isin(class_concepts) & ~custom
    mapped = ~custom & (seg == "") & (prefix + ":" + num["tag"]).isin(standard or set())
    num = num[(custom & (seg == "")) | by_class | mapped].copy()
    if num.empty:
        return pd.DataFrame(columns=cols)
    member = seg[num.index].str.extract(r"ClassOfStock=([^;]+);")[0]
    end = pd.to_datetime(num["ddate"], format="%Y%m%d")
    qtrs = num["qtrs"].astype(int)
    start = [None if q == 0 else (e - pd.DateOffset(months=3 * q) + pd.Timedelta(days=1))
             for e, q in zip(end, qtrs, strict=True)]  # fmt: skip
    pre = pre.drop_duplicates(["adsh", "tag", "version"])
    num = num.merge(pre, on=["adsh", "tag", "version"], how="left")
    sub = sub.set_index("adsh")
    is_custom = (num["version"] == num["adsh"]).to_numpy()
    out = pd.DataFrame(
        {
            "cik": sub.loc[num["adsh"], "cik"].astype(int).to_numpy(),
            "accn": num["adsh"].to_numpy(),
            "concept": [
                ("custom" if c else v.split("/")[0]) + ":" + t
                for c, v, t in zip(is_custom, num["version"], num["tag"], strict=True)
            ],  # fmt: skip
            "axis": ["" if pd.isna(m) else xbrl.CLASS_AXIS for m in member.to_numpy()],
            "member": ["" if pd.isna(m) else f"us-gaap:{m}Member" for m in member.to_numpy()],
            "unit": num["uom"].replace({"USD/shares": "USD/shares"}).to_numpy(),
            "period_start": [None if s is None else s.strftime("%Y-%m-%d") for s in start],
            "period_end": end.dt.strftime("%Y-%m-%d").to_numpy(),
            "value": pd.to_numeric(num["value"], errors="coerce").to_numpy(),
            "form": sub.loc[num["adsh"], "form"].to_numpy(),
            "filed": pd.to_datetime(sub.loc[num["adsh"], "filed"], format="%Y%m%d")
            .dt.strftime("%Y-%m-%d")
            .to_numpy(),
            "label": num["plabel"].to_numpy(),
            "statement": num["stmt"].to_numpy(),
            "custom": is_custom,
        }
    )
    return out.dropna(subset=["value"]).drop_duplicates(xbrl.FACT_KEY)[cols]


def import_fsds(db: Database, path: Path, symbols: list[str] | None = None) -> dict:
    """One quarter of the Financial Statement Data Sets."""
    with db.connect() as conn:
        follow = followed_ciks(conn, symbols)
    when = datetime.fromtimestamp(path.stat().st_mtime, UTC).replace(tzinfo=None)
    standard = {f"{a}:{b}" for a, b in mapped_tags()}
    df = fsds_frame(path, set(follow), xbrl.mapped_concepts(), standard)
    size = path.stat().st_size
    payload = path.read_bytes() if size <= PAYLOAD_MAX_BYTES else None
    key = path.stem if symbols is None else f"{path.stem}:{','.join(sorted(symbols))}"
    done = {"rows": len(df), "stored": 0, "companies": int(df["cik"].nunique()) if len(df) else 0}
    with db.begin() as conn:
        fetch_id = start_fetch(
            conn, "sec_fsds", key, f"file:{path.as_posix()}", file_sha256(path), when,
            payload=payload, media_type="application/zip",
        )  # fmt: skip
        if fetch_id is None:
            return {**done, "rows": 0, "note": "imported before"}
        for cik, part in df.groupby("cik"):
            part = not_in_company_facts(conn, int(cik), part)
            done["stored"] += store_changed(
                conn, "raw_sec_xbrl_fact", part, xbrl.FACT_KEY, xbrl.FACT_VALUES, fetch_id
            )
        finish_fetch(conn, fetch_id, len(df), done["stored"])
    return done


def not_in_company_facts(conn, cik: int, part: pd.DataFrame) -> pd.DataFrame:
    """A data set's standard facts that SEC's company facts doesn't have (some filings never
    reach company facts: DTE's 10-Q for June 2026 is in the data set only). The company's own
    tags and the per-class values are kept whatever company facts has."""
    have = frame(
        conn,
        "SELECT accn, taxonomy || ':' || tag AS concept, "
        "to_char(period_end, 'YYYY-MM-DD') AS period_end FROM raw_sec_fact "
        "WHERE cik = :cik AND accn = ANY(:accns)",
        {"cik": cik, "accns": sorted(set(part["accn"]))},
    )
    standard = ~part["custom"] & (part["axis"] == "")
    if have.empty or not standard.any():
        return part
    key = ["accn", "concept", "period_end"]
    seen = part[key].merge(have.drop_duplicates(), on=key, how="left", indicator=True)
    return part[~(standard.to_numpy() & (seen["_merge"] == "both").to_numpy())]


def reparse_fsds(db: Database) -> dict:
    """Read every imported data-set quarter again with today's mapping, from the file its
    raw_fetch row names (a quarter is too big to keep in the database). A file no longer on
    this PC is skipped."""
    with db.connect() as conn:
        done_before = frame(
            conn, "SELECT fetch_id, request_key, url FROM raw_fetch WHERE source = 'sec_fsds'"
        )
    out = {"files": 0, "missing_files": 0, "stored": 0}
    standard = {f"{a}:{b}" for a, b in mapped_tags()}
    for fetch_id, key, url in done_before.itertuples(index=False):
        path = Path(str(url).removeprefix("file:"))
        if not path.exists():
            out["missing_files"] += 1
            continue
        symbols = key.split(":", 1)[1].split(",") if ":" in key else None
        with db.begin() as conn:
            follow = followed_ciks(conn, symbols)
            df = fsds_frame(path, set(follow), xbrl.mapped_concepts(), standard)
            for cik, part in df.groupby("cik"):
                part = not_in_company_facts(conn, int(cik), part)
                out["stored"] += store_changed(
                    conn, "raw_sec_xbrl_fact", part, xbrl.FACT_KEY, xbrl.FACT_VALUES,
                    int(fetch_id),
                )  # fmt: skip
        out["files"] += 1
    return out


def reparse_all(db: Database) -> dict:
    """Every kept payload read again with today's mapping (db reparse): SEC company facts,
    full filings, data-set quarters. No request to any source."""
    from .sec import reparse_companyfacts

    return {
        "sec_companyfacts": reparse_companyfacts(db),
        "sec_xbrl": xbrl.reparse(db),
        "sec_fsds": reparse_fsds(db),
    }


IMPORTERS = {"sec_companyfacts": import_companyfacts, "sec_fsds": import_fsds}


def import_file(
    db: Database, path: str | Path, kind: str | None = None, symbols: list[str] | None = None
) -> dict:
    """Load one file; its kind is --kind or the name of its folder (inbox/<kind>/)."""
    path = Path(path)
    kind = kind or path.parent.name
    if kind not in IMPORTERS:
        raise ValueError(f"unknown kind {kind!r}: one of {', '.join(IMPORTERS)} (--kind)")
    return {"kind": kind, "file": str(path), **IMPORTERS[kind](db, path, symbols)}
