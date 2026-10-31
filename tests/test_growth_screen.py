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


def _stock(rev, ni, eps, rev_ttm, ni_ttm, sector="Tech", debt=(0.0, 10.0, 0.0, 5.0)):
    """`debt` = (total debt, cash, debt due within a year, 12-month free cash flow)."""
    total, cash, short, fcf = debt
    return {
        "sector": sector,
        "type": "general",
        "total_debt_fq": total,
        "net_debt_fq": total - cash,
        "cash_n_short_term_invest_fq": cash,
        "short_term_debt_fq": short,
        "free_cash_flow_ttm": fcf,
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


def test_margin_must_beat_sector_average():
    cfg = load_config()["growth"] | {"min_sector_size": 2}
    assert cfg["sector_margin"] == "mean"
    d = _universe()
    gs.growth_measures(d, cfg["years"])
    gs.apply_rules(d, cfg, ttm=True)
    # margins 0.20, 0.05, 0.20, 0.22, 0.20: the sector average is 0.174
    assert round(d.loc["good", "margin_floor"], 3) == 0.174
    assert d.loc["good", "status"] == "pass"
    d.loc["good", "net_income_ttm"] = 27  # 16.4% margin: above 10%, below its sector
    gs.apply_rules(d, cfg, ttm=True)
    assert "net margin" in d.loc["good", "failed"]


def test_low_margin_sector_and_small_sector_fallback():
    cfg = load_config()["growth"] | {"min_sector_size": 2}
    grow = [160, 150, 130, 120, 110, 100, 90, 80, 70, 60]
    d = pd.DataFrame.from_dict(
        {
            "grocer": _stock(grow, [x * 0.07 for x in grow], grow, 165, 11.55, "Retail"),
            "rival": _stock(grow, [x * 0.03 for x in grow], grow, 165, 4.95, "Retail"),
            "alone": _stock(grow, [x * 0.12 for x in grow], grow, 165, 19.8, "Telecom"),
        },
        orient="index",
    )
    gs.growth_measures(d, cfg["years"])
    gs.apply_rules(d, cfg, ttm=True)
    assert d.loc["grocer", "status"] == "pass"  # 7% beats the sector's 5% average
    assert "net margin" in d.loc["rival", "failed"]
    assert d.loc["alone", "margin_floor"] == cfg["min_net_margin"]  # one company: 10%
    assert d.loc["alone", "status"] == "pass"


def test_debt_rules():
    cfg = load_config()["growth"] | {"min_sector_size": 99}
    grow = [160, 150, 130, 120, 110, 100, 90, 80, 70, 60]
    profit = [x * 0.2 for x in grow]

    def stock(debt, kind="general"):
        return _stock(grow, profit, profit, 165, 33, debt=debt) | {"type": kind}

    d = pd.DataFrame.from_dict(
        {
            # Domino's on 2026-10-31: debt 5.12, cash 0.47, due in a year 1.37, FCF 0.64
            "pizza": stock((5.12, 0.47, 1.37, 0.64)),
            "payable": stock((10.0, 2.0, 1.0, 2.0)),  # 4 years of FCF, 4.0x cover
            "slow_payer": stock((14.0, 2.0, 1.0, 2.0)),  # 6 years
            "due_now": stock((5.0, 0.5, 3.0, 2.0)),  # cash + FCF 2.5 < 3.0 due
            "no_fcf": stock((5.0, 1.0, 0.0, -1.0)),
            "net_cash": stock((1.0, 5.0, 1.0, -1.0)),  # nothing to repay
            "bank": stock((50.0, 1.0, 40.0, np.nan), kind="banks"),
        },
        orient="index",
    )
    gs.growth_measures(d, cfg["years"])
    gs.apply_rules(d, cfg, ttm=True)
    assert "debt payback" in d.loc["pizza", "failed"]
    assert "short-term debt covered" in d.loc["pizza", "failed"]
    assert d.loc["payable", "net_debt_to_fcf"] == 4
    assert d.loc["payable", "status"] == "pass"
    assert d.loc["slow_payer", "failed"] == "debt payback; "
    assert d.loc["due_now", "failed"] == "short-term debt covered; "
    assert "debt payback" in d.loc["no_fcf", "failed"]
    assert "debt payback" not in d.loc["net_cash", "failed"]
    assert d.loc["bank", "status"] == "pass"


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
