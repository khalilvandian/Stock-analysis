"""The database: migrations, file import into raw and out, the raw-to-core build, the views.
No network."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import text

from stock_analysis.db import Database, db_path, migration_sql, migrations, target_settings
from stock_analysis.db.build import adjusted_close, build, build_ttm
from stock_analysis.db.check import Reader, run_checks
from stock_analysis.db.load_files import load_all

QUARTERS = ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]


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
    return data


def opendb(path: Path) -> Database:
    db = Database(f"sqlite:///{Path(path).as_posix()}")
    db.migrate()
    return db


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
    """Run a query with ? placeholders and return its rows (closed connection)."""
    names = iter(range(len(params)))
    sql = re.sub(r"\?", lambda _: f":p{next(names)}", sql)
    with db.connect() as conn:
        res = conn.execute(text(sql), {f"p{i}": v for i, v in enumerate(params)})
        return Rows([tuple(r) for r in res.fetchall()], res.keys())


@pytest.fixture()
def con(tmp_path: Path, data_dir: Path):
    db = opendb(tmp_path / "test.db")
    load_all(db, data_dir)
    yield db
    db.close()


def one(con, sql: str, *params):
    return q(con, sql, *params).fetchone()[0]


def test_migrations_portable_and_recorded(con) -> None:
    assert one(con, "SELECT MAX(version) FROM schema_version") == migrations()[-1][0]
    for _, path in migrations():
        pg = migration_sql(path, "postgresql")
        assert "{{ID}}" not in pg
        if "{{ID}}" in path.read_text(encoding="utf-8"):
            assert "GENERATED BY DEFAULT AS IDENTITY" in pg
        assert "PRAGMA" not in pg.upper()


def test_existing_database_is_upgraded(tmp_path: Path) -> None:
    first = migrations()[0]
    old = sqlite3.connect(tmp_path / "v1.db")
    old.executescript(migration_sql(first[1]))
    old.execute("INSERT INTO schema_version VALUES (?, '2026-11-16')", (first[0],))
    old.commit()
    old.close()
    c = opendb(tmp_path / "v1.db")
    assert one(c, "SELECT MAX(version) FROM schema_version") == migrations()[-1][0]
    columns = {r[1] for r in q(c, "PRAGMA table_info(core_price_daily)")}
    assert {"open", "high", "low"} <= columns
    c.close()


def test_old_file_is_refused(tmp_path: Path) -> None:
    old = sqlite3.connect(tmp_path / "old.db")
    old.execute("CREATE TABLE raw_fetch (fetch_id INTEGER)")
    old.close()
    with pytest.raises(RuntimeError, match="predates the migrations"):
        opendb(tmp_path / "old.db")


def test_load_files_and_rerun(tmp_path: Path, data_dir: Path) -> None:
    c = opendb(tmp_path / "load.db")
    added = load_all(c, data_dir)
    assert added["raw_yahoo_price"] == len(prices_frame())
    assert added["raw_yahoo_statement"] == 4 * 5 + 4 * 7
    assert added["raw_tv_constituent"] == 5
    assert added["raw_project_history"] == 4
    assert added["out_screener_result"] == 4
    assert added["out_valuation"] == 1
    extra = json.loads(one(c, "SELECT extra_json FROM raw_tv_constituent LIMIT 1"))
    assert extra == {"close": 10.0, "total_debt_fq": None}
    assert set(load_all(c, data_dir).values()) == {0}

    # A changed file adds only the rows that changed.
    p = prices_frame()
    p.loc[p["date"] == "2026-09-30", "Close"] = 11.0
    write_csv(data_dir / "AAA" / "prices_daily.csv", p)
    assert load_all(c, data_dir)["raw_yahoo_price"] == 1
    assert one(c, "SELECT rows_stored FROM raw_fetch ORDER BY fetch_id DESC LIMIT 1") == 1
    c.close()


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


def test_ttm_keeps_every_version(tmp_path: Path) -> None:
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
    db = opendb(tmp_path / "ttm.db")
    with db.begin() as conn:
        conn.execute(text("INSERT INTO core_company (company_id, symbol) VALUES (1, 'AAA')"))
        conn.execute(
            text(
                "INSERT INTO core_item (item, label, kind, unit) "
                "VALUES ('revenue', 'R', 'flow', 'USD')"
            )
        )
        ttm = build_ttm(conn, f).sort_values("filed")
    db.close()
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


def test_out_tables(con) -> None:
    top = q(
        con,
        "SELECT symbol, rank_in_sector, cheap_price FROM out_screener_result WHERE stage = 2 "
        "ORDER BY rank_in_sector",
    ).fetchall()
    assert [tuple(r) for r in top] == [("AAA", 1, 12.0), ("BBB", 2, 8.0)]
    v = q(con, "SELECT as_of, method, fair_value FROM out_valuation").fetchone()
    assert tuple(v) == ("2026-09-28", "fcff", 14.0)


def test_targets(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert db_path().name == "stock.db"  # the selected target in config/database.toml
    target = tmp_path / "x.db"
    assert db_path(f"sqlite:///{target.as_posix()}") == target
    config = {
        "selected": "local",
        "targets": {"local": {"url": "sqlite:///data/a.db"}, "server": {"url": ""}},
    }
    assert target_settings(config=config)["url"] == "sqlite:///data/a.db"
    with pytest.raises(ValueError, match="no url"):
        target_settings("server", config)
    with pytest.raises(ValueError, match="No target"):
        target_settings("other", config)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///data/other.db")
    assert target_settings(config=config)["name"] == "DATABASE_URL"
    assert target_settings("local", config)["url"] == "sqlite:///data/a.db"  # --target wins
    with pytest.raises(ValueError, match="SQLite"):
        db_path("postgresql://host/db")


def test_check_passes_on_a_built_database(tmp_path: Path, data_dir: Path) -> None:
    c = opendb(tmp_path / "check.db")
    load_all(c, data_dir)
    build(c)
    c.close()
    db = Reader(f"sqlite:///{(tmp_path / 'check.db').as_posix()}")
    settings = {"sample_symbols": ["AAA"], "max_age_days": 7, "min_coverage": 0.3}
    results = {r.name: r for r in run_checks(db, settings, today=date(2026, 11, 14))}
    db.close()
    assert not [r for r in results.values() if r.status == "FAIL"], results
    assert results["AAA prices"].status == "PASS"
    assert results["AAA fiscal years"].status == "PASS"
    assert results["newest price"].status == "WARN"  # 2026-09-30 is 45 days old
    assert results["rows in raw_sec_fact"].status == "WARN"  # no SEC loader yet


def test_check_fails_on_an_empty_database(tmp_path: Path) -> None:
    opendb(tmp_path / "empty.db").close()
    db = Reader(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    results = {r.name: r for r in run_checks(db, {"sample_symbols": ["AAA"]})}
    db.close()
    assert results["last build"].status == "FAIL"
    assert results["rows in core_price_daily"].status == "FAIL"
    assert results["AAA"].status == "FAIL"
    with pytest.raises(FileNotFoundError):
        Reader(f"sqlite:///{(tmp_path / 'missing.db').as_posix()}")


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


@pytest.mark.skipif(
    not os.environ.get("STOCK_TEST_PG_URL"),
    reason="set STOCK_TEST_PG_URL to a throwaway PostgreSQL database to run this",
)
def test_whole_flow_on_postgresql(data_dir: Path) -> None:
    """The same import, build and check on PostgreSQL (e.g. the stock_test database in the
    local Docker container). The test empties that database first."""
    url = os.environ["STOCK_TEST_PG_URL"]
    db = Database(url, os.environ.get("STOCK_DB_PASSWORD"))
    with db.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA public CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA public")
    db.migrate()
    load_all(db, data_dir)
    summary = build(db)
    assert summary["core_price_daily"] > 0 and summary["sp500_members_now"] == 2
    assert set(load_all(db, data_dir).values()) == {0}
    assert (
        one(db, "SELECT total_debt FROM v_annual WHERE symbol = 'AAA' AND fiscal_year = 2025")
        == 50.0
    )
    db.close()
    reader = Reader(url, "STOCK_DB_PASSWORD")
    settings = {"sample_symbols": ["AAA"], "min_coverage": 0.3}
    results = run_checks(reader, settings, today=date(2026, 11, 14))
    reader.close()
    assert not [r for r in results if r.status == "FAIL"], results
