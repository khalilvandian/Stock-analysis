"""Unit tests for the data pipeline: missing values, splits, currencies, outliers and the
cross-checks between sources. No network: HTTP is mocked with respx (httpx) or
monkeypatched (requests, yfinance); everything else runs on small hand-built frames.

Tests marked xfail(strict=True) expose bugs in the source; each reason says what is wrong.
"""

import json
import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
import respx
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import history  # noqa: E402
import screen_common  # noqa: E402
import sector  # noqa: E402
import send_email  # noqa: E402
import stage1  # noqa: E402
import stage2  # noqa: E402
import watchlist  # noqa: E402
from screen_common import load_config  # noqa: E402

from stock_analysis import ecb  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --- helpers -------------------------------------------------------------------------


class FakeTicker:
    """Stands in for yfinance.Ticker: prices, splits and exchange rates, no network."""

    fx = {"EURUSD=X": 1.1, "GBPUSD=X": 1.3}
    splits_by_symbol: dict[str, pd.Series] = {}
    price = 4.0
    requested: list[str] = []

    def __init__(self, symbol: str):
        self.symbol = symbol
        FakeTicker.requested.append(symbol)
        self.splits = self.splits_by_symbol.get(symbol, pd.Series(dtype=float))

    def history(self, **kwargs) -> pd.DataFrame:
        idx = pd.bdate_range("2015-12-01", "2026-10-23").tz_localize("America/New_York")
        if self.symbol.endswith("=X"):
            if self.symbol not in self.fx:
                return pd.DataFrame(columns=["Close"])
            return pd.DataFrame({"Close": self.fx[self.symbol]}, index=idx[-5:])
        return pd.DataFrame({"Close": self.price}, index=idx)


@pytest.fixture
def fake_yf(monkeypatch):
    FakeTicker.splits_by_symbol = {}
    FakeTicker.requested = []
    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    monkeypatch.setattr(history, "_fx", {"USD": 1.0})
    monkeypatch.setattr(sector, "_fx", {"USD": 1.0})
    return FakeTicker


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
        "ttm": watchlist.trailing_eps(q),
        "next_report": None,
        "next_estimate": next_estimate,
    }


def _sec_hist(rows: list[tuple[str, str, float, str]]) -> pd.DataFrame:
    """(fiscal_year_end, column, value, filed) -> history long frame."""
    return pd.DataFrame(
        {
            "symbol": "X",
            "fiscal_year_end": pd.to_datetime([r[0] for r in rows]),
            "column": [r[1] for r in rows],
            "value": [r[2] for r in rows],
            "source": "SEC",
            "filed": [r[3] for r in rows],
        }
    )


def _value(hist: pd.DataFrame, column: str, year: int | None = None) -> float:
    h = hist[hist["column"] == column]
    if year is not None:
        h = h[pd.to_datetime(h["fiscal_year_end"]).dt.year == year]
    assert len(h) == 1, f"{column} {year}: {len(h)} rows"
    return float(h["value"].iloc[0])


def _fact(start, end, val, form="10-K", filed="2025-02-01") -> dict:
    x = {"end": end, "val": val, "form": form, "filed": filed}
    if start:
        x["start"] = start
    return x


def _facts(tags: dict[str, tuple[str, list[dict]]]) -> dict:
    """{tag: (unit, [facts])} -> SEC company facts (us-gaap)."""
    return {"facts": {"us-gaap": {tag: {"units": {unit: xs}} for tag, (unit, xs) in tags.items()}}}


# --- 1. missing values: adjusted EPS and P/E history ----------------------------------


def test_quarterly_eps_of_an_empty_or_all_blank_frame_is_empty():
    empty = pd.DataFrame(
        {"EPS Estimate": [], "Reported EPS": []},
        index=pd.DatetimeIndex([], tz="America/New_York"),
    )
    assert watchlist.quarterly_eps(empty).empty
    blank = _earnings([("2026-01-20", None), ("2026-04-20", np.nan)])
    q = watchlist.quarterly_eps(blank)
    assert q.empty and q.dtype == float
    assert watchlist.trailing_eps(q).empty


def test_quarterly_eps_ignores_overrides_for_unknown_dates_and_keeps_order():
    d = _earnings([("2026-07-16", 1.2), ("2026-01-20", 1.0), ("2026-04-16", None)])
    q = watchlist.quarterly_eps(d, [{"reported": "2025-01-01", "eps": 99.0}])
    assert list(q) == [1.0, 1.2]  # blank quarter dropped, oldest first, override ignored
    assert q.index.is_monotonic_increasing and q.index.tz is None


def test_quarterly_eps_keeps_the_later_of_two_entries_for_the_same_quarter():
    d = _earnings([("2026-01-20", 1.0), ("2026-02-05", 1.1), ("2026-04-20", 1.2)])
    assert list(watchlist.quarterly_eps(d)) == [1.1, 1.2]


def test_trailing_eps_needs_four_quarters():
    assert watchlist.trailing_eps(_quarters(3)).empty
    assert watchlist.trailing_eps(pd.Series(dtype=float, index=pd.DatetimeIndex([]))).empty
    ttm = watchlist.trailing_eps(_quarters(5))
    assert list(ttm) == [4.0, 4.0]


def test_yearly_pe_blank_for_a_loss_year_and_empty_without_eps():
    prices = pd.Series(100.0, index=pd.bdate_range("2023-01-01", "2026-06-30"))
    ttm = pd.Series([-2.0, 5.0], index=pd.to_datetime(["2024-02-10", "2025-02-10"]))
    y = watchlist.yearly_pe(prices, ttm)
    assert np.isnan(y.loc[2023, "pe"]) and y.loc[2024, "pe"] == 20.0
    assert watchlist.yearly_pe(prices, pd.Series(dtype=float, index=pd.DatetimeIndex([]))).empty
    # a year whose Q4 report never came (no EPS before April 30) is left out
    late = pd.Series([5.0], index=pd.to_datetime(["2025-06-10"]))
    assert watchlist.yearly_pe(prices, late).empty


def test_daily_pe_blank_while_eps_is_negative():
    prices = pd.Series(50.0, index=pd.bdate_range("2025-01-01", "2025-12-31"))
    ttm = pd.Series([-1.0, 2.0], index=pd.to_datetime(["2024-12-01", "2025-07-01"]))
    pe = watchlist.daily_pe(prices, ttm)
    assert pe.index.min() >= pd.Timestamp("2025-07-01") and set(pe) == {25.0}


def test_next_report_none_when_every_report_is_in():
    d = _earnings([("2026-01-20", 1.0), ("2026-04-20", 1.1)])
    when, est = watchlist.next_report(d, pd.Timestamp("2026-10-27"))
    assert when is None and np.isnan(est)


def test_key_numbers_entry_price_from_target_pe_and_adjusted_eps():
    k = watchlist.key_numbers(_key_inputs(next_estimate=1.5))
    assert k["eps_adj_ttm"] == 4.0 and k["pe_adj"] == 25.0
    assert k["pe_median_10y"] == 25.0
    assert k["entry_price"] == 60.0 and round(k["to_entry"], 4) == -0.4
    # next report replaces the oldest of the four quarters: 4 - 1 + 1.5
    assert k["entry_after_next"] == 15 * 4.5


def test_key_numbers_without_eps_history_is_blank_not_an_error():
    no_eps = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    k = watchlist.key_numbers(_key_inputs(q=no_eps))
    for key in ("eps_adj_ttm", "pe_adj", "pe_median_10y", "entry_price", "to_entry"):
        assert np.isnan(k[key]), key
    assert k["price"] == 100.0 and k["next_report"] == ""


def test_key_numbers_with_a_loss_has_no_entry_price():
    k = watchlist.key_numbers(_key_inputs(q=_quarters(eps=-0.5), next_estimate=0.1))
    assert k["eps_adj_ttm"] == -2.0
    assert np.isnan(k["pe_adj"]) and np.isnan(k["entry_price"])
    assert np.isnan(k["entry_after_next"])


def test_key_numbers_falls_back_to_the_last_close_when_yahoo_has_no_price():
    assert watchlist.key_numbers(_key_inputs(price=None))["price"] == 100.0


@pytest.mark.xfail(
    strict=True,
    reason="watchlist.key_numbers: `row.get('price') or prices.iloc[-1]` keeps a NaN price "
    "(NaN is truthy), so P/E, entry gap and the summary go blank instead of using the "
    "last close; fetch_row's retry has the same `if row.get('price')` test",
)
def test_key_numbers_falls_back_to_the_last_close_when_the_price_is_nan():
    assert watchlist.key_numbers(_key_inputs(price=np.nan))["price"] == 100.0


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


@pytest.mark.parametrize(
    "path, name",
    [
        ("analyses/BSX/2026-10-27_2100.pdf", "BSX_2026-10-27_2100.pdf"),
        ("analyses/summaries/2026-10-27_2100-2.pdf", "summaries_2026-10-27_2100-2.pdf"),
        ("analyses/market/2026-10-27_2100.pdf", "market_2026-10-27_2100.pdf"),
    ],
)
def test_attachment_names_keep_the_folder(path, name):
    assert send_email.attachment_name(path) == name


def test_recipients_limits_and_blanks():
    assert send_email.recipients(" a@x.com , b@y.com ,") == ["a@x.com", "b@y.com"]
    five = ",".join(f"{i}@x.com" for i in range(5))
    assert len(send_email.recipients(five)) == send_email.MAX_RECIPIENTS
    for bad in ("", " , ,", five + ",5@x.com"):
        with pytest.raises(SystemExit):
            send_email.recipients(bad)


def test_email_without_a_sender_name_and_with_a_missing_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr(send_email, "ROOT", tmp_path)
    (tmp_path / "email.html").write_text("<p>hi</p>")
    msg = send_email.build_message(
        {"subject": "S", "html": "email.html", "files": []}, "a@x.com", "bot@x.com"
    )
    assert msg["sender"] == {"email": "bot@x.com"} and msg["attachment"] == []
    assert msg["subject"] == "S" and "Test" not in msg["htmlContent"]
    run = {"subject": "S", "html": "email.html", "files": ["analyses/BSX/missing.pdf"]}
    with pytest.raises(FileNotFoundError):
        send_email.build_message(run, "a@x.com", "bot@x.com")


@respx.mock
def test_brevo_refusal_stops_with_the_reason():
    respx.post(send_email.API).mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(SystemExit, match="401"):
        send_email.send({"to": []}, "k")


def test_email_main_refuses_without_key_or_sender(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["send_email.py", "--to", "a@x.com"])
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="BREVO_API_KEY"):
        send_email.main()
    monkeypatch.setenv("BREVO_API_KEY", "k")
    monkeypatch.delenv("WATCHLIST_EMAIL_FROM", raising=False)
    with pytest.raises(SystemExit, match="WATCHLIST_EMAIL_FROM"):
        send_email.main()


# --- 2. splits ------------------------------------------------------------------------

# 2:1 and 10:1 forward splits, a 1-for-20 reverse split (Yahoo writes it as 0.05)
SPLITS = [2.0, 10.0, 0.05]


@pytest.mark.parametrize("ratio", SPLITS)
def test_history_split_adjust_keeps_market_value_net_income_and_pe(ratio):
    shares_pre, eps_pre, price_pre = 100e6, 5.0, 60.0
    hist = _sec_hist(
        [
            ("2024-12-31", "_shares", shares_pre, "2025-02-01"),
            ("2024-12-31", "eps", eps_pre, "2025-02-01"),
            ("2024-12-31", "revenue", 9.0, "2025-02-01"),
        ]
    )
    splits = pd.Series([ratio], index=pd.to_datetime(["2025-06-01"]).tz_localize("UTC"))
    out = history.split_adjust(hist, splits)
    shares, eps = _value(out, "_shares"), _value(out, "eps")
    price = price_pre / ratio  # Yahoo prices are split-adjusted
    assert shares * price == pytest.approx(shares_pre * price_pre)  # market value
    assert shares * eps == pytest.approx(shares_pre * eps_pre)  # net income
    assert price / eps == pytest.approx(price_pre / eps_pre)  # P/E
    assert _value(out, "revenue") == 9.0  # amounts never change


def test_history_split_adjust_leaves_restated_values_and_counts_only_later_splits():
    hist = _sec_hist(
        [
            ("2022-12-31", "eps", 12.0, "2023-02-01"),  # before both splits
            ("2023-12-31", "eps", 3.0, "2024-08-01"),  # filed between them
            ("2024-12-31", "eps", 1.0, "2026-02-01"),  # filed after both: restated
            ("2024-12-31", "net_income", 7.0, ""),
        ]
    )
    splits = pd.Series(
        [2.0, 3.0, 0.0], index=pd.to_datetime(["2024-06-01", "2025-06-01", "2025-07-01"])
    )
    out = history.split_adjust(hist, splits)
    assert list(out["value"]) == [2.0, 1.0, 1.0, 7.0]
    assert history.split_adjust(hist, pd.Series(dtype=float)).equals(hist)
    assert history.split_adjust(hist.drop(columns="filed"), splits).equals(
        hist.drop(columns="filed")
    )


@pytest.mark.parametrize(
    "ratio",
    [
        2.0,
        10.0,
        pytest.param(
            0.05,
            marks=pytest.mark.xfail(
                strict=True,
                reason="watchlist.split_adjust skips any split product under 1.5 "
                "(`if factor < 1.5`), so a reverse split is never applied: pre-split share "
                "counts stay 20x too high and EPS 20x too low against Yahoo's adjusted prices",
            ),
        ),
    ],
)
def test_watchlist_split_adjust_keeps_market_value_and_pe(ratio):
    shares_now, eps_now = 1000.0, 4.0
    hist = pd.DataFrame(
        {
            "symbol": "X",
            "fiscal_year_end": pd.to_datetime(["2024-12-31", "2024-12-31"]),
            "column": ["_shares", "eps"],
            "value": [shares_now / ratio, eps_now * ratio],  # filed on the pre-split basis
        }
    )
    splits = pd.Series(
        [ratio], index=pd.to_datetime(["2025-06-01"]).tz_localize("America/New_York")
    )
    out = watchlist.split_adjust(hist, splits, shares_now=shares_now)
    assert _value(out, "_shares") == pytest.approx(shares_now)
    assert _value(out, "eps") == pytest.approx(eps_now)


def test_watchlist_split_adjust_leaves_restated_counts_and_handles_missing_inputs():
    hist = pd.DataFrame(
        {
            "symbol": "X",
            "fiscal_year_end": pd.to_datetime(["2024-12-31", "2024-12-31", "2026-12-31"]),
            "column": ["_shares", "eps", "eps"],
            "value": [1000.0, 4.0, 5.0],  # already on today's basis
        }
    )
    splits = pd.Series([25.0], index=pd.to_datetime(["2025-06-01"]))  # tz-naive works too
    out = watchlist.split_adjust(hist, splits, shares_now=1000.0)
    assert list(out["value"]) == [1000.0, 4.0, 5.0]
    for shares_now in (np.nan, 0.0, -1.0):
        assert watchlist.split_adjust(hist, splits, shares_now).equals(hist)
    assert watchlist.split_adjust(hist, pd.Series(dtype=float), 1000.0).equals(hist)


@pytest.mark.xfail(
    strict=True,
    reason="watchlist.sec_years applies a split twice: watchlist.split_adjust rescales the "
    "pre-split SEC shares and EPS, then history.add_prices calls history.split_adjust, which "
    "rescales them again from their (unchanged) filing dates; a 25:1 split leaves EPS 625x "
    "too low and market value 25x too high",
)
def test_watchlist_sec_years_applies_a_split_once(fake_yf, monkeypatch, tmp_path):
    facts = _facts(
        {
            "WeightedAverageNumberOfDilutedSharesOutstanding": (
                "shares",
                [_fact("2024-01-01", "2024-12-31", 40.0)],
            ),
            "EarningsPerShareDiluted": ("USD/shares", [_fact("2024-01-01", "2024-12-31", 100.0)]),
            "NetIncomeLoss": ("USD", [_fact("2024-01-01", "2024-12-31", 4000.0)]),
        }
    )
    fake_yf.splits_by_symbol["X"] = pd.Series(
        [25.0], index=pd.to_datetime(["2025-06-01"]).tz_localize("America/New_York")
    )
    monkeypatch.setattr(history, "CACHE", tmp_path)
    monkeypatch.setattr(history, "ticker_ciks", lambda: {"X": 1})
    monkeypatch.setattr(history, "company_facts", lambda symbol, cik, refresh: facts)
    yahoo = [{"symbol": "X", "period_end": "2024-12-31", "column": "revenue", "value": 1.0}]
    out = watchlist.sec_years("X", yahoo, "USD", shares_now=1000.0)
    assert _value(out, "eps") == pytest.approx(4.0)
    assert _value(out, "market_cap") == pytest.approx(fake_yf.price * 1000.0 / 1e9)


def test_yahoo_quarterly_eps_is_used_as_split_adjusted():
    """Yahoo restates quarterly EPS after a split, so the P/E history must not jump at the
    split: quarterly_eps and trailing_eps pass the values through unchanged."""
    split_day = pd.Timestamp("2022-06-01")
    rows = [
        (d.strftime("%Y-%m-%d"), 0.5) for d in pd.date_range("2018-02-15", periods=36, freq="91D")
    ]
    q = watchlist.quarterly_eps(_earnings(rows))
    assert set(q) == {0.5}  # no rescaling on either side of the split
    prices = pd.Series(50.0, index=pd.bdate_range("2018-01-01", "2026-10-23"))  # adjusted
    yearly = watchlist.yearly_pe(prices, watchlist.trailing_eps(q))
    assert len(yearly) >= 6 and set(yearly["pe"]) == {25.0}
    assert yearly.index.min() < split_day.year < yearly.index.max()
    # had Yahoo not adjusted a 25:1 split, the EPS would be 25x diluted: rejected
    assert not stage2.adjusted_eps_plausible(2.0 * 25, 2.0)


# --- 3. currencies ---------------------------------------------------------------------


@respx.mock
def test_ecb_rates_from_the_full_csv_layout():
    route = respx.get(url__startswith=ecb.URL).mock(
        return_value=httpx.Response(200, text=(FIXTURES / "ecb_exr.csv").read_text())
    )
    fx = ecb.usd_per_unit()
    assert route.calls[0].request.url.params["format"] == "csvdata"
    assert fx["USD"] == 1.0 and fx["EUR"] == pytest.approx(1.10)
    assert fx["JPY"] == pytest.approx(1.10 / 165)
    assert fx["SEK"] == pytest.approx(0.1)
    assert fx["GBX"] == pytest.approx(fx["GBP"] / 100)  # pence


@respx.mock
def test_ecb_error_raises_and_a_given_client_stays_open():
    respx.get(url__startswith=ecb.URL).mock(return_value=httpx.Response(503))
    with httpx.Client() as client:
        with pytest.raises(httpx.HTTPStatusError):
            ecb.usd_per_unit(client)
        assert not client.is_closed


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
    assert bt["yahoo"] == "BT-A.L"
    assert bt["price_fund"] == pytest.approx(2.5)  # 250 pence = 2.50 pounds
    assert bt["price_fund"] / bt["eps"] == pytest.approx(12.5)  # P/E in one currency
    assert bt["cap_usd_bn"] == pytest.approx(50e9 * 1.3 / 1e9)
    xyz = d.loc["EURONEXT:XYZ"]  # reports in dollars, trades in euros
    assert xyz["yahoo"] == "XYZ.AS" and xyz["price_fund"] == pytest.approx(110.0)
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
    prices = pd.DataFrame({"BT-A.L": 250.0}, index=months)  # pence
    d = pd.DataFrame(
        {
            "yahoo": ["BT-A.L"],
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


def test_history_converts_a_foreign_filer_at_todays_rate(fake_yf):
    facts = json.loads((FIXTURES / "sec_companyfacts_foreign.json").read_text())
    h = history.sec_history("FOR", facts)
    assert set(h["source"]) == {"SEC"}
    assert _value(h, "revenue", 2024) == pytest.approx(12 * 1.1)
    assert _value(h, "net_income", 2024) == pytest.approx(1.2 * 1.1)
    assert _value(h, "eps", 2024) == pytest.approx(2.4 * 1.1)  # EUR/shares -> USD/share
    assert _value(h, "_shares", 2024) == 500e6  # share counts are never converted
    assert _value(h, "total_debt", 2024) == pytest.approx(5 * 1.1)
    assert _value(h, "net_debt", 2024) == pytest.approx(4 * 1.1)
    assert _value(h, "free_cf", 2024) == pytest.approx(2.0 * 1.1)
    assert _value(h, "capex", 2024) < 0
    assert h[(h["column"] == "free_cf")]["fiscal_year_end"].dt.year.tolist() == [2024]
    assert "EURUSD=X" in fake_yf.requested
    assert history.reporting_currency(facts) == "EUR"
    # no market value for foreign filers: their shares are ordinary shares, the price per ADR
    priced = history.add_prices(h, "FOR", "EUR")
    assert "price" in set(priced["column"]) and "market_cap" not in set(priced["column"])
    usd = history.add_prices(h, "FOR", "USD")
    assert _value(usd, "market_cap", 2024) == pytest.approx(fake_yf.price * 500e6 / 1e9)


def test_history_unknown_currency_rate_leaves_the_value_blank(fake_yf):
    facts = _facts({"Revenues": ("XYZ", [_fact("2024-01-01", "2024-12-31", 5e9)])})
    assert np.isnan(history.annual_values(facts, "Revenues", instant=False).iloc[0])
    assert history._currency("shares") is None and history._currency("BRL/shares") == "BRL"
    assert history._currency("pure") is None


def test_sector_fx_defaults_to_dollars_and_reads_yahoo_rates(fake_yf):
    assert sector.fx_to_usd(None) == 1.0
    assert sector.fx_to_usd("eur") == pytest.approx(1.1)
    assert np.isnan(sector.fx_to_usd("XYZ"))
    assert fake_yf.requested == ["EURUSD=X", "XYZUSD=X"]


def test_yahoo_yearly_history_converts_to_dollars():
    periods = pd.to_datetime(["2023-12-31", "2024-12-31"])

    def frame(rows: dict) -> pd.DataFrame:
        return pd.DataFrame(rows, index=periods).T

    ia = frame(
        {
            "Total Revenue": [10e9, 12e9],
            "EBITDA": [3e9, 4e9],
            "Net Income": [1e9, 1.2e9],
            "Diluted EPS": [2.0, 2.4],
            "Interest Expense": [-0.1e9, -0.1e9],
        }
    )
    ba = frame(
        {
            "Total Debt": [5e9, 6e9],
            "Cash And Cash Equivalents": [1e9, 2e9],
            "Cash Cash Equivalents And Short Term Investments": [1.5e9, 2.5e9],
            "Ordinary Shares Number": [500e6, 500e6],
        }
    )
    ca = frame({"Operating Cash Flow": [2e9, 2.5e9], "Capital Expenditure": [-0.5e9, -0.6e9]})
    idx = pd.bdate_range("2023-01-01", "2025-01-31").tz_localize("America/New_York")
    prices = pd.DataFrame({"Close": 20.0}, index=idx)
    rows = pd.DataFrame(sector.annual_history("FOR", ia, ba, ca, prices, fx=1.1))
    v = rows[rows["period_end"] == "2024-12-31"].set_index("column")["value"]
    assert v["revenue"] == pytest.approx(13.2) and v["eps"] == pytest.approx(2.64)
    assert v["cash"] == pytest.approx(2.75)  # cash including short-term investments
    assert v["net_debt"] == pytest.approx((6 - 2) * 1.1)  # net debt on cash and equivalents
    assert v["free_cf"] == pytest.approx((2.5 - 0.6) * 1.1)
    assert v["market_cap"] == pytest.approx(20.0 * 500e6 / 1e9)


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


def test_sector_division_guards_against_zero_and_infinity():
    assert np.isnan(sector._div(1.0, 0.0))
    assert np.isnan(sector._div(np.inf, 1.0))
    assert np.isnan(sector._div(1.0, np.inf))
    assert np.isnan(sector._div(np.nan, 1.0))
    assert sector._div(-3.0, 2.0) == -1.5


def test_growth_with_a_loss_year_or_a_tiny_base():
    # a year after a loss has no growth figure; growth from a tiny base is kept as is
    assert stage1.yearly_growth([2.0, -1.0, 1.0], 5) == [-2.0]
    g = stage1.yearly_growth([10.0, 0.01], 5)
    assert g == [pytest.approx(999.0)]
    s = pd.Series([-1.0, 2.0, 4.0], index=pd.to_datetime(["2022", "2023", "2024"]))
    assert list(sector._yearly_growth(s)) == [1.0]
    assert np.isnan(sector._cagr(pd.Series([1.0], index=pd.to_datetime(["2024"]))))
    assert np.isnan(sector._cagr(pd.Series([-1.0, -2.0], index=pd.to_datetime(["2023", "2024"]))))


def test_dcf_refuses_negative_cash_flow_and_wacc_near_growth():
    assert np.isnan(sector.dcf_equity(-1.0, 0.0, 0.08))
    assert np.isnan(sector.dcf_equity(1.0, 0.0, sector.TERMINAL_GROWTH + 0.005))
    assert np.isnan(sector.dcf_equity(np.inf, 0.0, 0.08))
    fair = sector.dcf_equity(1.0, 2.0, 0.075)
    assert fair == pytest.approx(1.025 / 0.05 - 2.0)


# --- 5. source cross-checks -------------------------------------------------------------


def test_sec_values_win_and_yahoo_fills_gaps_with_its_source():
    facts = _facts(
        {
            "Revenues": ("USD", [_fact("2024-01-01", "2024-12-31", 10e9)]),
            "NetIncomeLoss": ("USD", [_fact("2024-01-01", "2024-12-31", 1e9)]),
        }
    )
    sec = history.sec_history("X", facts)
    yahoo = pd.DataFrame(
        [
            {"symbol": "X", "period_end": "2024-12-31", "column": "revenue", "value": 99.0},
            {"symbol": "X", "period_end": "2023-12-31", "column": "revenue", "value": 8.0},
            {"symbol": "X", "period_end": "2023-12-31", "column": "market_cap", "value": 1.0},
            {"symbol": "Y", "period_end": "2022-12-31", "column": "revenue", "value": 7.0},
        ]
    )
    h = history.fill_from_yahoo(sec, yahoo, "X")
    rev = h[h["column"] == "revenue"]
    rev = rev.set_index(pd.to_datetime(rev["fiscal_year_end"]).dt.year)
    assert rev.loc[2024, "value"] == 10.0 and rev.loc[2024, "source"] == "SEC"
    assert rev.loc[2023, "value"] == 8.0 and rev.loc[2023, "source"] == "Yahoo"
    assert "market_cap" not in set(h["column"])  # prices come from add_prices only
    assert set(h["symbol"]) == {"X"} and h["source"].notna().all()


@pytest.mark.xfail(
    strict=True,
    raises=KeyError,
    reason="history.fill_from_yahoo indexes yahoo['symbol'] before checking the frame is "
    "empty; watchlist.sec_years passes pd.DataFrame([]) when sector.analyse failed (no "
    "'_history'), so one failed Yahoo fetch crashes the stock's whole analysis",
)
def test_fill_from_yahoo_with_no_yahoo_rows():
    sec = _sec_hist([("2024-12-31", "revenue", 1.0, "")])
    assert history.fill_from_yahoo(sec, pd.DataFrame([]), "X").equals(sec)


def test_annual_values_latest_annual_filing_wins():
    facts = _facts(
        {
            "Revenues": (
                "USD",
                [
                    _fact("2024-01-01", "2024-12-31", 10.0, filed="2025-02-01"),
                    _fact("2024-01-01", "2024-12-31", 11.0, filed="2026-02-01"),  # restated
                    _fact("2024-01-01", "2024-12-31", 50.0, form="8-K", filed="2026-05-01"),
                    _fact("2024-10-01", "2024-12-31", 3.0, filed="2026-06-01"),  # a quarter
                    _fact("2015-01-01", "2015-12-31", 9.0),  # before FIRST_YEAR
                ],
            )
        }
    )
    s = history.annual_values(facts, "Revenues", instant=False)
    assert list(s) == [11.0] and s.index[0] == pd.Timestamp("2024-12-31")
    assert s.attrs["filed"][pd.Timestamp("2024-12-31")] == "2026-02-01"


def test_sec_history_identities_and_signs():
    end = "2024-12-31"
    flow = lambda v: [_fact("2024-01-01", end, v)]  # noqa: E731
    inst = lambda v: [_fact(None, end, v)]  # noqa: E731
    facts = _facts(
        {
            "Revenues": ("USD", flow(20e9)),
            "NetIncomeLoss": ("USD", flow(2e9)),
            "EarningsPerShareDiluted": ("USD/shares", flow(0.0)),  # zero with a profit
            "NetCashProvidedByUsedInOperatingActivities": ("USD", flow(5e9)),
            "PaymentsToAcquirePropertyPlantAndEquipment": ("USD", flow(1.5e9)),  # positive
            "CashAndCashEquivalentsAtCarryingValue": ("USD", inst(3e9)),
            "LongTermDebtNoncurrent": ("USD", inst(8e9)),
            "LongTermDebtCurrent": ("USD", inst(1e9)),
            "CommercialPaper": ("USD", inst(0.5e9)),
        }
    )
    h = history.sec_history("X", facts)
    v = h.set_index("column")["value"]
    assert v["capex"] == pytest.approx(-1.5)  # always negative
    assert v["free_cf"] == pytest.approx(v["operating_cf"] - abs(v["capex"]))
    assert v["short_term_debt"] == pytest.approx(1.5)
    assert v["total_debt"] == pytest.approx(v["short_term_debt"] + v["long_term_debt"])
    assert v["net_debt"] == pytest.approx(v["total_debt"] - v["cash"])
    assert "eps" not in v.index  # an EPS of 0 next to a profit means no public shares yet


def test_company_facts_reads_the_cache_and_handles_404(monkeypatch, tmp_path):
    monkeypatch.setattr(history, "CACHE", tmp_path)
    (tmp_path / "X.json").write_text('{"facts": {}}')

    def no_network(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(history.requests, "get", no_network)
    assert history.company_facts("X", 1, refresh=False) == {"facts": {}}

    class Resp:
        status_code, text = 404, ""

    calls = []
    monkeypatch.setattr(history.requests, "get", lambda url, **k: calls.append(k) or Resp())
    assert history.company_facts("Y", 1, refresh=True) is None
    assert calls[0]["headers"] == history.UA  # identifies itself from SEC_USER_AGENT


def test_ticker_ciks_use_dots_like_yahoo(monkeypatch):
    class Resp:
        def json(self):
            return json.loads((FIXTURES / "sec_company_tickers.json").read_text())

    monkeypatch.setattr(history.requests, "get", lambda *a, **k: Resp())
    ciks = history.ticker_ciks()
    assert ciks["BRK.B"] == 1067983 and ciks["BKNG"] == 1075531


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


def _mock_sec(router) -> None:
    router.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(200, text=(FIXTURES / "sec_company_tickers.json").read_text())
    )
    router.get(url__regex=r"https://data\.sec\.gov/api/xbrl/frames/.*/CY2025\.json").mock(
        return_value=httpx.Response(200, text=(FIXTURES / "sec_frames_eps_cy2025.json").read_text())
    )


def test_sec_check_flags_eps_more_than_10_percent_off():
    d = _sec_frame()
    with respx.mock(assert_all_called=True) as router:
        _mock_sec(router)
        stage2.sec_check(d, d.index)
        ua = router.calls[0].request.headers["user-agent"]
    assert ua == stage2.SEC_UA["User-Agent"]
    assert d.loc["NASDAQ:NFLX", "sec_eps"] == 2.40 and d.loc["NASDAQ:NFLX", "flags"] == ""
    assert d.loc["NYSE:BRK.B", "sec_eps"] == 41000.0  # BRK.B found as BRK-B
    assert d.loc["NYSE:BRK.B", "flags"] == ""
    assert "TradingView 1.50 vs SEC 1.95" in d.loc["NYSE:BSX", "flags"]
    assert np.isnan(d.loc["MIL:UCG", "sec_eps"]) and d.loc["MIL:UCG", "flags"] == ""


def test_sec_check_is_skipped_when_sec_is_unreachable():
    d = _sec_frame()
    with respx.mock(assert_all_called=False) as router:
        router.get(url__startswith="https://www.sec.gov/").mock(side_effect=httpx.ConnectError)
        stage2.sec_check(d, d.index)
    assert "sec_eps" not in d.columns and (d["flags"] == "").all()


def test_sec_check_survives_one_stock_without_history():
    # regression: a NaN history used to abort the whole check silently (fixed in bd15e8e)
    d = _sec_frame()
    d.loc["MIL:UCG", "fiscal_period_fy_h"] = np.nan
    with respx.mock(assert_all_called=False) as router:
        _mock_sec(router)
        stage2.sec_check(d, d.index)
    assert "vs SEC" in d.loc["NYSE:BSX", "flags"]
