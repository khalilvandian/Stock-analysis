import sys
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import respx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import history  # noqa: E402
import stage1  # noqa: E402
import stage2  # noqa: E402
from screen_common import load_config  # noqa: E402

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
    assert stage1.yahoo_symbol("MIL:UCG", "italy") == "UCG.MI"
    assert stage1.yahoo_symbol("NYSE:BRK.B", "america") == "BRK-B"
    assert stage1.yahoo_symbol("OMXSTO:INVE_A", "sweden") == "INVE-A.ST"
    assert stage1.yahoo_symbol("EURONEXT:ASML", "netherlands") == "ASML.AS"
    assert stage1.yahoo_symbol("EURONEXT:MC", "france") == "MC.PA"
    assert stage1.yahoo_symbol("LSE:BT.A", "uk") == "BT-A.L"
    assert stage1.yahoo_symbol("XYZ:ABC", "uk") is None


def test_screener_type_by_industry():
    types = load_config()["types"]
    assert stage1.screener_type("Finance", "Regional Banks", types) == "banks"
    assert stage1.screener_type("Finance", "Property/Casualty Insurance", types) == "insurers"
    assert stage1.screener_type("Finance", "Real Estate Investment Trusts", types) == "reits"
    assert stage1.screener_type("Utilities", "Electric Utilities", types) == "utilities"
    assert stage1.screener_type("Technology Services", "Packaged Software", types) == "general"
    assert stage1.screener_type("Finance", "Investment Trusts/Mutual Funds", types) is None


def test_every_configured_rule_is_known():
    cfg = load_config()
    for rules in [*cfg["screener"].values(), *cfg["category"].values()]:
        for name in rules:
            assert name == "optional" or name in stage1.RULE_LABELS, name


def test_yearly_growth_newest_first():
    g = stage1.yearly_growth([121, 110, 100, None, 50], years=5)
    assert [round(x, 2) for x in g] == [0.10, 0.10]
    assert stage1.yearly_growth(None, 5) == []


def _stocks() -> pd.DataFrame:
    d = pd.DataFrame(
        {
            "type": ["general"] * 4,
            "category": ["stalwart"] * 4,
            "recession_eps_change": [-0.1, np.nan, -0.1, -0.1],
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
    stage1.ratios(d)
    return d


def test_screeners_pass_fail_and_incomplete():
    d = stage1.apply_screeners(_stocks(), load_config())
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
    h = stage2.fiscal_pe(prices, eps, years, pd.Timestamp("2025-12-31"), 10)
    assert len(h) == 10
    assert h.loc[h["year"] == 2025, "pe"].iloc[0] == 10
    assert np.isnan(h.loc[h["year"] == 2021, "pe"].iloc[0])  # loss year has no P/E
    assert stage2.cheap_multiple(h["pe"], 0.25, 6) == 10
    assert np.isnan(stage2.cheap_multiple(h["pe"].head(4), 0.25, 6))


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
    stage2.set_cheap_price(d)
    # sector median P/E = median(20, 10, 15) = 15 caps the 40x history
    assert d.loc["growth_history", "cheap_multiple"] == 15
    assert d.loc["growth_history", "cheap_basis"] == "sector median"
    assert d.loc["value", "cheap_price"] == 40
    assert round(d.loc["value", "vs_cheap"], 2) == 0.25
    assert np.isnan(d.loc["no_history", "cheap_price"])


def test_adjusted_eps_rejected_when_far_from_diluted():
    assert stage2.adjusted_eps_plausible(5.5, 5.0)
    assert not stage2.adjusted_eps_plausible(50.0, 5.0)  # split not applied
    assert not stage2.adjusted_eps_plausible(1.0, -2.0)


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
    top = stage2.rank(d, cfg)
    assert list(top.index) == ["a", "c"]
    assert list(top["cheapness"]) == ["cheap", "cheap"]
    cfg["top_per_sector"] = 5
    top = stage2.rank(d, cfg)
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


def test_stage1_counts():
    d = pd.DataFrame(
        {
            "region": ["US", "US", "US", "Europe"],
            "sector": ["Retail Trade", "Retail Trade", "Finance", "Retail Trade"],
            "status": ["pass", "fail", "pass", "incomplete"],
        },
        index=["a", "b", "c", "d"],
    )
    counts = stage1.counts(d, "sector")
    assert counts.loc["Retail Trade", ("screened", "US")] == 2
    assert counts.loc["Retail Trade", ("passed", "US")] == 1
    assert counts.loc["Retail Trade", ("passed", "Europe")] == 0


def _history(eps: list, **extra) -> dict:
    row = {
        "industry": "Packaged Software",
        "earnings_per_share_diluted_fy_h": eps,
        "fiscal_period_fy_h": list(range(2025, 2025 - len(eps), -1)),
        "dps_common_stock_prim_issue_fy_h": [1.0] * 10,
        "ebitda_fy_h": [10.0] * 10,
        "net_debt_fq": 10.0,
        "market_cap_basic": 100.0,
        "price_book_fq": 3.0,
        "total_debt_fq": 20.0,
        "cash_n_short_term_invest_fq": 10.0,
        "debt_to_equity_fq": 0.2,
        "eps": eps[0],
    }
    row.update(extra)
    return row


def test_lynch_categories():
    lynch = load_config()["lynch"]
    rows = {
        # newest first; growth is the median of the last 5 yearly changes
        "fast": _history([2.5, 2.0, 1.6, 1.3, 1.0, 0.8, 0.7, 0.6, 0.5, 0.4]),
        "stalwart": _history([1.5, 1.38, 1.27, 1.17, 1.08, 1.0, 0.95, 0.9, 0.85, 0.8]),
        "slow": _history([1.1, 1.08, 1.06, 1.04, 1.02, 1.0, 1.0, 1.0, 1.0, 1.0]),
        "loss": _history([-0.3, 0.5, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
        "fallen": _history([0.4, 1.0, 1.2, 1.1, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]),
        "swings": _history([1.2, 0.8, 1.2, 1.3, 0.8, 1.3, 1.0, 0.6, 1.0, 1.0]),
        "steel": _history([1.1, 1.08, 1.06, 1.04, 1.02, 1.0], industry="Steel"),
        "cash_pile": _history([1.1, 1.08, 1.06, 1.04, 1.02, 1.0], net_debt_fq=-40.0),
        "short": _history([1.0, 0.9]),
        "never": _history([-0.5, -0.4, -0.6, -0.3, -0.2]),
        "one_off": _history([1.2, -0.5, 1.1, 1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7]),
    }
    d = pd.DataFrame(rows).T
    d["eps"] = d["eps"].astype(float)
    for c in ("net_debt_fq", "market_cap_basic", "price_book_fq", "total_debt_fq"):
        d[c] = d[c].astype(float)
    d["cash_n_short_term_invest_fq"] = d["cash_n_short_term_invest_fq"].astype(float)
    d["debt_to_equity_fq"] = d["debt_to_equity_fq"].astype(float)
    g = d["earnings_per_share_diluted_fy_h"].map(lambda v: stage1.yearly_growth(v, 5))
    d["eps_growth_median"] = g.map(lambda x: float(np.median(x)) if len(x) >= 3 else np.nan)
    stage1.history_measures(d, lynch)
    cat = stage1.lynch_category(d, lynch)
    assert cat["fast"] == "fast_grower"
    assert cat["stalwart"] == "stalwart"
    assert cat["slow"] == "slow_grower"
    assert cat["loss"] == "turnaround"
    assert cat["fallen"] == "turnaround"
    assert cat["swings"] == "cyclical"
    assert cat["steel"] == "cyclical"
    assert cat["cash_pile"] == "asset_play"
    assert cat["short"] == ""
    assert cat["never"] == "no_profit"
    assert cat["one_off"] != "turnaround"  # one write-down year, earning again
    assert round(d.loc["fast", "eps_growth_3y"], 3) == round((2.5 / 1.3) ** (1 / 3) - 1, 3)
    assert d.loc["slow", "dividend_years_10y"] == 10


def test_rules_follow_the_category():
    cfg = load_config()
    assert stage1.rules_for("banks", "stalwart", cfg) is cfg["screener"]["banks"]
    assert "max_debt_to_equity" in stage1.rules_for("general", "fast_grower", cfg)
    assert "min_altman_z" not in stage1.rules_for("utilities", "slow_grower", cfg)
    assert "min_altman_z" in stage1.rules_for("general", "slow_grower", cfg)
    assert stage1.rules_for("general", "", cfg) is None


def test_lynch_rules():
    d = pd.DataFrame(
        {
            "net_cash": [False, True, False],
            "debt_to_equity": [0.2, 2.0, 0.5],
            "price_book_fq": [3.0, 1.0, 2.0],
            "total_debt_fq": [10.0, 10.0, 10.0],
            "net_debt_to_ebitda": [1.0, -1.0, 3.0],
            "dividend_payout_ratio_ttm": [50.0, 90.0, np.nan],
            "net_debt_to_avg_ebitda": [2.0, np.nan, 3.0],
            "recession_eps_change": [-0.2, -0.5, np.nan],
            "dividend_years_10y": [10, 0, 7],
        },
        index=["a", "b", "c"],
    )
    assert list(stage1._rule(d, "max_debt_to_equity", 0.33)) == [True, True, False]
    assert list(stage1._rule(d, "max_payout", 0.8)[:2]) == [True, False]
    assert pd.isna(stage1._rule(d, "max_payout", 0.8)["c"])
    assert list(stage1._rule(d, "max_net_debt_to_avg_ebitda", 2.5)) == [True, True, False]
    assert list(stage1._rule(d, "max_recession_eps_drop", 0.3)[:2]) == [True, False]
    # negative equity (blank debt/equity and price/book): net debt / EBITDA at most 2x
    neg = d.assign(debt_to_equity=np.nan, price_book_fq=np.nan)
    assert list(stage1._rule(neg, "max_debt_to_equity", 0.33)) == [True, True, False]
    # a dividend record is checked for payers; never paying one passes
    assert list(stage1._rule(d, "min_dividend_years", 10)) == [True, True, False]


def test_stage2_refuses_stage1_output_without_its_columns(tmp_path):
    path = tmp_path / "stage1_full.pkl"
    pd.DataFrame({"status": ["pass"]}).to_pickle(path)
    try:
        stage2.load_stage1(path)
    except SystemExit as e:
        assert "lacks" in str(e)
    else:
        raise AssertionError("expected SystemExit")
    full = pd.DataFrame({c: [1] for c in stage2.NEEDS})
    full.to_pickle(path)
    assert len(stage2.load_stage1(path)) == 1


def test_index_membership():
    idx = pd.Series(
        [
            [
                {"name": "S&P 500", "proname": "SP:SPX"},
                {"name": "Nasdaq 100", "proname": "NASDAQ:NDX"},
            ],
            [{"name": "Russell 2000", "proname": "TVC:RUT"}],
            None,
        ]
    )
    assert list(stage1.in_index(idx, "SP:SPX")) == [True, False, False]
