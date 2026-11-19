"""The nightly analyses (stock_analysis.nightly): what is stored for the evening run, read
back unchanged, and used only while it is fresh. No database: a small fake stands in."""

import json

import numpy as np
import pandas as pd

from stock_analysis import nightly


def _gathered() -> dict:
    days = pd.bdate_range("2024-01-01", "2026-11-17")
    q = pd.Series(
        [1.0, 1.1, 1.2, 1.3, 1.4], index=pd.date_range("2025-01-30", periods=5, freq="91D")
    )
    peers = pd.DataFrame(
        {"price": [10.0, 20.0], "cash_to_short_term_debt": [np.inf, 1.5], "pe_ttm": [np.nan, 9.0]},
        index=pd.Index(["AAA", "BBB"], name="symbol"),
    )
    years = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "fiscal_year_end": "2025-12-31",
                "column": "revenue",
                "value": 1.5,
                "source": "sec",
            }
        ]  # fmt: skip
    )
    return {
        "stock": {"symbol": "AAA", "peers": ["BBB"], "target_pe": 15.0, "eps_override": []},
        "row": {
            "symbol": "AAA",
            "price": 10.0,
            "cash_to_short_term_debt": np.inf,
            "pe_fwd": np.nan,
        },
        "prices": pd.Series(np.linspace(8, 10, len(days)), index=days),
        "quarters": q,
        "ttm": nightly.trailing_eps(q),
        "years": years,
        "peers": peers,
        "next_report": pd.Timestamp("2027-01-28"),
        "next_estimate": 1.5,
    }


def test_a_stock_survives_the_round_trip_with_infinite_and_blank_values():
    d = _gathered()
    back = nightly.unpack_stock(json.loads(nightly.to_json(nightly.pack_stock(d))))
    assert np.isinf(back["row"]["cash_to_short_term_debt"])  # zero short-term debt passes
    assert np.isnan(back["row"]["pe_fwd"])
    pd.testing.assert_series_equal(back["prices"], d["prices"], check_freq=False, check_names=False)
    assert list(back["quarters"]) == list(d["quarters"])
    assert np.isinf(back["peers"].loc["AAA", "cash_to_short_term_debt"])
    assert back["years"].iloc[0]["value"] == 1.5
    assert back["next_report"] == pd.Timestamp("2027-01-28") and back["next_estimate"] == 1.5
    k1, k2 = nightly.key_numbers(d), nightly.key_numbers(back)
    assert (
        k1["entry_price"] == k2["entry_price"]
        and k1["pe_median_10y"] == k2["pe_median_10y"]
        or (np.isnan(k1["pe_median_10y"]) and np.isnan(k2["pe_median_10y"]))
    )


def test_the_stock_key_changes_with_the_settings_the_numbers_depend_on():
    s = {"symbol": "AAA", "peers": ["BBB"], "target_pe": 15, "target_note": "a", "eps_override": []}
    base = nightly.stock_key(s)
    assert nightly.stock_key({**s, "target_note": "b"}) == base  # a note isn't a number
    assert nightly.stock_key({**s, "target_pe": 14}) != base
    assert nightly.stock_key({**s, "peers": ["CCC"]}) != base
    over = [{"reported": "2026-10-28", "eps": 2.67, "reason": "x"}]
    assert nightly.stock_key({**s, "eps_override": over}) != base


class FakeData:
    """Answers the queries stored_stocks and stored_market make."""

    def __init__(self, stored: pd.DataFrame, built: str, market: pd.DataFrame | None = None):
        self.stored, self.built = stored, built
        self.market = market if market is not None else pd.DataFrame()

    def sql(self, query: str, limit: int = 50_000) -> pd.DataFrame:
        if "core_build" in query:
            return pd.DataFrame({"t": [self.built]})
        if "out_stock_numbers" in query:
            return self.stored
        if "out_market_numbers" in query:
            return self.market
        raise AssertionError(query)


def test_stored_numbers_are_used_only_while_fresh_and_for_the_same_settings():
    d = _gathered()
    stock = d["stock"]
    payload = nightly.to_json(nightly.pack_stock(d))
    stored = pd.DataFrame(
        {
            "symbol": ["AAA"],
            "computed_at": ["2026-11-18T23:10:00"],
            "stock_key": [nightly.stock_key(stock)],
            "payload_json": [payload],
        }  # fmt: skip
    )
    fresh = FakeData(stored, built="2026-11-18T23:00:00")
    assert set(nightly.stored_stocks(fresh, [stock])) == {"AAA"}
    stale = FakeData(stored, built="2026-11-19T23:00:00")  # a build after the numbers
    assert nightly.stored_stocks(stale, [stock]) == {}
    changed = {**stock, "target_pe": 12.0}  # Claude changed the target this evening
    assert nightly.stored_stocks(fresh, [changed]) == {}


def test_stored_market_numbers_need_a_computation_after_the_last_build():
    n = {
        "markets": pd.DataFrame({"last": [7000.0]}, index=["^GSPC"]),
        "sectors": pd.DataFrame({"last": [50.0]}, index=["XLU"]),
        "breadth": {"above_200d": 0.6, "near_high": 10, "near_low": 3, "count": 500, "date": "x"},
        "top": pd.DataFrame(),
        "screener": {"date": "2026-11-18"},
        "price_date": "2026-11-18",
    }
    row = pd.DataFrame(
        {
            "computed_at": ["2026-11-18T23:20:00"],
            "payload_json": [nightly.to_json(nightly.pack_market(n))],
        }  # fmt: skip
    )
    got = nightly.stored_market(FakeData(pd.DataFrame(), "2026-11-18T23:00:00", row))
    assert got["markets"].loc["^GSPC", "last"] == 7000.0 and got["breadth"]["count"] == 500
    assert nightly.stored_market(FakeData(pd.DataFrame(), "2026-11-19T23:00:00", row)) is None


def test_a_screener_run_is_stale_only_when_older_than_the_newest_prices(monkeypatch):
    top = pd.DataFrame({"vs_cheap": [0.1], "sector": ["X"]})
    s1 = pd.DataFrame({"status": ["pass", "fail"]})
    monkeypatch.setattr(nightly.stocks, "screener_run", lambda data: ("2026-11-18", s1, top))
    monkeypatch.setattr(nightly, "newest_price", lambda data: "2026-11-18")
    assert nightly.load_screener(None)[1]["stale"] is False  # the night's run, read next evening
    monkeypatch.setattr(nightly, "newest_price", lambda data: "2026-11-19")
    assert nightly.load_screener(None)[1]["stale"] is True
