"""The ticker explorer (issue #20): analysis/explore.py turns database rows into per-ticker
JSON, and analysis/site.py builds the explorer pages from it. No network: the queries are
answered from fixture rows."""

import importlib.util
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


explore = load("explore_under_test", "analysis/explore.py")


def fund(item, ptype, fy, fp, end, value):
    return {
        "symbol": "ABC",
        "item": item,
        "period_type": ptype,
        "fiscal_year": fy,
        "fiscal_period": fp,
        "period_end": end,
        "source": "sec",
        "value": value,
    }


FUNDAMENTALS = [
    # two fiscal years of flows
    fund("revenue", "FY", 2024, "FY", "2024-12-31", 100.0),
    fund("revenue", "FY", 2025, "FY", "2025-12-31", 121.0),
    fund("net_income", "FY", 2024, "FY", "2024-12-31", 10.0),
    fund("net_income", "FY", 2025, "FY", "2025-12-31", 12.0),
    fund("eps_diluted", "FY", 2024, "FY", "2024-12-31", 1.0),
    fund("eps_diluted", "FY", 2025, "FY", "2025-12-31", 1.2),
    fund("operating_cf", "FY", 2025, "FY", "2025-12-31", 20.0),
    fund("capex", "FY", 2025, "FY", "2025-12-31", -5.0),
    # the balance sheet at the fourth quarter's end
    fund("equity", "I", 2025, "Q4", "2025-12-31", 60.0),
    fund("cash", "I", 2025, "Q4", "2025-12-31", 8.0),
    fund("total_debt", "I", 2025, "Q4", "2025-12-31", 30.0),
    fund("shares_outstanding", "I", 2025, "Q4", "2025-12-31", 10.0),
    fund("equity", "I", 2025, "Q3", "2025-09-30", 58.0),
    # three quarters of 2025; the fourth is only in the 10-K
    fund("revenue", "Q", 2025, "Q1", "2025-03-31", 28.0),
    fund("revenue", "Q", 2025, "Q2", "2025-06-30", 30.0),
    fund("revenue", "Q", 2025, "Q3", "2025-09-30", 31.0),
]


def test_annual_takes_flows_from_fy_and_the_balance_sheet_at_q4():
    a = explore.annual(FUNDAMENTALS)
    assert a["years"] == [2024, 2025]
    assert a["period_end"] == ["2024-12-31", "2025-12-31"]
    assert a["items"]["revenue"] == [100.0, 121.0]
    assert a["items"]["equity"] == [None, 60.0]  # Q3's 58 is not a year-end value


def test_quarterly_derives_the_missing_fourth_quarter():
    q = explore.quarterly(FUNDAMENTALS)
    assert q["period_end"] == ["2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31"]
    assert q["items"]["revenue"] == [28.0, 30.0, 31.0, 32.0]  # 121 - 28 - 30 - 31
    assert q["label"][-1] == "Q4 FY2025"
    assert ["2025-12-31", "revenue"] in q["derived"]
    assert q["items"]["equity"][2] == 58.0


def test_growth_and_ratios_by_year():
    a = explore.annual(FUNDAMENTALS)
    weekly = [["2024-12-27", 20.0, 20.0], ["2025-12-26", 24.0, 24.0]]
    r = explore.annual_ratios(a, weekly)
    assert r["pe"] == [20.0, 20.0]  # 20 / 1.0 and 24 / 1.2
    assert r["market_cap"][0] is None  # 2024 has no share count
    assert r["market_cap"][1] == 240.0
    assert r["net_debt"][1] == 22.0
    assert r["roe"][1] == pytest.approx(0.2)
    g = explore.growth({**a, "years": [2024, 2025]})
    assert g == {}  # fewer years than the shortest span


def test_snapshot_and_ratios_skip_meaningless_multiples():
    ttm = [
        {"item": "net_income", "value": -5.0, "period_end": "2025-12-31"},
        {"item": "eps_diluted", "value": -0.5, "period_end": "2025-12-31"},
        {"item": "revenue", "value": 100.0, "period_end": "2025-12-31"},
        {"item": "shares_outstanding", "value": 10.0, "period_end": "2025-12-31"},
        {"item": "equity", "value": 50.0, "period_end": "2025-12-31"},
        {"item": "total_debt", "value": 20.0, "period_end": "2025-12-31"},
        {"item": "cash", "value": 5.0, "period_end": "2025-12-31"},
    ]
    s = explore.snapshot(ttm, 12.0)
    assert s["market_cap"] == 120.0 and s["net_debt"] == 15.0 and s["enterprise_value"] == 135.0
    r = explore.ratios(s)
    assert r["pe"] is None  # a loss has no P/E
    assert r["ps"] == pytest.approx(1.2)
    assert r["debt_to_assets"] is None  # no total assets


def test_rsi_and_technicals():
    rising = [float(i) for i in range(1, 40)]
    assert explore.rsi(rising) == 100.0
    zigzag = [10.0, 11.0] * 20
    assert 40 < explore.rsi(zigzag) < 60
    daily = [[f"2026-01-{d:02d}", 10.0 + d, 1000] for d in range(1, 29)]
    t = explore.technicals(daily, [])
    assert t["sma20"] == pytest.approx(sum(10.0 + d for d in range(9, 29)) / 20)
    assert t["high52"] == 38.0 and t["low52"] == 11.0 and t["volume"] == 1000


def test_dividends_yield_streak_and_frequency():
    rows = [
        {"date": f"{y}-{m:02d}-15", "dividend": 0.1 * (y - 2019)}
        for y in range(2020, 2026)
        for m in (3, 6, 9, 12)
    ]
    d = explore.dividends(rows, "2025-12-31", 20.0, 2.0)
    assert d["ttm"] == pytest.approx(2.4)  # 4 x 0.6 in the last 12 months
    assert d["yield"] == pytest.approx(0.12) and d["payout"] == pytest.approx(1.2)
    assert d["per_year_count"] == 4 and d["last"] == ["2025-12-15", pytest.approx(0.6)]
    assert d["growth_streak"] == 4  # 2021..2024 each above the year before (2025 is this year)
    assert explore.dividends([], "2025-12-31", 20.0, 2.0) == {}


def test_earnings_next_report_and_beat_rate():
    rows = [
        {"report_date": "2025-08-01", "eps_estimate": 1.0, "eps_reported": 1.1, "surprise_pct": 10},
        {"report_date": "2025-11-01", "eps_estimate": 1.2, "eps_reported": 1.1, "surprise_pct": -8},
        {
            "report_date": "2026-02-01",
            "eps_estimate": 1.3,
            "eps_reported": None,
            "surprise_pct": None,
        },
    ]
    e = explore.earnings(rows, "2025-12-01")
    assert e["next"] == {"date": "2026-02-01", "eps_estimate": 1.3}
    assert len(e["history"]) == 2 and e["beat_rate"] == 0.5


def test_screener_keeps_selected_fields():
    rows = [
        {
            "run_date": "2026-11-13",
            "stage": 1,
            "symbol": "ABC",
            "category": "stalwart",
            "status": "pass",
            "rank_in_sector": None,
            "close": 10.0,
            "cheap_price": None,
            "detail_json": json.dumps({"piotroski_f_score_ttm": 7, "secret": 1, "failed": ""}),
        }
    ]
    s = explore.screener(rows)
    assert s["stage1"]["piotroski_f_score_ttm"] == 7 and "secret" not in s["stage1"]
    assert "failed" not in s["stage1"]  # empty values are left out


def test_valuation_graham_and_own_pe():
    snap = {"eps_diluted": 2.0, "book_per_share": 10.0, "price": 30.0}
    v = explore.valuation(snap, {"pe": [10.0, 20.0, 30.0, None]}, [], None)
    assert v["graham_number"] == pytest.approx(math.sqrt(22.5 * 2 * 10), rel=1e-5)
    assert v["pe_median_10y"] == 20.0 and v["pe_low_10y"] == 10.0
    assert v["price_at_median_pe"] == 40.0 and v["pe_years"] == 3


def fake_query(sql: str) -> list[dict]:
    """Answers each of the explorer's queries with fixture rows."""
    if "FROM core_company c\nLEFT JOIN core_index_member" in sql:
        return [
            {
                "symbol": "ABC",
                "name": "Abc Corp",
                "exchange": "NYSE",
                "sector": "Utilities",
                "industry": "Electric",
                "currency": "USD",
                "cik": 1,
                "sp500_since": "2020-01-01",
            },
            {
                "symbol": "bad symbol",
                "name": None,
                "exchange": None,
                "sector": None,
                "industry": None,
                "currency": None,
                "cik": None,
                "sp500_since": None,
            },
        ]
    if "v_fundamental_latest" in sql:
        assert "'ABC'" in sql and "bad symbol" not in sql
        return FUNDAMENTALS
    if "core_fundamental_ttm" in sql:
        return [
            {
                "symbol": "ABC",
                "item": "eps_diluted",
                "period_end": "2025-12-31",
                "filed": "2026-02-01",
                "basis": "fy",
                "value": 1.2,
            }
        ]
    if "date_trunc('week'" in sql:
        return [{"symbol": "ABC", "date": "2025-12-26", "close": 24.0, "adj_close": 24.0}]
    if "p.volume" in sql:
        return [
            {"symbol": "ABC", "date": "2026-01-02", "close": 25.0, "volume": 100},
            {"symbol": "ABC", "date": "2026-01-05", "close": 26.0, "volume": 200},
        ]
    if "p.dividend > 0" in sql:
        return [{"symbol": "ABC", "date": "2025-06-01", "dividend": 0.5}]
    if "raw_yahoo_earnings" in sql:
        return [
            {
                "symbol": "ABC",
                "report_date": "2026-02-10",
                "eps_estimate": 0.4,
                "eps_reported": None,
                "surprise_pct": None,
            }
        ]
    if "out_screener_result" in sql or "out_valuation" in sql:
        return []
    if "user_watchlist" in sql:
        return [{"symbol": "ABC"}]
    raise AssertionError(f"unexpected query: {sql[:80]}")


def test_export_writes_one_file_per_ticker_and_an_index(tmp_path):
    idx = explore.export(tmp_path, query=fake_query, today="2026-01-06")
    files = sorted(p.name for p in (tmp_path / "tickers").iterdir())
    assert files == ["ABC.json", "index.json"]  # the bad symbol is skipped
    t = json.loads((tmp_path / "tickers/ABC.json").read_text(encoding="utf-8"))
    assert t["asof"] == "2026-01-05" and t["snapshot"]["price"] == 26.0
    assert t["profile"]["watchlist"] is True
    assert t["earnings"]["next"]["date"] == "2026-02-10"
    row = idx["tickers"][0]
    assert row["symbol"] == "ABC" and row["pe"] == pytest.approx(26 / 1.2, rel=1e-5)
    assert idx["asof"] == "2026-01-05"


def test_in_list_rejects_anything_but_tickers():
    assert explore.in_list(["BRK.B", "BF-B"]) == "'BRK.B', 'BF-B'"
    with pytest.raises(ValueError):
        explore.in_list(["A'; DROP TABLE x; --"])


def test_site_builds_the_explorer_pages(tmp_path, monkeypatch):
    site = load("site_explore_under_test", "analysis/site.py")
    explore.export(tmp_path / "export", query=fake_query, today="2026-01-06")
    monkeypatch.setenv("STOCK_EXPLORE", "files")
    monkeypatch.setattr(site, "EXPLORE_DATA", tmp_path / "export")
    monkeypatch.setattr(site, "ANALYSES", tmp_path / "analyses")
    monkeypatch.setattr(site, "CONFIG", tmp_path / "watchlist.toml")
    monkeypatch.setattr(site, "COVERAGE", tmp_path / "none.json")
    (tmp_path / "analyses").mkdir()
    (tmp_path / "watchlist.toml").write_text("")
    out = site.build(tmp_path / "_site")
    assert (out / "explorer.js").exists() and (out / "tickers/ABC.json").exists()
    tickers = (out / "tickers.html").read_text(encoding="utf-8")
    assert 'href="ticker.html?s=ABC"' in tickers and "<summary>Explore</summary>" in tickers
    assert "Utilities" in (out / "sectors.html").read_text(encoding="utf-8")
    calendar = (out / "calendar.html").read_text(encoding="utf-8")
    assert "Tuesday 10 February 2026" in calendar and "$0.40" in calendar
    assert 'src="explorer.js"' in (out / "ticker.html").read_text(encoding="utf-8")


def test_site_without_explorer_data_says_so(tmp_path, monkeypatch):
    site = load("site_explore_off", "analysis/site.py")
    monkeypatch.setenv("STOCK_EXPLORE", "off")
    monkeypatch.setattr(site, "ANALYSES", tmp_path / "analyses")
    monkeypatch.setattr(site, "CONFIG", tmp_path / "watchlist.toml")
    monkeypatch.setattr(site, "COVERAGE", tmp_path / "none.json")
    (tmp_path / "analyses").mkdir()
    (tmp_path / "watchlist.toml").write_text("")
    out = site.build(tmp_path / "_site")
    assert "No explorer data in this build" in (out / "tickers.html").read_text(encoding="utf-8")
    assert not (out / "tickers").exists()
