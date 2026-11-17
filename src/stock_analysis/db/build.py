"""Rebuild the core layer from the raw layer (docs/DATABASE.md, "Build rules").

The build reads only raw_* tables, config/db_items.toml and config/companies.toml (predecessor
CIKs). In one transaction it rewrites core_item, core_item_tag, core_index_member,
core_price_daily, core_fundamental and core_fundamental_ttm, updates core_company in place (so
company_id stays the same), and adds a core_build row with that build's core_quality_issue
rows.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import ROOT, Database, frame, insert_df, records, run, scalar
from .load_files import UNIVERSE, now

ITEMS_CONFIG = ROOT / "config" / "db_items.toml"
COMPANIES_CONFIG = ROOT / "config" / "companies.toml"


def load_companies(path: Path = COMPANIES_CONFIG) -> dict:
    """config/companies.toml: predecessor CIKs and formation dates."""
    if not Path(path).exists():
        return {}
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


FIRST_DATE = "2016-01-01"
SOURCE_RANK = {"sec": 1, "history": 2, "yahoo": 3}
# No source loaded so far records filing dates: estimate them as the latest SEC deadline.
FILED_LAG_DAYS = {"year": 90, "quarter": 45}
SPLIT_ITEMS = {"shares_outstanding": "multiply", "eps_diluted": "divide"}
KEY = ["company_id", "item", "period_type", "period_end"]


def plain(x):
    """A value the database driver accepts (no numpy scalars, None for missing)."""
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return None
    return x.item() if hasattr(x, "item") else x


# ---------------------------------------------------------------- items


def load_items(path: Path = ITEMS_CONFIG) -> tuple[pd.DataFrame, pd.DataFrame]:
    config = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    items, tags = [], []
    for it in config["items"]:
        row = {k: it.get(k) for k in ("item", "label", "kind", "unit", "derive")}
        row["derive_mode"] = it.get("derive_mode", "replace")
        row["helper"] = bool(it.get("helper", False))
        items.append(row)
        for i, tag in enumerate(it.get("sec", []), start=1):
            taxonomy, _, name = tag.rpartition(":")
            tags.append((it["item"], taxonomy or "us-gaap", name, i, float(it.get("sec_scale", 1))))
        for i, tag in enumerate(it.get("sec_class", []), start=1):  # per share class
            tags.append((it["item"], "sec_class", tag, i, float(it.get("sec_scale", 1))))
        for i, tag in enumerate(it.get("history", []), start=1):
            tags.append((it["item"], "history", tag, i, float(it.get("history_scale", 1))))
        for i, tag in enumerate(it.get("yahoo", []), start=1):
            tags.append((it["item"], "yahoo", tag, i, 1.0))
    tags = pd.DataFrame(tags, columns=["item", "taxonomy", "tag", "priority", "scale"])
    return pd.DataFrame(items), tags


ITEM_COLUMNS = ["item", "label", "kind", "unit", "derive"]  # the columns of core_item


def stored(items: pd.DataFrame, tags: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The items and tags written to core_item and core_item_tag: helpers (the parts of a
    derivation, such as liabilities and equity) are used inside the build only."""
    keep = items[~items["helper"]]
    return keep[ITEM_COLUMNS], tags[tags["item"].isin(keep["item"])]


def parse_derive(expr: str) -> list[tuple[int, str, bool]]:
    """'a - b - c?' as [(1, 'a', False), (-1, 'b', False), (-1, 'c', True)]: the sign, the
    item, and whether the term is optional (counted as 0 when the company has none)."""
    terms, sign = [], 1
    for token in expr.replace("+", " + ").replace("-", " - ").split():
        if token in "+-":
            sign = 1 if token == "+" else -1
            continue
        terms.append((sign, token.rstrip("?"), token.endswith("?")))
        sign = 1
    return terms


# ---------------------------------------------------------------- companies and membership


def build_companies(conn: Connection) -> dict[str, int]:
    tv = frame(
        conn,
        "SELECT c.*, f.fetched_at FROM raw_tv_constituent c JOIN raw_fetch f "
        "ON f.fetch_id = c.fetch_id WHERE f.source = 'tradingview' AND f.request_key = :u",
        {"u": UNIVERSE},
    )
    if not tv.empty:
        last = tv.sort_values("fetch_id", kind="stable").drop_duplicates("symbol", keep="last")
        last = last.sort_values("symbol")  # new companies get ids in symbol order
        cols = ["symbol", "name", "exchange", "sector", "industry", "currency"]
        run(
            conn,
            "INSERT INTO core_company (symbol, name, exchange, sector, industry, currency) "
            "VALUES (:symbol, :name, :exchange, :sector, :industry, :currency) "
            "ON CONFLICT (symbol) DO UPDATE SET name = excluded.name, "
            "exchange = excluded.exchange, sector = excluded.sector, "
            "industry = excluded.industry, currency = excluded.currency",
            records(last[cols]),
        )
    sec = frame(
        conn,
        "SELECT ticker, cik FROM raw_sec_ticker "
        "WHERE fetch_id = (SELECT MAX(fetch_id) FROM raw_sec_ticker)",
    )
    if not sec.empty:  # SEC writes BRK-B, TradingView BRK.B
        sec["symbol"] = sec["ticker"].str.replace("-", ".", regex=False)
        run(
            conn,
            "UPDATE core_company SET cik = :cik WHERE symbol = :symbol",
            records(sec[["cik", "symbol"]]),  # share classes (GOOG, GOOGL) share the CIK
        )
    companies = {r[0]: r[1] for r in run(conn, "SELECT symbol, company_id FROM core_company")}
    build_membership(conn, tv, companies)
    return companies


def build_membership(conn: Connection, tv: pd.DataFrame, companies: dict) -> None:
    """Spells of consecutive snapshots each company was in."""
    if tv.empty:
        return
    tv = tv.assign(day=tv["fetched_at"].str[:10])
    days = sorted(tv["day"].unique())
    member = set(zip(tv["symbol"], tv["day"], strict=True))
    spells = []
    for symbol in sorted(tv["symbol"].unique()):
        start = prev = None
        for day in days:
            if (symbol, day) in member:
                start = start or day
                prev = day
            elif start:
                spells.append((companies[symbol], UNIVERSE, start, prev))
                start = None
        if start:
            spells.append((companies[symbol], UNIVERSE, start, None if prev == days[-1] else prev))
    cols = ["company_id", "index_code", "start_date", "end_date"]
    insert_df(conn, "core_index_member", pd.DataFrame(spells, columns=cols))


# ---------------------------------------------------------------- prices


def adjusted_close(close: pd.Series, dividends: pd.Series) -> pd.Series:
    """Yahoo's dividend adjustment: before each ex-date, multiply by 1 - dividend / prior close."""
    step = np.where(dividends.fillna(0) > 0, 1 - dividends.fillna(0) / close.shift(1), 1.0)
    later = np.nan_to_num(step, nan=1.0)[::-1].cumprod()[::-1]
    factor = np.append(later[1:], 1.0)  # a day is adjusted by the ex-dates after it
    return close * factor


def build_prices(conn: Connection, companies: dict[str, int]) -> pd.DataFrame:
    # The latest version of each day, from a little before core starts (the first dividend
    # adjustment needs the close before it), read in the database to keep memory low.
    raw = frame(
        conn,
        "SELECT DISTINCT ON (symbol, date) symbol, date, open, high, low, close, volume, "
        "dividends, stock_splits FROM raw_yahoo_price WHERE date >= :start "
        "ORDER BY symbol, date, fetch_id DESC",
        {"start": (pd.Timestamp(FIRST_DATE) - pd.Timedelta(days=10)).strftime("%F")},
    )
    raw = raw[raw["symbol"].isin(companies)]
    frames = []
    for symbol, g in raw.sort_values("date").groupby("symbol"):
        g = g.assign(adj_close=adjusted_close(g["close"], g["dividends"]))
        frames.append(g[g["date"] >= FIRST_DATE].assign(company_id=companies[symbol]))
    if not frames:
        return pd.DataFrame(columns=["company_id", "date"])
    p = pd.concat(frames)
    p["split_ratio"] = p["stock_splits"].where(p["stock_splits"] > 0)
    cols = ["company_id", "date", "open", "high", "low", "close", "adj_close", "volume"]
    out = p[[*cols, "dividends", "split_ratio"]]
    out = out.rename(columns={"dividends": "dividend"}).copy()
    out["volume"] = out["volume"].astype("Int64")
    insert_df(conn, "core_price_daily", out)
    return out


def all_splits(conn: Connection, companies: dict[str, int]) -> pd.DataFrame:
    s = frame(
        conn,
        "SELECT DISTINCT symbol, date, stock_splits AS ratio FROM raw_yahoo_price "
        "WHERE stock_splits > 0",
    )
    s = s[s["symbol"].isin(companies)].drop_duplicates(["symbol", "date"])
    return s.assign(company_id=s["symbol"].map(companies))[["company_id", "date", "ratio"]]


# ---------------------------------------------------------------- fundamentals


SEC_FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "10-KT", "10-KT/A", "20-F", "20-F/A"}
SEC_FORMS |= {"40-F", "40-F/A"}
SEC_UNITS = {"USD", "USD/shares", "shares"}
# Period lengths in days (end - start + 1). 52/53-week years have quarters of 12 to 17 weeks
# (84 to 119 days), half years of 24 to 28 weeks and nine months of 36 to 40 weeks.
QUARTER_DAYS, YEAR_DAYS = (80, 120), (350, 380)
HALF_DAYS, NINE_MONTH_DAYS = (165, 200), (245, 290)
QUARTER_SLACK = 0.35  # how far (in quarters, about a month) a quarter may sit off its slot
SEC_FIRST_PERIOD = "2015-01-01"
CLASS_AXIS = "us-gaap:StatementClassOfStockAxis"


def to_month_end(dates: pd.Series) -> pd.Series:
    """Each date as the nearest month end (2026-09-26 and 2026-10-02 are both 2026-09-30), so a
    52/53-week period reported by SEC on its real end and by Yahoo on the month end is one
    period."""
    m = month_index(dates)
    first = pd.to_datetime({"year": m // 12, "month": m % 12 + 1, "day": 1})
    return (first + pd.offsets.MonthEnd(0)).dt.strftime("%Y-%m-%d")


def read_compact(
    conn: Connection, sql: str, params: dict, categories: dict[str, list], chunk: int = 200_000
) -> pd.DataFrame:
    """A large query read in chunks, with the repeated text columns (a tag, a unit, a form)
    turned into categories chunk by chunk, so the whole result never exists as one Python string
    per cell. Dates must come as text (to_char in the SQL)."""
    dtypes = {col: pd.CategoricalDtype(sorted(set(values))) for col, values in categories.items()}
    parts = []
    for part in pd.read_sql(text(sql), conn, params=params, chunksize=chunk):
        for col, dtype in dtypes.items():
            part[col] = part[col].astype(dtype)
        parts.append(part)
    if not parts:
        return pd.DataFrame()
    df = pd.concat(parts, ignore_index=True)
    for col in dtypes:  # back to text: every cell points at one shared string per value
        df[col] = df[col].astype(object)
    return df


def sec_quarters_from_ytd(sec: pd.DataFrame) -> pd.DataFrame:
    """10-Q cash flows are year to date (3, 6 and 9 months): the second quarter is the six
    months less the first quarter, the third the nine months less the six, both from the same
    start date and in their latest versions. Only where SEC reports no such quarter itself."""
    cols = ["symbol", "taxonomy", "tag", "unit"]
    latest = sec.sort_values("filed").drop_duplicates([*cols, "period_start", "period_end"],
                                                      keep="last")  # fmt: skip
    q, h, n = (latest[latest["span"] == x] for x in ("Q", "H", "N"))
    out = []
    for longer, shorter in ((h, q), (n, h)):
        m = longer.merge(shorter, on=[*cols, "period_start"], suffixes=("", "_s"))
        m = m[m["period_end_s"] < m["period_end"]]
        if m.empty:
            continue
        start = (pd.to_datetime(m["period_end_s"]) + pd.Timedelta(days=1)).dt.strftime("%F")
        out.append(m.assign(value=m["value"] - m["value_s"], period_start=start, span="Q",
                            method="derived")[latest.columns])  # fmt: skip
    if not out:
        return sec.iloc[0:0]
    d = pd.concat(out, ignore_index=True)
    have = q[[*cols, "period_end"]].drop_duplicates()
    d = d.merge(have, on=[*cols, "period_end"], how="left", indicator=True)
    return d[d["_merge"] == "left_only"].drop(columns="_merge")


def sec_candidates(conn: Connection, kind: pd.Series, tags: pd.DataFrame) -> pd.DataFrame:
    """SEC company facts that map to an item: a quarter or fiscal-year flow (quarters derived
    from year-to-date totals where needed), or an instant, with its real filing date. Cover-page
    share counts (dei) are dated at the balance-sheet date of their filing, not the cover date.
    Only the latest fetched version of each fact is read, in the database."""
    sec_tags = tags[~tags["taxonomy"].isin(["history", "yahoo", "sec_class"])]
    forms = ", ".join(f"'{x}'" for x in sorted(SEC_FORMS))
    units = ", ".join(f"'{x}'" for x in sorted(SEC_UNITS))
    pairs = ", ".join(f"('{a}', '{b}')" for a, b in zip(sec_tags["taxonomy"], sec_tags["tag"],
                                                        strict=True))  # fmt: skip
    symbols = frame(conn, "SELECT symbol FROM core_company WHERE cik IS NOT NULL")["symbol"]
    if sec_tags.empty or symbols.empty:
        return pd.DataFrame()
    # Each company's own CIK, and the CIKs of its predecessors up to the new one's first filing
    # (config/companies.toml): one company may read two CIKs, two share classes one CIK.
    preds = [
        f"('{p['symbol']}', {int(p['cik'])}, DATE '{p['until']}')"
        for p in load_companies().get("predecessor", [])
    ]
    owners = "SELECT symbol, cik, NULL::date AS until FROM core_company WHERE cik IS NOT NULL"
    if preds:
        owners += " UNION ALL SELECT * FROM (VALUES " + ", ".join(preds) + ") AS p(s, c, u)"
    sec = read_compact(
        conn,
        "SELECT DISTINCT ON (c.symbol, f.taxonomy, f.tag, f.unit, f.period_start, f.period_end, "
        "f.accn) f.raw_id, f.fetch_id, c.symbol, f.taxonomy, f.tag, f.unit, "
        "to_char(f.period_start, 'YYYY-MM-DD') AS period_start, "
        "to_char(f.period_end, 'YYYY-MM-DD') AS period_end, f.value, f.form, "
        "to_char(f.filed, 'YYYY-MM-DD') AS filed, "
        "('x' || substr(md5(f.accn), 1, 16))::bit(64)::bigint AS accn FROM raw_sec_fact f "
        f"JOIN ({owners}) c ON c.cik = f.cik WHERE f.form IN ({forms}) AND f.unit IN ({units}) "
        f"AND (f.taxonomy, f.tag) IN ({pairs}) AND f.period_end >= :first "
        "AND (c.until IS NULL OR f.period_end < c.until) "
        "ORDER BY c.symbol, f.taxonomy, f.tag, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        {"first": SEC_FIRST_PERIOD},
        {"symbol": list(symbols), "taxonomy": list(sec_tags["taxonomy"]),
         "tag": list(sec_tags["tag"]), "unit": list(SEC_UNITS), "form": list(SEC_FORMS)},
    )  # fmt: skip
    # The same tags from the data sets and full filings, for the filings company facts lacks
    # (db import keeps only those there).
    concepts = [f"{a}:{b}" for a, b in zip(sec_tags["taxonomy"], sec_tags["tag"], strict=True)]
    filings = frame(
        conn,
        "SELECT DISTINCT ON (c.symbol, f.concept, f.unit, f.period_start, f.period_end, f.accn) "
        "f.raw_id, f.fetch_id, c.symbol, split_part(f.concept, ':', 1) AS taxonomy, "
        "split_part(f.concept, ':', 2) AS tag, f.unit, "
        "to_char(f.period_start, 'YYYY-MM-DD') AS period_start, "
        "to_char(f.period_end, 'YYYY-MM-DD') AS period_end, f.value, f.form, "
        "to_char(f.filed, 'YYYY-MM-DD') AS filed, "
        "('x' || substr(md5(f.accn), 1, 16))::bit(64)::bigint AS accn "
        f"FROM raw_sec_xbrl_fact f JOIN ({owners}) c ON c.cik = f.cik "
        f"WHERE NOT f.custom AND f.axis = '' AND f.concept = ANY(:concepts) "
        f"AND f.form IN ({forms}) AND f.unit IN ({units}) AND f.period_end >= :first "
        "AND (c.until IS NULL OR f.period_end < c.until) "
        "ORDER BY c.symbol, f.concept, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        {"concepts": concepts, "first": SEC_FIRST_PERIOD},
    )
    sec = pd.concat(
        [sec.assign(raw_table="raw_sec_fact"), filings.assign(raw_table="raw_sec_xbrl_fact")],
        ignore_index=True,
    )
    if sec.empty:
        return sec
    instant = sec["period_start"].isna()
    balance_date = sec[instant & (sec["taxonomy"] != "dei")].groupby("accn")["period_end"].max()
    dei = sec["taxonomy"] == "dei"
    sec.loc[dei, "period_end"] = sec.loc[dei, "accn"].map(balance_date)
    sec = sec.dropna(subset=["period_end"])
    sec = sec.merge(sec_tags, on=["taxonomy", "tag"])
    sec = pd.concat([sec, class_facts(conn, tags), custom_facts(conn, tags)], ignore_index=True)
    if sec.empty:
        return sec
    days = (pd.to_datetime(sec["period_end"]) - pd.to_datetime(sec["period_start"])).dt.days + 1
    sec["span"] = np.select(
        [days.between(*QUARTER_DAYS), days.between(*HALF_DAYS), days.between(*NINE_MONTH_DAYS),
         days.between(*YEAR_DAYS)],
        ["Q", "H", "N", "FY"], default="",
    )  # fmt: skip
    sec["method"] = "reported"
    is_instant_item = sec["item"].map(kind) == "instant"
    flows = sec[~is_instant_item & sec["period_start"].notna()]
    sec = pd.concat([sec, sec_quarters_from_ytd(flows)], ignore_index=True)
    is_instant_item = sec["item"].map(kind) == "instant"
    flow_type = sec["span"].where(sec["span"].isin(["Q", "FY"]), "")
    sec["period_type"] = np.where(
        sec["period_start"].isna() | (is_instant_item & (flow_type != "")), "I", flow_type
    )
    # Before the price history starts the splits are unknown, so per-share values and share
    # counts could not be put on today's basis: SEC values start a year before core does.
    sec = sec[(sec["period_type"] != "") & (sec["period_end"] >= SEC_FIRST_PERIOD)]
    return sec.drop(columns="span").assign(source="sec")


def custom_facts(conn: Connection, tags: pd.DataFrame) -> pd.DataFrame:
    """A company's own tags for an item ([[custom_tag]] in config/companies.toml), from the
    full filings (raw_sec_xbrl_fact): Dominion reports capex only as "plant construction and
    other property additions", DTE in two lines (utility, non-utility), summed per filing and
    period. Tried after the standard tags (priority 200), with the item's SEC scale."""
    rules = load_companies().get("custom_tag", [])
    if not rules:
        return pd.DataFrame()
    concepts = sorted({f"custom:{t}" for r in rules for t in r["tags"]})
    x = frame(
        conn,
        "SELECT DISTINCT ON (c.symbol, f.concept, f.unit, f.period_start, f.period_end, f.accn) "
        "f.raw_id, f.fetch_id, c.symbol, f.concept, f.unit, "
        "to_char(f.period_start, 'YYYY-MM-DD') AS period_start, "
        "to_char(f.period_end, 'YYYY-MM-DD') AS period_end, f.value, f.form, "
        "to_char(f.filed, 'YYYY-MM-DD') AS filed, "
        "('x' || substr(md5(f.accn), 1, 16))::bit(64)::bigint AS accn "
        "FROM raw_sec_xbrl_fact f JOIN core_company c ON c.cik = f.cik "
        "WHERE f.custom AND f.axis = '' AND f.concept = ANY(:concepts) "
        "AND f.unit = ANY(:units) AND f.period_end >= :first "
        "ORDER BY c.symbol, f.concept, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        {"concepts": concepts, "units": list(SEC_UNITS), "first": SEC_FIRST_PERIOD},
    )
    if x.empty:
        return pd.DataFrame()
    out = []
    for r in rules:
        mine = x[
            (x["symbol"] == r["symbol"]) & x["concept"].isin([f"custom:{t}" for t in r["tags"]])
        ]
        if mine.empty:
            continue
        keys = ["symbol", "unit", "period_start", "period_end", "accn", "form", "filed"]
        g = mine.groupby(keys, dropna=False).agg(
            value=("value", "sum"), raw_id=("raw_id", "first"), fetch_id=("fetch_id", "max")
        ).reset_index()  # fmt: skip
        sec_scale = tags.loc[(tags["item"] == r["item"]) & (tags["taxonomy"] == "us-gaap"), "scale"]
        out.append(g.assign(
            item=r["item"], taxonomy="custom", tag=" + ".join(f"custom:{t}" for t in r["tags"]),
            priority=200, scale=float(sec_scale.iloc[0]) if len(sec_scale) else 1.0,
            raw_table="raw_sec_xbrl_fact",
        ))  # fmt: skip
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def class_facts(conn: Connection, tags: pd.DataFrame) -> pd.DataFrame:
    """The listed share class's facts from full filings (raw_sec_xbrl_fact), for the items
    read per class (sec_class in config/db_items.toml) and the companies with a listed class
    (config/companies.toml): Visa's diluted EPS is reported only per class, and the price is
    the Class A share's. Tried after the company's undimensioned tags (priority + 100)."""
    classes = {c["symbol"]: c["member"] for c in load_companies().get("share_class", [])}
    by_class = tags[tags["taxonomy"] == "sec_class"]
    if not classes or by_class.empty:
        return pd.DataFrame()
    x = frame(
        conn,
        "SELECT DISTINCT ON (c.symbol, f.concept, f.member, f.unit, f.period_start, "
        "f.period_end, f.accn) f.raw_id, f.fetch_id, c.symbol, f.concept, f.member, f.unit, "
        "to_char(f.period_start, 'YYYY-MM-DD') AS period_start, "
        "to_char(f.period_end, 'YYYY-MM-DD') AS period_end, f.value, f.form, "
        "to_char(f.filed, 'YYYY-MM-DD') AS filed, "
        "('x' || substr(md5(f.accn), 1, 16))::bit(64)::bigint AS accn "
        "FROM raw_sec_xbrl_fact f JOIN core_company c ON c.cik = f.cik "
        "WHERE c.symbol = ANY(:symbols) AND f.axis = :axis AND f.concept = ANY(:concepts) "
        "AND f.unit = ANY(:units) AND f.period_end >= :first "
        "ORDER BY c.symbol, f.concept, f.member, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        {"symbols": list(classes), "axis": CLASS_AXIS, "concepts": list(by_class["tag"]),
         "units": list(SEC_UNITS), "first": SEC_FIRST_PERIOD},
    )  # fmt: skip
    x = x[x["member"] == x["symbol"].map(classes)]
    if x.empty:
        return pd.DataFrame()
    x = x.merge(by_class.rename(columns={"tag": "concept"}), on="concept")
    return x.assign(
        taxonomy="sec_class",
        tag=x["concept"] + " [" + x["member"] + "]",
        priority=x["priority"] + 100,
        raw_table="raw_sec_xbrl_fact",
    ).drop(columns=["concept", "member", "taxonomy_y"], errors="ignore")


def candidates(
    conn: Connection, companies: dict[str, int], items: pd.DataFrame, tags: pd.DataFrame
) -> pd.DataFrame:
    """Every source value that maps to an item, with its period and filing date (estimated
    where the source has none)."""
    kind = items.set_index("item")["kind"]
    frames = []
    sec = sec_candidates(conn, kind, tags)
    if not sec.empty:
        frames.append(sec[sec["symbol"].isin(companies)])
    names = sorted(set(tags.loc[tags["taxonomy"] == "yahoo", "tag"]))
    yahoo = read_compact(
        conn,
        "SELECT raw_id, fetch_id, symbol, statement, frequency, "
        "to_char(period_end, 'YYYY-MM-DD') AS period_end, line_item, value "
        "FROM raw_yahoo_statement WHERE line_item = ANY(:names)",
        {"names": names},
        {"line_item": names},
    )
    if yahoo.empty:
        yahoo = pd.DataFrame(columns=["symbol", "line_item", "frequency"])
    yahoo = yahoo[yahoo["symbol"].isin(companies)].merge(
        tags[tags["taxonomy"] == "yahoo"], left_on="line_item", right_on="tag"
    )
    if not yahoo.empty:
        flow_type = np.where(yahoo["frequency"] == "annual", "FY", "Q")
        yahoo["period_type"] = np.where(yahoo["item"].map(kind) == "instant", "I", flow_type)
        frames.append(yahoo.assign(source="yahoo", raw_table="raw_yahoo_statement"))
    hist = frame(
        conn,
        "SELECT * FROM raw_project_history WHERE item = ANY(:names)",
        {"names": sorted(set(tags.loc[tags["taxonomy"] == "history", "tag"]))},
    )
    hist = hist[hist["symbol"].isin(companies)].merge(
        tags[tags["taxonomy"] == "history"], left_on="item", right_on="tag", suffixes=("_raw", "")
    )
    if not hist.empty:
        hist["period_type"] = np.where(hist["item"].map(kind) == "instant", "I", "FY")
        hist["period_end"] = hist["fiscal_year_end"]
        hist["source"] = "history:" + hist["source"].fillna("unknown")
        frames.append(hist.assign(raw_table="raw_project_history"))
    if not frames:
        return pd.DataFrame()
    c = pd.concat(frames, ignore_index=True)
    c["company_id"] = c["symbol"].map(companies)
    c["value"] = c["value"] * c["scale"]
    c["rank"] = c["source"].str.split(":").str[0].map(SOURCE_RANK)
    c["kind"] = c["item"].map(kind)
    c = add_periods(c)
    c["method"] = c["method"].fillna("reported") if "method" in c else "reported"
    cols = [*KEY, "kind", "filed", "filed_estimated", "fiscal_year", "fiscal_period", "value"]
    cols += ["source", "tag", "raw_table", "raw_id", "rank", "priority", "fetch_id", "method"]
    return c[cols]


def month_index(dates: pd.Series) -> pd.Series:
    """year * 12 + month of the nearest month end (Dec 28 and Jan 2 both count as December)."""
    d = pd.to_datetime(dates) - pd.Timedelta(days=15)
    return d.dt.year * 12 + d.dt.month - 1


def month_end_of(index: pd.Series) -> pd.Series:
    """The last day of the month numbered year * 12 + month - 1 (as month_index returns)."""
    first = pd.to_datetime({"year": index // 12, "month": index % 12 + 1, "day": 1})
    return first + pd.offsets.MonthEnd(0)


def add_periods(c: pd.DataFrame) -> pd.DataFrame:
    """Each period on its company's fiscal calendar: the fiscal year and quarter, a month-end
    period_end and the estimated filing date. period_end comes in as the source's real date.

    A quarter is placed by the days since the last fiscal year end (91.3 per quarter), not by
    its calendar month, because 52/53-week years have quarters of 12 to 17 weeks: Costco's
    third quarter ends around 10 May, Kroger's first after 16 weeks in late May. Its
    period_end is the month end of its slot in the fiscal calendar (fiscal year end + 3, 6, 9
    or 12 months), so every source's date for the same quarter gives one period. Fiscal years
    and other dates keep the nearest month end."""
    real = pd.to_datetime(c["period_end"])
    m = month_index(real)
    fy = c["period_type"] == "FY"
    if "form" in c:  # a twelve-month total in a 10-Q is a trailing year, not a fiscal year
        fy &= ~c["form"].fillna("").str.startswith("10-Q")
    fy = c[fy].assign(month=m % 12)
    fye = fy.groupby("company_id")["month"].agg(lambda s: s.mode().iloc[0])
    fye_month = c["company_id"].map(fye).fillna(11).astype(int)
    offset = (m % 12 - fye_month) % 12
    last_fye = m - offset  # month index of the fiscal year end at or before the date
    position = (real - month_end_of(last_fye)).dt.days / (365.25 / 4)
    slot = position.round()
    on_calendar = (position - slot).abs() <= QUARTER_SLACK
    quarter = (slot % 4).map({1: "Q1", 2: "Q2", 3: "Q3", 0: "Q4"}).where(on_calendar)
    snap = c["period_type"].isin(["Q", "I"]) & on_calendar
    m = m.where(~snap, last_fye + 3 * slot.astype(int))
    offset = (m % 12 - fye_month) % 12
    c["period_end"] = month_end_of(m).dt.strftime("%Y-%m-%d")
    c["fiscal_year"] = ((m + (12 - offset) % 12) // 12).astype(int)
    c["fiscal_period"] = np.where(c["period_type"] == "FY", "FY", quarter)
    # A twelve-month total that doesn't end in the fiscal year-end month (SEC filings show
    # trailing twelve months too) is not a fiscal year, and a quarter off the fiscal quarters
    # is not a quarter.
    off = ((c["period_type"] == "FY") & (offset != 0)) | (
        (c["period_type"] == "Q") & quarter.isna()
    )
    c, offset = c[~off].copy(), offset[~off]
    year_end = (c["period_type"] == "FY") | ((c["period_type"] == "I") & (offset == 0))
    lag = np.where(year_end, FILED_LAG_DAYS["year"], FILED_LAG_DAYS["quarter"])
    estimate = (pd.to_datetime(c["period_end"]) + pd.to_timedelta(lag, unit="D")).dt.strftime(
        "%Y-%m-%d"
    )
    known = c["filed"].notna() if "filed" in c else pd.Series(False, index=c.index)
    c["filed"] = c["filed"].where(known, estimate) if "filed" in c else estimate
    c["filed"] = c["filed"].astype(str).str[:10]
    c["filed_estimated"] = ~known
    return c


def choose(c: pd.DataFrame) -> pd.DataFrame:
    """Per period, the best source and field; all its versions (filing dates) are kept."""
    c = c.sort_values(["rank", "priority", "fetch_id"], ascending=[True, True, False])
    best = c.drop_duplicates(KEY)[[*KEY, "rank", "tag"]]
    c = c.merge(best, on=[*KEY, "rank", "tag"])
    return c.drop_duplicates([*KEY, "filed"]).reset_index(drop=True)


def latest(f: pd.DataFrame) -> pd.DataFrame:
    return f.sort_values("filed").drop_duplicates(KEY, keep="last")


def derive(f: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """Items computed from others ('a + b', 'a - b - c?'), wherever every part that isn't
    optional (?) exists; an optional part missing counts as 0. The derived value is as good as
    its worst part. With derive_mode "replace" it replaces a reported value from the same or a
    lower-ranked source (EBITDA: the parts are what we trust); with "fallback" only one from a
    lower-ranked source, so a value the company reports itself always wins (total
    liabilities). Never one from a better source: Yahoo's parts do not override history.csv's
    EBITDA."""
    for _, it in items[items["derive"].notna()].iterrows():
        terms = parse_derive(it["derive"])
        parts = [t[1] for t in terms]
        needed = [t[1] for t in terms if not t[2]]
        have = latest(f[f["item"].isin(parts)])
        idx = ["company_id", "period_type", "period_end"]
        wide = have.pivot_table(index=idx, columns="item", values="value", aggfunc="first")
        if not set(needed) <= set(wide.columns):
            continue
        wide = wide.reindex(columns=parts).dropna(subset=needed)
        if not needed:  # every part optional: at least one must be there
            wide = wide.dropna(how="all")
        if wide.empty:
            continue
        signs = pd.Series({t[1]: t[0] for t in terms})
        meta = have.groupby(idx).agg(
            filed=("filed", "max"),
            filed_estimated=("filed_estimated", "max"),
            fiscal_year=("fiscal_year", "first"),
            fiscal_period=("fiscal_period", "first"),
            source=("source", lambda s: s.iloc[0] if s.nunique() == 1 else "derived"),
            rank=("rank", "max"),  # as good as its worst part
        )
        total = (wide.fillna(0) * signs).sum(axis=1)
        d = total.rename("value").to_frame().join(meta).reset_index()
        d = d.assign(item=it["item"], kind=it["kind"], tag=it["derive"], method="derived")
        reported = f[f["item"] == it["item"]].groupby(KEY)["rank"].min().rename("reported_rank")
        d = d.merge(reported.reset_index(), on=KEY, how="left")
        if it.get("derive_mode") == "fallback":
            d = d[~(d["reported_rank"] <= d["rank"])]
        else:
            d = d[~(d["reported_rank"] < d["rank"])]
        d = d.drop(columns="reported_rank")
        drop = f.merge(d[KEY], on=KEY, how="left", indicator=True)["_merge"] == "both"
        f = pd.concat([f[~drop.to_numpy()], d], ignore_index=True)
    return f


def derive_q4(f: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """SEC filings have no fourth quarter (the 10-K reports the year): for flows, Q4 = the
    fiscal year less its first three quarters, in their latest versions, where all four are
    from SEC and Q4 is not reported. Not for EPS (shares differ between quarters)."""
    flows = set(items.loc[items["kind"] == "flow", "item"]) - {"eps_diluted"}
    have = latest(f[f["item"].isin(flows) & (f["source"] == "sec")])
    if have.empty:
        return f
    fy = have[have["period_type"] == "FY"]
    q = have[(have["period_type"] == "Q") & have["fiscal_period"].isin(["Q1", "Q2", "Q3"])]
    parts = q.groupby(["company_id", "item", "fiscal_year"]).agg(
        n=("value", "size"), total=("value", "sum")
    )
    d = fy.merge(parts.reset_index(), on=["company_id", "item", "fiscal_year"])
    d = d[d["n"] == 3]
    reported = f[(f["period_type"] == "Q") & (f["fiscal_period"] == "Q4")][
        ["company_id", "item", "period_end"]
    ].drop_duplicates()
    d = d.merge(reported, how="left", on=["company_id", "item", "period_end"], indicator=True)
    d = d[d["_merge"] == "left_only"]
    if d.empty:
        return f
    d = d.assign(
        value=d["value"] - d["total"],
        period_type="Q",
        fiscal_period="Q4",
        method="derived",
        tag="FY - Q1 - Q2 - Q3",
        raw_table=None,
        raw_id=None,
    )
    return pd.concat([f, d[f.columns.intersection(d.columns)]], ignore_index=True)


def add_split_factor(f: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Shares and per-share values filed before a split, on today's (split-adjusted) basis.
    history.csv is already adjusted."""
    f = f.reset_index(drop=True)
    f["split_factor"] = 1.0
    todo = f["item"].isin(list(SPLIT_ITEMS)) & ~f["source"].str.startswith("history")
    if todo.any() and not splits.empty:
        rows = f.loc[todo, ["company_id", "filed"]].reset_index()
        pairs = rows.merge(splits, on="company_id")
        pairs = pairs[pairs["date"] > pairs["filed"]]
        factor = pairs.groupby("index")["ratio"].prod()
        f.loc[factor.index, "split_factor"] = factor.astype(float)
    how = f["item"].map(SPLIT_ITEMS)
    f["value_adj"] = np.where(
        how == "multiply",
        f["value"] * f["split_factor"],
        np.where(how == "divide", f["value"] / f["split_factor"], f["value"]),
    )
    return f


def build_fundamentals(conn, companies, items, tags, splits) -> tuple[pd.DataFrame, pd.DataFrame]:
    c = candidates(conn, companies, items, tags)
    if c.empty:
        return c, c
    f = choose(c)
    f["method"] = f["method"].fillna("reported") if "method" in f else "reported"
    f = derive(derive_q4(f, items), items)
    helpers = set(items.loc[items["helper"], "item"])
    f, c = f[~f["item"].isin(helpers)], c[~c["item"].isin(helpers)]
    f = add_split_factor(f, splits)
    cols = [*KEY, "filed", "filed_estimated", "fiscal_year", "fiscal_period", "value"]
    cols += ["split_factor", "method", "source", "tag", "raw_table", "raw_id"]
    out = f[cols].copy()
    for col in ("fiscal_year", "raw_id"):
        out[col] = out[col].astype("Int64")
    out["filed_estimated"] = out["filed_estimated"].astype(bool)
    # One row per key and filing date, a reported value before a derived one.
    key = [*KEY, "filed"]
    out = out.sort_values("method", key=lambda m: m.eq("derived")).drop_duplicates(key)
    f = f.loc[out.index]
    insert_df(conn, "core_fundamental", out)
    return f, c


def build_ttm(conn: Connection, f: pd.DataFrame) -> pd.DataFrame:
    """Trailing twelve months for every version: as known on each filing date."""
    if f.empty:
        return f
    base = ["company_id", "item", "period_end", "filed", "filed_estimated", "value", "value_adj"]
    inst = f[f["period_type"] == "I"][base + ["source"]].assign(basis="instant")
    fy = f[f["period_type"] == "FY"][base + ["source"]].assign(basis="fy")
    sums = []
    for (cid, item), g in f[f["period_type"] == "Q"].groupby(["company_id", "item"]):
        versions = {e: v.sort_values("filed") for e, v in g.groupby("period_end")}
        ends = sorted(versions)
        for i in range(3, len(ends)):
            window = ends[i - 3 : i + 1]
            span = (pd.Timestamp(window[-1]) - pd.Timestamp(window[0])).days
            if not 250 <= span <= 300:  # four consecutive quarters
                continue
            first_known = max(versions[e]["filed"].iloc[0] for e in window)
            dates = sorted({d for e in window for d in versions[e]["filed"] if d >= first_known})
            for day in dates:
                used = [versions[e][versions[e]["filed"] <= day].iloc[-1] for e in window]
                sums.append(
                    {
                        "company_id": cid,
                        "item": item,
                        "period_end": window[-1],
                        "filed": day,
                        "filed_estimated": any(bool(u["filed_estimated"]) for u in used),
                        "value": sum(u["value"] for u in used),
                        "value_adj": sum(u["value_adj"] for u in used),
                        "source": used[-1]["source"],
                        "basis": "4q",
                    }
                )
    q = pd.DataFrame(sums)
    if not q.empty and not fy.empty:  # at a fiscal year end the fiscal-year value is used
        has_fy = q.merge(
            fy[["company_id", "item", "period_end"]].drop_duplicates(),
            how="left",
            on=["company_id", "item", "period_end"],
            indicator=True,
        )
        q = q[(has_fy["_merge"] == "left_only").to_numpy()]
    ttm = pd.concat([inst, fy, q], ignore_index=True)
    ttm = ttm.drop_duplicates(["company_id", "item", "period_end", "filed"])
    ttm["filed_estimated"] = ttm["filed_estimated"].astype(bool)
    cols = ["company_id", "item", "period_end", "filed", "filed_estimated", "basis", "value"]
    insert_df(conn, "core_fundamental_ttm", ttm[cols + ["value_adj", "source"]])
    return ttm


# ---------------------------------------------------------------- quality checks


def quality_checks(prices: pd.DataFrame, f: pd.DataFrame, c: pd.DataFrame) -> list[tuple]:
    """(company_id, item, at_date, check_name, severity, detail) for each problem found."""
    issues: list[tuple] = []
    if not f.empty:
        f = latest(f)
        bs = f[f["period_type"] == "I"].pivot_table(
            index=["company_id", "period_end"], columns="item", values="value", aggfunc="first"
        )
        need = ["total_assets", "total_liabilities", "equity"]
        if set(need) <= set(bs.columns):
            bs = bs.dropna(subset=need)
            share = (bs["total_assets"] - bs["total_liabilities"] - bs["equity"]) / bs[
                "total_assets"
            ]
            for (cid, end), s in share[share.abs() > 0.02].items():
                issues.append(
                    (cid, "total_assets", end, "balance_sheet_identity", "warn",
                     f"assets - liabilities - equity = {s:.1%} of assets "
                     "(minority interest is a usual cause)")
                )  # fmt: skip
        limit = {"Q": 100, "FY": 380}
        for (cid, item, ptype), g in f[f["period_type"].isin(list(limit))].groupby(
            ["company_id", "item", "period_type"]
        ):
            ends = pd.to_datetime(g["period_end"]).sort_values()
            for a, b in zip(ends.iloc[:-1], ends.iloc[1:], strict=True):
                if (b - a).days > limit[ptype]:
                    issues.append(
                        (cid, item, f"{b:%Y-%m-%d}", "missing_period", "warn",
                         f"{ptype} gap of {(b - a).days} days since {a:%Y-%m-%d}")
                    )  # fmt: skip
        for (cid, item, _), g in f.groupby(["company_id", "item", "period_type"]):
            g = g.sort_values("period_end")
            v = g["value"].to_numpy()
            for i in range(1, len(v)):
                if v[i - 1] and v[i] and not 0.1 <= abs(v[i] / v[i - 1]) <= 10:
                    issues.append(
                        (cid, item, g["period_end"].iloc[i], "jump_10x", "warn",
                         f"{v[i - 1]:.4g} to {v[i]:.4g}")
                    )  # fmt: skip
        # Shares implied by net income / EPS should move slowly; a jump of 1.8x or more from
        # one year to the next is usually a share split that EPS was not adjusted for.
        fy = f[f["period_type"] == "FY"]
        ni = fy[fy["item"] == "net_income"].set_index(["company_id", "period_end"])["value"]
        eps = fy[fy["item"] == "eps_diluted"].set_index(["company_id", "period_end"])["value_adj"]
        implied = (ni / eps[eps != 0]).dropna().sort_index()
        for cid, s in implied.groupby(level=0):
            s = s.droplevel(0)
            ratio = (s / s.shift(1)).abs()
            for end, r in ratio[(ratio >= 1.8) | (ratio <= 1 / 1.8)].items():
                issues.append(
                    (cid, "eps_diluted", end, "implied_shares_jump", "warn",
                     f"net income / EPS moved {r:.2f}x from the year before: "
                     "a share split not applied to EPS?")
                )  # fmt: skip
    if not c.empty:
        # The best filed source (SEC, else history.csv), latest version, against Yahoo.
        ref = c[c["rank"] < SOURCE_RANK["yahoo"]].sort_values(
            ["rank", "priority", "filed"], ascending=[True, True, False]
        )
        yahoo = c[c["source"] == "yahoo"].sort_values(["priority", "fetch_id"])
        both = ref.drop_duplicates(KEY).merge(
            yahoo.drop_duplicates(KEY), on=KEY, suffixes=("_h", "_y")
        )
        both = both[both["value_h"] != 0]
        diff = (both["value_y"] - both["value_h"]).abs() / both["value_h"].abs()
        for _, r in both[diff > 0.02].iterrows():
            issues.append(
                (r["company_id"], r["item"], r["period_end"], "sources_disagree", "info",
                 f"{r['source_h']} {r['value_h']:.4g} vs Yahoo {r['value_y']:.4g}")
            )  # fmt: skip
    if len(prices):
        p = prices.sort_values(["company_id", "date"])
        change = p.groupby("company_id")["close"].pct_change()
        jump = (change.abs() > 0.5) & p["split_ratio"].isna()
        for _, r in p[jump].iterrows():
            issues.append(
                (r["company_id"], None, r["date"], "price_jump", "warn",
                 f"close moved {change[r.name]:+.0%} in a day with no split")
            )  # fmt: skip
    if len(prices):
        p = prices.assign(year=prices["date"].str[:4].astype(int))
        for cid, g in p.groupby("company_id"):
            counts = g.groupby("year").size()
            for year in range(counts.index.min() + 1, counts.index.max()):
                if (n := int(counts.get(year, 0))) < 200:
                    issues.append(
                        (cid, None, f"{year}-12-31", "short_trading_year", "warn",
                         f"{n} trading days in {year}")
                    )  # fmt: skip
    return issues


# ---------------------------------------------------------------- the build


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def build(db: Database, items_config: Path = ITEMS_CONFIG) -> dict:
    """Rebuild core from raw in one transaction. Returns the summary stored in core_build."""
    started = now()
    try:
        with db.begin() as conn:
            build_id = scalar(
                conn,
                "INSERT INTO core_build (started_at, git_sha, max_fetch_id, status) VALUES "
                "(:t, :sha, (SELECT MAX(fetch_id) FROM raw_fetch), 'running') RETURNING build_id",
                {"t": started, "sha": git_sha()},
            )
            for table in (
                "core_fundamental_ttm",
                "core_fundamental",
                "core_price_daily",
                "core_index_member",
                "core_item_tag",
                "core_item",
            ):
                run(conn, f"DELETE FROM {table}")
            items, tags = load_items(items_config)
            for table, df in zip(("core_item", "core_item_tag"), stored(items, tags), strict=True):
                insert_df(conn, table, df)
            companies = build_companies(conn)
            prices = build_prices(conn, companies)
            f, c = build_fundamentals(conn, companies, items, tags, all_splits(conn, companies))
            ttm = build_ttm(conn, f)
            issues = quality_checks(prices, f, c)
            cols = ["company_id", "item", "at_date", "check_name", "severity", "detail"]
            found = pd.DataFrame([[plain(x) for x in i] for i in issues], columns=cols)
            insert_df(conn, "core_quality_issue", found.assign(build_id=build_id))
            summary = {
                "companies": len(companies),
                "sp500_members_now": scalar(
                    conn, "SELECT COUNT(*) FROM core_index_member WHERE end_date IS NULL"
                ),
                "companies_with_prices": int(prices["company_id"].nunique()),
                "core_price_daily": len(prices),
                "core_fundamental": len(f),
                "companies_with_fundamentals": int(f["company_id"].nunique()) if len(f) else 0,
                "core_fundamental_ttm": len(ttm),
                "quality_issues": len(issues),
            }
            run(
                conn,
                "UPDATE core_build SET finished_at = :t, status = 'ok', summary = :s "
                "WHERE build_id = :id",
                {"t": now(), "s": json.dumps(summary), "id": build_id},
            )
        return {"build_id": build_id, **summary}
    except Exception as exc:
        with db.begin() as conn:
            run(
                conn,
                "INSERT INTO core_build (started_at, finished_at, git_sha, status, summary) "
                "VALUES (:s, :f, :sha, 'failed', :summary)",
                {
                    "s": started,
                    "f": now(),
                    "sha": git_sha(),
                    "summary": json.dumps({"error": repr(exc)}),
                },
            )
        raise
