"""The database: migrations, file import into raw, user and out, the raw-to-core build, the
views and the check. On PostgreSQL: the `stock_test` database in the local Docker container
(compose.yaml), or STOCK_TEST_PG_URL. Every test empties that database first. Without a
reachable PostgreSQL the database tests are skipped. No network beyond this machine."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv
from seed_files import load_all
from sqlalchemy import text

from stock_analysis.db import ROOT, Database, iso, migrations, statements, target_settings
from stock_analysis.db.build import adjusted_close, build, build_ttm
from stock_analysis.db.check import Reader, run_checks

load_dotenv(ROOT / ".env")
TEST_URL = os.environ.get("STOCK_TEST_PG_URL", "postgresql://stock@127.0.0.1:5432/stock_test")
PASSWORD_ENV = "STOCK_DB_PASSWORD"
QUARTERS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
WATCHLIST = """
timezone = "Europe/Rome"

[[stock]]
symbol = "AAA"
peers = ["BBB", "CCC"]
target_pe = 12
target_note = "test"
eps_override = [{ reported = "2026-02-01", eps = 0.25, reason = "one-off" }]

[[stock]]
symbol = "BBB"
peers = []
target_pe = 20
stakes_per_share = 1.5
"""


def write_csv(path: Path, df: pd.DataFrame, index: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=index)


def prices_frame() -> pd.DataFrame:
    days = pd.bdate_range("2015-12-01", "2026-09-30")
    p = pd.DataFrame(
        {
            "date": days.strftime("%Y-%m-%d"),
            "Open": 10.0,
            "High": 11.0,
            "Low": 9.0,
            "Close": 10.0,
            "Adj Close": 9.5,
            "Volume": 1000.0,
            "Dividends": 0.0,
            "Stock Splits": 0.0,
        }
    )
    p.loc[p["date"] == "2026-06-01", "Stock Splits"] = 2.0
    p.loc[p["date"] == "2026-03-02", "Dividends"] = 0.5
    return p


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    aaa = data / "AAA"
    write_csv(aaa / "prices_daily.csv", prices_frame())
    (aaa / "_meta.json").write_text(json.dumps({"fetched_at": "2026-09-27T12:00:00+00:00"}))
    q = pd.DataFrame(
        {
            "Total Revenue": [100.0, 110.0, 120.0, 130.0],
            "Diluted EPS": [1.0, 1.0, 1.0, 1.0],
            "Operating Income": [20.0, 20.0, 20.0, 20.0],
            "Reconciled Depreciation": [5.0, 5.0, 5.0, 5.0],
            "EBITDA": [99.0, 99.0, 99.0, 99.0],  # the derived value wins
        },
        index=pd.Index(QUARTERS, name="period_end"),
    )
    write_csv(aaa / "income_quarterly.csv", q, index=True)
    bs = pd.DataFrame(
        {
            "Current Debt": [5.0] * 4,
            "Long Term Debt": [45.0] * 4,
            "Total Debt": [60.0] * 4,  # includes leases: the derived total wins
            "Ordinary Shares Number": [10.0] * 4,
            "Total Assets": [200.0] * 4,
            "Total Liabilities Net Minority Interest": [120.0, 120.0, 120.0, 150.0],
            "Stockholders Equity": [80.0] * 4,
        },
        index=pd.Index(QUARTERS, name="period_end"),
    )
    write_csv(aaa / "balance_sheet_quarterly.csv", bs, index=True)

    def snapshot(symbols: list[str]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "tv_symbol": [f"NYSE:{s}" for s in symbols],
                "name": symbols,
                "description": [f"{s} Corp" for s in symbols],
                "exchange": "NYSE",
                "country": "United States",
                "sector": "Utilities",
                "industry": "Electric Utilities",
                "market_cap_basic": 1e9,
                "currency": "USD",
                "close": 10.0,
                "total_debt_fq": None,
            }
        )

    screener = data / "screener"
    write_csv(screener / "2026-11-12.csv", snapshot(["AAA", "BBB", "CCC"]))
    write_csv(screener / "2026-11-13.csv", snapshot(["AAA", "BBB"]))  # CCC left
    stage1 = snapshot(["AAA", "BBB"])[["tv_symbol", "sector", "close"]]
    write_csv(screener / "stage1.csv", stage1.assign(category="stalwart", status="pass"))
    write_csv(
        screener / "top.csv",
        stage1.assign(name=["AAA", "BBB"], rank_in_sector=[1, 2], cheap_price=[12.0, 8.0]),
    )

    history = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA", "AAA", "ZZZ"],
            "fiscal_year_end": ["2024-12-31", "2025-12-31", "2025-12-31", "2025-12-31"],
            "column": ["revenue", "revenue", "cash", "revenue"],
            "value": [0.4, 0.5, 0.02, 9.0],  # $bn
            "source": ["SEC"] * 4,
        }
    )
    write_csv(data / "sector" / "history.csv", history)
    utilities = pd.DataFrame(
        {"symbol": ["AAA"], "price": [10.0], "dcf_fair_value": [14.0], "dcf_method": ["fcff"],
         "wacc": [0.07]}
    )  # fmt: skip
    write_csv(data / "sector" / "utilities.csv", utilities)
    (data / "sector" / "_meta.json").write_text(json.dumps({"fetched_at": "2026-09-28T02:55Z"}))

    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "watchlist.toml").write_text(WATCHLIST, encoding="utf-8")
    runs = pd.DataFrame(
        {
            "run": ["2026-11-12 21:32 CET", "2026-11-13 20:53 CET"],
            "file": ["2026-11-12_2132.pdf", "2026-11-13_2053.pdf"],
            "price": [10.0, 11.0],
            "eps_adj_ttm": [1.0, 1.0],
            "pe_adj": [10.0, 11.0],
            "pe_median_10y": [15.0, 15.0],
            "target_pe": [12, 12],
            "entry_price": [12.0, 12.0],
            "to_entry": [0.2, 0.0909],
            "verdict": ["cheap", "near entry"],
            "stakes_per_share": [None, None],
        }
    )
    write_csv(tmp_path / "analyses" / "AAA" / "runs.csv", runs)
    market = pd.DataFrame({"run": ["2026-11-13 20:53 CET"], "file": ["x.pdf"], "sp500": [1.0]})
    write_csv(tmp_path / "analyses" / "market" / "runs.csv", market)  # not a stock: skipped
    return data


@pytest.fixture(scope="session")
def pg_url() -> str:
    db = Database(TEST_URL, os.environ.get(PASSWORD_ENV))
    try:
        with db.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
    except Exception as exc:  # no server: skip, do not fail
        pytest.skip(f"no test PostgreSQL at {db.where} (docker compose up -d --wait): {exc}")
    finally:
        db.close()
    return TEST_URL


def empty_db(url: str) -> Database:
    """The test database with nothing in it (not migrated)."""
    db = Database(url, os.environ.get(PASSWORD_ENV))
    with db.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    return db


@pytest.fixture()
def fresh(pg_url: str):
    db = empty_db(pg_url)
    db.migrate()
    yield db
    db.close()


class Rows:
    def __init__(self, rows, keys):
        self.rows, self._keys = rows, list(keys)

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self.rows)


def q(db: Database, sql: str, *params) -> Rows:
    """Run a query with ? placeholders; dates come back as ISO text."""
    names = iter(range(len(params)))
    sql = re.sub(r"\?", lambda _: f":p{next(names)}", sql)
    with db.connect() as conn:
        res = conn.execute(text(sql), {f"p{i}": v for i, v in enumerate(params)})
        return Rows([tuple(iso(v) for v in r) for r in res.fetchall()], res.keys())


@pytest.fixture()
def con(fresh: Database, data_dir: Path):
    load_all(fresh, data_dir)
    return fresh


def one(con, sql: str, *params):
    return q(con, sql, *params).fetchone()[0]


def test_migrations_recorded(con) -> None:
    assert one(con, "SELECT MAX(version) FROM schema_version") == migrations()[-1][0]
    for _, path in migrations():
        assert "{{" not in path.read_text(encoding="utf-8")


def test_existing_database_is_upgraded(pg_url: str) -> None:
    db = empty_db(pg_url)
    version, path = migrations()[0]
    with db.begin() as conn:
        for statement in statements(path.read_text(encoding="utf-8")):
            conn.exec_driver_sql(statement)
        conn.execute(text("INSERT INTO schema_version VALUES (:v, '2026-11-16')"), {"v": version})
    assert db.migrate() == migrations()[-1][0]
    columns = {
        r[0]
        for r in q(
            db,
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'core_price_daily'",
        )
    }
    assert {"open", "high", "low"} <= columns
    db.close()


def test_old_database_is_refused(pg_url: str) -> None:
    db = empty_db(pg_url)
    with db.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE raw_fetch (fetch_id INTEGER)")
    with pytest.raises(RuntimeError, match="predates the migrations"):
        db.migrate()
    db.close()


def test_load_files_and_rerun(fresh: Database, data_dir: Path) -> None:
    c = fresh
    added = load_all(c, data_dir)
    assert added["raw_yahoo_price"] == len(prices_frame())
    assert added["raw_yahoo_statement"] == 4 * 5 + 4 * 7
    assert added["raw_tv_constituent"] == 5
    assert added["raw_project_history"] == 4
    assert added["out_screener_result"] == 4
    assert added["out_valuation"] == 1
    assert added["user_watchlist"] == 2 + 2 + 1  # stocks, peers, EPS overrides
    assert added["out_watchlist_run"] == 2
    extra = json.loads(one(c, "SELECT extra_json FROM raw_tv_constituent LIMIT 1"))
    assert extra == {"close": 10.0, "total_debt_fq": None}
    assert set(load_all(c, data_dir).values()) == {0}

    # A changed file adds only the rows that changed.
    p = prices_frame()
    p.loc[p["date"] == "2026-09-30", "Close"] = 11.0
    write_csv(data_dir / "AAA" / "prices_daily.csv", p)
    assert load_all(c, data_dir)["raw_yahoo_price"] == 1
    assert one(c, "SELECT rows_stored FROM raw_fetch ORDER BY fetch_id DESC LIMIT 1") == 1


def test_companies_membership_and_prices(con) -> None:
    build(con)
    assert one(con, "SELECT COUNT(*) FROM core_company WHERE symbol = 'ZZZ'") == 0
    spells = dict(
        q(
            con,
            "SELECT c.symbol, m.end_date FROM core_index_member m "
            "JOIN core_company c ON c.company_id = m.company_id",
        ).fetchall()
    )
    assert spells == {"AAA": None, "BBB": None, "CCC": "2026-11-12"}
    assert one(con, "SELECT MIN(date) FROM core_price_daily") >= "2016-01-01"
    ohlc = "SELECT open, high, low, close FROM core_price_daily LIMIT 1"
    assert tuple(q(con, ohlc).fetchone()) == (10.0, 11.0, 9.0, 10.0)
    before = one(con, "SELECT adj_close FROM core_price_daily WHERE date = '2026-02-27'")
    after = one(con, "SELECT adj_close FROM core_price_daily WHERE date = '2026-03-02'")
    assert before == pytest.approx(10.0 * (1 - 0.5 / 10.0))
    assert after == 10.0


def test_adjusted_close_matches_yahoo_formula() -> None:
    close = pd.Series([10.0, 10.0, 9.5, 9.5])
    dividends = pd.Series([0.0, 0.0, 0.5, 0.0])
    assert adjusted_close(close, dividends).tolist() == pytest.approx([9.5, 9.5, 9.5, 9.5])


def test_fundamentals(con) -> None:
    build(con)

    def value(item: str, period_type: str, end: str) -> float:
        return one(
            con,
            "SELECT value FROM core_fundamental WHERE item = ? AND period_type = ? "
            "AND period_end = ?",
            item,
            period_type,
            end,
        )

    assert value("revenue", "FY", "2025-12-31") == pytest.approx(0.5e9)  # history, scaled
    assert value("revenue", "Q", "2025-03-31") == 100.0
    assert value("total_debt", "I", "2025-03-31") == 50.0  # 5 + 45, not Yahoo's 60
    assert value("ebitda", "Q", "2025-03-31") == 25.0  # 20 + 5, not Yahoo's 99
    row = q(
        con,
        "SELECT filed, filed_estimated, fiscal_period, raw_table, raw_id FROM core_fundamental "
        "WHERE item = 'revenue' AND period_type = 'FY' AND period_end = '2025-12-31'",
    ).fetchone()
    assert tuple(row)[:4] == ("2026-03-31", 1, "FY", "raw_project_history")
    assert row[4] is not None
    q1 = q(
        con,
        "SELECT filed, fiscal_year, fiscal_period FROM core_fundamental "
        "WHERE item = 'revenue' AND period_end = '2025-03-31'",
    ).fetchone()
    assert tuple(q1) == ("2025-05-15", 2025, "Q1")
    split = "SELECT split_factor FROM core_fundamental WHERE item = ? AND period_end = ?"
    assert one(con, split, "shares_outstanding", "2025-12-31") == 2.0  # filed before the split


def test_annual_and_daily_views(con) -> None:
    build(con)
    year = q(con, "SELECT * FROM v_annual WHERE symbol = 'AAA' AND fiscal_year = 2025")
    year = dict(zip(year.keys(), year.fetchone(), strict=True))
    assert year["revenue"] == pytest.approx(0.5e9)
    assert year["total_debt"] == 50.0
    assert year["shares_outstanding"] == 20.0

    def day(date: str) -> dict:
        cur = q(con, "SELECT * FROM v_daily WHERE symbol = 'AAA' AND date = ?", date)
        return dict(zip(cur.keys(), cur.fetchone(), strict=True))

    assert day("2025-03-28")["revenue_ttm"] is None  # nothing filed yet
    assert day("2025-03-31")["revenue_ttm"] == pytest.approx(0.4e9)  # FY2024
    d = day("2026-04-01")
    assert d["revenue_ttm"] == pytest.approx(0.5e9)
    assert d["ebitda_ttm"] == 100.0  # four quarters of 25
    assert d["eps_diluted_ttm"] == 2.0  # 4.0 before the 2-for-1 split
    assert (d["total_debt"], d["shares_outstanding"], d["market_cap"]) == (50.0, 20.0, 200.0)


def test_ttm_keeps_every_version(fresh: Database) -> None:
    """A restated quarter gives a second trailing value from its filing date."""
    rows = [
        ("2025-03-31", "2025-05-01", 10.0),
        ("2025-06-30", "2025-08-01", 10.0),
        ("2025-09-30", "2025-11-01", 10.0),
        ("2025-12-31", "2026-02-01", 10.0),
        ("2025-06-30", "2026-03-01", 20.0),  # restated
    ]
    f = pd.DataFrame(rows, columns=["period_end", "filed", "value"]).assign(
        company_id=1, item="revenue", period_type="Q", filed_estimated=False, source="sec"
    )
    f["value_adj"] = f["value"]
    with fresh.begin() as conn:
        conn.execute(text("INSERT INTO core_company (company_id, symbol) VALUES (1, 'AAA')"))
        conn.execute(
            text(
                "INSERT INTO core_item (item, label, kind, unit) "
                "VALUES ('revenue', 'R', 'flow', 'USD')"
            )
        )
        ttm = build_ttm(conn, f).sort_values("filed")
    assert ttm[["filed", "value"]].values.tolist() == [["2026-02-01", 40.0], ["2026-03-01", 50.0]]


def test_quality_issues_and_rebuild(con) -> None:
    first = build(con)
    checks = {
        r[0]
        for r in q(
            con,
            "SELECT check_name FROM core_quality_issue WHERE build_id = ?",
            first["build_id"],
        )
    }
    assert "balance_sheet_identity" in checks  # 200 vs 150 + 80 at 2025-12-31
    ids = dict(q(con, "SELECT symbol, company_id FROM core_company").fetchall())
    second = build(con)
    assert second["core_fundamental"] == first["core_fundamental"]
    assert dict(q(con, "SELECT symbol, company_id FROM core_company").fetchall()) == ids


CORE_SNAPSHOT = {
    "core_fundamental": "SELECT company_id, item, period_type, period_end, filed, value, "
    "split_factor, method, source FROM core_fundamental",
    "core_fundamental_ttm": "SELECT company_id, item, period_end, filed, basis, value, "
    "value_adj FROM core_fundamental_ttm",
    "core_price_daily": "SELECT company_id, date, close, adj_close FROM core_price_daily",
}


def core_rows(con) -> dict:
    return {t: sorted(map(tuple, q(con, sql).fetchall())) for t, sql in CORE_SNAPSHOT.items()}


def issue_rows(con, build_id) -> list:
    sql = (
        "SELECT company_id, item, at_date, check_name, detail FROM core_quality_issue "
        "WHERE build_id = ?"
    )
    return sorted(map(tuple, q(con, sql, build_id).fetchall()))


def test_incremental_build_rebuilds_only_what_changed_and_matches_a_full_one(con) -> None:
    first = build(con)
    assert first["mode"] == "full" and first["why"] == "core is empty: first build"
    again = build(con)  # nothing changed since
    assert again["mode"] == "incremental" and again["rebuilt"] == 0
    assert again["quality_issues"] == first["quality_issues"]
    # A new Yahoo price for AAA: only AAA is rebuilt.
    with con.begin() as conn:
        fetch = conn.execute(text(
            "INSERT INTO raw_fetch (source, request_key, fetched_at, loaded_at, status) "
            "VALUES ('yahoo_prices', 'AAA', '2026-11-18', '2026-11-18', 'ok') RETURNING fetch_id"
        )).scalar()  # fmt: skip
        conn.execute(text(
            "INSERT INTO raw_yahoo_price (fetch_id, symbol, date, close, volume, dividends, "
            "stock_splits) SELECT :f, symbol, date, close * 1.01, volume, dividends, stock_splits "
            "FROM raw_yahoo_price WHERE symbol = 'AAA' ORDER BY date DESC LIMIT 1"
        ), {"f": fetch})  # fmt: skip
    step = build(con)
    assert step["mode"] == "incremental" and step["rebuilt_symbols"] == ["AAA"]
    incremental, step_issues = core_rows(con), issue_rows(con, step["build_id"])
    full = build(con, full=True)
    assert full["mode"] == "full"
    assert core_rows(con) == incremental  # the same core as a full build
    assert issue_rows(con, full["build_id"]) == step_issues
    # Asked for one company.
    only = build(con, symbols=["BBB"])
    assert only["rebuilt_symbols"] == ["BBB"] and core_rows(con) == incremental


def test_check_sample_reports_changes_and_writes_nothing(con) -> None:
    """A dry run on a sample: what a rebuild of AAA would change, then rolled back."""
    build(con)
    builds = one(con, "SELECT COUNT(*) FROM core_build")
    with con.begin() as conn:  # a stored value that the sources don't give (a stale row)
        conn.execute(text(
            "UPDATE core_fundamental SET value = value + 1 WHERE company_id = (SELECT company_id "
            "FROM core_company WHERE symbol = 'AAA') AND item = 'revenue' AND period_type = 'FY'"
        ))  # fmt: skip
    before = core_rows(con)
    report = build(con, symbols=["AAA"], dry_run=True)
    assert report["companies"] == ["AAA"] and "rolled back" in report["mode"]
    changed = [c for c in report["changes"] if c["change"] == "changed"]
    assert changed and {c["item"] for c in changed} == {"revenue"}
    assert all(c["value_old"] == c["value_new"] + 1 for c in changed)
    assert core_rows(con) == before  # nothing written
    assert one(con, "SELECT COUNT(*) FROM core_build") == builds
    with pytest.raises(ValueError):
        build(con, dry_run=True)  # a dry run needs a sample


def test_out_tables(con) -> None:
    top = q(
        con,
        "SELECT symbol, rank_in_sector, cheap_price FROM out_screener_result WHERE stage = 2 "
        "ORDER BY rank_in_sector",
    ).fetchall()
    assert [tuple(r) for r in top] == [("AAA", 1, 12.0), ("BBB", 2, 8.0)]
    v = q(con, "SELECT as_of, method, fair_value FROM out_valuation").fetchone()
    assert tuple(v) == ("2026-09-28", "fcff", 14.0)


def test_targets(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert target_settings()["name"] == "local"  # the selected target in config/database.toml
    config = {
        "selected": "local",
        "targets": {"local": {"url": "postgresql://a@127.0.0.1/x"}, "server": {"url": ""}},
    }
    assert target_settings(config=config)["url"] == "postgresql://a@127.0.0.1/x"
    with pytest.raises(ValueError, match="no url"):
        target_settings("server", config)
    with pytest.raises(ValueError, match="No target"):
        target_settings("other", config)
    monkeypatch.setenv("DATABASE_URL", "postgresql://b@127.0.0.1/y")
    assert target_settings(config=config)["name"] == "DATABASE_URL"
    assert target_settings("local", config)["url"] == "postgresql://a@127.0.0.1/x"  # --target
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/stock.db")
    with pytest.raises(ValueError, match="Only PostgreSQL"):
        target_settings(config=config)


def test_check_passes_on_a_built_database(con: Database, pg_url: str) -> None:
    build(con)
    db = Reader(pg_url, PASSWORD_ENV)
    settings = {"sample_symbols": ["AAA"], "max_age_days": 7, "min_coverage": 0.3}
    results = {r.name: r for r in run_checks(db, settings, today=date(2026, 11, 14))}
    db.close()
    assert not [r for r in results.values() if r.status == "FAIL"], results
    assert results["AAA prices"].status == "PASS"
    assert results["AAA fiscal years"].status == "PASS"
    assert results["newest price"].status == "WARN"  # 2026-09-30 is 45 days old
    assert results["rows in raw_sec_fact"].status == "WARN"  # no SEC loader yet
    assert results["watch list"].detail == "2 stocks, 1 with runs, 1 with prices in core"


def test_check_fails_on_an_empty_database(fresh: Database, pg_url: str) -> None:
    db = Reader(pg_url, PASSWORD_ENV)
    results = {r.name: r for r in run_checks(db, {"sample_symbols": ["AAA"]})}
    db.close()
    assert results["last build"].status == "FAIL"
    assert results["rows in core_price_daily"].status == "FAIL"
    assert results["AAA"].status == "FAIL"


def test_derived_value_never_overrides_a_better_source() -> None:
    from stock_analysis.db.build import derive

    base = {
        "company_id": 1,
        "period_type": "FY",
        "period_end": "2025-12-31",
        "filed": "2026-03-31",
        "filed_estimated": True,
        "fiscal_year": 2025,
        "fiscal_period": "FY",
        "method": "reported",
    }
    f = pd.DataFrame(
        [
            {**base, "item": "ebitda", "value": 10.0, "source": "history:SEC", "rank": 2},
            {**base, "item": "operating_income", "value": 7.0, "source": "yahoo", "rank": 3},
            {**base, "item": "d_and_a", "value": 5.0, "source": "yahoo", "rank": 3},
        ]
    )
    items = pd.DataFrame(
        [{"item": "ebitda", "kind": "flow", "derive": "operating_income + d_and_a"}]
    )
    out = derive(f, items)
    assert out.loc[out["item"] == "ebitda", "value"].tolist() == [10.0]
    f.loc[0, "rank"] = 3  # same rank: the derived value wins
    out = derive(f, items)
    assert out.loc[out["item"] == "ebitda", "value"].tolist() == [12.0]


def test_liabilities_derived_with_optional_part_and_reported_wins() -> None:
    from stock_analysis.db.build import derive, parse_derive

    assert parse_derive("a - b - c?") == [(1, "a", False), (-1, "b", False), (-1, "c", True)]
    base = {"company_id": 1, "period_type": "I", "filed": "2026-03-31",
            "filed_estimated": False, "fiscal_year": 2025, "fiscal_period": "Q4",
            "method": "reported", "source": "sec", "rank": 1}  # fmt: skip
    f = pd.DataFrame(
        [
            {**base, "period_end": "2024-12-31", "item": "liabilities_and_equity", "value": 100.0},
            {**base, "period_end": "2024-12-31", "item": "equity_total", "value": 30.0},
            {**base, "period_end": "2024-12-31", "item": "temporary_equity", "value": 5.0},
            {**base, "period_end": "2025-12-31", "item": "liabilities_and_equity", "value": 120.0},
            {**base, "period_end": "2025-12-31", "item": "equity_total", "value": 40.0},
            {**base, "period_end": "2025-06-30", "item": "liabilities_and_equity", "value": 110.0},
            {**base, "period_end": "2025-06-30", "item": "equity_total", "value": 35.0},
            {**base, "period_end": "2025-06-30", "item": "total_liabilities", "value": 74.0},
            {**base, "period_end": "2025-03-31", "item": "equity_total", "value": 33.0},
        ]
    )
    items = pd.DataFrame(
        [{"item": "total_liabilities", "kind": "instant", "derive_mode": "fallback",
          "derive": "liabilities_and_equity - equity_total - temporary_equity?"}]
    )  # fmt: skip
    out = derive(f, items)
    tl = out[out["item"] == "total_liabilities"].set_index("period_end")
    assert tl["value"].to_dict() == {"2024-12-31": 65.0, "2025-12-31": 80.0, "2025-06-30": 74.0}
    assert tl.loc["2025-06-30", "method"] == "reported"  # the company's own figure wins
    assert tl.loc["2024-12-31", "method"] == "derived"


def test_capex_is_the_sum_of_its_parts_when_no_total_is_reported() -> None:
    from stock_analysis.db.build import derive

    base = {"company_id": 1, "period_type": "FY", "filed": "2026-02-20",
            "filed_estimated": False, "fiscal_year": 2025, "fiscal_period": "FY",
            "method": "reported", "source": "sec", "rank": 1}  # fmt: skip
    rows = [
        ("2025-12-31", "capex_oil_gas", -6115.0),  # EOG: two lines, no total
        ("2025-12-31", "capex_other_property", -479.0),
        ("2024-12-31", "capex_construction", -8453.0),  # AEP: one line
        ("2023-12-31", "capex", -900.0),  # a reported total wins over its parts
        ("2023-12-31", "capex_other_property", -100.0),
    ]
    f = pd.DataFrame([{**base, "period_end": e, "item": i, "value": v} for e, i, v in rows])
    items = pd.DataFrame(
        [{"item": "capex", "kind": "flow", "derive_mode": "fallback",
          "derive": "capex_oil_gas? + capex_other_property? + capex_construction?"}]
    )  # fmt: skip
    out = derive(f, items)
    capex = out[out["item"] == "capex"].set_index("period_end")["value"].to_dict()
    assert capex == {"2025-12-31": -6594.0, "2024-12-31": -8453.0, "2023-12-31": -900.0}


def test_custom_tags_are_summed_and_signed(con, monkeypatch) -> None:
    from stock_analysis.db import build as b

    rules = {
        "custom_tag": [{"symbol": "AAA", "item": "capex", "tags": ["UtilityCapex", "OtherCapex"]}]
    }
    monkeypatch.setattr(b, "load_companies", lambda: rules)
    with con.begin() as conn:
        conn.execute(text(
            "INSERT INTO core_company (symbol, cik) VALUES ('AAA', 1001) "
            "ON CONFLICT (symbol) DO UPDATE SET cik = 1001"
        ))  # fmt: skip
        fetch = conn.execute(text(
            "INSERT INTO raw_fetch (source, request_key, fetched_at, loaded_at, status) "
            "VALUES ('sec_fsds', 'q', '2026-01-01', '2026-01-01', 'ok') RETURNING fetch_id"
        )).scalar()  # fmt: skip
        for tag, v in (("UtilityCapex", 4399e6), ("OtherCapex", 68e6), ("Unrelated", 5e6)):
            conn.execute(text(
                "INSERT INTO raw_sec_xbrl_fact (fetch_id, cik, accn, form, filed, concept, unit, "
                "period_start, period_end, value, custom) VALUES (:f, 1001, 'a1', '10-K', "
                "'2025-02-20', :c, 'USD', '2024-01-01', '2024-12-31', :v, TRUE)"
            ), {"f": fetch, "c": f"custom:{tag}", "v": v})  # fmt: skip
        _, tags = b.load_items()
        x = b.custom_facts(conn, tags)
    assert len(x) == 1 and x["item"].iloc[0] == "capex" and x["value"].iloc[0] == 4467e6
    assert x["scale"].iloc[0] == -1.0  # stored negative, like the other capex


def test_share_class_reads_the_listed_class_and_its_own_tag(con, monkeypatch) -> None:
    """AAA's diluted EPS per class A (the item's sec_class tag); BBB files basic only
    (Berkshire), named for it in [[share_class]] tags. Other classes and tags are ignored."""
    from stock_analysis.db import build as b

    rules = {"share_class": [
        {"symbol": "AAA", "member": "us-gaap:CommonClassAMember"},
        {"symbol": "BBB", "member": "us-gaap:EquivalentClassBMember",
         "tags": {"eps_diluted": ["us-gaap:EarningsPerShareBasic"]}},
    ]}  # fmt: skip
    monkeypatch.setattr(b, "load_companies", lambda: rules)
    facts = [
        (1001, "us-gaap:EarningsPerShareDiluted", "us-gaap:CommonClassAMember", 2.5),
        (1001, "us-gaap:EarningsPerShareDiluted", "us-gaap:CommonClassBMember", 9.0),
        (1001, "us-gaap:EarningsPerShareBasic", "us-gaap:CommonClassAMember", 2.6),
        (1002, "us-gaap:EarningsPerShareBasic", "us-gaap:EquivalentClassBMember", 41.27),
        (1002, "us-gaap:EarningsPerShareBasic", "us-gaap:EquivalentClassAMember", 61900.0),
    ]
    with con.begin() as conn:
        for sym, cik in (("AAA", 1001), ("BBB", 1002)):
            conn.execute(text(
                "INSERT INTO core_company (symbol, cik) VALUES (:s, :c) "
                "ON CONFLICT (symbol) DO UPDATE SET cik = :c"
            ), {"s": sym, "c": cik})  # fmt: skip
        fetch = conn.execute(text(
            "INSERT INTO raw_fetch (source, request_key, fetched_at, loaded_at, status) "
            "VALUES ('sec_fsds', 'q', '2026-01-01', '2026-01-01', 'ok') RETURNING fetch_id"
        )).scalar()  # fmt: skip
        for cik, concept, member, v in facts:
            conn.execute(text(
                "INSERT INTO raw_sec_xbrl_fact (fetch_id, cik, accn, form, filed, concept, axis, "
                "member, unit, period_start, period_end, value) VALUES (:f, :cik, 'a1', '10-K', "
                "'2025-02-20', :c, :axis, :m, 'USD/shares', '2024-01-01', '2024-12-31', :v)"
            ), {"f": fetch, "cik": cik, "c": concept, "axis": b.CLASS_AXIS, "m": member,
                "v": v})  # fmt: skip
        _, tags = b.load_items()
        x = b.class_facts(conn, tags)
    got = dict(zip(x["symbol"], x["value"], strict=True))
    assert got == {"AAA": 2.5, "BBB": 41.27}
    assert set(x["item"]) == {"eps_diluted"}


def test_share_class_converts_units_and_drops_yahoo(con, monkeypatch) -> None:
    """Berkshire states its shares in equivalent Class A shares (data-set member without a
    prefix, edgartools with brka:); BRK.B's count is 1,500 times that, and Yahoo's A-unit
    count is not used."""
    from stock_analysis.db import build as b

    rule = {"symbol": "BBB", "member": "us-gaap:EquivalentClassBMember",
            "convert": [{"item": "shares_outstanding",
                         "concept": "us-gaap:CommonStockSharesOutstanding",
                         "member": "brka:EquivalentClassAMember", "factor": 1500}],
            "not_from_yahoo": ["shares_outstanding"]}  # fmt: skip
    monkeypatch.setattr(b, "load_companies", lambda: {"share_class": [rule]})
    with con.begin() as conn:
        conn.execute(text(
            "INSERT INTO core_company (symbol, cik) VALUES ('BBB', 1002) "
            "ON CONFLICT (symbol) DO UPDATE SET cik = 1002"
        ))  # fmt: skip
        fetch = conn.execute(text(
            "INSERT INTO raw_fetch (source, request_key, fetched_at, loaded_at, status) "
            "VALUES ('sec_xbrl', 'k', '2026-01-01', '2026-01-01', 'ok') RETURNING fetch_id"
        )).scalar()  # fmt: skip
        for member, v in (("brka:EquivalentClassAMember", 1438223.0),
                          ("us-gaap:CommonClassAMember", 547562.0)):  # fmt: skip
            conn.execute(text(
                "INSERT INTO raw_sec_xbrl_fact (fetch_id, cik, accn, form, filed, concept, axis, "
                "member, unit, period_end, value) VALUES (:f, 1002, 'a1', '10-K', '2025-02-20', "
                "'us-gaap:CommonStockSharesOutstanding', :axis, :m, 'shares', '2024-12-31', :v)"
            ), {"f": fetch, "axis": b.CLASS_AXIS, "m": member, "v": v})  # fmt: skip
        _, tags = b.load_items()
        x = b.class_facts(conn, tags)
    assert list(x["item"]) == ["shares_outstanding"]
    assert list(x["value"]) == [1438223.0 * 1500]
    assert b.yahoo_excluded([rule]) == {("BBB", "shares_outstanding")}


def test_watchlist(con, tmp_path: Path, data_dir: Path) -> None:
    rows = q(
        con,
        "SELECT symbol, target_pe, stakes_per_share, last_run_at, price, verdict "
        "FROM v_watchlist ORDER BY position",
    ).fetchall()
    assert rows == [
        ("AAA", 12.0, None, "2026-11-13T19:53:00", 11.0, "near entry"),  # 20:53 CET in UTC
        ("BBB", 20.0, 1.5, None, None, None),
    ]
    assert one(con, "SELECT peer FROM user_watchlist_peer WHERE position = 2") == "CCC"
    assert one(con, "SELECT eps FROM user_eps_override WHERE symbol = 'AAA'") == 0.25
    # The TOML is the master copy: an edit replaces the mirror, no edit changes nothing.
    toml = tmp_path / "config" / "watchlist.toml"
    toml.write_text(WATCHLIST.replace("target_pe = 20", "target_pe = 25"), encoding="utf-8")
    assert load_all(con, data_dir)["user_watchlist"] == 5
    assert one(con, "SELECT target_pe FROM user_watchlist WHERE symbol = 'BBB'") == 25.0
    assert load_all(con, data_dir)["user_watchlist"] == 0


def test_allow_my_ip_builds_the_azure_command(monkeypatch) -> None:
    from stock_analysis.db import azure

    calls = []

    class Done:
        returncode, stdout, stderr = 0, '{"name": "home"}', ""

    monkeypatch.setattr(azure, "public_ip", lambda: "203.0.113.7")
    monkeypatch.setattr(azure, "az_command", lambda: "az")
    monkeypatch.setattr(azure.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    monkeypatch.delenv("DATABASE_URL", raising=False)
    message = azure.allow_my_ip("server")
    cmd = calls[0]
    assert cmd[1:5] == ["postgres", "flexible-server", "firewall-rule", "create"]
    assert cmd[cmd.index("--server-name") + 1] == "stock-db-bk"
    assert cmd[cmd.index("--name") + 1] == "home"
    assert cmd[cmd.index("--start-ip-address") + 1] == "203.0.113.7"
    assert message.endswith("now allows 203.0.113.7")
    azure.allow_my_ip("server", "claude-cloud", "198.51.100.9")
    cmd = calls[1]
    assert cmd[cmd.index("--name") + 1] == "claude-cloud"
    assert cmd[cmd.index("--end-ip-address") + 1] == "198.51.100.9"
    message = azure.allow_my_ip("server", "claude-cloud", "160.79.104.0/21")
    assert calls[2][calls[2].index("--start-ip-address") + 1] == "160.79.104.0"
    assert calls[2][calls[2].index("--end-ip-address") + 1] == "160.79.111.255"
    assert message.endswith("160.79.104.0 to 160.79.111.255")


def test_data_layer_reads_writes_and_safe_sql(con: Database) -> None:
    from stock_analysis.data import DbData

    build(con)
    data = DbData(con, con)
    assert data.watchlist()["symbol"].tolist() == ["AAA", "BBB"]
    assert data.annual("AAA").loc[0, "fiscal_year"] == 2024
    assert len(data.prices("AAA", start="2026-09-01")) == 22
    assert set(data.screener(stage=2)["symbol"]) == {"AAA", "BBB"}
    assert data.status()["schema_version"] == migrations()[-1][0]
    assert data.save_note("AAA", "## Thesis\ncheap") == 1
    assert data.notes("AAA").loc[0, "text"].startswith("## Thesis")
    run_row = {"symbol": "AAA", "run_at": "2026-11-20T20:00:00", "price": 9.0, "verdict": "x"}
    assert data.save_watchlist_run(run_row) == 1
    assert len(data.watchlist_runs("AAA")) == 3
    with pytest.raises(ValueError, match="Unknown fields"):
        data.save_watchlist_run({"symbol": "AAA", "run_at": "2026-11-21", "oops": 1})
    assert data.sql("SELECT symbol FROM core_company ORDER BY symbol", limit=1)[
        "symbol"
    ].tolist() == ["AAA"]
    for bad in ("DELETE FROM out_note", "SELECT 1; DROP TABLE out_note"):
        with pytest.raises(ValueError):
            data.sql(bad)
    # Even a SELECT that writes (a function call) runs in a read-only transaction.
    with pytest.raises(Exception, match="read-only"):
        data.sql("SELECT nextval('out_screener_run_run_id_seq')")


def test_ping_diagnoses_a_working_connection(pg_url: str, capsys, monkeypatch) -> None:
    from stock_analysis.db.ping import ping

    password = os.environ.get(PASSWORD_ENV, "")
    monkeypatch.setenv("DATABASE_URL", pg_url.replace("stock@", f"stock:{password}@", 1))
    assert ping() == 0
    out = capsys.readouterr().out
    assert "PASS  TCP connect" in out and "PASS  login" in out


class FakeProxy:
    """A local HTTP proxy that answers CONNECT and tunnels to the requested host:port."""

    def __init__(self, refuse: bool = False):
        import socket
        import threading

        from stock_analysis.db import tunnel

        self.requests: list[str] = []
        self.refuse = refuse
        self.server = socket.create_server(("127.0.0.1", 0))
        self.url = f"http://user:secret@127.0.0.1:{self.server.getsockname()[1]}"

        def handle(client):
            head = b""
            while b"\r\n\r\n" not in head:
                head += client.recv(4096)
            first = head.split(b"\r\n")[0].decode()
            self.requests.append(first)
            if self.refuse:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                client.close()
                return
            host, port = first.split(" ")[1].rsplit(":", 1)
            upstream = socket.create_connection((host, int(port)))
            client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            threading.Thread(target=tunnel.pipe, args=(client, upstream), daemon=True).start()
            tunnel.pipe(upstream, client)

        def serve():
            while True:
                client, _ = self.server.accept()
                threading.Thread(target=handle, args=(client,), daemon=True).start()

        threading.Thread(target=serve, daemon=True).start()


def test_connections_go_through_the_http_proxy(pg_url: str, monkeypatch, capsys) -> None:
    from stock_analysis.db.ping import ping

    proxy = FakeProxy()
    monkeypatch.setenv("HTTPS_PROXY", proxy.url)
    monkeypatch.setenv("NO_PROXY", "api.anthropic.com")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("STOCK_DB_PROXY", raising=False)
    password = os.environ.get(PASSWORD_ENV, "")
    url = pg_url.replace("stock@", f"stock:{password}@", 1)
    db = Database(url, read_only=True)
    try:
        assert db.local_port
        with db.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        db.close()
    assert proxy.requests and proxy.requests[0].startswith("CONNECT 127.0.0.1:")

    monkeypatch.setenv("DATABASE_URL", url)
    assert ping() == 0
    out = capsys.readouterr().out
    assert "through the HTTP proxy" in out and "PostgreSQL answered" in out and "PASS  login" in out

    monkeypatch.setenv("STOCK_DB_PROXY", "off")
    direct = Database(url, read_only=True)
    assert direct.local_port is None
    direct.close()


def test_ping_reports_a_proxy_that_refuses(pg_url: str, monkeypatch, capsys) -> None:
    from stock_analysis.db.ping import ping

    monkeypatch.setenv("HTTPS_PROXY", FakeProxy(refuse=True).url)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("DATABASE_URL", pg_url)
    assert ping() == 1
    out = capsys.readouterr().out
    assert "FAIL  TCP connect" in out and "403 Forbidden" in out


@pytest.fixture
def api(pg_url: str, monkeypatch):
    """The web API app (api/app.py) on the test database, called in-process."""
    import importlib.util

    from fastapi.testclient import TestClient

    password = os.environ.get(PASSWORD_ENV, "")
    url = pg_url.replace("stock@", f"stock:{password}@", 1)
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("DATABASE_WRITER_URL", url)
    monkeypatch.setenv("STOCK_API_KEY", "test-key")
    monkeypatch.setenv("CLAUDE_API_KEY", "claude-key")
    monkeypatch.syspath_prepend(str(ROOT / "api"))  # app.py imports operations.py beside it
    spec = importlib.util.spec_from_file_location("stock_api_app", ROOT / "api" / "app.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["stock_api_app"] = module
    spec.loader.exec_module(module)
    client = TestClient(module.app)
    yield client
    for setting in ("DATABASE_URL", "DATABASE_WRITER_URL"):
        module.engine(setting).dispose()


def test_api_needs_the_key_and_one_read_statement(con: Database, api) -> None:
    assert api.get("/health").json() == {"ok": True}
    assert api.post("/query", json={"sql": "SELECT 1"}).status_code == 401
    bad = api.post("/query", json={"sql": "SELECT 1"}, headers={"X-API-Key": "wrong"})
    assert bad.status_code == 401
    key = {"X-API-Key": "test-key"}
    for sql in ("DELETE FROM out_note", "SELECT 1; SELECT 2", "DROP TABLE out_note"):
        answer = api.post("/query", json={"sql": sql}, headers=key)
        assert answer.status_code == 400, sql
    sneaky = "WITH d AS (DELETE FROM out_note RETURNING *) SELECT * FROM d"
    answer = api.post("/query", json={"sql": sneaky}, headers=key)
    assert answer.status_code == 400 and "read-only" in answer.json()["detail"]
    answer = api.post("/execute", json={"steps": [{"sql": "DROP TABLE out_note"}]}, headers=key)
    assert answer.status_code == 400


def test_api_data_matches_the_database(con: Database, api) -> None:
    from stock_analysis.data import ApiData, DbData

    build(con)
    api.headers["X-API-Key"] = "test-key"
    via_api, direct = ApiData("http://testserver", client=api), DbData(con, con)
    for name in ("watchlist", "companies", "quality", "status"):
        pd.testing.assert_frame_equal(via_api.read(name), direct.read(name), check_dtype=False)
    pd.testing.assert_frame_equal(
        via_api.prices("AAA", start="2026-09-01"),
        direct.prices("AAA", start="2026-09-01"),
        check_dtype=False,
    )
    assert via_api.sql("SELECT symbol FROM core_company ORDER BY symbol", limit=1)[
        "symbol"
    ].tolist() == ["AAA"]
    answer = api.post("/query", json={"sql": "SELECT * FROM core_company", "limit": 1})
    assert answer.json()["truncated"] is True

    assert via_api.save_note("AAA", "via the API") == 1
    assert direct.notes("AAA")["text"].tolist() == ["via the API"]
    stocks = [{"symbol": "BBB", "target_pe": 15, "peers": ["AAA"]}]
    assert via_api.set_watchlist(stocks) == 2
    assert direct.watchlist()["symbol"].tolist() == ["BBB"]

    before = direct.notes()["text"].tolist()
    with pytest.raises(RuntimeError, match="400"):
        via_api.execute(
            [
                (
                    "INSERT INTO out_note (subject, updated_at, text, source) VALUES "
                    "('ZZZ', '2026-01-01T00:00:00', 'x', 'api')",
                    [],
                ),  # fmt: skip
                ("INSERT INTO no_such_table VALUES (1)", []),
            ]
        )
    assert direct.notes()["text"].tolist() == before  # all or nothing


def test_data_open_picks_the_api_when_configured(monkeypatch) -> None:
    from stock_analysis.data import ApiData, Data

    monkeypatch.setenv("STOCK_API_URL", "https://example.test")
    monkeypatch.setenv("STOCK_API_KEY", "k")
    data = Data.open()
    assert isinstance(data, ApiData)
    assert data.client.headers["X-API-Key"] == "k"
    assert str(data.client.base_url) == "https://example.test"


def test_companies_config_is_well_formed() -> None:
    """config/companies.toml parses and every entry has the keys the build reads."""
    from stock_analysis.db.build import load_companies

    cfg = load_companies()
    for c in cfg.get("share_class", []):
        assert c["symbol"] and c["member"]
        for r in c.get("convert", []):
            assert {"item", "concept", "member", "factor"} <= set(r) and float(r["factor"]) > 0
        assert all(isinstance(v, list) for v in c.get("tags", {}).values())
    for c in cfg.get("custom_tag", []):
        assert c["symbol"] and c["item"] and c["tags"]
    for c in cfg.get("predecessor", []):
        assert c["symbol"] and int(c["cik"]) and c["until"]


# --- the application's operations (issue #60) -------------------------------------------

CLAUDE = {"X-API-Key": "claude-key"}
RUN = "manual__2026-11-25T22:30:00+00:00"
RUN_URL = "/app/runs/manual__2026-11-25T22%3A30%3A00%2B00%3A00"
HEADINGS = ("Verdict", "Today", "Summary", "Business", "Risks", "News", "What to watch")
STOCK_NOTE = {s: f"{s} text" for s in HEADINGS} | {
    "News": "- 2026-11-20: deal ([Reuters](https://example.test/a))",
    "What to watch": "- Margins (ongoing)",
}


def open_run(con: Database, subjects: list[str]) -> None:
    with con.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO out_analysis_run (run_key, trading_day, subjects_json, opened_at) "
                "VALUES (:k, CURRENT_DATE - 1, :s, now() AT TIME ZONE 'UTC')"
            ),
            {"k": RUN, "s": json.dumps(subjects)},
        )


def test_app_claude_key_has_operations_but_no_general_sql(con: Database, api) -> None:
    assert api.get("/app/watchlist").status_code == 401
    assert api.get("/app/watchlist", headers=CLAUDE).status_code == 200
    body = {"steps": [{"sql": "DELETE FROM out_note"}]}
    assert api.post("/execute", json=body, headers=CLAUDE).status_code == 403
    assert api.post("/query", json={"sql": "SELECT 1"}, headers=CLAUDE).status_code == 403
    ok = api.post("/app/query", json={"sql": "SELECT 41 + 1 AS n"}, headers=CLAUDE)
    assert ok.json()["rows"] == [[42]]
    sneaky = "WITH d AS (DELETE FROM out_note RETURNING *) SELECT * FROM d"
    assert api.post("/app/query", json={"sql": sneaky}, headers=CLAUDE).status_code == 400
    calls = one(con, "SELECT string_agg(status::text, ' ' ORDER BY call_id) FROM ops_api_call")
    assert calls == "200 200 400"
    assert one(con, "SELECT detail FROM ops_api_call WHERE call_id = 2") == "SELECT 41 + 1 AS n"


def test_app_analysis_is_checked_saved_and_submitted(con: Database, api) -> None:
    api.headers.update(CLAUDE)
    assert api.get("/app/runs/current").status_code == 404
    open_run(con, ["AAA", "summaries"])
    assert api.get("/app/runs/current").json()["missing"] == ["AAA", "summaries"]
    assert "Today" in api.get(RUN_URL).json()["sections"]["AAA"]
    today = one(con, "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD')")
    put = f"{RUN_URL}/analyses"

    bad = api.put(f"{put}/AAA", json={"reviewed": today, "sections": {**STOCK_NOTE, "Risks": " "}})
    assert bad.status_code == 422 and bad.json()["detail"] == ["section missing or empty: Risks"]
    unsourced = {**STOCK_NOTE, "News": "- 2026-11-20: deal", "What to watch": "- Margins"}
    poor = api.put(f"{put}/AAA", json={"reviewed": today, "sections": unsourced})
    assert poor.status_code == 422 and len(poor.json()["detail"]) == 2  # no source, no date
    stale = api.put(f"{put}/AAA", json={"reviewed": "2026-01-01", "sections": STOCK_NOTE})
    assert stale.status_code == 422
    other = api.put(f"{put}/ZZZ", json={"reviewed": today, "sections": STOCK_NOTE})
    assert other.status_code == 422
    assert api.post(f"{RUN_URL}/submit", json={}).status_code == 409  # nothing saved

    fix = {"reported": "2026-02-01", "eps": 1.5, "reason": "a tax gain", "source": "10-Q, p. 4"}
    good = {"reviewed": today, "sections": STOCK_NOTE, "corrections": [fix]}
    overrides = one(con, "SELECT COUNT(*) FROM user_eps_override")
    for _ in range(2):  # saving again replaces
        saved = api.put(f"{put}/AAA", json=good)
        assert saved.json() == {"saved": "AAA", "missing": ["summaries"]}
    assert one(con, "SELECT COUNT(*) FROM out_analysis") == 1
    assert one(con, "SELECT COUNT(*) FROM user_eps_override") == overrides  # report only
    note = {"reviewed": today, "sections": {"Verdict": "v", "Analysis": "a"}}
    with_fix = api.put(f"{put}/summaries", json={**note, "corrections": [fix]})
    assert with_fix.status_code == 422
    assert api.put(f"{put}/summaries", json=note).status_code == 200
    assert api.post(f"{RUN_URL}/submit", json={"note": "all done"}).status_code == 200
    assert api.post(f"{RUN_URL}/submit", json={"note": "again"}).status_code == 200
    assert one(con, "SELECT submit_note FROM out_analysis_run") == "all done"
    assert api.put(f"{put}/AAA", json=good).status_code == 409
    newest = api.get("/app/analyses/aaa").json()[0]
    assert newest["corrections"] == [fix] and newest["saved_by"] == "claude"


def test_app_watchlist_changes_are_checked_kept_and_undone(con: Database, api) -> None:
    api.headers.update(CLAUDE)
    start = api.get("/app/watchlist").json()
    first = next(s for s in start if s["symbol"] == "AAA")

    for bad in (
        {"target_pe": 15},
        {"target_pe": 15, "peers": ["NEW"]},
        {"target_pe": 0, "peers": ["BBB"]},
        {"target_pe": 15, "peers": ["B B"]},
        {"target_pe": 15, "peers": ["BBB"], "reason": ""},
    ):
        answer = api.put("/app/watchlist/NEW", json={"reason": "try it", **bad})
        assert answer.status_code == 422, bad
    assert api.get("/app/watchlist").json() == start  # a refused change changes nothing

    body = {"reason": "asked by Babak", "target_pe": 15, "peers": ["bbb", "CCC"]}
    added = api.put("/app/watchlist/new", json=body).json()
    assert added["stock"]["peers"] == ["BBB", "CCC"] and "warning" in added
    assert api.put("/app/watchlist/NEW", json=body).json()["changed"] is False

    changed = api.put("/app/watchlist/AAA", json={"reason": "cheaper", "target_pe": 11}).json()
    assert changed["stock"] == {**first, "target_pe": 11}  # everything else kept
    removed = api.request("DELETE", "/app/watchlist/AAA", json={"reason": "drop it"}).json()
    assert "AAA" not in [s["symbol"] for s in api.get("/app/watchlist").json()]
    early = api.post(f"/app/watchlist/undo/{changed['change_id']}", json={"reason": "oops"})
    assert early.status_code == 409
    back = api.post(f"/app/watchlist/undo/{removed['change_id']}", json={"reason": "oops"})
    assert back.json()["stock"] == {**first, "target_pe": 11}  # with its corrections and peers
    history = api.get("/app/watchlist/history?symbol=aaa").json()
    assert [h["action"] for h in history] == ["undo", "remove", "change"]
    assert history[0]["by"] == "claude"


def test_app_run_requests(con: Database, api) -> None:
    api.headers.update(CLAUDE)
    bad = api.post("/app/requests", json={"subjects": ["NOPE"], "reason": "why not"})
    assert bad.status_code == 422
    ok = api.post("/app/requests", json={"subjects": ["aaa"], "reason": "earnings out"})
    assert ok.status_code == 200
    assert one(con, "SELECT subjects_json FROM ops_run_request") == '["AAA"]'


def test_app_client_runs_the_operations(con: Database, api, tmp_path, capsys) -> None:
    from stock_analysis.app import App, main

    api.headers.update(CLAUDE)
    app = App(client=api)
    open_run(con, ["AAA"])
    today = one(con, "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD')")
    file = tmp_path / "AAA.json"
    file.write_text(json.dumps({"reviewed": today, "sections": {**STOCK_NOTE, "News": ""}}))
    assert main(["save", RUN, "AAA", str(file)], app) == 1
    assert "section missing or empty: News" in capsys.readouterr().err
    file.write_text(json.dumps({"reviewed": today, "sections": STOCK_NOTE}))
    assert main(["save", RUN, "AAA", str(file)], app) == 0
    assert main(["submit", RUN, "--note", "ok"], app) == 0
    assert main(["run"], app) == 1  # no open run any more
    capsys.readouterr()
    assert main(["watchlist-set", "AAA", "--reason", "test it", "--target-pe", "12"], app) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["stock"]["target_pe"] == 12 and answer["stock"]["peers"]
    with con.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO out_stock_numbers VALUES ('AAA', CURRENT_DATE, "
                "now() AT TIME ZONE 'UTC', 'k', :p)"
            ),
            {"p": '{"pe": Infinity}'},
        )
    assert app.numbers("AAA")["payload"]["pe"] == float("inf")
