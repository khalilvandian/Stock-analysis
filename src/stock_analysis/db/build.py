"""Rebuild the core layer from the raw layer (docs/DATABASE.md, "Build rules").

The build reads only raw_* tables and config/db_items.toml. In one transaction it rewrites
core_item, core_item_tag, core_index_member, core_price_daily, core_fundamental and
core_fundamental_ttm, updates core_company in place (so company_id stays the same), and adds a
core_build row with that build's core_quality_issue rows.
"""

from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy.engine import Connection

from . import ROOT, Database, frame, insert_df, records, run, scalar
from .load_files import UNIVERSE, now

ITEMS_CONFIG = ROOT / "config" / "db_items.toml"
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
        items.append({k: it.get(k) for k in ("item", "label", "kind", "unit", "derive")})
        for i, tag in enumerate(it.get("sec", []), start=1):
            taxonomy, _, name = tag.rpartition(":")
            tags.append((it["item"], taxonomy or "us-gaap", name, i, 1.0))
        for i, tag in enumerate(it.get("history", []), start=1):
            tags.append((it["item"], "history", tag, i, float(it.get("history_scale", 1))))
        for i, tag in enumerate(it.get("yahoo", []), start=1):
            tags.append((it["item"], "yahoo", tag, i, 1.0))
    tags = pd.DataFrame(tags, columns=["item", "taxonomy", "tag", "priority", "scale"])
    return pd.DataFrame(items), tags


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
            records(sec.drop_duplicates("cik")[["cik", "symbol"]]),
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
    raw = frame(conn, "SELECT * FROM raw_yahoo_price ORDER BY fetch_id")
    raw = raw[raw["symbol"].isin(companies)].drop_duplicates(["symbol", "date"], keep="last")
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
QUARTER_DAYS, YEAR_DAYS = (80, 100), (350, 380)
SEC_FIRST_PERIOD = "2015-01-01"


def to_month_end(dates: pd.Series) -> pd.Series:
    """Each date as the nearest month end (2026-09-26 and 2026-10-02 are both 2026-09-30), so a
    52/53-week period reported by SEC on its real end and by Yahoo on the month end is one
    period."""
    m = month_index(dates)
    first = pd.to_datetime({"year": m // 12, "month": m % 12 + 1, "day": 1})
    return (first + pd.offsets.MonthEnd(0)).dt.strftime("%Y-%m-%d")


def sec_candidates(conn: Connection, kind: pd.Series, tags: pd.DataFrame) -> pd.DataFrame:
    """SEC company facts that map to an item: a quarter or fiscal-year flow, or an instant,
    with its real filing date. Cover-page share counts (dei) are dated at the balance-sheet
    date of their filing, not the cover date."""
    sec = frame(
        conn,
        "SELECT f.raw_id, f.fetch_id, c.symbol, f.taxonomy, f.tag, f.unit, f.period_start, "
        "f.period_end, f.value, f.form, f.filed, f.accn FROM raw_sec_fact f "
        "JOIN core_company c ON c.cik = f.cik",
    )
    if sec.empty:
        return sec
    sec = sec[sec["form"].isin(SEC_FORMS) & sec["unit"].isin(SEC_UNITS)]
    key = ["symbol", "taxonomy", "tag", "unit", "period_start", "period_end", "accn"]
    sec = sec.sort_values("fetch_id").drop_duplicates(key, keep="last")
    instant = sec["period_start"].isna()
    balance_date = sec[instant & (sec["taxonomy"] != "dei")].groupby("accn")["period_end"].max()
    dei = sec["taxonomy"] == "dei"
    sec.loc[dei, "period_end"] = sec.loc[dei, "accn"].map(balance_date)
    sec = sec.dropna(subset=["period_end"])
    sec_tags = tags[~tags["taxonomy"].isin(["history", "yahoo"])]
    sec = sec.merge(sec_tags, on=["taxonomy", "tag"])
    if sec.empty:
        return sec
    days = (pd.to_datetime(sec["period_end"]) - pd.to_datetime(sec["period_start"])).dt.days + 1
    flow_type = np.select(
        [days.between(*QUARTER_DAYS), days.between(*YEAR_DAYS)], ["Q", "FY"], default=""
    )
    is_instant_item = sec["item"].map(kind) == "instant"
    sec["period_type"] = np.where(
        sec["period_start"].isna() | (is_instant_item & (flow_type != "")), "I", flow_type
    )
    # Before the price history starts the splits are unknown, so per-share values and share
    # counts could not be put on today's basis: SEC values start a year before core does.
    sec = sec[(sec["period_type"] != "") & (sec["period_end"] >= SEC_FIRST_PERIOD)]
    return sec.assign(source="sec", raw_table="raw_sec_fact")


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
    yahoo = frame(conn, "SELECT * FROM raw_yahoo_statement")
    yahoo = yahoo[yahoo["symbol"].isin(companies)].merge(
        tags[tags["taxonomy"] == "yahoo"], left_on="line_item", right_on="tag"
    )
    if not yahoo.empty:
        flow_type = np.where(yahoo["frequency"] == "annual", "FY", "Q")
        yahoo["period_type"] = np.where(yahoo["item"].map(kind) == "instant", "I", flow_type)
        frames.append(yahoo.assign(source="yahoo", raw_table="raw_yahoo_statement"))
    hist = frame(conn, "SELECT * FROM raw_project_history")
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
    c["period_end"] = to_month_end(c["period_end"])
    c["company_id"] = c["symbol"].map(companies)
    c["value"] = c["value"] * c["scale"]
    c["rank"] = c["source"].str.split(":").str[0].map(SOURCE_RANK)
    c["kind"] = c["item"].map(kind)
    c = add_periods(c)
    cols = [*KEY, "kind", "filed", "filed_estimated", "fiscal_year", "fiscal_period", "value"]
    cols += ["source", "tag", "raw_table", "raw_id", "rank", "priority", "fetch_id"]
    return c[cols]


def month_index(dates: pd.Series) -> pd.Series:
    """year * 12 + month of the nearest month end (Dec 28 and Jan 2 both count as December)."""
    d = pd.to_datetime(dates) - pd.Timedelta(days=15)
    return d.dt.year * 12 + d.dt.month - 1


def add_periods(c: pd.DataFrame) -> pd.DataFrame:
    """Fiscal year and quarter from the fiscal year-end month, and the estimated filing date."""
    m = month_index(c["period_end"])
    fy = c[c["period_type"] == "FY"].assign(month=m % 12)
    fye = fy.groupby("company_id")["month"].agg(lambda s: s.mode().iloc[0])
    offset = (m % 12 - c["company_id"].map(fye).fillna(11).astype(int)) % 12
    c["fiscal_year"] = ((m + (12 - offset) % 12) // 12).astype(int)
    quarter = offset.map({3: "Q1", 6: "Q2", 9: "Q3", 0: "Q4"})
    c["fiscal_period"] = np.where(c["period_type"] == "FY", "FY", quarter)
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
    """Items defined as a sum of others, wherever all parts exist. The derived value replaces a
    reported one from the same or a lower-ranked source, never one from a better source
    (Yahoo's parts do not override history.csv's EBITDA)."""
    for _, it in items[items["derive"].notna()].iterrows():
        parts = [p.strip() for p in it["derive"].split("+")]
        have = latest(f[f["item"].isin(parts)])
        idx = ["company_id", "period_type", "period_end"]
        wide = have.pivot_table(index=idx, columns="item", values="value", aggfunc="first")
        if not set(parts) <= set(wide.columns):
            continue
        wide = wide[parts].dropna()
        if wide.empty:
            continue
        meta = have.groupby(idx).agg(
            filed=("filed", "max"),
            filed_estimated=("filed_estimated", "max"),
            fiscal_year=("fiscal_year", "first"),
            fiscal_period=("fiscal_period", "first"),
            source=("source", lambda s: s.iloc[0] if s.nunique() == 1 else "derived"),
            rank=("rank", "max"),  # as good as its worst part
        )
        d = wide.sum(axis=1).rename("value").to_frame().join(meta).reset_index()
        d = d.assign(item=it["item"], kind=it["kind"], tag=it["derive"], method="derived")
        reported = f[f["item"] == it["item"]].groupby(KEY)["rank"].min().rename("reported_rank")
        d = d.merge(reported.reset_index(), on=KEY, how="left")
        d = d[~(d["reported_rank"] < d["rank"])].drop(columns="reported_rank")
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
    f["method"] = "reported"
    f = add_split_factor(derive(derive_q4(f, items), items), splits)
    cols = [*KEY, "filed", "filed_estimated", "fiscal_year", "fiscal_period", "value"]
    cols += ["split_factor", "method", "source", "tag", "raw_table", "raw_id"]
    out = f[cols].copy()
    for col in ("fiscal_year", "raw_id"):
        out[col] = out[col].astype("Int64")
    out["filed_estimated"] = out["filed_estimated"].astype(bool)
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
            insert_df(conn, "core_item", items)
            insert_df(conn, "core_item_tag", tags)
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
