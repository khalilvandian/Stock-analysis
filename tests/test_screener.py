import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import respx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import history  # noqa: E402
import screener  # noqa: E402

from stock_analysis import ecb, tradingview  # noqa: E402


@respx.mock
def test_tradingview_scan_reads_every_page(monkeypatch):
    monkeypatch.setattr(tradingview, "PAGE", 2)
    route = respx.post("https://scanner.tradingview.com/italy/scan")
    route.side_effect = [
        httpx.Response(
            200,
            json={
                "totalCount": 3,
                "data": [
                    {"s": "MIL:UCG", "d": ["UCG", 74.3]},
                    {"s": "MIL:ENEL", "d": ["ENEL", 9.1]},
                ],
            },
        ),
        httpx.Response(200, json={"totalCount": 3, "data": [{"s": "MIL:ISP", "d": ["ISP", 5.2]}]}),
    ]
    d = tradingview.scan("italy", ["name", "close"])
    assert list(d.index) == ["MIL:UCG", "MIL:ENEL", "MIL:ISP"]
    assert d.loc["MIL:ISP", "close"] == 5.2
    assert route.call_count == 2


@respx.mock
def test_ecb_rates_in_dollars_per_unit():
    csv = "CURRENCY,OBS_VALUE\nUSD,1.10\nGBP,0.85\nCHF,0.95\n"
    respx.get(url__startswith=ecb.URL).mock(return_value=httpx.Response(200, text=csv))
    fx = ecb.usd_per_unit()
    assert fx["USD"] == 1.0
    assert round(fx["EUR"], 4) == 1.10
    assert round(fx["GBP"], 4) == round(1.10 / 0.85, 4)
    assert round(fx["GBX"] * 100, 4) == round(fx["GBP"], 4)


def test_yahoo_symbols():
    assert screener.yahoo_symbol("MIL:UCG", "italy") == "UCG.MI"
    assert screener.yahoo_symbol("NYSE:BRK.B", "america") == "BRK-B"
    assert screener.yahoo_symbol("OMXSTO:INVE_A", "sweden") == "INVE-A.ST"
    assert screener.yahoo_symbol("EURONEXT:ASML", "netherlands") == "ASML.AS"
    assert screener.yahoo_symbol("EURONEXT:MC", "france") == "MC.PA"
    assert screener.yahoo_symbol("LSE:BT.A", "uk") == "BT-A.L"
    assert screener.yahoo_symbol("XYZ:ABC", "uk") is None


def test_screener_type_by_industry():
    types = screener.load_config()["types"]
    assert screener.screener_type("Finance", "Regional Banks", types) == "banks"
    assert screener.screener_type("Finance", "Property/Casualty Insurance", types) == "insurers"
    assert screener.screener_type("Finance", "Real Estate Investment Trusts", types) == "reits"
    assert screener.screener_type("Utilities", "Electric Utilities", types) == "utilities"
    assert screener.screener_type("Technology Services", "Packaged Software", types) == "general"
    assert screener.screener_type("Finance", "Investment Trusts/Mutual Funds", types) is None


def test_every_configured_rule_is_known():
    cfg = screener.load_config()
    for rules in cfg["screener"].values():
        for name in rules:
            assert name == "optional" or name in screener.RULE_LABELS, name


def test_yearly_growth_newest_first():
    g = screener.yearly_growth([121, 110, 100, None, 50], years=5)
    assert [round(x, 2) for x in g] == [0.10, 0.10]
    assert screener.yearly_growth(None, 5) == []


def _stocks() -> pd.DataFrame:
    d = pd.DataFrame(
        {
            "type": ["general"] * 4,
            "cash_n_short_term_invest_fq": [10, 10, 1, np.nan],
            "short_term_debt_fq": [5, 0, 5, 5],
            "long_term_debt_fq": [50, 0, 50, 50],
            "total_debt_fq": [55, 0, 55, 55],
            "net_debt_fq": [45, -10, 54, 45],
            "ebitda_ttm": [20, 5, 20, 20],
            "ebitda_interst_cover_ttm": [10, np.nan, 10, 10],
            "net_income_ttm": [5, 2, 5, 5],
            "eps": [1.0, 0.5, 1.0, 1.0],
            "revenue_growth_avg": [0.05] * 4,
            "revenue_growth_median": [0.05] * 4,
            "eps_growth_avg": [0.05] * 4,
            "eps_growth_median": [0.05] * 4,
            "return_on_equity_fq": [15] * 4,
            "piotroski_f_score_ttm": [7, np.nan, 7, 7],
            "altman_z_score_ttm": [3, 3, 3, 3],
        },
        index=["ok", "net_cash", "low_cash", "no_cash_data"],
    )
    screener.ratios(d)
    return d


def test_screeners_pass_fail_and_incomplete():
    d = screener.apply_screeners(_stocks(), screener.load_config())
    assert d.loc["ok", "status"] == "pass"
    # net cash passes the leverage and interest rules without an interest figure
    assert d.loc["net_cash", "status"] == "pass"
    assert "Piotroski" in d.loc["net_cash", "flags"]  # optional rule, data missing
    assert d.loc["low_cash", "status"] == "fail"
    assert "cash covers short-term debt" in d.loc["low_cash", "failed"]
    assert d.loc["no_cash_data", "status"] == "incomplete"


def test_fiscal_pe_and_cheap_multiple():
    idx = pd.date_range("2015-01-31", "2025-12-31", freq="ME")
    prices = pd.Series(20.0, index=idx)
    eps = [2.0, 1.0, 2.0, 2.0, -1.0, 2.0, 1.0, 2.0, 2.0, 2.0]
    years = list(range(2025, 2015, -1))
    h = screener.fiscal_pe(prices, eps, years, pd.Timestamp("2025-12-31"), 10)
    assert len(h) == 10
    assert h.loc[h["year"] == 2025, "pe"].iloc[0] == 10
    assert np.isnan(h.loc[h["year"] == 2021, "pe"].iloc[0])  # loss year has no P/E
    assert screener.cheap_multiple(h["pe"], 0.25, 6) == 10
    assert np.isnan(screener.cheap_multiple(h["pe"].head(4), 0.25, 6))


def test_cheap_price_capped_at_sector_median():
    d = pd.DataFrame(
        {
            "region": "US",
            "sector": "Retail Trade",
            "price_fund": [100.0, 50.0, 30.0],
            "close": [100.0, 50.0, 30.0],
            "eps": [5.0, 5.0, 2.0],
            "cheap_pe": [40.0, 8.0, np.nan],
            "fx_fund": 1.0,
            "fx_price": 1.0,
        },
        index=["growth_history", "value", "no_history"],
    )
    screener.set_cheap_price(d)
    # sector median P/E = median(20, 10, 15) = 15 caps the 40x history
    assert d.loc["growth_history", "cheap_multiple"] == 15
    assert d.loc["growth_history", "cheap_basis"] == "sector median"
    assert d.loc["value", "cheap_price"] == 40
    assert round(d.loc["value", "vs_cheap"], 2) == 0.25
    assert np.isnan(d.loc["no_history", "cheap_price"])


def test_adjusted_eps_rejected_when_far_from_diluted():
    assert screener.adjusted_eps_plausible(5.5, 5.0)
    assert not screener.adjusted_eps_plausible(50.0, 5.0)  # split not applied
    assert not screener.adjusted_eps_plausible(1.0, -2.0)


def test_rank_lists_only_cheap_or_close_top_n():
    d = pd.DataFrame(
        {
            "region": "US",
            "sector": "Health",
            "status": ["pass", "pass", "pass", "pass", "fail"],
            "vs_cheap": [-0.3, 0.1, -0.1, 0.5, -0.9],
            "pe_now": 10.0,
            "cheap_multiple": 12.0,
            "cheap_basis": "own history",
            "trend": "uptrend",
        },
        index=["a", "b", "c", "d", "e"],
    )
    cfg = {"top_per_sector": 2, "close_to_cheap": 0.15}
    top = screener.rank(d, cfg)
    assert list(top.index) == ["a", "c"]
    assert list(top["cheapness"]) == ["cheap", "cheap"]
    cfg["top_per_sector"] = 5
    top = screener.rank(d, cfg)
    assert list(top.index) == ["a", "c", "b"]  # d is not close to cheap, e failed
    assert top.loc["b", "cheapness"] == "close"


def test_split_adjust_only_values_filed_before_the_split():
    hist = pd.DataFrame(
        {
            "symbol": "BKNG",
            "fiscal_year_end": pd.to_datetime(["2024-12-31", "2024-12-31", "2026-12-31"]),
            "column": ["_shares", "eps", "_shares"],
            "value": [34e6, 172.7, 800e6],
            "source": "SEC",
            "filed": ["2026-02-18", "2026-02-18", "2027-02-18"],
        }
    )
    splits = pd.Series([25.0], index=pd.to_datetime(["2026-06-08"]))
    out = history.split_adjust(hist, splits)
    assert list(out["value"]) == [34e6 * 25, 172.7 / 25, 800e6]


def test_stage1_counts_and_survivors():
    d = pd.DataFrame(
        {
            "region": ["US", "US", "US", "Europe"],
            "sector": ["Retail Trade", "Retail Trade", "Finance", "Retail Trade"],
            "status": ["pass", "fail", "pass", "incomplete"],
            "cap_usd_bn": [5.0, 9.0, 3.0, 2.0],
        },
        index=["a", "b", "c", "d"],
    )
    counts = screener.stage1_counts(d)
    assert counts.loc["Retail Trade", ("screened", "US")] == 2
    assert counts.loc["Retail Trade", ("passed", "US")] == 1
    assert counts.loc["Retail Trade", ("passed", "Europe")] == 0
    assert list(screener.stage1_survivors(d).index) == ["c", "a"]
