"""Rebuild the core layer from the raw layer (docs/DATABASE.md, "Build rules").

The build reads only raw_* tables, config/db_items.toml and config/companies.toml (predecessor
CIKs). In one transaction it rewrites core_item, core_item_tag, core_index_member,
core_price_daily, core_fundamental and core_fundamental_ttm, updates core_company in place (so
company_id stays the same), and adds a core_build row with that build's core_quality_issue
rows.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import subprocess
import time
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import ROOT, Database, frame, insert_df, records, run, scalar
from .raw import UNIVERSE, now

ITEMS_CONFIG = ROOT / "config" / "db_items.toml"
COMPANIES_CONFIG = ROOT / "config" / "companies.toml"
MARKET_CONFIG = ROOT / "config" / "market.toml"
WATCHLIST_KEY = "watchlist"  # TradingView snapshot of the watch list's own symbols


def load_companies(path: Path = COMPANIES_CONFIG) -> dict:
    """config/companies.toml: predecessor CIKs and formation dates."""
    if not Path(path).exists():
        return {}
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


FIRST_DATE = "2016-01-01"
SOURCE_RANK = {"sec": 1, "history": 2, "yahoo": 3}
# No source loaded so far records filing dates: estimate them as the latest SEC deadline.
FILED_LAG_DAYS = {"year": 90, "quarter": 45}
SPLIT_ITEMS = {"shares_outstanding": "multiply", "eps_diluted": "divide",
               "eps_continuing": "divide"}  # fmt: skip
KEY = ["company_id", "item", "period_type", "period_end"]

# The companies the running build rebuilds (symbols); None while a full build runs. Every
# raw read below adds scoped(...) to its WHERE and with_scope(...) to its parameters, so an
# incremental build reads only those companies' rows. Every step works company by company,
# so a company's core rows don't depend on the others.
_SCOPE: list[str] | None = None


def scoped(column: str) -> str:
    return "" if _SCOPE is None else f" AND {column} = ANY(:scope)"


def with_scope(params: dict) -> dict:
    return params if _SCOPE is None else {**params, "scope": _SCOPE}


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
    """Every company of the index snapshots and of the watch list's own snapshots (the watch
    list's stocks and peers outside the index); membership comes from the index's alone."""
    tv = frame(
        conn,
        "SELECT c.*, f.fetched_at, f.request_key FROM raw_tv_constituent c JOIN raw_fetch f "
        "ON f.fetch_id = c.fetch_id WHERE f.source = 'tradingview' "
        "AND f.request_key IN (:u, :w)",
        {"u": UNIVERSE, "w": WATCHLIST_KEY},
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
    if not tv.empty:
        tv = tv[tv["request_key"] == UNIVERSE]
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
        "dividends, stock_splits FROM raw_yahoo_price WHERE date >= :start"
        f"{scoped('symbol')} ORDER BY symbol, date, fetch_id DESC",
        with_scope({"start": (pd.Timestamp(FIRST_DATE) - pd.Timedelta(days=10)).strftime("%F")}),
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


def market_symbols(path: Path | None = None) -> list[str]:
    path = path or MARKET_CONFIG
    if not Path(path).exists():
        return []
    cfg = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    return sorted({s for group in cfg.values() for s in group})


def build_market_prices(conn: Connection, symbols: list[str]) -> int:
    """The market instruments' closes (config/market.toml), the latest version of each day."""
    if not symbols:
        return 0
    m = frame(
        conn,
        "SELECT DISTINCT ON (symbol, date) symbol, date, close FROM raw_yahoo_price "
        "WHERE symbol = ANY(:s) AND date >= :start AND close IS NOT NULL "
        "ORDER BY symbol, date, fetch_id DESC",
        {"s": symbols, "start": FIRST_DATE},
    )
    return insert_df(conn, "core_market_daily", m)


def all_splits(conn: Connection, companies: dict[str, int]) -> pd.DataFrame:
    s = frame(
        conn,
        "SELECT DISTINCT symbol, date, stock_splits AS ratio FROM raw_yahoo_price "
        f"WHERE stock_splits > 0{scoped('symbol')}",
        with_scope({}),
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


def as_of(rows: pd.DataFrame, group: list[str], part: str) -> pd.DataFrame:
    """A combination of parts as it was known over time: for each group (a period, a fiscal
    year) and each date one of its parts was filed, the latest version of every part filed by
    then, with that date as `asof`. A value computed from them is known on the day its last
    part was filed; taking each part's latest version instead dates it by whichever later report
    repeated a part (next year's 10-Q or 10-K), up to two years late (#49)."""
    dates = rows[[*group, "filed"]].drop_duplicates().rename(columns={"filed": "asof"})
    x = rows.merge(dates, on=group)
    x = x[x["filed"] <= x["asof"]]
    return x.sort_values("filed", kind="stable").drop_duplicates([*group, "asof", part],
                                                                 keep="last")  # fmt: skip


def before_reported(d: pd.DataFrame, reported: pd.DataFrame, on: list[str]) -> pd.DataFrame:
    """Derived versions (d) filed before the period's first reported version: JNJ's 2023 10-K
    reports 2022's quarters (restated for Kenvue), but its fourth quarter was known, as the
    year less three quarters, from the 2022 10-K on."""
    first = reported.groupby(on)["filed"].min().rename("reported_from").reset_index()
    d = d.merge(first, on=on, how="left")
    return d[d["reported_from"].isna() | (d["filed"] < d["reported_from"])].drop(
        columns="reported_from"
    )


def drop_repeats(d: pd.DataFrame, value: str = "value") -> pd.DataFrame:
    """Versions of a computed value without those equal to the version before (a later report
    repeating its parts adds nothing)."""
    d = d.sort_values([*KEY, "filed"])
    return d[~d.groupby(KEY)[value].shift().eq(d[value])]


def sec_quarters_from_ytd(sec: pd.DataFrame) -> pd.DataFrame:
    """10-Q cash flows are year to date (3, 6 and 9 months): the second quarter is the six
    months less the first quarter, the third the nine months less the six, both from the same
    start date, in every version as known on each filing date (as_of). Only until SEC reports
    the quarter itself (before_reported)."""
    cols = ["symbol", "taxonomy", "tag", "unit"]
    ends = [*cols, "period_start", "period_end"]
    group = [*ends, "short_end"]
    q, h, n = (sec[sec["span"] == x] for x in ("Q", "H", "N"))
    out = []
    for longer, shorter in ((h, q), (n, h)):
        shorter = shorter.rename(columns={"period_end": "short_end"})
        pairs = (
            longer[ends]
            .drop_duplicates()
            .merge(
                shorter[[*cols, "period_start", "short_end"]].drop_duplicates(),
                on=[*cols, "period_start"],
            )
        )
        pairs = pairs[pairs["short_end"] < pairs["period_end"]]
        if pairs.empty:
            continue
        parts = pd.concat(
            [longer.merge(pairs, on=ends).assign(part="long"),
             shorter.merge(pairs, on=[*cols, "period_start", "short_end"]).assign(part="short")],
            ignore_index=True,
        )  # fmt: skip
        x = as_of(parts, group, "part")
        short = x.loc[x["part"] == "short", [*group, "asof", "value"]]
        m = x[x["part"] == "long"].merge(short, on=[*group, "asof"], suffixes=("", "_s"))
        start = (pd.to_datetime(m["short_end"]) + pd.Timedelta(days=1)).dt.strftime("%F")
        out.append(m.assign(value=m["value"] - m["value_s"], period_start=start, span="Q",
                            filed=m["asof"], method="derived")[sec.columns])  # fmt: skip
    if not out:
        return sec.iloc[0:0]
    return before_reported(pd.concat(out, ignore_index=True), q, [*cols, "period_end"])


RELEASE_LEAD_DAYS = 60  # an earnings release at most this long before its 10-Q / 10-K


def release_dates(conn: Connection) -> pd.DataFrame:
    """Yahoo's earnings report dates (symbol, report_date) that have a reported EPS."""
    return frame(
        conn,
        "SELECT symbol, to_char(report_date, 'YYYY-MM-DD') AS report_date FROM v_earnings "
        f"WHERE eps_reported IS NOT NULL{scoped('symbol')}",
        with_scope({}),
    )


def date_by_release(sec: pd.DataFrame, releases: pd.DataFrame) -> pd.DataFrame:
    """A 10-Q's or 10-K's figures for its own period count from the company's earnings press
    release, which announces them one to four weeks before the filing (#49; data providers date
    them so): `filed` becomes the period's release (the first after the period ended) when it
    came before the filing and at most RELEASE_LEAD_DAYS before it. The filing's comparatives
    (last year's quarter, the year-end balance sheet in a 10-Q) had their release long before
    and keep their date, as do amendments."""
    if releases.empty or sec.empty:
        return sec
    own = sec["form"].isin(["10-Q", "10-K"])
    keys = sec.loc[own, ["symbol", "period_end", "filed"]].drop_duplicates()
    keys = keys.assign(at=pd.to_datetime(keys["period_end"]),
                       by=keys["symbol"].astype(object)).sort_values("at")  # fmt: skip
    rel = releases.assign(at=pd.to_datetime(releases["report_date"]),
                          by=releases["symbol"].astype(object)).sort_values("at")  # fmt: skip
    m = pd.merge_asof(keys, rel[["by", "at", "report_date"]], on="at", by="by",
                      direction="forward", allow_exact_matches=False)  # fmt: skip
    r, filed = pd.to_datetime(m["report_date"]), pd.to_datetime(m["filed"])
    ok = (r < filed) & ((filed - r).dt.days <= RELEASE_LEAD_DAYS)
    m = m[ok.fillna(False)][["symbol", "period_end", "filed", "report_date"]]
    if m.empty:
        return sec
    sec = sec.merge(m, on=["symbol", "period_end", "filed"], how="left")
    shift = own.to_numpy() & sec["report_date"].notna().to_numpy()
    sec.loc[shift, "filed"] = sec.loc[shift, "report_date"]
    return sec.drop(columns="report_date")


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
        f"AND (c.until IS NULL OR f.period_end < c.until){scoped('c.symbol')} "
        "ORDER BY c.symbol, f.taxonomy, f.tag, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        with_scope({"first": SEC_FIRST_PERIOD}),
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
        f"AND (c.until IS NULL OR f.period_end < c.until){scoped('c.symbol')} "
        "ORDER BY c.symbol, f.concept, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        with_scope({"concepts": concepts, "first": SEC_FIRST_PERIOD}),
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
    # the filing's own date fixes the share basis of its per-share figures and share counts,
    # even when they count from the earlier release: Walmart released FY2024 before its 3:1
    # split of 2024-02-26 and filed it, on the new basis, after (add_split_factor)
    sec["split_basis"] = sec["filed"]
    # A fact filed before its own period ended is an error in the company's XBRL (AES's 10-Q
    # for June 2025 carries a "nine months to September" value): it is left out.
    sec = sec[sec["filed"] >= sec["period_end"]]
    sec = date_by_release(sec, release_dates(conn))
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
        f"AND f.unit = ANY(:units) AND f.period_end >= :first{scoped('c.symbol')} "
        "ORDER BY c.symbol, f.concept, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        with_scope({"concepts": concepts, "units": list(SEC_UNITS), "first": SEC_FIRST_PERIOD}),
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
    entries = load_companies().get("share_class", [])
    classes = {c["symbol"]: c["member"] for c in entries}
    by_class = tags[tags["taxonomy"] == "sec_class"]
    if not classes or by_class.empty:
        return pd.DataFrame()
    # Which concept gives which item, per company: the items' sec_class tags, or the tags an
    # entry names for an item (`tags`, the concept that company files it under).
    allowed = []
    for c in entries:
        own = c.get("tags", {})
        for item, rows in by_class.groupby("item"):
            if item in own:
                for i, concept in enumerate(own[item]):
                    allowed.append((c["symbol"], concept, item, int(rows["priority"].min()) + i,
                                    float(rows["scale"].iloc[0])))  # fmt: skip
            else:
                allowed += [
                    (c["symbol"], r.tag, item, r.priority, r.scale) for r in rows.itertuples()
                ]
    allowed = pd.DataFrame(allowed, columns=["symbol", "concept", "item", "priority", "scale"])
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
        f"AND f.unit = ANY(:units) AND f.period_end >= :first{scoped('c.symbol')} "
        "ORDER BY c.symbol, f.concept, f.member, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        with_scope({"symbols": list(classes), "axis": CLASS_AXIS,
                    "concepts": list(set(allowed["concept"])), "units": list(SEC_UNITS),
                    "first": SEC_FIRST_PERIOD}),
    )  # fmt: skip
    x = x[x["member"] == x["symbol"].map(classes)]
    x = x.merge(allowed, on=["symbol", "concept"])
    conv = converted_facts(conn, entries, tags)
    x = pd.concat([d for d in (x, conv) if not d.empty], ignore_index=True) if len(conv) else x
    if x.empty:
        return pd.DataFrame()
    return x.assign(
        taxonomy="sec_class",
        tag=x["concept"] + " [" + x["member"] + "]",
        priority=x["priority"] + 100,
        raw_table="raw_sec_xbrl_fact",
    ).drop(columns=["concept", "member", "taxonomy_y"], errors="ignore")


def local_name(member: pd.Series) -> pd.Series:
    """'brka:EquivalentClassAMember' -> 'EquivalentClassAMember' (the data sets don't keep a
    member's prefix, edgartools does)."""
    return member.astype(str).str.split(":").str[-1]


def converted_facts(conn: Connection, entries: list[dict], tags: pd.DataFrame) -> pd.DataFrame:
    """[[share_class]] `convert`: an item the company reports only in another class's units,
    multiplied by the fixed conversion ratio of its charter. Berkshire states its shares
    outstanding in equivalent Class A shares; one A share converts into 1,500 B shares, so the
    count in BRK.B's units is 1,500 times the reported one. Nothing is estimated."""
    rules = [(c["symbol"], r) for c in entries for r in c.get("convert", [])]
    if not rules:
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
        f"AND f.unit = ANY(:units) AND f.period_end >= :first{scoped('c.symbol')} "
        "ORDER BY c.symbol, f.concept, f.member, f.unit, f.period_start, f.period_end, f.accn, "
        "f.fetch_id DESC",
        with_scope({"symbols": sorted({s for s, _ in rules}), "axis": CLASS_AXIS,
                    "concepts": sorted({r["concept"] for _, r in rules}), "units": list(SEC_UNITS),
                    "first": SEC_FIRST_PERIOD}),
    )  # fmt: skip
    if x.empty:
        return pd.DataFrame()
    out = []
    for symbol, r in rules:
        item_tags = tags[(tags["item"] == r["item"]) & (tags["taxonomy"] != "yahoo")]
        priority = int(item_tags["priority"].min()) if len(item_tags) else 0
        member = r["member"].split(":")[-1]
        hit = x[(x["symbol"] == symbol) & (x["concept"] == r["concept"])
                & (local_name(x["member"]) == member)]  # fmt: skip
        if hit.empty:
            continue
        out.append(hit.assign(
            value=hit["value"] * float(r["factor"]), item=r["item"], priority=priority,
            scale=1.0, member=hit["member"] + f" x {r['factor']:g}",
        ))  # fmt: skip
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def yahoo_excluded(entries: list[dict]) -> set[tuple[str, str]]:
    """(symbol, item) pairs whose Yahoo values are in another class's units
    ([[share_class]] `not_from_yahoo`): Yahoo gives BRK.B's shares in Class A units."""
    return {(c["symbol"], item) for c in entries for item in c.get("not_from_yahoo", [])}


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
        f"FROM raw_yahoo_statement WHERE line_item = ANY(:names){scoped('symbol')}",
        with_scope({"names": names}),
        {"line_item": names},
    )
    if yahoo.empty:
        yahoo = pd.DataFrame(columns=["symbol", "line_item", "frequency"])
    yahoo = yahoo[yahoo["symbol"].isin(companies)].merge(
        tags[tags["taxonomy"] == "yahoo"], left_on="line_item", right_on="tag"
    )
    wrong_units = yahoo_excluded(load_companies().get("share_class", []))
    if wrong_units and not yahoo.empty:
        pairs = pd.Series(list(zip(yahoo["symbol"], yahoo["item"], strict=True)), index=yahoo.index)
        yahoo = yahoo[~pairs.isin(wrong_units)]
    if not yahoo.empty:
        flow_type = np.where(yahoo["frequency"] == "annual", "FY", "Q")
        yahoo["period_type"] = np.where(yahoo["item"].map(kind) == "instant", "I", flow_type)
        frames.append(yahoo.assign(source="yahoo", raw_table="raw_yahoo_statement"))
    hist = frame(
        conn,
        f"SELECT * FROM raw_project_history WHERE item = ANY(:names){scoped('symbol')}",
        with_scope({"names": sorted(set(tags.loc[tags["taxonomy"] == "history", "tag"]))}),
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
    if "split_basis" not in c:
        c["split_basis"] = np.nan
    return c[[*cols, "split_basis"]]


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
    # never known before the stored period end: a 52/53-week quarter (AutoZone's ends in early
    # May) is stored at its slot's month end (May 31), after its earnings release (May 21)
    c["filed"] = c["filed"].where(c["filed"] >= c["period_end"], c["period_end"])
    c["filed_estimated"] = ~known
    return c


def choose(c: pd.DataFrame) -> pd.DataFrame:
    """Per period, the best source and field; all its versions (filing dates) are kept. Before
    the best field's first version, the best other field of that source filed by then: Alphabet
    filed 2018 revenue as RevenueFromContractWithCustomer... in 2019 and as Revenues only in
    2021, and the year is known from 2019 (#49)."""
    c = c.sort_values(["rank", "priority", "fetch_id"], ascending=[True, True, False])
    best = c.drop_duplicates(KEY)[[*KEY, "rank", "tag"]]
    chosen = c.merge(best, on=[*KEY, "rank", "tag"])
    first = chosen.groupby(KEY)["filed"].min().rename("first_filed").reset_index()
    early = c.merge(best[[*KEY, "rank"]], on=[*KEY, "rank"]).merge(first, on=KEY)
    early = early[early["filed"] < early["first_filed"]].drop(columns="first_filed")
    out = pd.concat([chosen, early], ignore_index=True)  # in rank, priority order
    return out.drop_duplicates([*KEY, "filed"]).reset_index(drop=True)


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
        have = f[f["item"].isin(parts)]
        idx = ["company_id", "period_type", "period_end"]
        x = as_of(have, idx, "item")  # every version, as known on each filing date
        wide = x.pivot_table(index=[*idx, "asof"], columns="item", values="value",
                             aggfunc="first")  # fmt: skip
        if not set(needed) <= set(wide.columns):
            continue
        wide = wide.reindex(columns=parts).dropna(subset=needed)
        if not needed:  # every part optional: at least one must be there
            wide = wide.dropna(how="all")
        if wide.empty:
            continue
        signs = pd.Series({t[1]: t[0] for t in terms})
        g = x.groupby([*idx, "asof"])
        meta = g.agg(
            filed_estimated=("filed_estimated", "max"),
            fiscal_year=("fiscal_year", "first"),
            fiscal_period=("fiscal_period", "first"),
        )
        sources = g["source"].agg(["first", "nunique"])
        meta["source"] = sources["first"].where(sources["nunique"] == 1, "derived")
        if "split_basis" in x:  # the share basis of the latest part (add_split_factor)
            meta["split_basis"] = g["split_basis"].max()
        total = (wide.fillna(0) * signs).sum(axis=1)
        d = total.rename("value").to_frame().join(meta).reset_index()
        rank = have.groupby(idx)["rank"].max().rename("rank")  # as good as its worst part
        d = d.merge(rank.reset_index(), on=idx).rename(columns={"asof": "filed"})
        d = d.assign(item=it["item"], kind=it["kind"], tag=it["derive"], method="derived")
        d = drop_repeats(d)
        rep = f[f["item"] == it["item"]]
        if it.get("derive_mode") == "fallback":
            # A value reported by a source as good or better always wins; the derived one only
            # fills the period until that is first filed (as Q4 until a 10-K reports it), and
            # replaces only a value from a lower-ranked source.
            d_rank = d[[*KEY, "rank"]].drop_duplicates(KEY).rename(columns={"rank": "rank_d"})
            pair = rep[[*KEY, "rank", "filed"]].merge(d_rank, on=KEY)
            d = before_reported(d, pair[pair["rank"] <= pair["rank_d"]], KEY)
            d_rank = d[[*KEY, "rank"]].drop_duplicates(KEY).rename(columns={"rank": "rank_d"})
            m = f[KEY + ["rank"]].merge(d_rank, on=KEY, how="left")
            drop = (m["rank_d"].notna() & (m["rank"] > m["rank_d"])).to_numpy()
        else:
            reported = rep.groupby(KEY)["rank"].min().rename("reported_rank")
            d = d.merge(reported.reset_index(), on=KEY, how="left")
            d = d[~(d["reported_rank"] < d["rank"])].drop(columns="reported_rank")
            drop = f.merge(d[KEY].drop_duplicates(), on=KEY, how="left", indicator=True)
            drop = (drop["_merge"] == "both").to_numpy()
        f = pd.concat([f[~drop], d], ignore_index=True)
    return f


def fourth_quarters(f: pd.DataFrame, have: pd.DataFrame, value: str = "value") -> pd.DataFrame:
    """Q4 = the fiscal year less its first three quarters, from SEC rows (`have`), until f has
    a reported Q4 (before_reported). Every version as known on each filing date (as_of): Q4 is
    known when the 10-K is filed, not when the next 10-K repeats the year."""
    have = have[(have["period_type"] == "FY") | have["fiscal_period"].isin(["Q1", "Q2", "Q3"])]
    group = ["company_id", "item", "fiscal_year"]
    x = as_of(have, group, "fiscal_period")
    fy, q = x[x["fiscal_period"] == "FY"], x[x["fiscal_period"] != "FY"]
    agg = {"n": (value, "size"), "total": (value, "sum")}
    if "filed_estimated" in q:
        agg["parts_estimated"] = ("filed_estimated", "max")
    d = fy.merge(q.groupby([*group, "asof"]).agg(**agg).reset_index(), on=[*group, "asof"])
    d = d[d["n"] == 3]
    d = d.assign(
        **{value: d[value] - d["total"]},
        filed=d["asof"],
        period_type="Q",
        fiscal_period="Q4",
        method="derived",
        tag="FY - Q1 - Q2 - Q3",
        raw_table=None,
        raw_id=None,
    )
    if "parts_estimated" in d:
        d["filed_estimated"] = d["filed_estimated"].astype(bool) | d["parts_estimated"].astype(bool)
    reported = f[(f["period_type"] == "Q") & (f["fiscal_period"] == "Q4")]
    return drop_repeats(before_reported(d, reported, ["company_id", "item", "period_end"]), value)


def derive_q4(f: pd.DataFrame, items: pd.DataFrame) -> pd.DataFrame:
    """SEC filings have no fourth quarter (the 10-K reports the year): for flows, Q4 = the
    fiscal year less its first three quarters, where all four are from SEC, until a Q4 is
    reported. Per-share values come later, on today's share basis (derive_q4_per_share)."""
    flows = set(items.loc[items["kind"] == "flow", "item"]) - set(SPLIT_ITEMS)
    have = f[f["item"].isin(flows) & (f["source"] == "sec")]
    if have.empty:
        return f
    d = fourth_quarters(f, have)
    if d.empty:
        return f
    return pd.concat([f, d[f.columns.intersection(d.columns)]], ignore_index=True)


def derive_q4_per_share(f: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Q4 diluted EPS = the fiscal year's less its first three quarters' (how data providers
    build twelve-month EPS; the four quarters then add up to the year), on today's share basis:
    a split during the year leaves Q1 in old shares and the 10-K in new ones. Without it a
    twelve-month EPS exists only at fiscal year ends (#49). Runs after add_split_factor; the
    derived value as filed is put back on its filing date's basis. For every per-share item
    (diluted EPS, EPS from continuing operations)."""
    per_share = [k for k, how in SPLIT_ITEMS.items() if how == "divide"]
    have = f[f["item"].isin(per_share) & (f["source"] == "sec")]
    if have.empty:
        return f
    d = fourth_quarters(f, have, "value_adj")
    if d.empty:
        return f
    adj = d["value_adj"].to_numpy()
    d = add_split_factor(d.drop(columns=["split_factor"]).assign(value=adj), splits)
    d["value"], d["value_adj"] = adj * d["split_factor"].to_numpy(), adj
    return pd.concat([f, d[f.columns.intersection(d.columns)]], ignore_index=True)


def add_split_factor(f: pd.DataFrame, splits: pd.DataFrame) -> pd.DataFrame:
    """Shares and per-share values filed before a split, on today's (split-adjusted) basis.
    history.csv is already adjusted. The basis is the filing's own date (`split_basis`), which
    can be after `filed` when the figures count from the earnings release (#49)."""
    f = f.reset_index(drop=True)
    f["split_factor"] = 1.0
    todo = f["item"].isin(list(SPLIT_ITEMS)) & ~f["source"].str.startswith("history")
    if todo.any() and not splits.empty:
        basis = f["split_basis"].fillna(f["filed"]) if "split_basis" in f else f["filed"]
        rows = f.loc[todo, ["company_id"]].assign(basis=basis[todo]).reset_index()
        pairs = rows.merge(splits, on="company_id")
        pairs = pairs[pairs["date"] > pairs["basis"]]
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
    f = derive_q4_per_share(add_split_factor(f, splits), splits)
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


PER_SHARE = [k for k, how in SPLIT_ITEMS.items() if how == "divide"]


def per_share_ttm(f: pd.DataFrame) -> list[dict]:
    """Twelve-month EPS anchored on the reported year, for the windows ending in Q1-Q3: the
    last fiscal year's EPS plus this year's quarters so far less the same quarters a year
    before (how data providers build it, #49). Four quarterly EPS don't add up to the year's
    (each has its own share count; a loss quarter has no dilution): Johnson & Johnson's Q4
    2017 is -3.99 against 0.47 - 1.61 - 1.40 - 1.37 = -3.91, 18% of its twelve-month EPS then.
    Every version as known on each filing date. EPS from continuing operations only where
    every part reports it: a window mixing restated quarters (JNJ's 2022, without Kenvue) with
    ones never restated (2021, total EPS standing in) is neither, so such a window takes
    diluted EPS throughout."""
    p = f[f["item"].isin(PER_SHARE) & f["period_type"].isin(["Q", "FY"])]
    if p.empty:
        return []
    p = p[p["fiscal_period"].isin(["FY", "Q1", "Q2", "Q3"])].sort_values("filed")
    versions: dict[tuple, list] = {}
    ends: dict[tuple, str] = {}
    for r in p.itertuples(index=False):
        k = (r.company_id, r.item, int(r.fiscal_year), r.fiscal_period)
        versions.setdefault(k, []).append(
            (r.filed, bool(r.filed_estimated), r.value, r.value_adj, r.source,
             r.method == "reported")
        )  # fmt: skip
        ends[k] = r.period_end
    out = []
    for (cid, item, year, period), _ in versions.items():
        if period == "FY":
            continue
        n = int(period[1])
        parts = [(year - 1, "FY")] + [(year, f"Q{i}") for i in range(1, n + 1)]
        parts += [(year - 1, f"Q{i}") for i in range(1, n + 1)]
        signs = [1] + [1] * n + [-1] * n
        keys = [(cid, item, y, fp) for y, fp in parts]
        if not all(k in versions for k in keys):
            continue
        filed_of = [[v[0] for v in versions[k]] for k in keys]
        first_known = max(fl[0] for fl in filed_of)
        dates = sorted({d for fl in filed_of for d in fl if d >= first_known})
        for day in dates:
            used = [versions[k][bisect.bisect_right(fl, day) - 1]
                    for k, fl in zip(keys, filed_of, strict=True)]  # fmt: skip
            out.append({
                "company_id": cid, "item": item, "period_end": ends[(cid, item, year, period)],
                "filed": day, "filed_estimated": any(u[1] for u in used),
                "value": sum(s * u[2] for s, u in zip(signs, used, strict=True)),
                "value_adj": sum(s * u[3] for s, u in zip(signs, used, strict=True)),
                "source": used[1][4], "basis": "4q", "all_reported": all(u[5] for u in used),
            })  # fmt: skip
    # EPS from continuing operations: a window not reported throughout takes diluted EPS
    total: dict[tuple, list] = {}
    for r in out:
        if r["item"] == "eps_diluted":
            total.setdefault((r["company_id"], r["period_end"]), []).append(r)
    for rows in total.values():
        rows.sort(key=lambda r: r["filed"])
    kept = []
    for r in out:
        if r["item"] == "eps_continuing" and not r["all_reported"]:
            rows = total.get((r["company_id"], r["period_end"]), [])
            i = bisect.bisect_right([x["filed"] for x in rows], r["filed"]) - 1
            if i < 0:
                continue
            r = {**r, "value": rows[i]["value"], "value_adj": rows[i]["value_adj"]}
        kept.append({k: v for k, v in r.items() if k != "all_reported"})
    return kept


def build_ttm(conn: Connection, f: pd.DataFrame) -> pd.DataFrame:
    """Trailing twelve months for every version: as known on each filing date. Per-share
    values are anchored on the fiscal year (per_share_ttm) where it is known; otherwise, and
    for everything else, four quarters are summed."""
    if f.empty:
        return f
    base = ["company_id", "item", "period_end", "filed", "filed_estimated", "value", "value_adj"]
    inst = f[f["period_type"] == "I"][base + ["source"]].assign(basis="instant")
    fy = f[f["period_type"] == "FY"][base + ["source"]].assign(basis="fy")
    anchored = per_share_ttm(f)
    sums = []
    cols = ["company_id", "item", "period_end", "filed", "filed_estimated", "value", "value_adj",
            "source"]  # fmt: skip
    quarters = f.loc[f["period_type"] == "Q", cols].sort_values(cols[:4])
    # Plain lists, not pandas: this runs for every window and filing date (millions of times).
    groups: dict[tuple, dict[str, list]] = {}
    for cid, item, end, filed, est, value, adj, source in quarters.itertuples(index=False):
        groups.setdefault((cid, item), {}).setdefault(end, []).append(
            (filed, bool(est), value, adj, source)
        )
    for (cid, item), versions in groups.items():
        ends = sorted(versions)
        filed_of = {e: [v[0] for v in versions[e]] for e in ends}  # sorted by filing date
        for i in range(3, len(ends)):
            window = ends[i - 3 : i + 1]
            span = (pd.Timestamp(window[-1]) - pd.Timestamp(window[0])).days
            if not 250 <= span <= 300:  # four consecutive quarters
                continue
            first_known = max(filed_of[e][0] for e in window)
            dates = sorted({d for e in window for d in filed_of[e] if d >= first_known})
            for day in dates:
                # the latest version of each quarter known on that day
                used = [versions[e][bisect.bisect_right(filed_of[e], day) - 1] for e in window]
                sums.append(
                    {
                        "company_id": cid,
                        "item": item,
                        "period_end": window[-1],
                        "filed": day,
                        "filed_estimated": any(u[1] for u in used),
                        "value": sum(u[2] for u in used),
                        "value_adj": sum(u[3] for u in used),
                        "source": used[-1][4],
                        "basis": "4q",
                    }
                )
    q = pd.DataFrame(sums)
    if anchored:  # a per-share window anchored on the year replaces its four-quarter sum
        a = pd.DataFrame(anchored)
        if not q.empty:
            done = a[["company_id", "item", "period_end"]].drop_duplicates()
            m = q.merge(done, how="left", on=["company_id", "item", "period_end"], indicator=True)
            q = q[(m["_merge"] == "left_only").to_numpy()]
        q = pd.concat([q, a], ignore_index=True)
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


CORE_TABLES = ("core_fundamental_ttm", "core_fundamental", "core_price_daily")
ISSUE_COLUMNS = ["company_id", "item", "at_date", "check_name", "severity", "detail"]


def file_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def company_rules() -> dict[str, str]:
    """A fingerprint of each company's entries in config/companies.toml, so a changed entry
    rebuilds only that company."""
    by_symbol: dict[str, list] = {}
    for kind, entries in load_companies().items():
        for e in entries if isinstance(entries, list) else []:
            if isinstance(e, dict) and e.get("symbol"):
                by_symbol.setdefault(e["symbol"], []).append([kind, e])
    return {
        s: hashlib.sha256(json.dumps(v, sort_keys=True, default=str).encode()).hexdigest()[:16]
        for s, v in by_symbol.items()
    }


def last_build(conn: Connection) -> dict | None:
    row = run(
        conn,
        "SELECT build_id, max_fetch_id, summary FROM core_build WHERE status = 'ok' "
        "ORDER BY build_id DESC LIMIT 1",
    ).fetchone()
    if row is None:
        return None
    try:
        summary = json.loads(row[2] or "{}")
    except ValueError:
        summary = {}
    return {**summary, "build_id": row[0], "max_fetch_id": row[1]}


def changed_since(conn: Connection, fetch_id: int) -> set[str]:
    """The companies with raw rows stored after this fetch. The raw tables keep new or changed
    rows only, so these are exactly the companies whose sources changed."""
    preds = load_companies().get("predecessor", [])
    owners = "SELECT symbol, cik FROM core_company WHERE cik IS NOT NULL"
    if preds:
        values = ", ".join(f"('{p['symbol']}', {int(p['cik'])})" for p in preds)
        owners += f" UNION ALL SELECT * FROM (VALUES {values}) AS p(s, c)"
    rows = run(
        conn,
        "SELECT symbol FROM raw_yahoo_price WHERE fetch_id > :f "
        "UNION SELECT symbol FROM raw_yahoo_statement WHERE fetch_id > :f "
        "UNION SELECT symbol FROM raw_project_history WHERE fetch_id > :f "
        f"UNION SELECT o.symbol FROM raw_sec_fact r JOIN ({owners}) o ON o.cik = r.cik "
        "WHERE r.fetch_id > :f "
        f"UNION SELECT o.symbol FROM raw_sec_xbrl_fact r JOIN ({owners}) o ON o.cik = r.cik "
        "WHERE r.fetch_id > :f",
        {"f": int(fetch_id)},
    )
    return {r[0] for r in rows}


def plan_build(
    conn: Connection, items_config: Path, before: dict, full: bool, symbols: list[str] | None
) -> tuple[list[str] | None, str]:
    """(the companies to rebuild, or None for all; why). Only the companies with new raw data,
    a changed company rule or a new CIK: the job adds what is new and never rebuilds the whole
    database. A full build only when asked (--full) or when core is still empty. A changed
    item mapping or build code does not rebuild anything by itself: check it on a sample
    (db check-sample) and rebuild those companies (--symbols); the others keep their rows
    until their sources bring new data."""
    if full:
        return None, "asked for a full build"
    if symbols:
        return sorted(symbols), "asked for these companies"
    last = last_build(conn)
    if last is None or last.get("max_fetch_id") is None:
        return None, "core is empty: first build"
    notes = []
    if last.get("items_sha") and last["items_sha"] != file_sha(items_config):
        notes.append("config/db_items.toml changed since the last build")
    if last.get("code_sha") and last["code_sha"] != file_sha(Path(__file__)):
        notes.append("the build code changed since the last build")
    scope = changed_since(conn, last["max_fetch_id"])
    rules, old_rules = company_rules(), last.get("company_rules", {})
    scope |= {s for s in rules.keys() | old_rules.keys() if rules.get(s) != old_rules.get(s)}
    after = {r[0]: r[1] for r in run(conn, "SELECT symbol, cik FROM core_company")}
    scope |= {s for s, cik in after.items() if s not in before or before[s] != cik}
    scope &= after.keys()
    why = "new raw data, company rules or CIKs" if scope else "nothing new"
    if notes:
        why += " (" + "; ".join(notes) + ": existing rows keep their values; check samples)"
    return sorted(scope), why


class DryRun(Exception):  # noqa: N818 - not an error: ends a dry run and rolls it back
    def __init__(self, report: dict):
        super().__init__("dry run")
        self.report = report


SAMPLE_KEY = ["company_id", "item", "period_type", "period_end", "filed"]


def sample_rows(conn: Connection, ids: list[int]) -> pd.DataFrame:
    """The core values of these companies, every version."""
    return frame(
        conn,
        "SELECT company_id, item, period_type, to_char(period_end, 'YYYY-MM-DD') AS period_end, "
        "to_char(filed, 'YYYY-MM-DD') AS filed, value, source, tag FROM core_fundamental "
        "WHERE company_id = ANY(:ids)",
        {"ids": ids},
    )


def compare_rows(old: pd.DataFrame, new: pd.DataFrame, todo: dict, seconds: dict) -> dict:
    """What a dry run would change for each company: values added, removed or changed."""
    names = {v: k for k, v in todo.items()}
    m = old.merge(new, on=SAMPLE_KEY, how="outer", suffixes=("_old", "_new"), indicator=True)
    same = (m["value_old"] - m["value_new"]).abs() <= 1e-9 * m["value_old"].abs().clip(lower=1)
    m["change"] = np.select(
        [m["_merge"] == "left_only", m["_merge"] == "right_only", ~same],
        ["removed", "added", "changed"], "same",
    )  # fmt: skip
    m["symbol"] = m["company_id"].map(names)
    counts = m.pivot_table(index="symbol", columns="change", values="item", aggfunc="count",
                           fill_value=0)  # fmt: skip
    shown = m[m["change"] != "same"].sort_values(["symbol", "item", "period_end", "filed"])
    cols = ["symbol", "item", "period_type", "period_end", "filed", "change", "value_old",
            "value_new", "source_old", "source_new"]  # fmt: skip
    return {
        "mode": "dry run (rolled back, nothing written)",
        "companies": sorted(todo),
        "per_company": {s: {k: int(v) for k, v in r.items()} for s, r in counts.iterrows()},
        "changes": [
            {k: plain(v) for k, v in r.items()} for r in shown[cols].head(200).to_dict("records")
        ],
        "seconds": seconds,
    }


def add_new_items(conn: Connection, items: pd.DataFrame, tags: pd.DataFrame) -> None:
    """Items and tags added to config/db_items.toml since core_item was written, so an
    incremental build can store them; existing rows stay as they are."""
    item_df, tag_df = stored(items, tags)
    have = {r[0] for r in run(conn, "SELECT item FROM core_item")}
    insert_df(conn, "core_item", item_df[~item_df["item"].isin(have)])
    have_tags = {tuple(r) for r in run(conn, "SELECT item, taxonomy, tag FROM core_item_tag")}
    keys = list(zip(tag_df["item"], tag_df["taxonomy"], tag_df["tag"], strict=True))
    insert_df(conn, "core_item_tag", tag_df[[k not in have_tags for k in keys]])


def build(
    db: Database,
    items_config: Path = ITEMS_CONFIG,
    *,
    full: bool = False,
    symbols: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """Build core from raw in one transaction, for the companies whose raw data, company rules
    (config/companies.toml) or CIK changed since the last build (plan_build); every company
    only with full=True or on an empty core. Returns the summary stored in core_build.

    dry_run (needs symbols; db check-sample): build those companies, compare their new core
    rows with the ones in the database, and roll everything back. The way to check a change
    of the extraction on a sample before using it."""
    if dry_run and not symbols:
        raise ValueError("a dry run checks a sample: name the companies (symbols)")
    global _SCOPE
    started = now()
    seconds: dict[str, float] = {}
    clock = [time.monotonic()]

    def lap(step: str) -> None:
        seconds[step] = round(time.monotonic() - clock[0], 1)
        clock[0] = time.monotonic()

    try:
        with db.begin() as conn:
            prev = last_build(conn)
            build_id = scalar(
                conn,
                "INSERT INTO core_build (started_at, git_sha, max_fetch_id, status) VALUES "
                "(:t, :sha, (SELECT MAX(fetch_id) FROM raw_fetch), 'running') RETURNING build_id",
                {"t": started, "sha": git_sha()},
            )
            before = {r[0]: r[1] for r in run(conn, "SELECT symbol, cik FROM core_company")}
            run(conn, "DELETE FROM core_index_member")
            companies = build_companies(conn)
            # the market report's instruments: few rows, rebuilt in full every time
            run(conn, "DELETE FROM core_market_daily")
            market_rows = build_market_prices(conn, market_symbols())
            scope, why = plan_build(conn, items_config, before, full, symbols)
            items, tags = load_items(items_config)
            lap("plan")
            if scope is None:
                for table in (*CORE_TABLES, "core_item_tag", "core_item"):
                    run(conn, f"DELETE FROM {table}")
                for table, df in zip(("core_item", "core_item_tag"), stored(items, tags),
                                     strict=True):  # fmt: skip
                    insert_df(conn, table, df)
                todo = companies
            else:
                todo = {s: companies[s] for s in scope if s in companies}
                ids = list(todo.values())
                add_new_items(conn, items, tags)
                old_rows = sample_rows(conn, ids) if dry_run else None
                for table in CORE_TABLES:
                    run(conn, f"DELETE FROM {table} WHERE company_id = ANY(:ids)", {"ids": ids})
            lap("delete")
            _SCOPE = None if scope is None else list(todo)
            issues: list[tuple] = []
            if todo:
                prices = build_prices(conn, todo)
                lap("prices")
                f, c = build_fundamentals(conn, todo, items, tags, all_splits(conn, todo))
                lap("fundamentals")
                build_ttm(conn, f)
                lap("ttm")
                issues = quality_checks(prices, f, c)
            found = pd.DataFrame([[plain(x) for x in i] for i in issues], columns=ISSUE_COLUMNS)
            insert_df(conn, "core_quality_issue", found.assign(build_id=build_id))
            if scope is not None and prev:  # the other companies' issues stay as they were
                cols = ", ".join(ISSUE_COLUMNS)
                run(
                    conn,
                    f"INSERT INTO core_quality_issue (build_id, {cols}) SELECT :new, {cols} "
                    "FROM core_quality_issue WHERE build_id = :old "
                    "AND (company_id IS NULL OR NOT company_id = ANY(:ids))",
                    {"new": build_id, "old": prev["build_id"], "ids": list(todo.values())},
                )
            lap("quality")
            if dry_run:
                raise DryRun(compare_rows(old_rows, sample_rows(conn, ids), todo, seconds))

            def count(sql: str) -> int:
                return int(scalar(conn, sql) or 0)

            summary = {
                "mode": "full" if scope is None else "incremental",
                "why": why,
                "rebuilt": len(todo),
                "rebuilt_symbols": sorted(todo)[:50] if scope is not None else [],
                "companies": len(companies),
                "sp500_members_now": count(
                    "SELECT COUNT(*) FROM core_index_member WHERE end_date IS NULL"
                ),
                "companies_with_prices": count(
                    "SELECT COUNT(DISTINCT company_id) FROM core_price_daily"
                ),
                "core_price_daily": count("SELECT COUNT(*) FROM core_price_daily"),
                "core_market_daily": market_rows,
                "core_fundamental": count("SELECT COUNT(*) FROM core_fundamental"),
                "companies_with_fundamentals": count(
                    "SELECT COUNT(DISTINCT company_id) FROM core_fundamental"
                ),
                "core_fundamental_ttm": count("SELECT COUNT(*) FROM core_fundamental_ttm"),
                "quality_issues": count(
                    f"SELECT COUNT(*) FROM core_quality_issue WHERE build_id = {int(build_id)}"
                ),
                "seconds": seconds,
                # what the next build compares with, to rebuild only what changed
                "items_sha": file_sha(items_config),
                "code_sha": file_sha(Path(__file__)),
                "company_rules": company_rules(),
            }
            run(
                conn,
                "UPDATE core_build SET finished_at = :t, status = 'ok', summary = :s "
                "WHERE build_id = :id",
                {"t": now(), "s": json.dumps(summary), "id": build_id},
            )
        hidden = ("company_rules", "items_sha", "code_sha")
        return {"build_id": build_id, **{k: v for k, v in summary.items() if k not in hidden}}
    except DryRun as done:  # the transaction was rolled back: nothing was written
        return done.report
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
    finally:
        _SCOPE = None
