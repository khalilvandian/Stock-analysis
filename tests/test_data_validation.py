"""Validation of the committed pipeline outputs (offline: reads files in the repository) and
tests of analysis/validate.py on small hand-built repositories."""

import json
import shutil
import sys
import tomllib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
import stage1  # noqa: E402
import validate  # noqa: E402
from screen_common import ABSOLUTE, load_config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SCREENER = ROOT / "data/screener"
ANALYSES = ROOT / "analyses"
TOL = 0.01  # $bn; the CSVs round to 4 decimals


@pytest.fixture(scope="module")
def top() -> pd.DataFrame:
    return pd.read_csv(SCREENER / "top.csv", index_col=0)


@pytest.fixture(scope="module")
def s1() -> pd.DataFrame:
    return pd.read_csv(SCREENER / "stage1.csv", index_col=0)


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config()


def _close(a, b, tol=TOL) -> pd.Series:
    return ~validate.off(pd.Series(a, dtype=float), pd.Series(b, dtype=float), tol)


# --- 6. committed market screener ----------------------------------------------------


def test_screener_outputs_have_the_columns_readers_need(top, s1):
    assert not [c for c in validate.TOP_REQUIRED if c not in top.columns]
    assert not [c for c in stage1.STAGE1_COLUMNS if c not in s1.columns]
    assert not [c for c in ABSOLUTE if c not in s1.columns]
    assert top.index.is_unique and s1.index.is_unique
    assert len(top) > 0 and len(s1) > 0


def test_top_lists_at_most_n_per_region_and_sector(top, cfg):
    assert top.groupby(["region", "sector"]).size().max() <= cfg["top_per_sector"]


def test_top_lists_only_stage1_passes(top, s1):
    assert (top["status"] == "pass").all()
    assert set(top.index) <= set(s1.index)
    assert (s1.loc[top.index, "status"] == "pass").all()
    assert np.allclose(s1.loc[top.index, "close"], top["close"])


def test_vs_cheap_is_close_over_cheap_price(top):
    assert top["vs_cheap"].notna().all() and (top["cheap_price"] > 0).all()
    assert _close(top["close"] / top["cheap_price"] - 1, top["vs_cheap"], 1e-3).all()


def test_cheap_and_close_labels_follow_close_to_cheap(top, cfg):
    close = cfg["close_to_cheap"]
    assert (top["vs_cheap"] <= close).all()
    assert (top.loc[top["vs_cheap"] <= 0, "cheapness"] == "cheap").all()
    assert (top.loc[top["vs_cheap"] > 0, "cheapness"] == "close").all()


def test_ranks_run_from_one_by_vs_cheap(top):
    for _, g in top.groupby(["region", "sector"]):
        g = g.sort_values("rank_in_sector")
        assert list(g["rank_in_sector"]) == list(range(1, len(g) + 1))
        assert g["vs_cheap"].is_monotonic_increasing


def test_listed_stocks_earn_money_and_pe_matches_eps(top):
    assert (top["eps"] > 0).all()
    assert _close(top["price_fund"] / top["eps"], top["pe_now"], 1e-2).all()
    cheap = top["cheap_multiple"] * top["eps"] * top["fx_fund"] / top["fx_price"]
    assert _close(cheap, top["cheap_price"], 1e-2).all()


def test_stage1_status_is_explained(s1):
    assert set(s1["status"]) <= validate.STATUSES
    blank = lambda c: s1[c].fillna("").eq("")  # noqa: E731
    assert not ((s1["status"] == "fail") & blank("failed")).any()
    assert not ((s1["status"] == "incomplete") & blank("missing")).any()
    assert not ((s1["status"] == "pass") & ~blank("failed")).any()


# --- 5. consistency identities on the committed data -------------------------------------


def test_market_value_in_dollars_is_market_value_times_rate(top):
    assert _close(top["market_cap_basic"] * top["fx_fund"] / 1e9, top["cap_usd_bn"]).all()


@pytest.mark.parametrize("name", ["top", "s1"])
def test_debt_identities_hold_unless_yahoo_filled_a_value(name, request):
    """TradingView's own figures add up; a mismatch only comes from a value Yahoo filled."""
    d = request.getfixturevalue(name)
    yahoo = d["filled"].fillna("").str.contains("Yahoo")
    net = _close(d["net_debt_usd_bn"], d["total_debt_usd_bn"] - d["cash_usd_bn"])
    total = _close(d["total_debt_usd_bn"], d["short_term_debt_usd_bn"] + d["long_term_debt_usd_bn"])
    assert d.index[~net & ~yahoo].tolist() == []
    assert d.index[~total & ~yahoo].tolist() == []


@pytest.mark.parametrize("name", ["top", "s1"])
def test_free_cash_flow_never_above_operating_cash_flow(name, request):
    """TradingView's FCF differs from OCF - |capex| for some companies (its own definition),
    but it is never more than the operating cash flow itself."""
    d = request.getfixturevalue(name)
    tol = np.maximum(TOL, 0.02 * d["ocf_usd_bn"].abs())
    assert d.index[d["fcf_usd_bn"] > d["ocf_usd_bn"] + tol].tolist() == []
    assert (d["capex_usd_bn"].dropna() <= TOL).all()  # capex is an outflow


def test_sector_net_debt_at_least_total_debt_minus_cash():
    """Net debt subtracts cash and equivalents; the cash column also has short-term
    investments, so net debt can only be at or above total debt - cash."""
    u = pd.read_csv(ROOT / "data/sector/utilities.csv", index_col=0)
    low = u["net_debt"] < u["total_debt"] - u["cash"] - TOL
    assert u.index[low].tolist() == []
    assert _close(u["free_cf"], u["operating_cf"] - u["capex"].abs()).all()


def test_history_records_a_known_source_for_every_value():
    h = pd.read_csv(ROOT / "data/sector/history.csv")
    assert set(h["source"]) <= validate.HISTORY_SOURCES and h["source"].notna().all()
    assert not h.duplicated(["symbol", "fiscal_year_end", "column"]).any()
    mc = h[h["column"] == "market_cap"]
    assert (mc["source"] == "Yahoo price x SEC shares").all()
    prices = h[h["column"] == "price"].set_index(["symbol", "fiscal_year_end"]).index
    assert mc.set_index(["symbol", "fiscal_year_end"]).index.isin(prices).all()


def test_history_sec_values_obey_the_identities():
    h = pd.read_csv(ROOT / "data/sector/history.csv")
    w = h[h["source"] == "SEC"].pivot_table(
        index=["symbol", "fiscal_year_end"], columns="column", values="value"
    )
    assert _close(w["net_debt"], w["total_debt"] - w["cash"], 1e-6).all()
    assert _close(w["total_debt"], w["short_term_debt"] + w["long_term_debt"], 1e-6).all()
    assert _close(w["free_cf"], w["operating_cf"] - w["capex"].abs(), 1e-6).all()
    assert (w["capex"].dropna() <= 0).all()


# --- 6. committed dated analyses and configuration --------------------------------------


def test_every_runs_csv_parses_in_order_and_lists_existing_pdfs():
    folders = sorted(p.parent for p in ANALYSES.glob("*/runs.csv"))
    assert folders
    for folder in folders:
        fails = [c for c in validate.check_runs(folder) if c.level == "FAIL"]
        assert not fails, fails


def test_watch_list_stocks_have_notes():
    with (ROOT / "config/watchlist.toml").open("rb") as f:
        symbols = [s["symbol"] for s in tomllib.load(f)["stock"]]
    assert symbols
    assert [s for s in symbols if not (ANALYSES / s / "notes.md").exists()] == []


def test_absolute_values_config_columns_exist():
    with (ROOT / "config/absolute_values.toml").open("rb") as f:
        groups = tomllib.load(f)["group"]
    header = pd.read_csv(ROOT / "data/sector/utilities.csv", nrows=0, index_col=0).columns
    assert [v["column"] for g in groups for v in g["values"] if v["column"] not in header] == []


def test_validate_finds_no_failure_in_the_committed_outputs():
    checks = validate.run_checks(ROOT, date.today())
    fails = [c for c in checks if c.level == "FAIL"]
    assert not fails, validate.report(fails)


# --- analysis/validate.py on hand-built repositories ----------------------------------


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


def _mini_repo(root: Path, today: str = "2026-10-27") -> Path:
    (root / "config").mkdir(parents=True)
    for name in ("screeners.toml", "absolute_values.toml"):
        shutil.copy(ROOT / "config" / name, root / "config" / name)
    (root / "config/watchlist.toml").write_text('[[stock]]\nsymbol = "AAA"\n')
    screener = root / "data/screener"
    screener.mkdir(parents=True)
    top = pd.DataFrame(
        [_top_row("NYSE:A", "Tech", 1, -0.2), _top_row("NYSE:B", "Tech", 2, 0.1)]
    ).set_index("tv_symbol")
    top.to_csv(screener / "top.csv")
    s1 = top[[c for c in validate.STAGE1_REQUIRED if c in top.columns]].copy()
    for c in ("industry", "type", "failed", "missing", "flags", "filled"):
        s1[c] = ""
    s1.loc["NYSE:C"] = s1.iloc[0]
    s1.loc["NYSE:C", ["status", "failed"]] = ["fail", "profitable; "]
    s1.to_csv(screener / "stage1.csv")
    (screener / f"{today}.csv").write_text("tv_symbol\n")
    stamp = today + "_2100"
    run = f"{today} 21:00 CET"
    for folder in ("AAA", "market", "summaries"):
        (root / "analyses" / folder).mkdir(parents=True)
        (root / "analyses" / folder / f"{stamp}.pdf").write_bytes(b"%PDF-1.4 x")
    (root / "analyses/AAA/notes.md").write_text("# AAA\n")
    (root / "analyses/AAA/runs.csv").write_text(
        "run,file,price,eps_adj_ttm,pe_adj,pe_median_10y,target_pe,entry_price,to_entry,verdict\n"
        f"{run},{stamp}.pdf,50,2,25,20,15,30,-0.4,Fine.\n"
    )
    (root / "analyses/market/runs.csv").write_text(f"run,file,sp500\n{run},{stamp}.pdf,7000\n")
    return root


def _levels(checks, name_part: str) -> set[str]:
    return {c.level for c in checks if name_part in c.name}


def test_validate_passes_a_consistent_repository(tmp_path):
    root = _mini_repo(tmp_path)
    checks = validate.run_checks(root, date(2026, 10, 27))
    assert [c for c in checks if c.level == "FAIL"] == []
    assert _levels(checks, "vs_cheap") == {"PASS"}
    assert _levels(checks, "last_run.json") == {"WARN"}  # not built in this checkout
    assert validate.overall(checks) == "WARN"


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
    path = root / "data/screener/top.csv"
    change(pd.read_csv(path, index_col=0)).to_csv(path)
    checks = validate.check_screener(root, date(2026, 10, 27))
    assert "FAIL" in _levels(checks, check), validate.report(checks)


def test_validate_warns_on_a_stale_screener_and_identity_gaps(tmp_path):
    root = _mini_repo(tmp_path)
    path = root / "data/screener/top.csv"
    t = pd.read_csv(path, index_col=0)
    t.loc["NYSE:A", "net_debt_usd_bn"] = 9.0
    t.to_csv(path)
    checks = validate.check_screener(root, date(2026, 10, 28))
    assert _levels(checks, "screener date") == {"WARN"}
    assert _levels(checks, "top.csv: net debt") == {"WARN"}
    assert "FAIL" not in {c.level for c in checks}


def test_validate_runs_csv_problems(tmp_path):
    root = _mini_repo(tmp_path)
    folder = root / "analyses/AAA"
    assert {c.level for c in validate.check_runs(folder)} == {"PASS"}
    runs = folder / "runs.csv"
    good = runs.read_text()
    bad_rows = {
        "missing PDF": good.replace("2026-10-27_2100.pdf", "2026-10-26_2100.pdf"),
        "time mismatch": good.replace("21:00 CET", "20:55 CET"),
        "out of order": good + "2026-10-26 21:00 CET,2026-10-26_2100.pdf,50,2,25,20,15,30,-0.4,x\n",
        "entry price": good.replace(",15,30,", ",15,31,"),
    }
    (folder / "2026-10-26_2100.pdf").write_bytes(b"%PDF-1.4 x")
    for what, text in bad_rows.items():
        runs.write_text(text)
        assert "FAIL" in {c.level for c in validate.check_runs(folder)}, what
    runs.write_text(good)
    (folder / "2026-10-27_2100.pdf").write_bytes(b"")
    assert "FAIL" in {c.level for c in validate.check_runs(folder)}


def test_validate_last_run_lists_files_that_exist(tmp_path):
    root = _mini_repo(tmp_path)
    cache = root / ".cache/watchlist"
    cache.mkdir(parents=True)
    (cache / "email.html").write_text("<p>x</p>")
    run = {
        "subject": "Watch list analyses",
        "html": ".cache/watchlist/email.html",
        "files": ["analyses/AAA/2026-10-27_2100.pdf"],
    }
    (cache / "last_run.json").write_text(json.dumps(run))
    assert [c.level for c in validate.check_last_run(root)] == ["PASS"]
    run["files"].append("analyses/AAA/2026-10-28_2100.pdf")
    (cache / "last_run.json").write_text(json.dumps(run))
    assert [c.level for c in validate.check_last_run(root)] == ["FAIL"]


def test_validate_newest_pdfs_should_come_from_one_run(tmp_path):
    root = _mini_repo(tmp_path)
    (root / "analyses/market/2026-10-28_2100.pdf").write_bytes(b"%PDF-1.4 x")
    checks = validate.check_analyses(root, date(2026, 10, 28))
    assert _levels(checks, "same run") == {"WARN"}
    (root / "analyses/AAA/notes.md").unlink()
    assert "FAIL" in _levels(validate.check_analyses(root, date(2026, 10, 28)), "notes.md")


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


def test_validate_main_exit_codes(tmp_path, monkeypatch, capsys):
    root = _mini_repo(tmp_path)
    monkeypatch.setattr(validate, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["validate.py", "--today", "2026-10-27"])
    with pytest.raises(SystemExit) as e:
        validate.main()
    assert e.value.code == 0 and "Result: WARN" in capsys.readouterr().out
    monkeypatch.setattr(sys, "argv", ["validate.py", "--today", "2026-10-27", "--strict"])
    with pytest.raises(SystemExit) as e:
        validate.main()
    assert e.value.code == 1
    (root / "data/screener/top.csv").unlink()
    monkeypatch.setattr(sys, "argv", ["validate.py", "--today", "2026-10-27"])
    with pytest.raises(SystemExit) as e:
        validate.main()
    assert e.value.code == 1 and "FAIL  screener files" in capsys.readouterr().out
