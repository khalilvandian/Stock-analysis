"""Tests of stock_analysis.report.validate on small hand-built repositories: the screener run, the
recorded runs and the watch list's rows are made here and the database calls replaced, so
no database or network is needed."""

import shutil
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_analysis.report import validate
from stock_analysis.screener.common import ABSOLUTE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TODAY = date(2026, 10, 27)


def _top_row(sym: str, sector: str, rank: int, vs: float, close: float = 100.0) -> dict:
    cheap = close / (1 + vs)
    row = {c: 1.0 for c in ABSOLUTE}
    row |= {
        "tv_symbol": sym,
        "description": sym,
        "region": "US",
        "sector": sector,
        "status": "pass",
        "category": "stalwart",
        "close": close,
        "currency": "USD",
        "eps": 5.0,
        "eps_basis": "diluted",
        "pe_now": close / 5.0,
        "cheap_multiple": cheap / 5.0,
        "cheap_basis": "own history",
        "cheap_price": cheap,
        "vs_cheap": vs,
        "cheapness": "cheap" if vs <= 0 else "close",
        "rank_in_sector": rank,
        "why": "",
        "total_debt_usd_bn": 3.0,
        "cash_usd_bn": 1.0,
        "net_debt_usd_bn": 2.0,
        "short_term_debt_usd_bn": 1.0,
        "long_term_debt_usd_bn": 2.0,
        "ocf_usd_bn": 2.0,
        "capex_usd_bn": -0.5,
        "fcf_usd_bn": 1.5,
    }
    return row


def _screener() -> tuple[pd.DataFrame, pd.DataFrame]:
    top = pd.DataFrame(
        [_top_row("NYSE:A", "Tech", 1, -0.2), _top_row("NYSE:B", "Tech", 2, 0.1)]
    ).set_index("tv_symbol")
    s1 = top[[c for c in validate.STAGE1_REQUIRED if c in top.columns]].copy()
    for c in ("industry", "type", "failed", "missing", "flags", "filled"):
        s1[c] = ""
    s1.loc["NYSE:C"] = s1.iloc[0]
    s1.loc["NYSE:C", ["status", "failed"]] = ["fail", "profitable; "]
    return s1, top


def _runs(file: str = "2026-10-27_2100.pdf", run_at: str = "2026-10-27T20:00:00", **kw):
    row = {"symbol": "AAA", "run_at": run_at, "file": file, "price": 50.0, "eps_adj_ttm": 2.0,
           "pe_adj": 25.0, "pe_median_10y": 20.0, "target_pe": 15.0, "entry_price": 30.0,
           "to_entry": -0.4, "verdict": "Fine.", "stakes_per_share": None}  # fmt: skip
    return pd.DataFrame([row | kw])


def _mini_repo(root: Path, today: str = "2026-10-27") -> Path:
    (root / "config").mkdir(parents=True)
    for name in ("screeners.toml", "absolute_values.toml"):
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    return root


class FakeData:
    def __init__(self, runs: pd.DataFrame):
        self.runs = runs

    def watchlist(self):
        return pd.DataFrame({"symbol": ["AAA"]})

    def watchlist_runs(self, symbol=None):
        return self.runs


def _fake_database(monkeypatch, s1, top, run_date="2026-10-27"):
    """stocks.screener_run, rows and history as the checks would read them."""
    monkeypatch.setattr(validate.stocks, "screener_run", lambda data: (run_date, s1, top))
    row = {c: 1.0 for c in validate.stocks.row_columns()}
    row |= {"total_debt": 3.0, "cash": 1.0, "net_debt": 2.0, "short_term_debt": 1.0,
            "long_term_debt": 2.0, "operating_cf": 2.0, "capex": -0.5, "free_cf": 1.5}  # fmt: skip
    monkeypatch.setattr(
        validate.stocks, "rows", lambda data, symbols: pd.DataFrame([row], index=["AAA"])
    )
    monkeypatch.setattr(
        validate.stocks,
        "history",
        lambda data, symbols: pd.DataFrame(
            [
                {
                    "symbol": "AAA",
                    "fiscal_year_end": "2025-12-31",
                    "column": "revenue",
                    "value": 1.0,
                    "source": "sec",
                }
            ]  # fmt: skip
        ),
    )


def _levels(checks, name_part: str) -> set[str]:
    return {c.level for c in checks if name_part in c.name}


@pytest.mark.parametrize(
    "change, check",
    [
        (lambda t: t.assign(status=["pass", "fail"]), "only Stage 1 passes"),
        (lambda t: t.assign(vs_cheap=[-0.2, 0.3]), "vs_cheap"),
        (lambda t: t.assign(cheapness=["close", "close"]), "labels"),
        (lambda t: t.assign(rank_in_sector=[2, 1]), "ranks"),
        (lambda t: t.drop(columns="cheap_price"), "columns"),
        (
            lambda t: pd.concat([t] + [t.rename(index=lambda i, k=k: f"{i}{k}") for k in range(2)]),
            "per sector",
        ),
    ],
)
def test_validate_fails_a_broken_screener_list(tmp_path, change, check):
    root = _mini_repo(tmp_path)
    s1, top = _screener()
    checks = validate.screener_checks(root, TODAY, "2026-10-27", s1, change(top))
    assert "FAIL" in _levels(checks, check), validate.report(checks)


def test_validate_warns_on_a_stale_screener_and_identity_gaps(tmp_path):
    root = _mini_repo(tmp_path)
    s1, top = _screener()
    top.loc["NYSE:A", "net_debt_usd_bn"] = 9.0
    checks = validate.screener_checks(root, date(2026, 10, 28), "2026-10-27", s1, top)
    assert _levels(checks, "screener date") == {"WARN"}
    assert _levels(checks, "Stage 2 top: net debt") == {"WARN"}
    assert "FAIL" not in {c.level for c in checks}


def test_validate_no_screener_run_fails(tmp_path, monkeypatch):
    root = _mini_repo(tmp_path)
    monkeypatch.setattr(
        validate.stocks, "screener_run", lambda data: (None, pd.DataFrame(), pd.DataFrame())
    )
    assert _levels(validate.check_screener(root, TODAY, None), "screener run") == {"FAIL"}


def test_validate_lists_outliers():
    top = pd.DataFrame(
        {
            "pe_now": [3.0, 15.0, 150.0, 12.0],
            "eps": [10.0, 9.6, 1.0, 2.0],
            "sec_eps": [9.0, 240.0, 1.0, -1.0],
            "earnings_per_share_diluted_ttm": [4.0, 9.0, 1.0, 2.0],
            "eps_basis": ["adjusted", "adjusted", "diluted", "diluted"],
            "eps_growth_median": [0.1, 0.1, 2.5, 0.1],
            "net_debt_to_ebitda": [1.0, np.inf, 1.0, 1.0],
        },
        index=["low_pe", "split", "high_pe", "sec_loss"],
    )
    (check,) = validate.outliers(top)
    text = "\n".join(check.rows)
    assert check.level == "WARN"
    assert "low_pe: P/E 3.0 under 5" in text and "high_pe: P/E 150.0 over 100" in text
    assert "split: EPS 9.60 vs SEC 240.00" in text  # 25:1 split not in the SEC figure
    assert "low_pe: adjusted EPS 10.00 vs diluted 4.00" in text
    assert "high_pe: median yearly EPS growth +250%" in text
    assert "split: net_debt_to_ebitda is infinite" in text
    assert "sec_loss: SEC EPS -1.00 not positive" in text
    assert validate.outliers(top.loc[[]])[0].level == "PASS"


def test_implied_share_jumps_catch_unapplied_splits_and_unit_errors():
    rows = []
    for year, shares, price in ((2022, 40e6, 3000.0), (2023, 1e9, 120.0), (2024, 1e9, 125.0)):
        end = f"{year}-12-31"
        rows += [
            {"symbol": "SPLIT", "fiscal_year_end": end, "column": "price", "value": price},
            {
                "symbol": "SPLIT",
                "fiscal_year_end": end,
                "column": "market_cap",
                "value": price * shares / 1e9,
            },
            {"symbol": "OK", "fiscal_year_end": end, "column": "price", "value": 10.0},
            {"symbol": "OK", "fiscal_year_end": end, "column": "market_cap", "value": 1.0},
        ]
    jumps = validate.implied_share_jumps(pd.DataFrame(rows))
    assert list(jumps["symbol"]) == ["SPLIT"] and list(jumps["fiscal_year_end"]) == ["2023-12-31"]
    assert jumps["change"].iloc[0] == pytest.approx(25.0)
    assert _levels(validate.history_checks(pd.DataFrame(rows)), "steady") == {"WARN"}


class Store(dict):
    def get(self, path):  # a missing file raises, like the real stores
        return self[path]


def _run(**report):
    made = {"subject": "S", "html": "<p>", "files": ["AAA/2026-10-27_2100.pdf"], "failed": []}
    return {"run_key": "r", "subjects": ["AAA"], "report": made | report}


def test_validate_the_runs_reports():
    store = Store({"AAA/2026-10-27_2100.pdf": b"%PDF-1.4" + b"x" * 6000})
    good = validate.check_report(_run(), store, _runs())
    assert validate.overall(good) == "PASS"
    assert (
        validate.check_report({"run_key": "r", "report": None}, store, _runs())[0].level == "FAIL"
    )
    assert "FAIL" in _levels(validate.check_report(_run(html=""), store, _runs()), "report")
    two = _run() | {"subjects": ["AAA", "market"]}
    assert "FAIL" in _levels(validate.check_report(two, store, _runs()), "report")
    assert "FAIL" in _levels(validate.check_report(_run(), Store(), _runs()), "PDFs")
    small = Store({"AAA/2026-10-27_2100.pdf": b"%PDF-1.4"})
    assert "FAIL" in _levels(validate.check_report(_run(), small, _runs()), "PDFs")
    unlisted = validate.check_report(_run(), store, _runs().iloc[:0])
    assert "FAIL" in _levels(unlisted, "recorded run")
    wrong = validate.check_report(_run(), store, _runs(entry_price=31.0))
    assert "FAIL" in _levels(wrong, "entry price")
    no_target = _runs(target_pe=None, entry_price=None, to_entry=None)
    assert validate.overall(validate.check_report(_run(), store, no_target)) == "PASS"


def test_validate_separates_the_reports_from_the_data(monkeypatch):
    s1, top = _screener()
    _fake_database(monkeypatch, s1, top)
    store = Store({"AAA/2026-10-27_2100.pdf": b"%PDF-1.4" + b"x" * 6000})
    own, behind = validate.run_checks(_run(), store, FakeData(_runs()), TODAY)
    assert validate.overall(own) == "PASS" and validate.overall(behind) != "FAIL"
    monkeypatch.setattr(
        validate.stocks, "screener_run", lambda data: (None, pd.DataFrame(), pd.DataFrame())
    )
    own, behind = validate.run_checks(_run(), store, FakeData(_runs()), TODAY)
    assert validate.overall(own) == "PASS" and validate.overall(behind) == "FAIL"
