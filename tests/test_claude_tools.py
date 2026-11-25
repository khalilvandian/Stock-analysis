"""Claude's tools print the app's numbers (claude/tools)."""

import numpy as np
import pandas as pd
import pytest

from claude.tools import absolute, peer_screen, screen
from stock_analysis import stocks
from stock_analysis.absolute import columns, load_config


@pytest.fixture
def rows(monkeypatch):
    """Three made-up companies with every column of the real rows."""
    n = {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0}
    df = pd.DataFrame({c: pd.Series(n) for c in stocks.row_columns()})
    df["name"] = ["Alpha", "Beta", "Gamma"]
    df["industry"], df["data_flag"] = "Tools", ""
    df["price_vs_fair_value"] = [-0.2, 0.1, 0.3]
    df["net_debt_to_ebitda"] = [1.0, 2.0, 9.0]  # Gamma fails the debt rules
    for c in ("cash_to_short_term_debt", "cash_to_long_term_debt", "ebitda_to_interest"):
        df[c] = [9.0, 8.0, 0.01]
    for c in ("revenue_growth_years", "eps_growth_years"):
        df[c] = 4
    asked = []

    def fake(data, symbols):
        asked.append(list(symbols))
        out = df.reindex(list(symbols))
        if out["name"].isna().any():
            out["error"] = np.where(out["name"].isna(), "not in the database", None)
        return out

    monkeypatch.setattr(stocks, "rows", fake)
    return asked


def test_absolute_shows_every_configured_value(rows, capsys):
    absolute.main(["aaa", "BBB"], data="db")
    out = capsys.readouterr().out
    assert rows == [["AAA", "BBB"]] and "AAA" in out and "BBB" in out
    for group in load_config():
        assert group["name"] in out
    for c in columns(load_config()):
        assert c["label"] in out
    with pytest.raises(KeyError, match="Not in the database"):
        absolute.main(["NOPE"], data="db")


def test_absolute_history_shows_the_years(rows, capsys, monkeypatch):
    first = columns(load_config())[0]
    hist = pd.DataFrame(
        {
            "symbol": ["AAA"] * 2,
            "fiscal_year_end": ["2024-12-31", "2025-12-31"],
            "column": first.get("history") or "revenue",
            "value": [7.0, 8.0],
        }
    )
    monkeypatch.setattr(stocks, "history", lambda data, symbols: hist)
    absolute.main(["--history", "AAA"], data="db")
    out = capsys.readouterr().out
    assert "FY2024" in out and "FY2025" in out and "Latest 12m" in out


def test_peer_screen_names_the_missing_and_ranks_the_rest(rows, capsys):
    peer_screen.main(["tools", "AAA", "BBB", "CCC", "NOPE"], data="db")
    out = capsys.readouterr().out
    assert "Peer group tools: 3 stocks; not in the database: NOPE" in out
    strict = out.split("Weighted screen")[0]
    assert "Alpha" in strict and "Gamma" not in strict
    assert "Gamma" in out.split("Weighted screen")[1]
    with pytest.raises(SystemExit):
        peer_screen.main(["tools"])


@pytest.mark.parametrize(
    "option, gamma", [([], False), (["--strict"], False), (["--balanced"], True)]
)
def test_screen_options(rows, capsys, option, gamma):
    screen.main(["AAA", "BBB", "CCC", *option], data="db")
    out = capsys.readouterr().out
    assert "Alpha" in out and ("Gamma" in out) is gamma
