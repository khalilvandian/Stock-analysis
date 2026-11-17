"""How much of the required data is in the database, and how good it is (config/coverage.toml,
docs/COVERAGE.md).

    python -m stock_analysis.db coverage                    # print the summary, save the snapshot
    python -m stock_analysis.db coverage --json FILE        # also write the page's JSON

The universe is the newest TradingView snapshot of the index (the same list the ingest job
fetches). For every member it counts the required cells (each fiscal year x item, each recent
quarter x item, the price history, the reported EPS) and how many are present or explained,
and adds freshness, the source of each value, the quality issues of the last build and the
ingest job's progress. One snapshot per day goes into out_coverage_snapshot; its detail_json
is what the coverage page on the site shows.
"""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Connection

from . import ROOT, Database, frame, run
from .build import ITEMS_CONFIG, load_items

CONFIG = ROOT / "config" / "coverage.toml"
MAX_MISSING_SHOWN = 12


def load_config(path: Path = CONFIG) -> dict:
    return tomllib.loads(Path(path).read_text(encoding="utf-8"))


def month_end(year: int, month: int) -> date:
    first_next = date(year + month // 12, month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def month_index(d) -> int:
    """year * 12 + month - 1 of the nearest month end, as the build counts fiscal periods."""
    d = pd.Timestamp(d) - pd.Timedelta(days=15)
    return d.year * 12 + d.month - 1


def fiscal_end(year: int, fye_month: int) -> date:
    return month_end(year, fye_month)


def explained_for(rules: list[dict], item: str, year: int | None) -> bool:
    """A gap accepted by hand in config/coverage.toml ([[explained]])."""
    for e in rules:
        if e.get("item") == item and (
            year is None or not e.get("fiscal_years") or year in e["fiscal_years"]
        ):
            return True
    return False


# ---------------------------------------------------------------- reading


def universe(conn: Connection, index: str) -> pd.DataFrame:
    """Members in the newest snapshot, with their company_id once the build has run."""
    return frame(
        conn,
        "SELECT t.symbol, t.name, t.sector, t.industry, c.company_id FROM raw_tv_constituent t "
        "LEFT JOIN core_company c ON c.symbol = t.symbol "
        "WHERE t.fetch_id = (SELECT MAX(f.fetch_id) FROM raw_fetch f JOIN raw_tv_constituent x "
        "ON x.fetch_id = f.fetch_id WHERE f.source = 'tradingview' AND f.request_key = :u) "
        "ORDER BY t.symbol",
        {"u": index},
    ).drop_duplicates("symbol")


def price_stats(conn: Connection, start: str) -> pd.DataFrame:
    """Per company: first and last day, days present and days expected, against the
    database's own trading calendar (days on which at least a fifth of the companies traded)."""
    companies = frame(conn, "SELECT COUNT(DISTINCT company_id) AS n FROM core_price_daily")
    min_n = max(1, int(0.2 * int(companies["n"].iloc[0] or 0)))
    return frame(
        conn,
        "WITH cal AS (SELECT date FROM core_price_daily WHERE date >= :s GROUP BY date "
        "HAVING COUNT(*) >= :n), "
        "span AS (SELECT company_id, MIN(date) AS first_day, MAX(date) AS last_day "
        "FROM core_price_daily WHERE date >= :s GROUP BY company_id) "
        "SELECT span.company_id, span.first_day, span.last_day, "
        "(SELECT COUNT(*) FROM core_price_daily p JOIN cal ON cal.date = p.date "
        " WHERE p.company_id = span.company_id AND p.date >= :s) AS days, "
        "(SELECT COUNT(*) FROM cal WHERE cal.date >= span.first_day) AS expected, "
        "(SELECT MAX(date) FROM cal) AS calendar_last "
        "FROM span",
        {"s": start, "n": min_n},
    )


def fundamentals(conn: Connection) -> pd.DataFrame:
    """Latest version of every period: company, item, type, end, fiscal year and period,
    source, filing date."""
    return frame(
        conn,
        "SELECT company_id, item, period_type, period_end, fiscal_year, fiscal_period, source, "
        "filed, filed_estimated FROM v_fundamental_latest",
    )


def earnings(conn: Connection, since: str) -> pd.DataFrame:
    return frame(
        conn,
        "SELECT symbol, report_date, eps_reported FROM (SELECT e.*, ROW_NUMBER() OVER "
        "(PARTITION BY symbol, report_date ORDER BY fetch_id DESC) AS rn "
        "FROM raw_yahoo_earnings e) x WHERE rn = 1 AND report_date >= :s "
        "AND eps_reported IS NOT NULL",
        {"s": since},
    )


def latest_issues(conn: Connection) -> pd.DataFrame:
    return frame(
        conn,
        "SELECT company_id, check_name, severity FROM core_quality_issue "
        "WHERE build_id = (SELECT MAX(build_id) FROM core_build WHERE status = 'ok')",
    )


def pipeline(conn: Connection) -> dict:
    tasks = frame(
        conn,
        "SELECT source, status, COUNT(*) AS n, "
        "SUM(CASE WHEN last_success_at IS NULL THEN 1 ELSE 0 END) AS never "
        "FROM ops_task WHERE active GROUP BY source, status",
    )
    by_source: dict[str, dict] = {}
    for r in tasks.to_dict("records"):
        s = by_source.setdefault(r["source"], {"tasks": 0, "never_fetched": 0})
        s[r["status"]] = int(r["n"])
        s["tasks"] += int(r["n"])
        s["never_fetched"] += int(r["never"] or 0)
    runs = frame(
        conn,
        "SELECT run_id, started_at, finished_at, mode, status, requests, tasks_ok, "
        "tasks_failed, rows_stored, summary FROM ops_run ORDER BY run_id DESC LIMIT 20",
    )
    last_runs = []
    for r in runs.to_dict("records"):
        raw = r.pop("summary")
        s = json.loads(raw) if isinstance(raw, str) and raw else {}
        r["stopped"] = {
            g: v["stopped"] for g, v in (s.get("groups") or {}).items() if v.get("stopped")
        }
        last_runs.append(r)
    never = sum(s["never_fetched"] for s in by_source.values())
    done = [r["tasks_ok"] for r in last_runs[:7] if r["tasks_ok"]]
    per_run = sum(done) / len(done) if done else 0
    return {
        "sources": by_source,
        "never_fetched": never,
        "runs": last_runs,
        "runs_to_finish": (round(never / per_run, 1) if per_run else None) if never else 0,
    }


# ---------------------------------------------------------------- computing


def fye_months(f: pd.DataFrame) -> dict:
    fy = f[f["period_type"] == "FY"]
    if fy.empty:
        return {}
    months = fy["period_end"].map(lambda d: month_index(d) % 12 + 1)
    return months.groupby(fy["company_id"]).agg(lambda s: int(s.mode().iloc[0])).to_dict()


def compute(conn: Connection, config: dict | None = None, today: date | None = None) -> dict:
    """The coverage of the universe today, as the dict stored in detail_json."""
    cfg = config or load_config()
    today = today or date.today()
    items_df, _ = load_items(cfg.get("items_config", ITEMS_CONFIG))
    labels = dict(zip(items_df["item"], items_df["label"], strict=True))
    kinds = dict(zip(items_df["item"], items_df["kind"], strict=True))
    all_items = list(items_df["item"])
    optional = set(cfg.get("optional_items", []))
    na_rules = cfg.get("not_applicable", [])
    explained = cfg.get("explained", [])
    start = cfg.get("prices_from", "2016-01-01")
    first_fy = int(cfg.get("first_fiscal_year", 2016))
    n_quarters = int(cfg.get("quarters", 8))
    n_eps = int(cfg.get("earnings_quarters", 8))

    members = universe(conn, cfg.get("universe", "SP:SPX"))
    prices = price_stats(conn, start).set_index("company_id")
    f = fundamentals(conn)
    fye = fye_months(f)
    eps = earnings(conn, (today - timedelta(days=int(n_eps * 91.5) + 75)).isoformat())
    eps_count = eps.groupby("symbol").size().to_dict()
    issues = latest_issues(conn)
    annual = f[
        (f["period_type"] == "FY") | ((f["period_type"] == "I") & (f["fiscal_period"] == "Q4"))
    ]
    have_year = set(zip(annual["company_id"], annual["item"], annual["fiscal_year"], strict=True))
    qf = f[f["period_type"].isin(["Q", "I"])]
    have_quarter = {
        (cid, item, month_index(end), ptype)
        for cid, item, end, ptype in zip(
            qf["company_id"], qf["item"], qf["period_end"], qf["period_type"], strict=True
        )
    }
    filed = f[(f["source"] == "sec") & ~f["filed_estimated"].astype(bool)]
    last_filed = filed.groupby("company_id")["filed"].max().to_dict()
    price_last = prices["calendar_last"].dropna().max() if len(prices) else None

    item_cells = {i: [0, 0] for i in all_items}  # required, present (annual)
    year_cells: dict[int, list[int]] = {}
    companies = []
    for m in members.to_dict("records"):
        cid = m["company_id"]
        cid = int(cid) if cid is not None and not pd.isna(cid) else None
        na = {
            i for rule in na_rules if m.get("industry") in rule.get("industries", [])
            for i in rule.get("items", [])
        }  # fmt: skip
        required = [i for i in all_items if i not in na and i not in optional]
        measured = [i for i in all_items if i not in na]
        ok_by_hand = [e for e in explained if e.get("symbol") == m["symbol"]]

        # prices
        p = prices.loc[cid] if cid is not None and cid in prices.index else None
        listed = None
        if p is not None and str(p["first_day"]) > (
            pd.Timestamp(start) + pd.Timedelta(days=15)
        ).strftime("%Y-%m-%d"):
            listed = date.fromisoformat(str(p["first_day"])[:10])
        price_share = float(p["days"] / p["expected"]) if p is not None and p["expected"] else 0.0
        price_age = (
            (today - date.fromisoformat(str(p["last_day"])[:10])).days if p is not None else None
        )
        prices_ok = (
            p is not None
            and price_share >= float(cfg.get("price_days_share", 0.98))
            and price_age is not None
            and price_age <= int(cfg.get("price_max_age_days", 5))
        )

        # fiscal years
        month = fye.get(cid, 12)
        lag = timedelta(days=int(cfg.get("annual_lag_days", 100)))
        last_year = today.year
        while fiscal_end(last_year, month) + lag > today:
            last_year -= 1
        first_year = first_fy
        if listed:
            while fiscal_end(first_year, month) < listed:
                first_year += 1
        years = list(range(first_year, last_year + 1))
        a_req = a_have = 0
        missing: list[str] = []
        shares = []
        for item in all_items:
            if item not in measured:
                shares.append(None)
                continue
            got = 0
            for y in years:
                present = (cid, item, y) in have_year or explained_for(ok_by_hand, item, y)
                got += present
                item_cells[item][0] += 1
                item_cells[item][1] += present
                if item in required:
                    yc = year_cells.setdefault(y, [0, 0])
                    yc[0] += 1
                    yc[1] += present
                    if not present:
                        missing.append(f"{item} FY{y}")
            if item in required:
                a_req += len(years)
                a_have += got
            shares.append(round(got / len(years), 3) if years else None)

        # quarters: the last n quarter ends that should be filed by now
        qlag = timedelta(days=int(cfg.get("quarter_lag_days", 60)))
        q_ends = []
        y, mo = today.year, today.month
        while len(q_ends) < n_quarters and y > 2000:
            if (mo - month) % 3 == 0:
                end = month_end(y, mo)
                if end + qlag <= today and (listed is None or end >= listed):
                    q_ends.append(end)
            mo -= 1
            if mo == 0:
                y, mo = y - 1, 12
        q_req = q_have = 0
        for item in required:
            ptype = "I" if kinds[item] == "instant" else "Q"
            for end in q_ends:
                q_req += 1
                ok = (cid, item, month_index(end), ptype) in have_quarter or explained_for(
                    ok_by_hand, item, None
                )
                q_have += ok
                if not ok:
                    missing.append(f"{item} {end:%Y-%m}")

        # reported EPS
        eps_needed = n_eps
        if listed:
            eps_needed = min(n_eps, max(1, (today - listed).days // 92))
        eps_have = int(eps_count.get(m["symbol"], 0))
        eps_ok = eps_have >= eps_needed

        cells_req = a_req + q_req + 2
        cells_have = a_have + q_have + int(prices_ok) + int(eps_ok)
        ci = issues[issues["company_id"] == cid] if cid is not None else issues.iloc[0:0]
        companies.append(
            {
                "symbol": m["symbol"],
                "name": m.get("name"),
                "sector": m.get("sector"),
                "industry": m.get("industry"),
                "covered": cells_have == cells_req,
                "cells_required": cells_req,
                "cells_present": cells_have,
                "share": round(cells_have / cells_req, 4) if cells_req else 0,
                "listed": listed.isoformat() if listed else None,
                "prices": {
                    "first": str(p["first_day"])[:10] if p is not None else None,
                    "last": str(p["last_day"])[:10] if p is not None else None,
                    "share": round(price_share, 4),
                    "age_days": price_age,
                    "ok": bool(prices_ok),
                },
                "annual": {"years": f"{first_year}-{last_year}", "required": a_req,
                           "present": a_have},
                "quarterly": {"required": q_req, "present": q_have},
                "earnings": {"required": eps_needed, "present": eps_have, "ok": eps_ok},
                "last_filed": last_filed.get(cid),
                "issues": {"warn": int((ci["severity"] == "warn").sum()),
                           "info": int((ci["severity"] == "info").sum()),
                           "error": int((ci["severity"] == "error").sum())},
                "item_shares": shares,
                "missing": missing[:MAX_MISSING_SHOWN],
                "missing_count": len(missing),
            }
        )  # fmt: skip

    n = len(companies)
    covered = sum(c["covered"] for c in companies)
    req = sum(c["cells_required"] for c in companies)
    have = sum(c["cells_present"] for c in companies)
    sectors: dict[str, dict] = {}
    for c in companies:
        s = sectors.setdefault(
            c["sector"] or "unknown", {"companies": 0, "covered": 0, "required": 0, "present": 0}
        )
        s["companies"] += 1
        s["covered"] += c["covered"]
        s["required"] += c["cells_required"]
        s["present"] += c["cells_present"]
    ids = {int(x) for x in members["company_id"].dropna()}
    fa = annual[annual["company_id"].isin(ids)]
    source_mix = fa["source"].str.split(":").str[0].replace({"history": "history (SEC file)"})
    stale_filing = sum(
        1 for c in companies
        if c["last_filed"] and (today - date.fromisoformat(c["last_filed"][:10])).days > 120
    )  # fmt: skip
    mi = issues[issues["company_id"].isin(ids)]
    quality = (
        mi.groupby(["check_name", "severity"]).size().rename("count").reset_index()
        .sort_values("count", ascending=False).to_dict("records")
    )  # fmt: skip
    return {
        "as_of": today.isoformat(),
        "computed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "universe": cfg.get("universe", "SP:SPX"),
        "totals": {
            "companies": n,
            "companies_covered": covered,
            "cells_required": req,
            "cells_present": have,
            "share_present": round(have / req, 4) if req else 0,
            "with_prices": sum(c["prices"]["last"] is not None for c in companies),
            "prices_ok": sum(c["prices"]["ok"] for c in companies),
            "with_annual": sum(c["annual"]["present"] > 0 for c in companies),
            "annual_required": sum(c["annual"]["required"] for c in companies),
            "annual_present": sum(c["annual"]["present"] for c in companies),
            "quarterly_required": sum(c["quarterly"]["required"] for c in companies),
            "quarterly_present": sum(c["quarterly"]["present"] for c in companies),
            "earnings_ok": sum(c["earnings"]["ok"] for c in companies),
        },
        "items": [
            {
                "item": i,
                "label": labels[i],
                "optional": i in optional,
                "required": item_cells[i][0],
                "present": item_cells[i][1],
            }
            for i in all_items
        ],  # fmt: skip
        "years": [
            {"fiscal_year": y, "required": v[0], "present": v[1]}
            for y, v in sorted(year_cells.items())
        ],
        "sectors": [{"sector": k, **v} for k, v in sorted(sectors.items())],
        "freshness": {
            "newest_price": price_last,
            "prices_stale": sum(
                not c["prices"]["ok"] and c["prices"]["last"] is not None for c in companies
            ),
            "no_filing_120_days": stale_filing,
            "newest_filing": max(
                (c["last_filed"] for c in companies if c["last_filed"]), default=None
            ),
        },  # fmt: skip
        "sources": [{"source": k, "values": int(v)} for k, v in source_mix.value_counts().items()],
        "quality": quality,
        "pipeline": pipeline(conn),
        "companies": companies,
        "item_order": all_items,
    }


def choose_mode(detail: dict, threshold: float) -> str:
    t = detail["totals"]
    share = t["cells_present"] / t["cells_required"] if t["cells_required"] else 0
    never = detail["pipeline"]["never_fetched"]
    return "maintain" if share >= threshold and not never else "backfill"


def snapshot(db: Database, config: dict | None = None, today: date | None = None) -> dict:
    """Compute today's coverage and store it (one row per day; a rerun replaces it). Returns
    the detail with the trend of every earlier snapshot."""
    cfg = config or load_config()
    with db.connect() as conn:
        detail = compute(conn, cfg, today)
    detail["mode"] = choose_mode(detail, float(cfg.get("present_share_to_maintain", 0.90)))
    t = detail["totals"]
    with db.begin() as conn:
        trend = frame(
            conn,
            "SELECT snapshot_date AS date, companies, companies_covered, cells_required, "
            "cells_present FROM out_coverage_snapshot WHERE snapshot_date < :d "
            "ORDER BY snapshot_date",
            {"d": detail["as_of"]},
        ).to_dict("records")
        trend.append(
            {"date": detail["as_of"], **{k: t[k] for k in
             ("companies", "companies_covered", "cells_required", "cells_present")}}
        )  # fmt: skip
        detail["trend"] = trend
        run(
            conn,
            "INSERT INTO out_coverage_snapshot (snapshot_date, computed_at, universe, companies, "
            "companies_covered, cells_required, cells_present, mode, detail_json) VALUES "
            "(:d, :t, :u, :n, :c, :r, :p, :m, :j) ON CONFLICT (snapshot_date) DO UPDATE SET "
            "computed_at = excluded.computed_at, universe = excluded.universe, "
            "companies = excluded.companies, companies_covered = excluded.companies_covered, "
            "cells_required = excluded.cells_required, cells_present = excluded.cells_present, "
            "mode = excluded.mode, detail_json = excluded.detail_json",
            {
                "d": detail["as_of"],
                "t": detail["computed_at"][:19],
                "u": detail["universe"],
                "n": t["companies"],
                "c": t["companies_covered"],
                "r": t["cells_required"],
                "p": t["cells_present"],
                "m": detail["mode"],
                "j": json.dumps(detail, default=str),
            },
        )
    return {**t, "mode": detail["mode"], "detail": detail}


def summary_lines(detail: dict) -> list[str]:
    t = detail["totals"]

    def pct(a, b):
        return f"{a:,} of {b:,} ({a / b:.0%})" if b else f"{a:,} of 0"

    lines = [
        f"Coverage of {detail['universe']} on {detail['as_of']} (mode: {detail.get('mode')})",
        f"  companies covered   {pct(t['companies_covered'], t['companies'])}",
        f"  required values     {pct(t['cells_present'], t['cells_required'])}",
        f"  prices complete     {pct(t['prices_ok'], t['companies'])}",
        f"  fiscal-year values  {pct(t['annual_present'], t['annual_required'])}",
        f"  quarterly values    {pct(t['quarterly_present'], t['quarterly_required'])}",
        f"  reported EPS        {pct(t['earnings_ok'], t['companies'])}",
        "  by item (fiscal years):",
    ]
    for i in detail["items"]:
        flag = " (optional)" if i["optional"] else ""
        lines.append(f"    {i['item']:<20} {pct(i['present'], i['required'])}{flag}")
    p = detail["pipeline"]
    lines.append(
        f"  ingest: {p['never_fetched']:,} tasks never fetched"
        + (f", about {p['runs_to_finish']} runs to finish" if p["runs_to_finish"] else "")
    )
    return lines
