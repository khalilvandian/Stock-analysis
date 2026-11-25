"""Unit tests for the data pipeline: missing values, splits, currencies, outliers and the
cross-checks between sources. No network and no database: HTTP is mocked with respx,
the database with a small fake (FakeData); everything else runs on small hand-built frames.

Four tests here first exposed bugs (double split, reverse splits, NaN price, empty Yahoo
history); they are regression tests now.
"""

import numpy as np
import pandas as pd
import pytest

from stock_analysis import nightly, stocks  # noqa: E402
from stock_analysis.report import render  # noqa: E402
from stock_analysis.screener import common as screen_common  # noqa: E402
from stock_analysis.screener import (
    stage1,  # noqa: E402
    stage2,  # noqa: E402
)
from stock_analysis.screener.common import load_config  # noqa: E402

# --- helpers -------------------------------------------------------------------------


def _earnings(rows: list[tuple[str, float | None]]) -> pd.DataFrame:
    idx = pd.to_datetime([d for d, _ in rows]).tz_localize("America/New_York")
    return pd.DataFrame({"EPS Estimate": 1.0, "Reported EPS": [e for _, e in rows]}, index=idx)


def _quarters(n: int = 48, eps: float = 1.0, start: str = "2014-02-15") -> pd.Series:
    idx = pd.date_range(start, periods=n, freq="91D")
    return pd.Series(eps, index=idx, dtype=float)


def _key_inputs(price=100.0, q=None, next_estimate=np.nan) -> dict:
    q = _quarters() if q is None else q
    prices = pd.Series(100.0, index=pd.bdate_range("2015-01-01", "2026-10-23"))
    return {
        "stock": {"symbol": "X", "target_pe": 15},
        "row": {"price": price},
        "prices": prices,
        "quarters": q,
        "ttm": nightly.trailing_eps(q),
        "next_report": None,
        "next_estimate": next_estimate,
    }


# --- 1. missing values: adjusted EPS and P/E history ----------------------------------


def test_quarterly_eps_of_an_empty_or_all_blank_frame_is_empty():
    empty = pd.DataFrame(
        {"EPS Estimate": [], "Reported EPS": []},
        index=pd.DatetimeIndex([], tz="America/New_York"),
    )
    assert nightly.quarterly_eps(empty).empty
    blank = _earnings([("2026-01-20", None), ("2026-04-20", np.nan)])
    q = nightly.quarterly_eps(blank)
    assert q.empty and q.dtype == float
    assert nightly.trailing_eps(q).empty


def test_quarterly_eps_ignores_overrides_for_unknown_dates_and_keeps_order():
    d = _earnings([("2026-07-16", 1.2), ("2026-01-20", 1.0), ("2026-04-16", None)])
    q = nightly.quarterly_eps(d, [{"reported": "2025-01-01", "eps": 99.0}])
    assert list(q) == [1.0, 1.2]  # blank quarter dropped, oldest first, override ignored
    assert q.index.is_monotonic_increasing and q.index.tz is None


def test_quarterly_eps_keeps_the_later_of_two_entries_for_the_same_quarter():
    d = _earnings([("2026-01-20", 1.0), ("2026-02-05", 1.1), ("2026-04-20", 1.2)])
    assert list(nightly.quarterly_eps(d)) == [1.1, 1.2]


def test_trailing_eps_needs_four_quarters():
    assert nightly.trailing_eps(_quarters(3)).empty
    assert nightly.trailing_eps(pd.Series(dtype=float, index=pd.DatetimeIndex([]))).empty
    ttm = nightly.trailing_eps(_quarters(5))
    assert list(ttm) == [4.0, 4.0]


def test_yearly_pe_blank_for_a_loss_year_and_empty_without_eps():
    prices = pd.Series(100.0, index=pd.bdate_range("2023-01-01", "2026-06-30"))
    ttm = pd.Series([-2.0, 5.0], index=pd.to_datetime(["2024-02-10", "2025-02-10"]))
    y = nightly.yearly_pe(prices, ttm)
    assert np.isnan(y.loc[2023, "pe"]) and y.loc[2024, "pe"] == 20.0
    assert nightly.yearly_pe(prices, pd.Series(dtype=float, index=pd.DatetimeIndex([]))).empty
    # a year whose Q4 report never came (no EPS before April 30) is left out
    late = pd.Series([5.0], index=pd.to_datetime(["2025-06-10"]))
    assert nightly.yearly_pe(prices, late).empty


def test_daily_pe_blank_while_eps_is_negative():
    prices = pd.Series(50.0, index=pd.bdate_range("2025-01-01", "2025-12-31"))
    ttm = pd.Series([-1.0, 2.0], index=pd.to_datetime(["2024-12-01", "2025-07-01"]))
    pe = nightly.daily_pe(prices, ttm)
    assert pe.index.min() >= pd.Timestamp("2025-07-01") and set(pe) == {25.0}


def test_next_report_none_when_every_report_is_in():
    d = _earnings([("2026-01-20", 1.0), ("2026-04-20", 1.1)])
    when, est = nightly.next_report(d, pd.Timestamp("2026-10-27"))
    assert when is None and np.isnan(est)


def test_key_numbers_entry_price_from_target_pe_and_adjusted_eps():
    k = nightly.key_numbers(_key_inputs(next_estimate=1.5))
    assert k["eps_adj_ttm"] == 4.0 and k["pe_adj"] == 25.0
    assert k["pe_median_10y"] == 25.0
    assert k["entry_price"] == 60.0 and round(k["to_entry"], 4) == -0.4
    # next report replaces the oldest of the four quarters: 4 - 1 + 1.5
    assert k["entry_after_next"] == 15 * 4.5


def test_key_numbers_keeps_equity_stakes_out_of_the_pe_and_adds_them_to_the_entry():
    d = _key_inputs(next_estimate=1.5)
    d["stock"]["stakes_per_share"] = 20.0
    k = nightly.key_numbers(d)
    assert k["pe_adj"] == 20.0  # (100 - 20) / 4
    assert k["entry_price"] == 80.0 and k["entry_after_next"] == 15 * 4.5 + 20


def test_key_numbers_without_a_target_has_no_entry_price():
    d = _key_inputs(next_estimate=1.5)
    del d["stock"]["target_pe"]
    k = nightly.key_numbers(d)
    assert k["pe_adj"] == 25.0
    assert np.isnan(k["target_pe"]) and np.isnan(k["entry_price"])
    assert np.isnan(k["to_entry"]) and np.isnan(k["entry_after_next"])
    assert render.target_text(k["target_pe"]) == "–"
    assert render.price_at(k, "pe_median_10y") == "$100.00"
    # the database stores a missing target as 0: that is no target too
    d["stock"]["target_pe"] = 0.0
    assert np.isnan(nightly.key_numbers(d)["entry_price"])


def test_key_numbers_without_eps_history_is_blank_not_an_error():
    no_eps = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    k = nightly.key_numbers(_key_inputs(q=no_eps))
    for key in ("eps_adj_ttm", "pe_adj", "pe_median_10y", "entry_price", "to_entry"):
        assert np.isnan(k[key]), key
    assert k["price"] == 100.0 and k["next_report"] == ""


def test_key_numbers_with_a_loss_has_no_entry_price():
    k = nightly.key_numbers(_key_inputs(q=_quarters(eps=-0.5), next_estimate=0.1))
    assert k["eps_adj_ttm"] == -2.0
    assert np.isnan(k["pe_adj"]) and np.isnan(k["entry_price"])
    assert np.isnan(k["entry_after_next"])


def test_key_numbers_falls_back_to_the_last_close_when_yahoo_has_no_price():
    assert nightly.key_numbers(_key_inputs(price=None))["price"] == 100.0


def test_key_numbers_falls_back_to_the_last_close_when_the_price_is_nan():
    assert nightly.key_numbers(_key_inputs(price=np.nan))["price"] == 100.0


# --- 1. missing values: Stage 1 rules -------------------------------------------------


def _rule_frame(**cols) -> pd.DataFrame:
    base = {"net_cash": [False], "ebitda_ttm": [10.0]}
    base.update({k: [v] for k, v in cols.items()})
    return pd.DataFrame(base, index=["x"])


def test_rules_are_blank_not_pass_when_a_figure_is_missing():
    d = _rule_frame(
        net_income_ttm=np.nan,
        eps=1.0,
        return_on_equity_fq=np.nan,
        interest_cover=np.nan,
        net_debt_to_ebitda=np.nan,
        cash_to_short_term_debt=np.nan,
        cash_f_operating_activities_ttm=np.nan,
        eps_avg_10y=np.nan,
    )
    for name, value in (
        ("profitable", True),
        ("min_roe", 10),
        ("min_interest_cover", 4),
        ("max_net_debt_to_ebitda", 3),
        ("cash_to_short_term_debt", 1),
        ("positive_ocf", True),
        ("profitable_10y_avg", True),
    ):
        assert pd.isna(stage1._rule(d, name, value)["x"]), name


def test_a_known_failure_outweighs_a_missing_figure():
    d = _rule_frame(net_income_ttm=np.nan, eps=-1.0)
    assert stage1._rule(d, "profitable", True)["x"] is False


def test_growth_rule_blank_without_enough_history():
    d = _rule_frame(
        revenue_growth_avg=0.05,
        revenue_growth_median=0.05,
        eps_growth_avg=np.nan,
        eps_growth_median=np.nan,
    )
    assert pd.isna(stage1._rule(d, "growth_years", True)["x"])


def test_net_cash_passes_leverage_rules_without_ebitda_or_interest():
    d = _rule_frame(net_cash=True, ebitda_ttm=np.nan, interest_cover=np.nan)
    d["net_debt_to_ebitda"] = np.nan
    assert stage1._rule(d, "max_net_debt_to_ebitda", 3)["x"] is True
    assert stage1._rule(d, "min_interest_cover", 4)["x"] is True


def test_negative_ebitda_with_net_debt_fails_leverage():
    d = _rule_frame(ebitda_ttm=-5.0, net_debt_to_ebitda=np.nan)
    assert stage1._rule(d, "max_net_debt_to_ebitda", 3)["x"] is False


def test_ratios_blank_when_cash_or_debt_is_missing():
    d = pd.DataFrame(
        {
            "cash_n_short_term_invest_fq": [np.nan, 10.0],
            "short_term_debt_fq": [5.0, np.nan],
            "long_term_debt_fq": [5.0, np.nan],
            "ebitda_ttm": [10.0, 10.0],
            "net_debt_fq": [np.nan, np.nan],
            "ebitda_interst_cover_ttm": [np.nan, np.nan],
        }
    )
    stage1.ratios(d)
    assert d[["cash_to_short_term_debt", "cash_to_long_term_debt"]].isna().all().all()
    assert not d["net_cash"].any()  # unknown net debt is not net cash


def test_short_term_debt_derived_from_total_minus_long_never_negative():
    d = pd.DataFrame(
        {
            "short_term_debt_fq": [np.nan, np.nan, np.nan],
            "long_term_debt_fq": [6.0, 12.0, np.nan],
            "total_debt_fq": [10.0, 10.0, 0.0],
            "filled": "",
        }
    )
    stage1.derive_short_term_debt(d)
    assert list(d["short_term_debt_fq"]) == [4.0, 0.0, 0.0]
    assert d.loc[2, "long_term_debt_fq"] == 0.0  # no debt at all: both parts zero
    assert "total minus long-term" in d.loc[0, "filled"]


def test_history_measures_with_blank_years():
    lynch = load_config()["lynch"]
    d = pd.DataFrame(
        {
            "earnings_per_share_diluted_fy_h": [[None, 1.0, None, 0.8, 0.7], None],
            "fiscal_period_fy_h": [[2025, 2024, 2023, 2022, 2021], None],
            "dps_common_stock_prim_issue_fy_h": [None, None],
            "ebitda_fy_h": [[None] * 10, None],
            "net_debt_fq": [1.0, np.nan],
            "market_cap_basic": [10.0, np.nan],
            "total_debt_fq": [2.0, np.nan],
            "cash_n_short_term_invest_fq": [1.0, np.nan],
            "debt_to_equity_fq": [0.1, np.nan],
            "eps": [1.0, np.nan],
        },
        index=["gaps", "nothing"],
    )
    stage1.history_measures(d, lynch)
    assert np.isnan(d.loc["gaps", "eps_growth_3y"])  # newest year blank
    assert np.isnan(d.loc["nothing", "eps_avg_10y"])
    assert np.isnan(d.loc["gaps", "net_debt_to_avg_ebitda"])
    assert np.isnan(d.loc["nothing", "cash_to_total_debt"])


def test_no_category_means_incomplete_not_pass():
    d = pd.DataFrame(
        {"type": ["general"], "category": [""], "net_cash": [True]},
        index=["new"],
    )
    out = stage1.apply_screeners(d, load_config())
    assert out.loc["new", "status"] == "incomplete"
    assert "too little EPS history" in out.loc["new", "missing"]


# --- 1. missing values: Stage 2 and the email -----------------------------------------


@pytest.mark.parametrize(
    "pe, expected",
    [
        ([10, 12, 14, 16, 18], np.nan),  # five years, six needed
        ([10, 12, 14, 16, 18, np.nan, -5.0], np.nan),  # blanks and losses don't count
        ([], np.nan),
        ([np.nan] * 8, np.nan),
        ([10, 12, 14, 16, 18, 20], 12.5),
    ],
)
def test_cheap_multiple_needs_enough_positive_years(pe, expected):
    got = stage2.cheap_multiple(pd.Series(pe, dtype=float), 0.25, 6)
    assert (np.isnan(got) and np.isnan(expected)) or got == expected


def test_fiscal_pe_skips_years_without_eps_or_nine_months_of_prices():
    idx = pd.date_range("2022-01-31", "2025-12-31", freq="ME")
    prices = pd.Series(20.0, index=idx)
    prices[(idx > "2023-12-31") & (idx <= "2024-06-30")] = np.nan  # half a year missing
    h = stage2.fiscal_pe(prices, [2.0, 1.0, None, 2.0], [2025, 2024, 2023, 2022], idx[-1], 4)
    assert list(h["year"]) == [2025, 2022]
    empty = stage2.fiscal_pe(prices, [], [], idx[-1], 10)
    assert empty.empty and "pe" in empty.columns


# --- 2. splits ------------------------------------------------------------------------

# 2:1 and 10:1 forward splits, a 1-for-20 reverse split (Yahoo writes it as 0.05)
SPLITS = [2.0, 10.0, 0.05]


def test_yahoo_quarterly_eps_is_used_as_split_adjusted():
    """Yahoo restates quarterly EPS after a split, so the P/E history must not jump at the
    split: quarterly_eps and trailing_eps pass the values through unchanged."""
    split_day = pd.Timestamp("2022-06-01")
    rows = [
        (d.strftime("%Y-%m-%d"), 0.5) for d in pd.date_range("2018-02-15", periods=36, freq="91D")
    ]
    q = nightly.quarterly_eps(_earnings(rows))
    assert set(q) == {0.5}  # no rescaling on either side of the split
    prices = pd.Series(50.0, index=pd.bdate_range("2018-01-01", "2026-10-23"))  # adjusted
    yearly = nightly.yearly_pe(prices, nightly.trailing_eps(q))
    assert len(yearly) >= 6 and set(yearly["pe"]) == {25.0}
    assert yearly.index.min() < split_day.year < yearly.index.max()
    # had Yahoo not adjusted a 25:1 split, the EPS would be 25x diluted: rejected
    assert not stage2.adjusted_eps_plausible(2.0 * 25, 2.0)


# --- 3. currencies ---------------------------------------------------------------------


def test_to_usd_converts_statement_currency_and_keeps_blanks():
    d = pd.DataFrame({src: [2e9, np.nan] for src in screen_common.USD_FIELDS})
    d["fx_fund"] = [1.25, 1.25]
    screen_common.to_usd(d)
    for dst in screen_common.USD_FIELDS.values():
        assert d.loc[0, dst] == pytest.approx(2.5)
        assert np.isnan(d.loc[1, dst])  # missing stays missing, never 0


def _raw_row(tv_symbol: str, market: str, currency: str, fund: str, close: float, eps: float):
    row = {}
    for c in stage1.COLUMNS:
        if c == "fiscal_period_fy_h":
            row[c] = list(range(2025, 2015, -1))
        elif c.endswith("_fy_h"):
            row[c] = [eps * 0.95**i for i in range(10)]
        elif c == "indexes":
            row[c] = []
        else:
            row[c] = 1.0
    row |= {
        "name": tv_symbol.split(":")[1],
        "description": "Example",
        "exchange": tv_symbol.split(":")[0],
        "country": "X",
        "sector": "Technology Services",
        "industry": "Packaged Software",
        "currency": currency,
        "fundamental_currency_code": fund,
        "close": close,
        "market_cap_basic": 50e9,
        "earnings_per_share_diluted_ttm": eps,
        "total_debt_fq": 10e9,
        "net_debt_fq": 5e9,
        "cash_n_short_term_invest_fq": 5e9,
        "market": market,
        "region": "Europe",
    }
    return pd.Series(row, name=tv_symbol)


def test_stage1_prices_in_pence_and_statements_in_pounds():
    fx = {"USD": 1.0, "GBP": 1.3, "GBX": 0.013, "EUR": 1.1}
    raw = pd.DataFrame(
        [
            _raw_row("LSE:BT.A", "uk", "GBX", "GBP", close=250.0, eps=0.2),
            _raw_row("EURONEXT:XYZ", "netherlands", "EUR", "USD", close=100.0, eps=10.0),
            _raw_row("LSE:ODD", "uk", "GBp", "GBP", close=250.0, eps=0.2),  # Yahoo-style code
        ]
    )
    d = stage1.prepare(raw, load_config(), fx)
    bt = d.loc["LSE:BT.A"]
    assert bt["symbol"] == "BT.A"
    assert bt["price_fund"] == pytest.approx(2.5)  # 250 pence = 2.50 pounds
    assert bt["price_fund"] / bt["eps"] == pytest.approx(12.5)  # P/E in one currency
    assert bt["cap_usd_bn"] == pytest.approx(50e9 * 1.3 / 1e9)
    xyz = d.loc["EURONEXT:XYZ"]  # reports in dollars, trades in euros
    assert xyz["symbol"] == "XYZ" and xyz["price_fund"] == pytest.approx(110.0)
    assert xyz["cap_usd_bn"] == pytest.approx(50.0)
    # an unknown currency code is dropped, never taken as dollars
    assert "LSE:ODD" not in d.index


def test_cheap_price_returns_to_the_trading_currency():
    d = pd.DataFrame(
        {
            "region": "Europe",
            "sector": "Communications",
            "close": [250.0],
            "price_fund": [2.5],
            "eps": [0.2],
            "cheap_pe": [10.0],
            "fx_fund": [1.3],
            "fx_price": [0.013],
        },
        index=["LSE:BT.A"],
    )
    stage2.set_cheap_price(d)
    assert d.loc["LSE:BT.A", "pe_now"] == pytest.approx(12.5)
    assert d.loc["LSE:BT.A", "cheap_price"] == pytest.approx(200.0)  # pence, like close
    assert d.loc["LSE:BT.A", "vs_cheap"] == pytest.approx(0.25)


def test_own_pe_history_converts_pence_prices_to_the_eps_currency():
    months = pd.date_range("2014-01-31", "2025-12-31", freq="ME")
    prices = pd.DataFrame({"BT.A": 250.0}, index=months)  # pence
    d = pd.DataFrame(
        {
            "symbol": ["BT.A"],
            "earnings_per_share_diluted_fy_h": [[0.25] * 10],  # pounds
            "fiscal_period_fy_h": [list(range(2025, 2015, -1))],
            "fiscal_period_end_fy": [pd.Timestamp("2025-12-31").timestamp()],
            "fx_price": [0.013],
            "fx_fund": [1.3],
            "price_fund": [2.5],
            "close": [250.0],
            "eps": [0.25],
            "region": "Europe",
            "sector": "Communications",
        },
        index=["LSE:BT.A"],
    )
    cfg = {"history_years": 10, "cheap_percentile": 0.25, "min_history_years": 6}
    out = stage2.add_cheap_price(d, prices, cfg)
    assert out.loc["LSE:BT.A", "pe_years"] == 10
    assert out.loc["LSE:BT.A", "cheap_pe"] == pytest.approx(10.0)  # not 1000x
    assert out.loc["LSE:BT.A", "cheap_price"] == pytest.approx(250.0)


# --- 4. outliers ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "adjusted, diluted, ok",
    [
        (5.0, 5.0, True),
        (2.5, 5.0, True),  # the bounds are inclusive
        (10.0, 5.0, True),
        (2.49, 5.0, False),
        (10.01, 5.0, False),
        (5.0, 0.0, False),
        (5.0, -2.0, False),
        (-1.0, 5.0, False),
        (np.nan, 5.0, False),
        (5.0, np.nan, False),
        (np.inf, 5.0, False),
    ],
)
def test_adjusted_eps_plausible_bounds(adjusted, diluted, ok):
    assert stage2.adjusted_eps_plausible(adjusted, diluted) is ok


def test_loss_makers_get_no_cheap_price_and_are_never_listed():
    d = pd.DataFrame(
        {
            "region": "US",
            "sector": "Energy",
            "status": "pass",
            "close": [30.0, 30.0, 30.0],
            "price_fund": [30.0, 30.0, 30.0],
            "eps": [-2.0, 0.0, 3.0],
            "cheap_pe": [12.0, 12.0, 12.0],
            "fx_fund": 1.0,
            "fx_price": 1.0,
            "cheap_basis": "",
            "trend": "",
        },
        index=["loss", "zero", "profit"],
    )
    stage2.set_cheap_price(d)
    assert d.loc[["loss", "zero"], "pe_now"].isna().all()
    assert d.loc[["loss", "zero"], "cheap_price"].isna().all()
    # the sector median P/E (10x, the only profitable one) caps the 12x own history
    assert d.loc["profit", "cheap_price"] == pytest.approx(30.0)
    top = stage2.rank(d, {"top_per_sector": 3, "close_to_cheap": 0.15})
    assert list(top.index) == ["profit"]


@pytest.mark.parametrize(
    "vs, label",
    [(-0.5, "cheap"), (0.0, "cheap"), (0.1, "close"), (0.15, "close"), (0.1501, ""), (np.nan, "")],
)
def test_cheapness_labels(vs, label):
    assert stage2.label(vs, 0.15) == label


def test_net_cash_and_no_debt_give_infinite_ratios_that_pass():
    d = pd.DataFrame(
        {
            "cash_n_short_term_invest_fq": [5.0, 0.0],
            "short_term_debt_fq": [0.0, 0.0],
            "long_term_debt_fq": [0.0, 0.0],
            "ebitda_ttm": [2.0, 2.0],
            "net_debt_fq": [-5.0, 0.0],
            "ebitda_interst_cover_ttm": [np.nan, np.nan],  # no interest: no cover figure
        },
        index=["cash_rich", "no_debt"],
    )
    stage1.ratios(d)
    assert np.isinf(d["cash_to_short_term_debt"]).all()
    assert np.isinf(d["cash_to_long_term_debt"]).all()
    assert d["net_cash"].all()
    for name, value in (("cash_to_short_term_debt", 1), ("min_interest_cover", 4)):
        assert list(stage1._rule(d, name, value)) == [True, True], name


def test_division_guards_against_zero_and_infinity():
    assert np.isnan(stocks._div(1.0, 0.0))
    assert np.isnan(stocks._div(np.inf, 1.0))
    assert np.isnan(stocks._div(1.0, np.inf))
    assert np.isnan(stocks._div(np.nan, 1.0))
    assert stocks._div(-3.0, 2.0) == -1.5


def test_growth_with_a_loss_year_or_a_tiny_base():
    # a year after a loss has no growth figure; growth from a tiny base is kept as is
    assert stage1.yearly_growth([2.0, -1.0, 1.0], 5) == [-2.0]
    g = stage1.yearly_growth([10.0, 0.01], 5)
    assert g == [pytest.approx(999.0)]
    s = pd.Series([-1.0, 2.0, 4.0], index=pd.to_datetime(["2022", "2023", "2024"]))
    assert stocks._growth_stats(s, "x")["x_growth_by_year"] == "2024: +100.0%"
    assert np.isnan(stocks._cagr(pd.Series([1.0], index=pd.to_datetime(["2024"]))))
    assert np.isnan(stocks._cagr(pd.Series([-1.0, -2.0], index=pd.to_datetime(["2023", "2024"]))))


def test_dcf_refuses_negative_cash_flow_and_wacc_near_growth():
    assert np.isnan(stocks.dcf_equity(-1.0, 0.0, 0.08))
    assert np.isnan(stocks.dcf_equity(1.0, 0.0, stocks.TERMINAL_GROWTH + 0.005))
    assert np.isnan(stocks.dcf_equity(np.inf, 0.0, 0.08))
    fair = stocks.dcf_equity(1.0, 2.0, 0.075)
    assert fair == pytest.approx(1.025 / 0.05 - 2.0)


# --- 5. source cross-checks -------------------------------------------------------------


def _sec_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["US", "US", "US", "Europe"],
            "fiscal_period_fy_h": [[2025, 2024], [2025, 2024], [2025, 2024], [2025, 2024]],
            "earnings_per_share_diluted_fy_h": [[2.42, 2.0], [41500.0, 1.0], [1.50, 1.0], [1.0]],
            "flags": "",
        },
        index=["NASDAQ:NFLX", "NYSE:BRK.B", "NYSE:BSX", "MIL:UCG"],
    )


class FakeData:
    """The database for stage2.sec_check: the SEC filings' EPS and the splits."""

    def __init__(self, filed: list[tuple[str, int, float]], splits: list[tuple[str, str, float]]):
        self.filed = pd.DataFrame(filed, columns=["symbol", "fiscal_year", "value"])
        self.splits = pd.DataFrame(splits, columns=["symbol", "date", "split_ratio"])

    def sql(self, query: str, limit: int = 50_000) -> pd.DataFrame:
        if "eps_diluted" in query:
            return self.filed
        if "split_ratio" in query:
            return self.splits
        raise AssertionError(f"unexpected query: {query[:60]}")


def _sec_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["NFLX", "BRK.B", "BSX", "UCG", "SPLT"],
            "region": ["US", "US", "US", "Europe", "US"],
            "fiscal_period_fy_h": [[2025, 2024]] * 5,
            "earnings_per_share_diluted_fy_h": [[2.42, 2.0], [41500.0, 1.0], [1.50, 1.0], [1.0],
                                                [1.0, 0.5]],
            "flags": "",
        },
        index=["NASDAQ:NFLX", "NYSE:BRK.B", "NYSE:BSX", "MIL:UCG", "NYSE:SPLT"],
    )  # fmt: skip


def test_sec_check_flags_eps_more_than_10_percent_off():
    d = _sec_frame()
    data = FakeData(
        [("NFLX", 2025, 2.40), ("BRK.B", 2025, 41000.0), ("BSX", 2025, 1.95), ("SPLT", 2025, 4.0)],
        [("SPLT", "2026-03-01", 4.0)],  # a 4:1 split after the 10-K: SEC's 4.0 is 1.0 today
    )
    stage2.sec_check(d, d.index, data)
    assert d.loc["NASDAQ:NFLX", "sec_eps"] == 2.40 and d.loc["NASDAQ:NFLX", "flags"] == ""
    assert d.loc["NYSE:BRK.B", "sec_eps"] == 41000.0 and d.loc["NYSE:BRK.B", "flags"] == ""
    assert "TradingView 1.50 vs SEC 1.95" in d.loc["NYSE:BSX", "flags"]
    assert d.loc["NYSE:SPLT", "sec_eps"] == 1.0 and d.loc["NYSE:SPLT", "flags"] == ""
    assert np.isnan(d.loc["MIL:UCG", "sec_eps"]) and d.loc["MIL:UCG", "flags"] == ""


def test_sec_check_survives_one_stock_without_history():
    # regression: a NaN history used to abort the whole check silently (fixed in bd15e8e)
    d = _sec_frame()
    d.loc["MIL:UCG", "fiscal_period_fy_h"] = np.nan
    stage2.sec_check(d, d.index, FakeData([("BSX", 2025, 1.95)], []))
    assert "vs SEC" in d.loc["NYSE:BSX", "flags"]
