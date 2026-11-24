"""The scheduled ingest (issue #18): the source parsers, the SEC facts and fourth quarters in
the build, the job's queue, budgets and stops, and the coverage snapshot. HTTP is mocked with
respx; Yahoo (yfinance, which respx can't reach) is a fake client. The database tests use the
same local PostgreSQL as tests/test_db.py and skip without it."""

from __future__ import annotations

import json
from datetime import date

import httpx
import pandas as pd
import pytest
import respx
from test_db import empty_db, pg_url  # noqa: F401  (pg_url is a fixture)

from stock_analysis import ecb, tradingview
from stock_analysis.db import build as build_module
from stock_analysis.db import frame
from stock_analysis.db.build import add_periods, derive_q4, to_month_end
from stock_analysis.db.coverage import month_index, snapshot
from stock_analysis.ingest import job, market, sec, yahoo
from stock_analysis.ingest.common import RateLimited

TODAY = date(2026, 11, 17)
SYMBOLS = ["AAA", "BBB"]
CIKS = {"AAA": 1001, "BBB": 1002}


# ---------------------------------------------------------------- fakes


def tv_rows(symbols: list[str]) -> dict:
    rows = []
    for s in symbols:
        d = [s, f"{s} Corp", "NYSE", "Utilities", "Electric Utilities", "United States", "USD",
             2e10, "USD", [{"name": "S&P 500", "proname": "SP:SPX"}], True]  # fmt: skip
        rows.append({"s": f"NYSE:{s}", "d": d})
    rows.append({"s": "NYSE:ZZZ", "d": ["ZZZ", "Not in it", "NYSE", "Finance", "Major Banks",
                 "United States", "USD", 5e9, "USD", [], True]})  # fmt: skip
    return {"totalCount": len(rows), "data": rows}


def fact(start, end, val, filed, form="10-K", accn="a"):
    x = {"end": end, "val": val, "filed": filed, "form": form, "accn": accn, "fy": int(end[:4])}
    if start:
        x["start"] = start
    return x


def companyfacts(cik: int) -> dict:
    """Two fiscal years and three quarters of revenue, a balance sheet, cover shares."""
    rev = [fact("2024-01-01", "2024-12-31", 400.0, "2025-02-20", accn="k24")]
    rev += [fact("2025-01-01", "2025-12-31", 500.0, "2026-02-20", accn="k25")]
    for i, (s, e) in enumerate(
        [("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"), ("2025-07-01", "2025-09-30")]
    ):
        rev.append(fact(s, e, 110.0 + i, f"2025-{5 + 3 * i:02d}-05", "10-Q", f"q{i}"))
    rev.append(fact("2025-01-01", "2025-06-30", 221.0, "2025-08-05", "10-Q", "q1"))  # half year
    # a trailing twelve months in a 10-Q: not a fiscal year
    rev.append(fact("2024-10-01", "2025-09-30", 460.0, "2025-11-05", "10-Q", "q2"))
    # cash flow is year to date in 10-Qs; capex is reported as a positive payment
    ocf = [
        fact("2025-01-01", "2025-03-31", 30.0, "2025-05-05", "10-Q", "q0"),
        fact("2025-01-01", "2025-06-30", 70.0, "2025-08-05", "10-Q", "q1"),
        fact("2025-01-01", "2025-09-30", 120.0, "2025-11-05", "10-Q", "q2"),
        fact("2025-01-01", "2025-12-31", 180.0, "2026-02-20", accn="k25"),
    ]
    capex = [fact("2025-01-01", "2025-12-31", 40.0, "2026-02-20", accn="k25")]
    assets = [fact(None, "2025-12-31", 900.0, "2026-02-20", accn="k25")]
    shares = [fact(None, "2026-02-10", 50.0, "2026-02-20", accn="k25")]  # cover date
    return {
        "cik": cik,
        "facts": {
            "us-gaap": {
                "Revenues": {"units": {"USD": rev}},
                "Assets": {"units": {"USD": assets}},
                "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": ocf}},
                "PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": capex}},
                "SomethingUnmapped": {"units": {"USD": [fact(None, "2025-12-31", 1, "x")]}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": shares}}},
        },
    }


ECB_CSV = (
    "KEY,FREQ,CURRENCY,CURRENCY_DENOM,EXR_TYPE,EXR_SUFFIX,TIME_PERIOD,OBS_VALUE\n"
    "x,D,USD,EUR,SP00,A,2026-11-13,1.10\nx,D,GBP,EUR,SP00,A,2026-11-13,0.88\n"
    "x,D,USD,EUR,SP00,A,2026-11-16,1.12\nx,D,GBP,EUR,SP00,A,2026-11-16,0.875\n"
)


class FakeYahoo:
    """Prices for every business day, two years of statements, eight earnings reports."""

    def __init__(self, limit_after: int | None = None):
        self.calls = 0
        self.limit_after = limit_after

    def _count(self):
        self.calls += 1
        if self.limit_after is not None and self.calls > self.limit_after:
            raise RateLimited("Yahoo: too many requests")

    def prices(self, symbol, start):
        self._count()
        days = pd.bdate_range(max(pd.Timestamp(start), pd.Timestamp("2015-12-01")), "2026-11-16")
        return pd.DataFrame(
            {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "Volume": 1000,
             "Dividends": 0.0, "Stock Splits": 0.0},
            index=days.tz_localize("America/New_York"),
        )  # fmt: skip

    def statement(self, symbol, attribute):
        self._count()
        if attribute == "quarterly_income_stmt":
            cols = pd.to_datetime(["2025-12-31", "2025-09-30"])
            return pd.DataFrame({c: {"Total Revenue": 130.0} for c in cols})
        return pd.DataFrame()

    def earnings(self, symbol):
        self._count()
        idx = pd.DatetimeIndex(
            [pd.Timestamp("2026-10-28 16:00") - pd.DateOffset(months=3 * i) for i in range(9)]
        ).tz_localize("America/New_York")
        return pd.DataFrame(
            {"EPS Estimate": 1.0, "Reported EPS": [None] + [1.1] * 8, "Surprise(%)": 10.0},
            index=idx,
        )


def mock_sources(router: respx.MockRouter, symbols=SYMBOLS) -> None:
    router.post(tradingview.SCAN_URL.format(market="america")).mock(
        return_value=httpx.Response(200, json=tv_rows(symbols))
    )
    tickers = {str(i): {"cik_str": CIKS[s], "ticker": s, "title": s} for i, s in enumerate(CIKS)}
    router.get(sec.TICKERS_URL).mock(return_value=httpx.Response(200, json=tickers))
    for cik in CIKS.values():
        router.get(sec.FACTS_URL.format(cik=cik)).mock(
            return_value=httpx.Response(200, json=companyfacts(cik))
        )
    router.get(ecb.URL).mock(return_value=httpx.Response(200, text=ECB_CSV))


WATCH_SOURCES = ("tradingview_watchlist", "yahoo_market")


def config(watch: bool = False, **budgets) -> dict:
    """config/ingest.toml without pauses; the watch list's and the market report's sources
    (and extra_symbols) only with watch=True."""
    cfg = job.load_config()
    if not watch:
        for name in WATCH_SOURCES:
            cfg["sources"].pop(name, None)
        cfg.pop("extra_symbols", None)
    cfg["nightly"] = False
    for g in cfg["groups"].values():
        g["min_interval_s"] = 0
    for name, n in budgets.items():
        cfg["groups"][name]["budget"] = {"backfill": n, "maintain": n}
    return cfg


def context(cfg, yahoo_client=None) -> job.Context:
    return job.Context(
        cfg, httpx.Client(), httpx.Client(), yahoo_client or FakeYahoo(), sleep=lambda s: None
    )


@pytest.fixture()
def fresh(pg_url: str):  # noqa: F811
    db = empty_db(pg_url)
    db.migrate()
    yield db
    db.close()


# ---------------------------------------------------------------- parsers (no database)


def test_companyfacts_keeps_only_mapped_tags() -> None:
    keep = sec.mapped_tags()
    assert ("us-gaap", "Revenues") in keep and ("dei", "EntityCommonStockSharesOutstanding") in keep
    df = sec.facts_frame(companyfacts(1001), 1001, keep)
    assert "SomethingUnmapped" not in set(df["tag"])
    assert len(df[df["tag"] == "Revenues"]) == 7
    assert df.loc[df["tag"] == "Assets", "period_start"].isna().all()


def test_never_known_before_the_stored_period_end() -> None:
    """#49: AutoZone's quarter ends 2019-05-04 and is stored at its slot's month end, May 31;
    released 2019-05-21, it counts from May 31, not before."""
    c = pd.DataFrame([
        {"company_id": 1, "period_type": "FY", "period_end": "2018-08-25", "filed": "2018-10-20"},
        {"company_id": 1, "period_type": "Q", "period_end": "2019-05-04", "filed": "2019-05-21"},
    ])  # fmt: skip
    out = add_periods(c).set_index("period_type")
    assert out.loc["Q", "period_end"] == "2019-05-31" and out.loc["Q", "filed"] == "2019-05-31"
    assert out.loc["FY", "filed"] == "2018-10-20"


def test_ecb_rates_are_dollars_per_unit() -> None:
    r = market.rates_frame(ECB_CSV).set_index(["currency", "date"])["usd_per_unit"]
    assert r[("USD", "2026-11-16")] == pytest.approx(1.0)
    assert r[("EUR", "2026-11-16")] == pytest.approx(1.12)
    assert r[("GBP", "2026-11-16")] == pytest.approx(1.12 / 0.875)


def test_yahoo_frames() -> None:
    y = FakeYahoo()
    p = yahoo.price_frame(y.prices("AAA", "2026-11-10"), "AAA")
    assert list(p["date"]) == ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13", "2026-11-16"]
    assert p["volume"].dtype == "Int64"
    s = yahoo.statement_frame(y.statement("AAA", "quarterly_income_stmt"), "AAA", "income", "q")
    assert set(s["period_end"]) == {"2025-09-30", "2025-12-31"}
    e = yahoo.earnings_frame(y.earnings("AAA"), "AAA")
    assert e["report_date"].iloc[-1] == "2026-10-28" and e["eps_reported"].isna().sum() == 1
    assert yahoo.yahoo_symbol("BRK.B") == "BRK-B"


def test_month_end_and_fourth_quarter() -> None:
    ends = to_month_end(pd.Series(["2026-09-26", "2026-10-02", "2025-12-31", "2026-03-28"]))
    assert list(ends) == ["2026-09-30", "2026-09-30", "2025-12-31", "2026-03-31"]
    assert month_index("2026-09-26") == month_index("2026-10-02")
    items = pd.DataFrame({"item": ["revenue", "eps_diluted"], "kind": ["flow", "flow"]})
    base = {"company_id": 1, "source": "sec", "fiscal_year": 2025, "filed": "2026-02-20",
            "method": "reported", "rank": 1, "tag": "Revenues"}  # fmt: skip
    rows = [{**base, "item": "revenue", "period_type": "FY", "period_end": "2025-12-31",
             "fiscal_period": "FY", "value": 500.0}]  # fmt: skip
    for q, end, v in (("Q1", "2025-03-31", 110.0), ("Q2", "2025-06-30", 111.0),
                      ("Q3", "2025-09-30", 112.0)):  # fmt: skip
        rows.append({**base, "item": "revenue", "period_type": "Q", "period_end": end,
                     "fiscal_period": q, "value": v})  # fmt: skip
    out = derive_q4(pd.DataFrame(rows), items)
    q4 = out[(out["period_type"] == "Q") & (out["fiscal_period"] == "Q4")]
    assert len(q4) == 1 and q4["value"].iloc[0] == pytest.approx(167.0)
    assert q4["period_end"].iloc[0] == "2025-12-31" and q4["method"].iloc[0] == "derived"


def quarter_rows(item: str, values: dict, **extra) -> list[dict]:
    """Fiscal 2025 rows (calendar year) of one item: values = {(period, filed): value}."""
    ends = {"Q1": "2025-03-31", "Q2": "2025-06-30", "Q3": "2025-09-30", "FY": "2025-12-31"}
    base = {"company_id": 1, "source": "sec", "fiscal_year": 2025, "method": "reported",
            "rank": 1, "tag": "T", "filed_estimated": False, "item": item}  # fmt: skip
    return [{**base, **extra, "period_type": "FY" if p == "FY" else "Q", "fiscal_period": p,
             "period_end": ends[p], "filed": filed, "value": v}
            for (p, filed), v in values.items()]  # fmt: skip


def test_fourth_quarter_is_known_when_the_10k_is_filed() -> None:
    """#49: Q4 is dated by the 10-K that reports the year, not by the next 10-K repeating it."""
    items = pd.DataFrame({"item": ["revenue"], "kind": ["flow"]})
    rows = quarter_rows("revenue", {
        ("Q1", "2025-05-01"): 110.0, ("Q2", "2025-08-01"): 111.0, ("Q3", "2025-11-01"): 112.0,
        ("FY", "2026-02-20"): 500.0,
        ("Q1", "2026-05-01"): 108.0,  # next year's 10-Q restates the quarter
        ("FY", "2027-02-20"): 500.0,  # next year's 10-K repeats the year
    })  # fmt: skip
    out = derive_q4(pd.DataFrame(rows), items)
    q4 = out[out["fiscal_period"] == "Q4"].sort_values("filed")
    assert q4["filed"].tolist() == ["2026-02-20", "2026-05-01"]
    assert q4["value"].tolist() == pytest.approx([167.0, 169.0])
    # A later 10-K reports the quarter itself (JNJ, restated): derived until then
    q4_reported = {**rows[0], "period_type": "Q", "fiscal_period": "Q4",
                   "period_end": "2025-12-31", "filed": "2026-05-01", "value": 168.0}  # fmt: skip
    out = derive_q4(pd.DataFrame([*rows, q4_reported]), items)
    q4 = out[out["fiscal_period"] == "Q4"].sort_values("filed")
    assert list(zip(q4["filed"], q4["method"], q4["value"], strict=True)) == [
        ("2026-02-20", "derived", 167.0), ("2026-05-01", "reported", 168.0)]  # fmt: skip


def test_period_known_from_its_first_filing_under_any_field() -> None:
    """#49: the preferred tag first appears in a later 10-K; until then the next-best tag the
    company did file dates the period. A lower source never fills in."""
    from stock_analysis.db.build import choose

    base = {"company_id": 1, "item": "revenue", "period_type": "FY", "period_end": "2018-12-31",
            "fetch_id": 1, "value": 136.8}  # fmt: skip
    c = pd.DataFrame([
        {**base, "rank": 1, "priority": 1, "tag": "Revenues", "filed": "2021-02-03"},
        {**base, "rank": 1, "priority": 2, "tag": "RevenueFromContract", "filed": "2019-02-05"},
        {**base, "rank": 1, "priority": 2, "tag": "RevenueFromContract", "filed": "2020-02-04"},
        {**base, "rank": 1, "priority": 2, "tag": "RevenueFromContract", "filed": "2021-02-03"},
        {**base, "rank": 3, "priority": 1, "tag": "TotalRevenue", "filed": "2019-01-15"},
    ])  # fmt: skip
    out = choose(c).sort_values("filed")
    assert out["filed"].tolist() == ["2019-02-05", "2020-02-04", "2021-02-03"]
    assert out["tag"].tolist() == ["RevenueFromContract", "RevenueFromContract", "Revenues"]


def test_figures_count_from_the_earnings_release() -> None:
    """#49: a 10-Q's own quarter counts from the press release before it; last year's
    comparative in the same 10-Q, an amendment and a release long before the filing don't move."""
    from stock_analysis.db.build import date_by_release

    base = {"symbol": "AAA", "tag": "T", "value": 1.0}
    sec = pd.DataFrame([
        {**base, "form": "10-Q", "period_end": "2025-06-30", "filed": "2025-08-05"},  # own
        {**base, "form": "10-Q", "period_end": "2024-06-30", "filed": "2025-08-05"},  # comparative
        {**base, "form": "10-Q/A", "period_end": "2025-06-30", "filed": "2025-08-20"},
        {**base, "form": "10-K", "period_end": "2025-12-31", "filed": "2026-06-01"},  # 4 months
    ])  # fmt: skip
    releases = pd.DataFrame(
        {"symbol": ["AAA", "AAA", "AAA"], "report_date": ["2024-07-25", "2025-07-24", "2026-01-29"]}
    )
    out = date_by_release(sec, releases)
    assert out["filed"].tolist() == ["2025-07-24", "2025-08-05", "2025-08-20", "2026-06-01"]


def test_twelve_month_eps_is_anchored_on_the_year() -> None:
    """#49: JNJ Q1 2018 twelve-month EPS = FY2017 0.47 + Q1 2018 1.60 - Q1 2017 1.61 = 0.46
    (Koyfin 0.45), not the four quarters' 1.40 + 1.37 - 3.99 + 1.60 = 0.38. EPS from
    continuing operations only for a window reported throughout, else diluted EPS."""
    from stock_analysis.db.build import per_share_ttm

    def rows(item, values, method="reported"):
        out = []
        for (year, period, end, filed), v in values.items():
            out.append({"company_id": 1, "item": item, "fiscal_year": year,
                        "fiscal_period": period, "period_type": "FY" if period == "FY" else "Q",
                        "period_end": end, "filed": filed, "filed_estimated": False, "value": v,
                        "value_adj": v, "source": "sec", "method": method})  # fmt: skip
        return out

    eps = {(2017, "Q1", "2017-03-31", "2017-04-18"): 1.61,
           (2017, "FY", "2017-12-31", "2018-01-23"): 0.47,
           (2018, "Q1", "2018-03-31", "2018-04-17"): 1.60}  # fmt: skip
    f = pd.DataFrame(rows("eps_diluted", eps))
    t = per_share_ttm(f)
    assert len(t) == 1 and t[0]["value_adj"] == pytest.approx(0.46)
    assert t[0]["period_end"] == "2018-03-31" and t[0]["filed"] == "2018-04-17"
    # continuing EPS restated for 2018 only: the window mixes bases, so it takes diluted EPS
    cont = rows("eps_continuing", {k: v for k, v in eps.items() if k[0] == 2017}, "derived")
    cont += rows("eps_continuing", {(2018, "Q1", "2018-03-31", "2018-04-17"): 1.20})
    t = per_share_ttm(pd.concat([f, pd.DataFrame(cont)]))
    c = [r for r in t if r["item"] == "eps_continuing"]
    assert len(c) == 1 and c[0]["value_adj"] == pytest.approx(0.46)


def test_split_between_release_and_filing_is_not_applied_twice() -> None:
    """#49: Walmart released FY2024 on 2024-02-20, split 3:1 on 2024-02-26 and filed the 10-K,
    on the new basis, in March. The figures count from the release; their share basis is the
    filing's."""
    from stock_analysis.db.build import add_split_factor

    f = pd.DataFrame([{"company_id": 1, "item": "eps_diluted", "source": "sec", "value": 1.91,
                       "filed": "2024-02-20", "split_basis": "2024-03-15"}])  # fmt: skip
    splits = pd.DataFrame({"company_id": [1], "date": ["2024-02-26"], "ratio": [3.0]})
    out = add_split_factor(f, splits)
    assert out["split_factor"].iloc[0] == 1.0 and out["value_adj"].iloc[0] == 1.91
    out = add_split_factor(f.drop(columns="split_basis"), splits)  # dated by the release only
    assert out["split_factor"].iloc[0] == 3.0


def test_continuing_eps_reported_wins_and_the_copy_fills_the_rest() -> None:
    """#49: EPS from continuing operations as the company reports it; where it reports none
    (no discontinued operations, or not yet), diluted EPS stands in, only until it is filed."""
    from stock_analysis.db.build import derive

    items = pd.DataFrame([{"item": "eps_continuing", "kind": "flow", "derive": "eps_diluted",
                           "derive_mode": "fallback"}])  # fmt: skip
    rows = quarter_rows("eps_diluted", {("Q1", "2025-05-01"): 2.0, ("Q2", "2025-08-01"): 1.5,
                                        ("Q1", "2026-05-01"): 2.0})  # fmt: skip
    # a spin-off: next year's 10-Q restates Q1 2025 without the spun-off business
    rows += quarter_rows("eps_continuing", {("Q1", "2026-05-01"): 1.2})
    out = derive(pd.DataFrame(rows), items)
    e = out[out["item"] == "eps_continuing"].sort_values(["period_end", "filed"])
    assert list(zip(e["period_end"], e["filed"], e["method"], e["value"], strict=True)) == [
        ("2025-03-31", "2025-05-01", "derived", 2.0),  # known from the 10-Q, as diluted EPS
        ("2025-03-31", "2026-05-01", "reported", 1.2),  # the company's own figure from then on
        ("2025-06-30", "2025-08-01", "derived", 1.5),
    ]


def test_quarters_from_year_to_date_are_known_on_the_10q_date() -> None:
    from stock_analysis.db.build import sec_quarters_from_ytd

    base = {"symbol": "AAA", "taxonomy": "us-gaap", "tag": "T", "unit": "USD",
            "period_start": "2025-01-01", "method": "reported"}  # fmt: skip
    sec = pd.DataFrame([
        {**base, "period_end": "2025-03-31", "span": "Q", "filed": "2025-05-01", "value": 100.0},
        {**base, "period_end": "2025-06-30", "span": "H", "filed": "2025-08-01", "value": 210.0},
        {**base, "period_end": "2025-09-30", "span": "N", "filed": "2025-11-01", "value": 330.0},
        # next year's 10-Qs repeat the year-to-date totals as comparatives
        {**base, "period_end": "2025-06-30", "span": "H", "filed": "2026-08-01", "value": 210.0},
        {**base, "period_end": "2025-09-30", "span": "N", "filed": "2026-11-01", "value": 330.0},
    ])  # fmt: skip
    d = sec_quarters_from_ytd(sec)
    first = d.sort_values("filed").drop_duplicates("period_end").set_index("period_end")
    assert first["filed"].to_dict() == {"2025-06-30": "2025-08-01", "2025-09-30": "2025-11-01"}
    assert first["value"].to_dict() == {"2025-06-30": 110.0, "2025-09-30": 120.0}
    assert set(d["period_start"]) == {"2025-04-01", "2025-07-01"}


def test_derived_value_is_known_when_its_last_part_is() -> None:
    from stock_analysis.db.build import derive

    items = pd.DataFrame(
        [{"item": "ebitda", "kind": "flow", "derive": "operating_income + d_and_a"}]
    )
    rows = quarter_rows("operating_income", {("Q1", "2025-05-01"): 7.0, ("Q1", "2026-05-01"): 7.0})
    rows += quarter_rows("d_and_a", {("Q1", "2025-05-02"): 5.0, ("Q1", "2026-05-01"): 6.0})
    out = derive(pd.DataFrame(rows), items)
    e = out[out["item"] == "ebitda"].sort_values("filed")
    assert e["filed"].tolist() == ["2025-05-02", "2026-05-01"]  # each date a part changed
    assert e["value"].tolist() == [12.0, 13.0]


def test_fourth_quarter_eps_on_todays_share_basis() -> None:
    """#49 P2: Q4 EPS = FY - Q1 - Q2 - Q3 with each on today's basis (a 2:1 split mid-year,
    a 3:1 one after the 10-K); the value as filed is on the 10-K date's basis."""
    from stock_analysis.db.build import add_split_factor, derive_q4_per_share

    rows = quarter_rows("eps_diluted", {
        ("Q1", "2025-05-01"): 2.0, ("Q2", "2025-08-01"): 1.1, ("Q3", "2025-11-01"): 1.2,
        ("FY", "2026-02-20"): 4.5,
    }, raw_table="t", raw_id=1)  # fmt: skip
    splits = pd.DataFrame(
        {"company_id": [1, 1], "date": ["2025-07-01", "2026-06-01"], "ratio": [2.0, 3.0]}
    )
    f = add_split_factor(pd.DataFrame(rows), splits)
    q4 = derive_q4_per_share(f, splits).query("fiscal_period == 'Q4'")
    assert len(q4) == 1 and q4["filed"].iloc[0] == "2026-02-20"
    assert q4["value_adj"].iloc[0] == pytest.approx(1.5 - 2.0 / 6 - 1.1 / 3 - 1.2 / 3)
    assert q4["value"].iloc[0] == pytest.approx(1.2) and q4["split_factor"].iloc[0] == 3.0


# ---------------------------------------------------------------- the job (database)


def rows(db, sql: str, params: dict | None = None) -> pd.DataFrame:
    with db.connect() as conn:
        return frame(conn, sql, params)


@respx.mock(assert_all_called=False)
def test_job_fills_the_database_and_reruns_store_nothing(fresh, respx_mock) -> None:
    mock_sources(respx_mock)
    cfg = config()
    result = job.run_job(fresh, cfg, ctx=context(cfg))
    assert result["status"] == "ok", result
    assert result["mode"] == "backfill"
    tasks = rows(fresh, "SELECT source, status, COUNT(*) AS n FROM ops_task GROUP BY 1, 2")
    assert set(tasks["status"]) == {"ok"}
    assert dict(zip(tasks["source"], tasks["n"], strict=True)) == {
        "tradingview": 1, "sec_tickers": 1, "ecb_rates": 1, "sec_companyfacts": 2,
        "yahoo_prices": 2, "yahoo_statements": 2, "yahoo_earnings": 2,
    }  # fmt: skip
    members = rows(fresh, "SELECT DISTINCT symbol FROM raw_tv_constituent")
    assert sorted(members["symbol"]) == SYMBOLS  # ZZZ is not in the index
    # cover-page shares are dated at the filing's balance-sheet date
    shares = rows(
        fresh,
        "SELECT period_end, value FROM core_fundamental f JOIN core_company c USING (company_id) "
        "WHERE c.symbol = 'AAA' AND item = 'shares_outstanding' AND source = 'sec'",
    )
    assert list(shares["period_end"]) == ["2025-12-31"]
    q4 = rows(
        fresh,
        "SELECT value, method, source, filed FROM core_fundamental f JOIN core_company c "
        "USING (company_id) WHERE c.symbol = 'AAA' AND item = 'revenue' AND period_type = 'Q' "
        "AND period_end = '2025-12-31' ORDER BY filed",
    )
    # Yahoo reports Q4: its figure wins from its date; before it, FY - Q1 - Q2 - Q3 from the
    # earnings release (2026-01-28) is all that is known
    assert q4[["method", "source"]].values.tolist() == [["derived", "sec"], ["reported", "yahoo"]]
    assert q4["value"].iloc[-1] == pytest.approx(130.0) and q4["filed"].iloc[0] == "2026-01-28"
    fy = rows(
        fresh,
        "SELECT value, filed, filed_estimated FROM core_fundamental f JOIN core_company c "
        "USING (company_id) WHERE symbol = 'AAA' AND item = 'revenue' AND period_type = 'FY' "
        "AND period_end = '2025-12-31'",
    )
    assert fy["value"].iloc[0] == 500.0 and not fy["filed_estimated"].iloc[0]

    def aaa(item, ptype):
        return rows(
            fresh,
            "SELECT period_end, value, method FROM v_fundamental_latest f JOIN core_company c "
            "USING (company_id) WHERE c.symbol = 'AAA' AND item = :i AND period_type = :t "
            "ORDER BY period_end",
            {"i": item, "t": ptype},
        )

    ocf = aaa("operating_cf", "Q")
    assert list(ocf["value"]) == [30.0, 40.0, 50.0, 60.0]  # Q1 reported, Q2-Q4 derived
    assert list(ocf["method"]) == ["reported", "derived", "derived", "derived"]
    assert list(aaa("capex", "FY")["value"]) == [-40.0]
    assert list(aaa("revenue", "FY")["period_end"]) == ["2024-12-31", "2025-12-31"]
    snap = rows(fresh, "SELECT companies, cells_present, detail_json FROM out_coverage_snapshot")
    assert snap["companies"].iloc[0] == 2
    detail = json.loads(snap["detail_json"].iloc[0])
    assert detail["pipeline"]["never_fetched"] == 0
    assert {c["symbol"] for c in detail["companies"]} == set(SYMBOLS)

    before = rows(fresh, "SELECT COUNT(*) AS n FROM raw_sec_fact")["n"].iloc[0]
    job.make_due(fresh, "sec_companyfacts")
    again = job.run_job(fresh, cfg, ctx=context(cfg), do_coverage=False)
    assert again["groups"]["sec"]["rows"] == 0  # same payloads: nothing stored twice
    assert rows(fresh, "SELECT COUNT(*) AS n FROM raw_sec_fact")["n"].iloc[0] == before
    assert again["groups"]["yahoo"]["requests"] == 0  # prices not due again yet


@respx.mock(assert_all_called=False)
def test_rate_limit_and_budget_stop_a_group(fresh, respx_mock) -> None:
    mock_sources(respx_mock)
    cfg = config(sec=2)  # tickers + one company
    fake = FakeYahoo(limit_after=1)
    result = job.run_job(fresh, cfg, ctx=context(cfg, fake), do_build=False, do_coverage=False)
    assert result["groups"]["sec"]["stopped"] == "budget used"
    assert result["groups"]["yahoo"]["stopped"].startswith("rate limited")
    assert result["status"] == "partial"
    pending = rows(
        fresh,
        "SELECT COUNT(*) AS n FROM ops_task WHERE status = 'pending' AND source LIKE 'yahoo%'",
    )["n"].iloc[0]
    assert pending == 5  # one of six Yahoo tasks ran; the rate-limited one is not a failure


@respx.mock(assert_all_called=False)
def test_failures_are_recorded_and_leavers_deactivated(fresh, respx_mock) -> None:
    mock_sources(respx_mock)
    respx_mock.get(sec.FACTS_URL.format(cik=1002)).mock(return_value=httpx.Response(500))
    cfg = config()
    result = job.run_job(fresh, cfg, ctx=context(cfg), do_build=False, do_coverage=False)
    assert result["groups"]["sec"]["failed"] == 1
    bad = rows(fresh, "SELECT status, attempts, last_error FROM ops_task WHERE request_key = 'BBB' "
               "AND source = 'sec_companyfacts'")  # fmt: skip
    assert bad["status"].iloc[0] == "error" and bad["attempts"].iloc[0] == 1
    assert rows(fresh, "SELECT COUNT(*) AS n FROM raw_fetch WHERE status = 'error'")["n"][0] == 1

    respx_mock.post(tradingview.SCAN_URL.format(market="america")).mock(
        return_value=httpx.Response(200, json=tv_rows(["AAA"]))
    )
    job.make_due(fresh, "tradingview")
    job.run_job(fresh, cfg, ctx=context(cfg), sources=["tradingview"], do_build=False,
                do_coverage=False)  # fmt: skip
    active = rows(fresh, "SELECT request_key, active FROM ops_task WHERE source = 'yahoo_prices'")
    assert dict(zip(active["request_key"], active["active"], strict=True)) == {
        "AAA": True, "BBB": False,
    }  # fmt: skip


@respx.mock(assert_all_called=False)
def test_coverage_counts_cells_and_switches_mode(fresh, respx_mock) -> None:
    mock_sources(respx_mock)
    cfg = config()
    job.run_job(fresh, cfg, ctx=context(cfg), do_coverage=False)
    from stock_analysis.db.coverage import load_config

    cov = load_config()
    cov["first_fiscal_year"] = 2024
    snap = snapshot(fresh, cov, today=TODAY)
    d = snap["detail"]
    aaa = next(c for c in d["companies"] if c["symbol"] == "AAA")
    assert aaa["prices"]["ok"] and aaa["earnings"]["ok"]
    assert aaa["annual"]["years"] == "2024-2025"
    assert "revenue FY2024" not in aaa["missing"] and "revenue FY2025" not in aaa["missing"]
    assert "net_income FY2025" in aaa["missing"]
    assert not aaa["covered"] and d["mode"] == "backfill"
    rev = next(i for i in d["items"] if i["item"] == "revenue")
    assert rev["required"] == 4 and rev["present"] == 4  # 2 companies x 2 years
    assert d["trend"][-1]["date"] == TODAY.isoformat()
    # every absent value is in out_coverage_gap with its reason
    gap = (
        "SELECT status, reason FROM out_coverage_gap "
        "WHERE symbol = 'AAA' AND item = '{}' AND period = 'FY2025'"
    )
    assert rows(fresh, gap.format("net_income"))["status"].tolist() == ["missing"]
    assert aaa["absent"]["missing"] == aaa["missing_count"]
    # a line the company doesn't report: absent for a reason, so not a gap
    cov["not_reported"] = [{"symbols": ["AAA"], "items": ["net_income"], "reason": "no such line"}]
    d1 = snapshot(fresh, cov, today=TODAY)["detail"]
    aaa1 = next(c for c in d1["companies"] if c["symbol"] == "AAA")
    assert "net_income FY2025" not in aaa1["missing"]
    assert rows(fresh, gap.format("net_income")).values.tolist() == [
        ["not_reported", "no such line"]
    ]
    assert d1["totals"]["absent"]["not_reported"] >= 1 and "gap_rows" not in d1
    # a rule for every company, fourth quarters only (fiscal years end in December here)
    cov["not_reported"] = [{"all": True, "items": ["capex"], "quarters": ["Q4"], "reason": "q4"}]
    snapshot(fresh, cov, today=TODAY)
    q = "SELECT period, status FROM out_coverage_gap WHERE symbol = 'BBB' AND item = 'capex' "
    status = dict(rows(fresh, q + "AND period LIKE '2025-%'").values.tolist())
    assert status["2025-12"] == "not_reported" and status["2025-09"] == "missing"
    # everything accepted by hand: covered, and the job may switch to maintenance
    items = [i["item"] for i in d["items"]]
    cov["explained"] = [{"symbol": s, "item": i, "reason": "test"} for s in SYMBOLS for i in items]
    d2 = snapshot(fresh, cov, today=TODAY)["detail"]
    assert d2["totals"]["companies_covered"] == 2 and d2["mode"] == "maintain"
    assert len(rows(fresh, "SELECT * FROM out_coverage_snapshot")) == 1  # one row per day
    with fresh.connect() as conn:
        assert job.choose_mode(conn, 0.95) == "maintain"


@respx.mock(assert_all_called=False)
def test_predecessor_cik_fills_the_years_before_the_new_company(
    fresh, respx_mock, monkeypatch
) -> None:
    """AAA's earlier filings are under CIK 2001 until mid-2024 (config/companies.toml): its
    FY2023 comes from there, while FY2024 stays the new company's own figure."""
    from stock_analysis.db import build as build_module

    companies = {"predecessor": [{"symbol": "AAA", "cik": 2001, "until": "2024-06-30"}]}
    monkeypatch.setattr(job, "load_companies", lambda: companies)
    monkeypatch.setattr(build_module, "load_companies", lambda: companies)
    mock_sources(respx_mock)
    old = {"cik": 2001, "facts": {"us-gaap": {"Revenues": {"units": {"USD": [
        fact("2023-01-01", "2023-12-31", 300.0, "2024-02-20", accn="old23"),
        fact("2024-01-01", "2024-12-31", 999.0, "2025-02-20", accn="old24"),  # after `until`
    ]}}}}}  # fmt: skip
    respx_mock.get(sec.FACTS_URL.format(cik=2001)).mock(return_value=httpx.Response(200, json=old))
    cfg = config()
    job.run_job(fresh, cfg, ctx=context(cfg), do_coverage=False)
    task = rows(fresh, "SELECT symbol, status FROM ops_task WHERE request_key = 'CIK2001'")
    assert task.values.tolist() == [["AAA", "ok"]]
    rev = rows(
        fresh,
        "SELECT f.fiscal_year, f.value FROM v_fundamental_latest f JOIN core_company c "
        "USING (company_id) WHERE c.symbol = 'AAA' AND f.item = 'revenue' "
        "AND f.period_type = 'FY' ORDER BY 1",
    )
    assert rev.values.tolist() == [[2023, 300.0], [2024, 400.0], [2025, 500.0]]


@respx.mock(assert_all_called=False)
def test_payload_is_kept_and_a_new_tag_is_read_from_it(fresh, respx_mock) -> None:
    """The company-facts file is kept as SEC returned it; a tag mapped later is read from the
    kept copy (reparse), without asking SEC again."""
    from stock_analysis.ingest.common import read_payload

    mock_sources(respx_mock)
    keep = {("us-gaap", "Revenues")}
    with fresh.begin() as conn:
        first = sec.load_companyfacts(conn, httpx.Client(), 1001, keep)
        again = sec.load_companyfacts(conn, httpx.Client(), 1001, keep)
        kept = read_payload(conn, first.fetch_ids[0])
    assert first.stored > 0 and again.stored == 0 and not again.fetch_ids  # same: skipped
    assert json.loads(kept) == companyfacts(1001)  # byte for byte what SEC sent
    calls = respx_mock.calls.call_count
    result = sec.reparse_companyfacts(fresh, keep | {("us-gaap", "Assets")})
    assert result == {"files": 1, "stored": 1}  # the one Assets fact
    assert respx_mock.calls.call_count == calls  # no request
    assert sec.reparse_companyfacts(fresh, keep | {("us-gaap", "Assets")})["stored"] == 0


@respx.mock(assert_all_called=False)
def test_a_downloaded_file_is_imported_and_not_fetched_again(fresh, respx_mock, tmp_path) -> None:
    """SEC's companyfacts.zip, downloaded by hand: the followed companies' facts go into raw
    as the API's would, their tasks count as fetched, and the job asks SEC for nothing."""
    import zipfile

    from stock_analysis.ingest.files import import_file

    mock_sources(respx_mock)
    cfg = config()
    job.run_job(fresh, cfg, ctx=context(cfg), sources=["tradingview", "sec_tickers"],
                do_build=False, do_coverage=False)  # fmt: skip
    folder = tmp_path / "sec_companyfacts"
    folder.mkdir()
    bulk = folder / "companyfacts.zip"
    with zipfile.ZipFile(bulk, "w") as z:
        for cik in (1001, 1002, 9999):  # 9999: a company the database doesn't follow
            z.writestr(f"CIK{cik:010d}.json", json.dumps(companyfacts(cik)))
    result = import_file(fresh, bulk, symbols=None)
    assert result["kind"] == "sec_companyfacts" and result["new"] == 2
    assert result["skipped_not_followed"] == 1 and result["stored"] > 0
    assert import_file(fresh, bulk)["new"] == 0  # the same payloads: nothing new
    t = rows(fresh, "SELECT request_key, status, next_due_at > now() AS later FROM ops_task "
                    "WHERE source = 'sec_companyfacts' ORDER BY 1")  # fmt: skip
    assert t.values.tolist() == [["AAA", "ok", True], ["BBB", "ok", True]]
    calls = respx_mock.calls.call_count
    job.run_job(fresh, cfg, ctx=context(cfg), sources=["sec_companyfacts"], do_build=False,
                do_coverage=False)  # fmt: skip
    assert respx_mock.calls.call_count == calls  # nothing due: no request to SEC
    urls = rows(fresh, "SELECT DISTINCT url FROM raw_fetch WHERE source = 'sec_companyfacts'")
    assert sorted(urls["url"]) == [
        "file:companyfacts.zip#CIK0000001001.json", "file:companyfacts.zip#CIK0000001002.json"
    ]  # fmt: skip


@respx.mock(assert_all_called=False)
def test_data_set_keeps_only_what_company_facts_lacks(fresh, respx_mock) -> None:
    import pandas as pd

    from stock_analysis.ingest.files import not_in_company_facts

    mock_sources(respx_mock)
    with fresh.begin() as conn:
        sec.load_companyfacts(conn, httpx.Client(), 1001, {("us-gaap", "Revenues")})
        row = {"cik": 1001, "axis": "", "member": "", "unit": "USD", "custom": False,
               "concept": "us-gaap:Revenues", "period_end": "2025-12-31"}  # fmt: skip
        part = pd.DataFrame([
            {**row, "accn": "k25"},                      # in company facts: dropped
            {**row, "accn": "q9", "period_end": "2026-06-30"},  # a filing it lacks: kept
            {**row, "accn": "k25", "custom": True, "concept": "custom:Own"},  # own tag: kept
        ])  # fmt: skip
        kept = not_in_company_facts(conn, 1001, part)
    assert kept["accn"].tolist() == ["q9", "k25"]


@pytest.fixture()
def peer(pg_url: str):  # noqa: F811
    """A second empty, migrated database: the server a push sends to."""
    import os

    from stock_analysis.db import Database

    admin = Database(pg_url, os.environ.get("STOCK_DB_PASSWORD"))
    with admin.connect() as conn:
        conn = conn.execution_options(isolation_level="AUTOCOMMIT")
        exists = conn.exec_driver_sql(
            "SELECT 1 FROM pg_database WHERE datname = 'stock_test_peer'"
        ).fetchone()
        if not exists:
            conn.exec_driver_sql("CREATE DATABASE stock_test_peer")
    admin.close()
    db = empty_db(pg_url.rsplit("/", 1)[0] + "/stock_test_peer")
    db.migrate()
    yield db
    db.close()


@respx.mock(assert_all_called=False)
def test_push_sends_kept_payloads_without_asking_sec(fresh, peer, respx_mock) -> None:
    """The PC fetched AAA's company facts and a full filing; a push gives the server the
    same raw rows and marks its tasks fetched, with no request to SEC."""
    from stock_analysis.ingest.push import push

    mock_sources(respx_mock)
    cfg = config()
    for db in (fresh, peer):  # both know the universe and the CIKs
        job.run_job(db, cfg, ctx=context(cfg), sources=["tradingview", "sec_tickers"],
                    do_build=False, do_coverage=False)  # fmt: skip
    job.run_job(fresh, cfg, ctx=context(cfg), sources=["sec_companyfacts"], do_build=False,
                do_coverage=False)  # fmt: skip
    calls = respx_mock.calls.call_count
    result = push(fresh, peer, ["sec_companyfacts"])
    assert respx_mock.calls.call_count == calls  # nothing asked of SEC
    assert result["sec_companyfacts"]["payloads"] == 2
    count = "SELECT COUNT(*) AS n FROM raw_sec_fact"
    assert rows(peer, count)["n"][0] == rows(fresh, count)["n"][0] > 0
    t = rows(peer, "SELECT request_key, status FROM ops_task WHERE source = 'sec_companyfacts' "
                   "ORDER BY 1")  # fmt: skip
    assert t.values.tolist() == [["AAA", "ok"], ["BBB", "ok"]]
    assert push(fresh, peer, ["sec_companyfacts"])["sec_companyfacts"]["payloads"] == 0
    assert job.raw_since_build(peer)  # the server's next run rebuilds core


def test_only_one_run_at_a_time(fresh) -> None:
    from sqlalchemy import text

    with fresh.connect() as other:
        other.execute(text("SELECT pg_advisory_lock(:k)"), {"k": job.LOCK_KEY})
        cfg = config()
        result = job.run_job(fresh, cfg, ctx=context(cfg))
        assert result["status"] == "skipped"
        other.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": job.LOCK_KEY})
    assert rows(fresh, "SELECT COUNT(*) AS n FROM ops_run")["n"].iloc[0] == 0


@respx.mock(assert_all_called=True)
def test_job_opens_and_closes_its_firewall_rule(respx_mock, monkeypatch) -> None:
    from stock_analysis.db import azure

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://identity.local/token")
    monkeypatch.setenv("IDENTITY_HEADER", "h")
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", "sub-1")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    respx_mock.get("http://identity.local/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok"})
    )
    respx_mock.get(azure.IP_SERVICE).mock(return_value=httpx.Response(200, text="20.1.2.3"))
    url = azure._rule_url("sub-1", "stock-rg", "stock-db-bk", "ingest-job")
    put = respx_mock.put(url).mock(
        return_value=httpx.Response(202, headers={"Azure-AsyncOperation": "https://op.local/1"})
    )
    respx_mock.get("https://op.local/1").mock(
        side_effect=[httpx.Response(200, json={"status": "InProgress"}),
                     httpx.Response(200, json={"status": "Succeeded"}),
                     httpx.Response(200, json={"status": "Succeeded"})]
    )  # fmt: skip
    delete = respx_mock.delete(url).mock(
        return_value=httpx.Response(202, headers={"Azure-AsyncOperation": "https://op.local/1"})
    )
    with azure.JobFirewall("server-writer", http=httpx.Client(), sleep=lambda s: None) as ip:
        assert ip == "20.1.2.3"
        sent = json.loads(put.calls.last.request.content)
        assert sent["properties"] == {"startIpAddress": "20.1.2.3", "endIpAddress": "20.1.2.3"}
        assert put.calls.last.request.headers["Authorization"] == "Bearer tok"
        assert not delete.called
    assert delete.called


def test_firewall_helper_does_nothing_outside_azure(monkeypatch) -> None:
    from stock_analysis.db import azure

    for name in ("IDENTITY_ENDPOINT", "IDENTITY_HEADER", "AZURE_SUBSCRIPTION_ID"):
        monkeypatch.delenv(name, raising=False)
    with azure.JobFirewall("local", http=httpx.Client()) as ip:
        assert ip is None


@respx.mock(assert_all_called=True)
def test_a_finished_run_asks_github_to_rebuild_the_site(respx_mock, monkeypatch) -> None:
    from stock_analysis.ingest import notify

    monkeypatch.setenv("GITHUB_DISPATCH_TOKEN", "t0ken")
    url = notify.DISPATCH_URL.format(repo=notify.REPOSITORY, workflow="pages.yml")
    route = respx_mock.post(url).mock(return_value=httpx.Response(204))
    assert "started" in notify.publish_site(httpx.Client())
    assert json.loads(route.calls.last.request.content) == {"ref": "main"}
    assert route.calls.last.request.headers["Authorization"] == "Bearer t0ken"
    monkeypatch.delenv("GITHUB_DISPATCH_TOKEN")
    assert "daily schedule" in notify.publish_site(httpx.Client())


def test_coverage_page_renders(monkeypatch, tmp_path) -> None:
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "analysis" / "site.py"
    spec = importlib.util.spec_from_file_location("site_page", path)
    site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(site)
    monkeypatch.delenv("STOCK_API_KEY", raising=False)
    monkeypatch.setattr(site, "db", lambda: None)
    menu = [("index", "Watch list"), ("coverage", "Data")]
    assert "No coverage snapshot yet" in site.coverage_page(menu)
    company = {
        "symbol": "AAA", "name": "AAA <Corp>", "sector": "Utilities", "covered": False,
        "share": 0.5, "prices": {"ok": True, "share": 1.0, "last": "2026-11-16"},
        "quarterly": {"present": 4, "required": 8}, "earnings": {"present": 8, "required": 8},
        "item_shares": [1.0, None, 0.3], "missing": ["capex FY2016"], "missing_count": 3,
    }  # fmt: skip
    detail = {
        "as_of": "2026-11-17", "universe": "SP:SPX", "mode": "backfill",
        "totals": {"companies": 1, "companies_covered": 0, "cells_required": 10,
                   "cells_present": 5, "annual_required": 6, "annual_present": 3,
                   "quarterly_required": 8, "quarterly_present": 4, "prices_ok": 1,
                   "earnings_ok": 1},
        "pipeline": {"sources": {"yahoo_prices": {"tasks": 1, "ok": 1}}, "never_fetched": 0,
                     "runs": [{"started_at": "2026-11-16T22:30:00", "mode": "backfill",
                               "status": "ok", "requests": 9, "tasks_ok": 7, "tasks_failed": 0,
                               "rows_stored": 100, "stopped": {}}],
                     "runs_to_finish": 0},
        "items": [{"item": i, "label": i.title(), "optional": False, "required": 2,
                   "present": 1} for i in ("revenue", "capex", "cash")],
        "years": [{"fiscal_year": 2016, "required": 3, "present": 1}],
        "sectors": [{"sector": "Utilities", "companies": 1, "covered": 0, "required": 10,
                     "present": 5}],
        "freshness": {"newest_price": "2026-11-16", "prices_stale": 0,
                      "no_filing_120_days": 0, "newest_filing": "2026-11-10"},
        "sources": [{"source": "sec", "values": 3}], "quality": [],
        "companies": [company], "item_order": ["revenue", "capex", "cash"],
        "trend": [{"date": "2026-11-16", "cells_required": 10, "cells_present": 2},
                  {"date": "2026-11-17", "cells_required": 10, "cells_present": 5}],
    }  # fmt: skip
    page = site.coverage_page(menu, detail)
    assert "0 / 1" in page and "50.0%" in page and "<polyline" in page
    assert "AAA &lt;Corp&gt;" in page and "<Corp>" not in page  # escaped
    assert page.count('class="c h') == 2 and 'class="c na"' in page


def test_52_53_week_quarters_sit_on_the_fiscal_calendar() -> None:
    """Costco (fiscal year to about 1 September; quarters of 12, 12, 12 and 16 weeks) and
    Kroger (to about 1 February; a 16-week first quarter): every quarter gets its fiscal slot,
    and the month end of that slot, whatever its real end date."""
    rows = [
        (1, "FY", "2024-09-01", "FY2024 Aug"),
        (1, "Q", "2024-11-24", "Q1 Nov"),
        (1, "Q", "2025-02-16", "Q2 Feb"),
        (1, "Q", "2025-05-11", "Q3 May"),  # nearest month end is April 30
        (1, "I", "2025-05-11", "Q3 May"),  # the balance sheet of that quarter
        (1, "FY", "2025-08-31", "FY2025 Aug"),
        (2, "FY", "2025-02-01", "FY2025 Jan"),  # fiscal year = the year it ends in
        (2, "Q", "2025-05-24", "Q1 Apr"),  # 16 weeks
        (2, "Q", "2025-08-16", "Q2 Jul"),
        (2, "Q", "2025-11-08", "Q3 Oct"),
        (2, "Q", "2025-12-15", "dropped"),  # half way between two quarters: not a quarter
    ]
    c = pd.DataFrame(
        [
            {"company_id": cid, "period_type": t, "period_end": end, "filed": None}
            for cid, t, end, _ in rows
        ]
    )
    out = add_periods(c)
    assert len(out) == len(rows) - 1
    got = [
        f"{p} {pd.Timestamp(e):%b}"
        for p, e in zip(out["fiscal_period"], out["period_end"], strict=True)
    ]
    got = [g.replace("FY ", f"FY{y} ") for g, y in zip(got, out["fiscal_year"], strict=True)]
    assert got == [r[3] for r in rows[:-1]]
    assert out["fiscal_year"].tolist() == [
        2024,
        2025,
        2025,
        2025,
        2025,
        2025,
        2025,
        2026,
        2026,
        2026,
    ]
    assert out["period_end"].iloc[3] == "2025-05-31"


# ---------------------------------------------------------------- issue #33: what the scripts read


@respx.mock(assert_all_called=False)
def test_watch_list_symbols_and_market_instruments_are_fetched(fresh, respx_mock, tmp_path):
    """The watch list's peers outside the index get tasks and core rows like members, the
    market instruments land in core_market_daily, and earnings dates are due again in the
    days after a report."""
    mock_sources(respx_mock)
    with fresh.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO user_watchlist (symbol, position, target_pe) VALUES ('AAA', 1, 15)"
        )
        conn.exec_driver_sql("INSERT INTO user_watchlist_peer (symbol, peer, position) "
                             "VALUES ('AAA', 'ZZZ', 1)")  # fmt: skip
    market = tmp_path / "market.toml"
    market.write_text('[markets]\n"^GSPC" = "S&P 500"\n[sectors]\nXLU = "Utilities"\n')
    cfg = config(watch=True)
    cfg["extra_symbols"] = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(job, "MARKET_CONFIG", market)
        mp.setattr(build_module, "MARKET_CONFIG", market)
        result = job.run_job(fresh, cfg, ctx=context(cfg))
    assert result["status"] in ("ok", "partial"), result
    tasks = rows(fresh, "SELECT source, request_key, status FROM ops_task")
    by = {(r.source, r.request_key): r.status for r in tasks.itertuples()}
    assert by[("yahoo_prices", "ZZZ")] == "ok"  # the peer, not in the index
    assert by[("yahoo_market", "^GSPC")] == "ok" and by[("yahoo_market", "XLU")] == "ok"
    assert ("tradingview_watchlist", "watchlist") in by
    companies = set(rows(fresh, "SELECT symbol FROM core_company")["symbol"])
    assert "ZZZ" in companies  # from the watch list's own TradingView snapshot
    members = rows(fresh, "SELECT c.symbol FROM core_index_member m JOIN core_company c "
                          "USING (company_id) WHERE m.end_date IS NULL")  # fmt: skip
    assert "ZZZ" not in set(members["symbol"])  # but not an index member
    m = rows(fresh, "SELECT symbol, COUNT(*) AS n FROM core_market_daily GROUP BY symbol")
    assert set(m["symbol"]) == {"^GSPC", "XLU"} and (m["n"] > 100).all()
    tv = rows(fresh, "SELECT extra_json FROM v_tv_latest WHERE symbol = 'AAA'")
    assert "fundamental_currency_code" in tv["extra_json"].iloc[0]


def test_earnings_are_due_again_after_a_report(fresh) -> None:
    now = job.utcnow()
    with fresh.begin() as conn:
        f = conn.exec_driver_sql(
            "INSERT INTO raw_fetch (source, request_key, url, fetched_at, loaded_at, status) "
            "VALUES ('yahoo_earnings', 'AAA', 'x', '2026-01-01', '2026-01-01', 'ok') "
            "RETURNING fetch_id"
        ).scalar()
        day = (now - pd.Timedelta(days=1)).date().isoformat()
        conn.exec_driver_sql(
            f"INSERT INTO raw_yahoo_earnings (fetch_id, symbol, report_date, eps_reported) "
            f"VALUES ({f}, 'AAA', '{day}', 1.0), ({f}, 'BBB', '2020-01-01', 1.0)"
        )
        later = (now + pd.Timedelta(days=5)).isoformat()
        before = (now - pd.Timedelta(days=3)).isoformat()
        for sym in ("AAA", "BBB"):
            conn.exec_driver_sql(
                "INSERT INTO ops_task (source, request_key, symbol, created_at, next_due_at, "
                f"last_success_at) VALUES ('yahoo_earnings', '{sym}', '{sym}', '{before}', "
                f"'{later}', '{before}')"
            )
        assert job.earnings_due(conn, now) == 1  # AAA reported yesterday; BBB long ago


def test_xbrl_units_named_as_company_facts_names_them() -> None:
    """A filing names its own unit ids (Berkshire: 'U_shares', 'U_xbrlishares')."""
    from stock_analysis.ingest.xbrl import unit_of

    assert [unit_of(u, None) for u in ("shares", "U_shares", "U_xbrlishares", "Shares")] == [
        "shares"
    ] * 4
    assert unit_of("U_USDPerShare", "USD") == "USD/shares"
    assert unit_of("usd", None) == "USD" and unit_of("U_iso4217USD", "USD") == "USD"
    assert unit_of("pure", None) == "pure"
