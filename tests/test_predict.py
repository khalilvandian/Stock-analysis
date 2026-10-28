"""Predictive analysis: point-in-time logic, labels and walk-forward purging (no network)."""

import httpx
import numpy as np
import pandas as pd
import pytest
import respx

from stock_analysis.predict import features, labels, load_config, models, universe
from stock_analysis.predict.prices import Prices
from stock_analysis.predict.sec import Facts


def _chart(days: pd.DatetimeIndex, adj: np.ndarray, close=None, splits=(), divs=()):
    t = [int(x) for x in (days - pd.Timestamp("1970-01-01")) // pd.Timedelta("1s")]
    return {
        "ok": True,
        "t": t,
        "close": list(close if close is not None else adj),
        "adjclose": list(adj),
        "splits": list(splits),
        "dividends": list(divs),
    }


def _bdays(start, end):
    return pd.bdate_range(start, end)


def test_config_loads():
    cfg = load_config()
    assert cfg["labels"]["horizon_years"] == 5
    assert (
        len(universe.decision_dates(cfg))
        == cfg["dates"]["last_year"] - cfg["dates"]["first_year"] + 1
    )


def test_members_on_uses_start_and_end():
    m = pd.DataFrame(
        {
            "ticker": ["A", "B", "C"],
            "start": pd.to_datetime(["2000-01-01", "2012-01-01", "2000-01-01"]),
            "end": pd.to_datetime([None, None, "2011-06-01"]),
        }
    )
    assert universe.members_on(m, "2011-01-01") == ["A", "C"]
    assert universe.members_on(m, "2013-01-01") == ["A", "B"]


def _facts():
    # revenue for FY2014 is first filed in Feb 2015 and restated in Feb 2016
    recs = [
        ["2013-01-01", "2013-12-31", 100.0, "10-K", "2014-02-20"],
        ["2014-01-01", "2014-12-31", 110.0, "10-K", "2015-02-20"],
        ["2014-01-01", "2014-12-31", 111.0, "10-K", "2016-02-20"],
        ["2015-01-01", "2015-12-31", 130.0, "10-K", "2016-02-20"],
        ["2015-01-01", "2015-03-31", 30.0, "10-Q", "2015-05-01"],
    ]
    return Facts({"facts": {"Revenues": recs}})


def test_annual_is_point_in_time():
    f = _facts()
    s = f.annual(["Revenues"], "2015-06-30", instant=False)
    assert list(s.values) == [100.0, 110.0]  # FY2015 not filed yet, restatement not known
    s = f.annual(["Revenues"], "2016-06-30", instant=False)
    assert list(s.values) == [100.0, 111.0, 130.0]  # restated value once it was filed


def test_split_factor():
    splits = pd.Series([4.0], index=pd.to_datetime(["2020-08-31"]))
    assert features.split_factor(splits, "2019-10-30", "2021-06-30") == 4.0
    assert features.split_factor(splits, "2020-10-30", "2021-06-30") == 1.0
    assert features.split_factor(splits, "2019-10-30", "2020-06-30") == 1.0


def test_actual_price_undoes_later_splits():
    days = _bdays("2020-01-01", "2020-12-31")
    split_ts = int(pd.Timestamp("2020-08-31", tz="UTC").timestamp())
    p = Prices(_chart(days, np.full(len(days), 100.0), splits=[[split_ts, 4, 1]]))
    assert p.actual_price("2020-06-30") == pytest.approx(400.0)
    assert p.actual_price("2020-10-30") == pytest.approx(100.0)


def test_labels_volatile_winner_is_not_good():
    days = _bdays("2015-06-01", "2020-07-15")
    n = len(days)
    spy = Prices(_chart(days, 100 * 1.08 ** (np.arange(n) / 252)))
    # the stock beats the index (ends 2x) but halves on the way
    path = np.concatenate([np.linspace(100, 45, n // 2), np.linspace(45, 200, n - n // 2)])
    stock = Prices(_chart(days, path))
    rf = pd.Series(1.0, index=days)
    lab = labels.compute(stock, spy, rf, "2015-06-30", 5, dd_margin=0.15)
    assert lab["beat_index"] == 1.0
    assert lab["max_dd"] > 0.5
    assert lab["good"] == 0.0
    steady = Prices(_chart(days, 100 * 1.10 ** (np.arange(n) / 252)))
    lab2 = labels.compute(steady, spy, rf, "2015-06-30", 5, dd_margin=0.15)
    assert lab2["good"] == 1.0 and lab2["max_dd"] == pytest.approx(0.0)


def test_labels_need_the_full_window():
    days = _bdays("2015-06-01", "2018-01-01")  # stops after 2.5 years
    p = Prices(_chart(days, np.linspace(100, 120, len(days))))
    lab = labels.compute(p, p, pd.Series(dtype=float), "2015-06-30", 5)
    assert np.isnan(lab["cagr"])


def test_walk_forward_never_trains_on_unfinished_labels():
    rng = np.random.default_rng(0)
    rows = []
    for c in range(2010, 2022):
        for i in range(80):
            rows.append(
                {
                    "cohort": c,
                    "ticker": f"T{i}",
                    "sector": "Technology",
                    "lynch_category": "stalwart",
                    "y5_x": rng.normal(),
                    "y5_excess_cagr": rng.normal(),
                    **{f: rng.normal() for f in models.NUMERIC},
                }
            )
    df = pd.DataFrame(rows)
    assert models.test_cohorts(df, 5, 2) == list(range(2016, 2022))
    scores, _ = models.walk_forward(df, "y5_x", 5, models={"Ridge": models.Ridge(alpha=1.0)})
    first = scores[scores.cohort == 2016].iloc[0]
    assert first.n_train == 160  # only cohorts 2010 and 2011 (2011 + 5 = 2016)


def test_lynch_category():
    eps = pd.Series([1.0, 1.3, 1.7, 2.2, 2.9])
    assert features.lynch_category(eps, 0.3, 3.0, 0.0) == "fast_grower"
    assert features.lynch_category(pd.Series([1.0, -0.5]), np.nan, 2.0, 0.0) == "turnaround"
    assert features.lynch_category(pd.Series([-1.0, -0.5]), np.nan, 2.0, 0.0) == "no_profit"


def test_sector_from_sic():
    assert features.sector_from_sic(3674) == "Technology"
    assert features.sector_from_sic(2834) == "Health care"
    assert features.sector_from_sic(6798) == "Real estate"
    assert features.sector_from_sic(None) == "Unknown"


@respx.mock
def test_resolve_detects_rename_and_keeps_current():
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "0": {"cik_str": 1, "ticker": "META", "title": "Meta"},
                "1": {"cik_str": 2, "ticker": "AAPL", "title": "Apple"},
            },
        )
    )
    m = pd.DataFrame(
        {
            "ticker": ["FB", "META", "AAPL"],
            "start": pd.to_datetime(["2013-12-23", "2022-06-09", "1990-01-01"]),
            "end": pd.to_datetime(["2022-06-09", None, None]),
        }
    )
    changes = pd.DataFrame(
        columns=["date", "added_ticker", "added_name", "removed_ticker", "removed_name", "reason"]
    )
    with httpx.Client() as c:
        out = universe.resolve(
            m, changes, ["AAPL", "FB"], c, first_annual_filed=lambda cik: pd.Timestamp("2013-01-01")
        ).set_index("ticker")
    assert out.loc["AAPL", "method"] == "sec_current"
    assert out.loc["FB", "method"] == "rename:META"
    assert out.loc["FB", "yahoo"] == "META"


def test_log_trend_straight_line_and_k_ratio_prefers_steady_path():
    from stock_analysis.predict import growth

    days = pd.date_range("2015-01-01", periods=60, freq="ME")
    line = pd.Series(np.exp(0.1 * np.arange(60) / 12), index=days)
    slope, r2, _ = growth.log_trend(line)
    assert slope == pytest.approx(0.1, rel=0.02)
    assert r2 == pytest.approx(1.0, abs=1e-4)
    wobble = line * np.exp(0.3 * np.sin(np.arange(60) / 3))
    assert (
        growth.log_trend(wobble)[2] < growth.log_trend(line * (1 + 1e-3 * np.cos(np.arange(60))))[2]
    )


def test_price_growth_labels_on_a_steady_climb():
    from stock_analysis.predict import growth

    days = pd.bdate_range("2014-01-01", "2020-12-31")
    yrs = (days - days[0]).days / 365.25
    stock = Prices(_chart(days, 10 * np.exp(0.12 * yrs)))
    spy = Prices(_chart(days, 100 * np.exp(0.08 * yrs)))
    out = growth.price_growth(stock, spy, "2015-06-30", 5)
    assert out["trend_growth"] == pytest.approx(np.exp(0.12) - 1, rel=0.01)
    assert out["excess_trend"] == pytest.approx(np.exp(0.12) - np.exp(0.08), rel=0.02)
    assert out["trend_r2"] == pytest.approx(1.0, abs=1e-4)
    assert out["win_12m"] == 1.0 and out["underwater"] == 0.0
    assert out["worst_12m"] > 0.1
