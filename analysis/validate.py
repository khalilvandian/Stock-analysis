"""Check the latest pipeline outputs and print a short PASS / WARN / FAIL report.

Reads the run's outputs in the database (the newest screener run, the watch list's runs,
the watch list's rows and history) and the files of the repository (the PDFs, notes.md and
.cache/watchlist/last_run.json). Run it in the evening run right after the build
(docs/EVENING_RUN.md, step 5).

What it checks:
  - Market screener (the newest run in out_screener_result): required columns, at most
    `top_per_sector` rows per region and sector, only Stage 1 passes listed, vs_cheap equal
    to close / cheap_price - 1, the cheap / close labels against `close_to_cheap`, ranks in
    order, P/E and cheap price consistent with EPS and the exchange rates, market value in
    dollars consistent with the statement currency, and whether the screener ran today.
  - Identities on the absolute values (the screener's, and the watch list's rows from the
    database), with tolerances: net debt = total debt - cash, total debt = short-term +
    long-term debt, free cash flow = operating cash flow - |capex|. In the watch list's
    yearly history the implied share count (market value / price) must not jump between
    years, which catches splits not applied and share counts in the wrong unit.
  - Suspicious outliers in the screener's list: P/E under 5 or over 100, EPS far from SEC,
    adjusted EPS far from diluted, extreme EPS growth, infinite ratios.
  - Dated analyses (out_watchlist_run): run times match the file names, every recorded
    PDF exists and is a non-empty PDF, the newest PDF of every folder is non-empty, entry
    price = target P/E x adjusted EPS (+ equity stakes per share where set), every watch
    list stock has notes.md; .cache/watchlist/last_run.json lists files that exist.

WARN = worth a look (known data differences between sources); FAIL = the outputs are broken.
Exits 1 on any FAIL (with --strict, also on WARN).

Usage:
    uv run python analysis/validate.py             # the report
    uv run python analysis/validate.py --verbose   # also list every row behind a WARN
    uv run python analysis/validate.py --strict    # exit non-zero on WARN as well
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from stock_analysis import notes_check, stocks, watchlist

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stock_analysis.screener.common import ABSOLUTE  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

# Columns the market report and the site read from top.csv, plus the absolute values
TOP_REQUIRED = [
    "description",
    "region",
    "sector",
    "status",
    "category",
    "close",
    "currency",
    "eps",
    "eps_basis",
    "pe_now",
    "cheap_multiple",
    "cheap_basis",
    "cheap_price",
    "vs_cheap",
    "cheapness",
    "rank_in_sector",
    "why",
    *ABSOLUTE,
]
STAGE1_REQUIRED = [
    "description",
    "region",
    "sector",
    "industry",
    "type",
    "category",
    "status",
    "failed",
    "missing",
    "flags",
    "filled",
    *ABSOLUTE,
]
STATUSES = {"pass", "fail", "incomplete"}
RUN_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}):(\d{2})")
FILE_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(-\d+)?\.pdf$")

# Tolerances: amounts are in US dollar billions, rounded to 4 decimals in the CSVs
ABS_TOL_BN = 0.01
REL_TOL = 0.01
SHARE_JUMP = 1.8  # implied shares moving more than this between years: split or unit error
PE_LOW, PE_HIGH = 5.0, 100.0
EPS_SOURCE_RATIO = 2.0  # EPS sources further apart than 2x: a split or a data problem


@dataclass
class Check:
    level: str  # PASS, WARN or FAIL
    name: str
    detail: str = ""
    rows: list[str] = field(default_factory=list)


def _pass(name: str, detail: str = "") -> Check:
    return Check("PASS", name, detail)


def _warn(name: str, detail: str, rows: list[str] | None = None) -> Check:
    return Check("WARN", name, detail, rows or [])


def _fail(name: str, detail: str, rows: list[str] | None = None) -> Check:
    return Check("FAIL", name, detail, rows or [])


def _names(index, n: int = 6) -> str:
    items = [str(x) for x in index]
    more = f" and {len(items) - n} more" if len(items) > n else ""
    return ", ".join(items[:n]) + more


def off(a: pd.Series, b: pd.Series, abs_tol: float = ABS_TOL_BN) -> pd.Series:
    """True where a and b differ by more than the tolerance (both known)."""
    scale = np.maximum(a.abs(), b.abs()).fillna(0)
    tol = np.maximum(abs_tol, REL_TOL * scale)
    return ((a - b).abs() > tol) & a.notna() & b.notna()


# --- identities ----------------------------------------------------------------------


def identities(
    d: pd.DataFrame,
    name: str,
    total: str,
    cash: str,
    net: str,
    short: str,
    long: str,
    ocf: str,
    capex: str,
    fcf: str,
) -> list[Check]:
    """Net debt = total debt - cash, total debt = short + long term, FCF = OCF - |capex|."""
    out = []
    for label, lhs, rhs in (
        ("net debt = total debt - cash", d[net], d[total] - d[cash]),
        ("total debt = short-term + long-term debt", d[total], d[short] + d[long]),
        ("free cash flow = operating cash flow - |capex|", d[fcf], d[ocf] - d[capex].abs()),
    ):
        bad = off(lhs, rhs)
        known = int((lhs.notna() & rhs.notna()).sum())
        title = f"{name}: {label}"
        if bad.any():
            gap = (lhs - rhs).abs()[bad].sort_values(ascending=False)
            rows = [f"{i}: {lhs[i]:.3f} vs {rhs[i]:.3f}" for i in gap.index]
            out.append(_warn(title, f"{bad.sum()} of {known} rows off: {_names(gap.index)}", rows))
        else:
            out.append(_pass(title, f"{known} rows"))
    return out


# --- market screener -----------------------------------------------------------------


def check_screener(root: Path, today: date, data) -> list[Check]:
    run_date, s1, top = stocks.screener_run(data)
    if run_date is None:
        return [_fail("screener run", "no screener run in the database")]
    return screener_checks(root, today, run_date, s1, top)


def screener_checks(
    root: Path, today: date, run_date: str, s1: pd.DataFrame, top: pd.DataFrame
) -> list[Check]:
    with (root / "config/screeners.toml").open("rb") as f:
        cfg = tomllib.load(f)
    out: list[Check] = []

    for frame, name, need in ((top, "Stage 2 top", TOP_REQUIRED), (s1, "Stage 1", STAGE1_REQUIRED)):
        lacking = [c for c in need if c not in frame.columns]
        if lacking:
            out.append(_fail(f"{name} columns", f"missing: {', '.join(lacking)}"))
            return out
        if frame.index.duplicated().any():
            dup = frame.index[frame.index.duplicated()]
            out.append(_fail(f"{name} symbols", f"listed twice: {_names(dup)}"))
        if frame.empty:
            out.append(_fail(f"{name} rows", "no rows"))
            return out
    out.append(_pass("screener columns", f"Stage 2 top {len(top)} rows, Stage 1 {len(s1)} rows"))

    # Stage 1: statuses and the reasons behind them
    bad = s1[~s1["status"].isin(STATUSES)]
    reason = {"fail": "failed", "incomplete": "missing"}
    for status, col in reason.items():
        sub = s1[(s1["status"] == status) & s1[col].fillna("").eq("")]
        bad = pd.concat([bad, sub])
    passed = s1[s1["status"] == "pass"]
    bad = pd.concat([bad, passed[passed["failed"].fillna("").ne("")]])
    if len(bad):
        out.append(_fail("Stage 1 statuses", f"unknown or unexplained: {_names(bad.index)}"))
    else:
        counts = s1["status"].value_counts().to_dict()
        out.append(_pass("Stage 1 statuses", ", ".join(f"{k} {v}" for k, v in counts.items())))

    # Stage 2's list
    n = cfg["top_per_sector"]
    per = top.groupby(["region", "sector"]).size()
    if (per > n).any():
        out.append(_fail("Stage 2 top per sector", f"more than {n}: {_names(per[per > n].index)}"))
    else:
        out.append(_pass("Stage 2 top per sector", f"at most {n} per region and sector"))

    not_pass = top[top["status"] != "pass"].index.tolist()
    not_in_s1 = [i for i in top.index if i not in s1.index]
    s1_not_pass = [i for i in top.index if i in s1.index and s1.loc[i, "status"] != "pass"]
    if not_pass or not_in_s1 or s1_not_pass:
        out.append(
            _fail(
                "Stage 2 top lists only Stage 1 passes",
                f"status not pass: {not_pass}; not in Stage 1: {not_in_s1}; "
                f"not passed in Stage 1: {s1_not_pass}",
            )
        )
    else:
        out.append(_pass("Stage 2 top lists only Stage 1 passes"))

    vs = top["close"] / top["cheap_price"] - 1
    wrong = top.index[off(vs, top["vs_cheap"], abs_tol=1e-3) | top["vs_cheap"].isna()]
    if len(wrong):
        out.append(_fail("vs_cheap = close / cheap price - 1", f"wrong: {_names(wrong)}"))
    else:
        out.append(_pass("vs_cheap = close / cheap price - 1"))

    close = cfg["close_to_cheap"]
    expect = np.where(
        top["vs_cheap"] <= 0, "cheap", np.where(top["vs_cheap"] <= close, "close", "")
    )
    label = top["cheapness"].fillna("")
    wrong = top.index[(label != expect) | (top["vs_cheap"] > close)]
    if len(wrong):
        out.append(_fail("cheap / close labels", f"inconsistent: {_names(wrong)}"))
    else:
        out.append(_pass("cheap / close labels", f"close = within {close:.0%} of the cheap price"))

    wrong = []
    for key, g in top.groupby(["region", "sector"]):
        ranks = g["rank_in_sector"].astype(int).tolist()
        ordered = g.sort_values("rank_in_sector")["vs_cheap"].is_monotonic_increasing
        if sorted(ranks) != list(range(1, len(g) + 1)) or not ordered:
            wrong.append("/".join(key))
    if wrong:
        out.append(_fail("ranks in sector", f"not 1..n by vs_cheap: {_names(wrong)}"))
    else:
        out.append(_pass("ranks in sector"))

    if (top["eps"] <= 0).any():
        out.append(_fail("listed EPS positive", _names(top.index[top["eps"] <= 0])))
    if {"price_fund", "fx_fund", "fx_price", "cheap_multiple"} <= set(top.columns):
        pe = top["price_fund"] / top["eps"]
        cheap = top["cheap_multiple"] * top["eps"] * top["fx_fund"] / top["fx_price"]
        price_fund = top["close"] * top["fx_price"] / top["fx_fund"]
        wrong = top.index[
            off(pe, top["pe_now"], 1e-2)
            | off(cheap, top["cheap_price"], 1e-2)
            | off(price_fund, top["price_fund"], 1e-2)
        ]
        if len(wrong):
            out.append(_fail("P/E and cheap price from EPS and exchange rates", _names(wrong)))
        else:
            out.append(_pass("P/E and cheap price from EPS and exchange rates"))
    if {"market_cap_basic", "fx_fund"} <= set(top.columns):
        cap = top["market_cap_basic"] * top["fx_fund"] / 1e9
        wrong = top.index[off(cap, top["cap_usd_bn"])]
        if len(wrong):
            out.append(_fail("market value in dollars", _names(wrong)))
        else:
            out.append(_pass("market value in dollars = market value x exchange rate"))

    if run_date != today.isoformat():
        out.append(_warn("screener date", f"last run {run_date}, not today ({today})"))
    else:
        out.append(_pass("screener date", run_date))

    cols = dict(
        total="total_debt_usd_bn",
        cash="cash_usd_bn",
        net="net_debt_usd_bn",
        short="short_term_debt_usd_bn",
        long="long_term_debt_usd_bn",
        ocf="ocf_usd_bn",
        capex="capex_usd_bn",
        fcf="fcf_usd_bn",
    )
    out += identities(top, "Stage 2 top", **cols)
    out += identities(s1, "Stage 1", **cols)
    out += outliers(top)
    return out


def outliers(top: pd.DataFrame) -> list[Check]:
    """Suspicious values in the screener's list: usually a data problem, worth a look."""
    found: list[str] = []
    pe = top.get("pe_now", pd.Series(dtype=float))
    for i in pe.index[pe < PE_LOW]:
        found.append(f"{i}: P/E {pe[i]:.1f} under {PE_LOW:g} (EPS not split-adjusted?)")
    for i in pe.index[pe > PE_HIGH]:
        found.append(f"{i}: P/E {pe[i]:.1f} over {PE_HIGH:g}")
    if "sec_eps" in top:
        ratio = (top["eps"] / top["sec_eps"]).where(top["sec_eps"] > 0)
        far = ratio[(ratio > EPS_SOURCE_RATIO) | (ratio < 1 / EPS_SOURCE_RATIO)]
        for i in far.index:
            found.append(f"{i}: EPS {top.loc[i, 'eps']:.2f} vs SEC {top.loc[i, 'sec_eps']:.2f}")
        neg = top.index[top["sec_eps"] <= 0]
        found += [f"{i}: SEC EPS {top.loc[i, 'sec_eps']:.2f} not positive" for i in neg]
    if "earnings_per_share_diluted_ttm" in top:
        dil = top["earnings_per_share_diluted_ttm"]
        adj = top["eps_basis"] == "adjusted"
        ratio = (top["eps"] / dil).where(adj & (dil > 0))
        for i in ratio.index[(ratio > EPS_SOURCE_RATIO) | (ratio < 1 / EPS_SOURCE_RATIO)]:
            found.append(f"{i}: adjusted EPS {top.loc[i, 'eps']:.2f} vs diluted {dil[i]:.2f}")
    if "eps_growth_median" in top:
        g = top["eps_growth_median"]
        for i in g.index[g.abs() > 1]:
            found.append(f"{i}: median yearly EPS growth {g[i]:+.0%}")
    ratio_cols = [c for c in ("net_debt_to_ebitda", "interest_cover", "pe_now") if c in top]
    for c in ratio_cols:
        vals = pd.to_numeric(top[c], errors="coerce")
        for i in vals.index[np.isinf(vals)]:
            found.append(f"{i}: {c} is infinite")
    if found:
        return [_warn("outliers in the Stage 2 top", f"{len(found)} to look at", found)]
    return [_pass("outliers in the Stage 2 top", "none")]


# --- the watch list's rows and yearly history ------------------------------------------


def check_rows(root: Path, data, symbols: list[str]) -> list[Check]:
    """The configured absolute values exist in the database's rows, and the identities hold
    for the watch list's stocks."""
    u = stocks.rows(data, symbols)
    if "error" in u and u["error"].notna().any():
        lost = u.index[u["error"].notna()]
        return [_fail("watch list in the database", f"missing: {_names(lost)}")]
    with (root / "config/absolute_values.toml").open("rb") as f:
        groups = tomllib.load(f)["group"]
    wanted = [v["column"] for g in groups for v in g["values"]]
    lacking = [c for c in wanted if c not in u.columns]
    if lacking:
        return [_fail("absolute values configured", f"missing from the rows: {lacking}")]
    out = [_pass("absolute values configured", f"{len(wanted)} columns")]
    out += identities(
        u, "watch list rows", total="total_debt", cash="cash", net="net_debt",
        short="short_term_debt", long="long_term_debt", ocf="operating_cf", capex="capex",
        fcf="free_cf",
    )  # fmt: skip
    return out


def implied_share_jumps(hist: pd.DataFrame) -> pd.DataFrame:
    """Years where market value / price moves more than SHARE_JUMP times from the year before."""
    wide = hist.pivot_table(
        index=["symbol", "fiscal_year_end"], columns="column", values="value", aggfunc="last"
    )
    if not {"market_cap", "price"} <= set(wide.columns):
        return pd.DataFrame(columns=["symbol", "fiscal_year_end", "shares_bn", "change"])
    sh = (wide["market_cap"] / wide["price"]).dropna().rename("shares_bn").reset_index()
    sh = sh.sort_values(["symbol", "fiscal_year_end"])
    sh["change"] = sh.groupby("symbol")["shares_bn"].transform(lambda s: s / s.shift(1))
    jump = (sh["change"] > SHARE_JUMP) | (sh["change"] < 1 / SHARE_JUMP)
    return sh[jump]


def check_history(data, symbols: list[str]) -> list[Check]:
    h = stocks.history(data, symbols)
    if h.empty:
        return [_warn("yearly history", "none for the watch list")]
    return history_checks(h)


def history_checks(h: pd.DataFrame) -> list[Check]:
    out = []
    dup = h.duplicated(["symbol", "fiscal_year_end", "column"])
    if dup.any():
        out.append(_fail("yearly history: one value per year", f"{dup.sum()} duplicates"))
    else:
        out.append(_pass("yearly history: one value per year", f"{h['symbol'].nunique()} stocks"))
    jumps = implied_share_jumps(h)
    if len(jumps):
        rows = [
            f"{r.symbol} {r.fiscal_year_end}: shares {r.change:.2f}x the year before"
            for r in jumps.itertuples()
        ]
        out.append(
            _warn(
                "yearly history: market value / price steady between years",
                f"{jumps['symbol'].nunique()} companies with a jump (split not applied or "
                f"shares in the wrong unit): {_names(jumps['symbol'].unique())}",
                rows,
            )
        )
    else:
        out.append(_pass("yearly history: market value / price steady between years"))
    return out


# --- dated analyses ------------------------------------------------------------------


def is_pdf(path: Path) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    with path.open("rb") as f:
        return f.read(5) == b"%PDF-"


def check_runs(folder: Path, runs: pd.DataFrame, tz: ZoneInfo) -> list[Check]:
    """One stock's recorded runs (out_watchlist_run): run times match the file names, the
    files exist, the entry price follows from the numbers."""
    name = f"{folder.name} runs"
    if runs.empty:
        return [_warn(name, "no runs yet")]
    out = []
    problems = []
    runs = runs.sort_values("run_at").reset_index(drop=True)
    for r in runs.itertuples():
        f = FILE_TIME.match(str(r.file))
        local = pd.Timestamp(r.run_at).tz_localize("UTC").tz_convert(tz)
        if not f:
            problems.append(f"unreadable file name: {r.file!r}")
            continue
        if (local.strftime("%Y-%m-%d"), local.strftime("%H"), local.strftime("%M")) != (
            f[1], f[2], f[3]
        ):  # fmt: skip
            problems.append(f"{r.file} recorded for the run at {local:%Y-%m-%d %H:%M}")
    lost = [f for f in runs["file"] if not is_pdf(folder / str(f))]
    if lost:
        problems.append(f"missing or empty PDFs: {', '.join(map(str, lost))}")
    if problems:
        out.append(_fail(name, "; ".join(problems)))
    else:
        out.append(_pass(name, f"{len(runs)} runs, latest {runs['run_at'].iloc[-1]} UTC"))
    r = runs.copy()
    for c in ("price", "eps_adj_ttm", "target_pe", "entry_price", "pe_adj", "to_entry"):
        r[c] = pd.to_numeric(r[c], errors="coerce")
    stakes = pd.to_numeric(r.get("stakes_per_share"), errors="coerce").fillna(0.0)
    entry = (r["target_pe"] * r["eps_adj_ttm"] + stakes).where(r["eps_adj_ttm"] > 0)
    pe = ((r["price"] - stakes) / r["eps_adj_ttm"]).where(r["eps_adj_ttm"] > 0)
    to_entry = entry / r["price"] - 1
    wrong = (
        off(entry, r["entry_price"], 1e-3)
        | off(pe, r["pe_adj"], 1e-3)
        | off(to_entry, r["to_entry"], 1e-3)
    )
    if wrong.any():
        out.append(
            _fail(
                f"{folder.name}: entry price = target P/E x adjusted EPS",
                f"runs {list(r.loc[wrong, 'run_at'])}",
            )
        )
    unlisted = sorted({p.name for p in folder.glob("*.pdf")} - set(runs["file"].astype(str)))
    if unlisted:
        out.append(_warn(f"{folder.name}: PDFs not recorded", ", ".join(unlisted)))
    return out


def newest_pdf(folder: Path) -> Path | None:
    pdfs = sorted(p for p in folder.glob("*.pdf") if FILE_TIME.match(p.name))
    return pdfs[-1] if pdfs else None


def check_analyses(root: Path, today: date, runs: pd.DataFrame, symbols: list[str]) -> list[Check]:
    analyses = root / "analyses"
    if not analyses.exists():
        return [_fail("analyses", "folder not found")]
    out = []
    tz = ZoneInfo(watchlist.TIMEZONE)
    no_notes = [s for s in symbols if not (analyses / s / "notes.md").exists()]
    have = set(runs["symbol"]) if len(runs) else set()
    no_runs = [s for s in symbols if s not in have]
    if no_notes:
        out.append(_fail("watch list notes.md", f"missing for {', '.join(no_notes)}"))
    else:
        out.append(_pass("watch list notes.md", ", ".join(symbols)))
    if no_runs:
        out.append(_warn("watch list runs", f"no runs yet for {', '.join(no_runs)}"))
    for sym in sorted(have):
        out += check_runs(analyses / sym, runs[runs["symbol"] == sym], tz)
    stamps = {}
    for folder in [analyses / s for s in symbols] + [analyses / "market", analyses / "summaries"]:
        pdf = newest_pdf(folder) if folder.exists() else None
        if pdf is None:
            out.append(_warn(f"{folder.name}: newest PDF", "none"))
            continue
        if not is_pdf(pdf):
            out.append(_fail(f"{folder.name}: newest PDF", f"{pdf.name} empty or not a PDF"))
            continue
        stamps[folder.name] = pdf.name[:15]
    if stamps:
        latest = max(stamps.values())
        behind = [k for k, v in stamps.items() if v != latest]
        if behind:
            out.append(_warn("newest PDFs from the same run", f"older than {latest}: {behind}"))
        else:
            out.append(_pass("newest PDFs from the same run", f"{latest}, {len(stamps)} folders"))
        # runs are stamped in the watch list's time zone (Italy), the screener in UTC
        local = datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
        if latest[:10] not in (today.isoformat(), local):
            out.append(_warn("newest run date", f"{latest[:10]}, not today ({today})"))
    return out


def check_notes(root: Path, today: date, symbols: list[str]) -> list[Check]:
    """Claude's notes are current, sourced and free of past events (notes_check)."""
    run, out = today, []
    for s in [*symbols, "market", "summaries"]:
        path = root / "analyses" / s / "notes.md"
        if not path.exists():
            continue  # check_analyses reports a missing notes.md
        found = notes_check.problems(notes_check.kind_of(s), path.read_text("utf-8"), run)
        name = f"{s}/notes.md: current and sourced"
        detail = f"{len(found)} problems: " + "; ".join(found[:3]) if found else ""
        out.append(_fail(name, detail, found) if found else _pass(name))
    return out


def check_last_run(root: Path) -> list[Check]:
    path = root / ".cache/watchlist/last_run.json"
    name = "last_run.json"
    if not path.exists():
        return [_warn(name, "not found (written by analysis/watchlist.py; not committed)")]
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [_fail(name, f"does not parse: {e}")]
    problems = []
    if not run.get("subject"):
        problems.append("no subject")
    if not run.get("html") or not (root / run["html"]).is_file():
        problems.append(f"email body {run.get('html')!r} not found")
    files = run.get("files") or []
    if not files:
        problems.append("no files")
    lost = [f for f in files if not is_pdf(root / f)]
    if lost:
        problems.append(f"missing or empty: {', '.join(lost)}")
    if problems:
        return [_fail(name, "; ".join(problems))]
    return [_pass(name, f"{len(files)} PDFs")]


# --- report --------------------------------------------------------------------------


def run_checks(root: Path = ROOT, today: date | None = None, data=None) -> list[Check]:
    today = today or date.today()
    data = data or stocks.default_data()
    symbols = data.watchlist()["symbol"].tolist()
    checks: list[Check] = []
    for part in (
        lambda: check_screener(root, today, data),
        lambda: check_rows(root, data, symbols),
        lambda: check_history(data, symbols),
        lambda: check_analyses(root, today, data.watchlist_runs(), symbols),
        lambda: check_notes(root, today, symbols),
        lambda: check_last_run(root),
    ):
        try:
            checks += part()
        except Exception as e:  # noqa: BLE001 - a crash in one part is a FAIL, not a stop
            checks.append(_fail("validate.py", f"{type(e).__name__}: {e}"))
    return checks


def overall(checks: list[Check]) -> str:
    levels = {c.level for c in checks}
    return "FAIL" if "FAIL" in levels else "WARN" if "WARN" in levels else "PASS"


def report(checks: list[Check], verbose: bool = False) -> str:
    lines = ["Pipeline check: the run's outputs in the database and on disk", ""]
    for c in checks:
        lines.append(f"{c.level:<5} {c.name}" + (f": {c.detail}" if c.detail else ""))
        if verbose and c.rows:
            lines += [f"        {r}" for r in c.rows]
    n = {lvl: sum(c.level == lvl for c in checks) for lvl in ("PASS", "WARN", "FAIL")}
    lines += [
        "",
        f"Result: {overall(checks)} ({n['PASS']} pass, {n['WARN']} warn, {n['FAIL']} fail)",
    ]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verbose", action="store_true", help="list every row behind a WARN")
    ap.add_argument("--strict", action="store_true", help="exit non-zero on WARN too")
    ap.add_argument("--today", help="date the outputs should be from (default: today)")
    args = ap.parse_args()
    # the run's date in Italy, as the PDFs are stamped: a midnight run is already the next day
    italy = datetime.now(ZoneInfo("Europe/Rome")).date()
    today = date.fromisoformat(args.today) if args.today else italy
    checks = run_checks(ROOT, today)
    print(report(checks, args.verbose))
    result = overall(checks)
    sys.exit(1 if result == "FAIL" or (args.strict and result == "WARN") else 0)


if __name__ == "__main__":
    main()
