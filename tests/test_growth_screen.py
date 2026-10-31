"""The growth screener (analysis/growth_screen.py): measures, rules, own-history P/E."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import growth_screen as gs  # noqa: E402
from screen_common import load_config  # noqa: E402

YEARS = list(range(2025, 2015, -1))


def test_cagr_up_years_and_window():
    v = [161.05, 146.41, 133.1, 121, 110, 100]  # +10% a year, newest first
    assert round(gs.cagr(v, 5), 4) == 0.10
    assert gs.up_years(v, 5) == 5
    assert gs.up_years([100, 110, 100, 110, 100, 90], 5) == 3
    assert np.isnan(gs.cagr([100, 90, None, 80, 70, 60], 5))  # a missing year
    assert np.isnan(gs.cagr([100, 90, 80, 70, 60, -5], 5))  # loss at the start
    assert gs.window([1, 2], 5) is None


def test_as_of_year_cuts_every_history_list():
    d = pd.DataFrame(
        {
            "fiscal_period_fy_h": [YEARS, [2025, 2024]],
            "total_revenue_fy_h": [list(range(10, 0, -1)), [5, 4]],
            "net_income_fy_h": [list(range(10, 0, -1)), [5, 4]],
            "earnings_per_share_diluted_fy_h": [list(range(10, 0, -1)), [5, 4]],
        },
        index=["long", "short"],
    )
    h = gs.as_of_year(d, 2022)
    assert h.loc["long", "fiscal_period_fy_h"][0] == 2022
    assert h.loc["long", "total_revenue_fy_h"][0] == 7
    assert h.loc["long", "years_back"] == 3
    assert h.loc["short", "total_revenue_fy_h"] == []


def _stock(rev, ni, eps, rev_ttm, ni_ttm, sector="Tech"):
    return {
        "sector": sector,
        "fiscal_period_fy_h": YEARS,
        "total_revenue_fy_h": rev,
        "net_income_fy_h": ni,
        "earnings_per_share_diluted_fy_h": eps,
        "total_revenue_ttm": rev_ttm,
        "net_income_ttm": ni_ttm,
    }


def _universe() -> pd.DataFrame:
    grow = [160, 150, 130, 120, 110, 100, 90, 80, 70, 60]
    profit = [x * 0.2 for x in grow]
    rows = {
        "good": _stock(grow, profit, [x / 10 for x in profit], 165, 33),
        "thin": _stock(grow, [x * 0.05 for x in grow], grow, 165, 8.5),
        "shrinking": _stock(grow[::-1], profit[::-1], profit[::-1], 60, 12),
        "slowing": _stock(grow, profit, profit, 150, 33),  # 12 months below the latest year
        "short": _stock([160, 150], [32, 30], [3.2, 3.0], 165, 33),
    }
    return pd.DataFrame.from_dict(rows, orient="index")


def test_rules_pass_fail_and_incomplete():
    cfg = load_config()
    d = _universe()
    gs.growth_measures(d, cfg["growth"]["years"])
    gs.apply_rules(d, cfg["growth"] | {"min_sector_size": 99}, ttm=True)
    assert d.loc["good", "status"] == "pass"
    assert "net margin" in d.loc["thin", "failed"]
    assert "revenue growth" in d.loc["shrinking", "failed"]
    assert "still growing" in d.loc["slowing", "failed"]
    assert d.loc["short", "status"] == "incomplete"


def test_margin_floor_is_sector_median_when_higher():
    cfg = load_config()["growth"] | {"min_sector_size": 2}
    d = _universe()
    gs.growth_measures(d, cfg["years"])
    gs.apply_rules(d, cfg, ttm=True)
    # sector median margin of the five is 0.2: the floor rises from 10% to 20%
    assert round(d.loc["good", "margin_floor"], 2) == 0.2
    d.loc["good", "net_income_ttm"] = 25  # 15% margin: above 10%, below its sector
    gs.apply_rules(d, cfg, ttm=True)
    assert "net margin" in d.loc["good", "failed"]


def test_flags_one_off_and_lumpy_profit():
    d = pd.DataFrame(
        {
            "net_income_ttm": [40.0, 21.0],
            "net_income_fy": [20.0, 20.0],
            "net_income_fy_h": [[20, 19, 18, 17, 16, 15], [20, 10, 18, 17, 16, 15]],
        },
        index=["one_off", "lumpy"],
    )
    gs.flags(d, 5)
    assert "one-off" in d.loc["one_off", "flags"]
    assert "fell 30%" in d.loc["lumpy", "flags"]
    assert "one-off" not in d.loc["lumpy", "flags"]


def test_own_pe_against_history_and_rank():
    cfg = load_config()
    idx = pd.date_range("2015-01-01", "2026-10-01", freq="MS")
    prices = pd.DataFrame({"AAA": 20.0, "BBB": 20.0}, index=idx)
    d = pd.DataFrame(
        {
            "status": ["pass", "pass"],
            "yahoo": ["AAA", "BBB"],
            "fx_price": [1.0, 1.0],
            "fx_fund": [1.0, 1.0],
            "fiscal_period_end_fy": [pd.Timestamp("2025-12-31").timestamp()] * 2,
            "fiscal_period_fy_h": [YEARS, YEARS],
            # AAA: P/E 20 every year; BBB: P/E 10, with one near-zero year (P/E 400)
            "earnings_per_share_diluted_fy_h": [[1.0] * 10, [2.0] * 9 + [0.05]],
            "eps": [2.0, 2.0],
            "price_fund": [20.0, 20.0],
        },
        index=["A", "B"],
    )
    gs.own_pe(d, d.index, prices, cfg)
    assert d.loc["A", "pe_now"] == 10 and d.loc["A", "pe_median"] == 20
    assert d.loc["A", "pe_vs_median"] == -0.5
    assert d.loc["B", "pe_median"] == 10  # the 400 year is left out (max_history_pe)
    assert d.loc["B", "pe_years"] == 9
    assert list(gs.rank(d).index) == ["A", "B"]


def test_growth_settings_present():
    g = load_config()["growth"]
    for key in (
        "years",
        "min_revenue_cagr",
        "min_net_income_cagr",
        "min_eps_cagr",
        "min_net_margin",
        "max_history_pe",
    ):
        assert key in g
