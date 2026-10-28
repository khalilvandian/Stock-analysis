"""Build the panel: one row per (decision date, S&P 500 member) with features and labels.

Rows are kept even when no label can be computed (delisted stocks), so the survivorship
gap can be measured. `usable` marks the rows the models can use.
"""

from __future__ import annotations

import gzip
import json
from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pandas as pd

from stock_analysis.predict import CACHE, ROOT, features, labels, load_config, universe
from stock_analysis.predict.prices import Prices
from stock_analysis.predict.sec import Facts


def _load_facts(cik) -> Facts | None:
    if pd.isna(cik):
        return None
    path = CACHE / "sec" / f"CIK{int(cik):010d}.json.gz"
    return Facts(json.loads(gzip.decompress(path.read_bytes()))) if path.exists() else None


def _load_prices(symbol) -> Prices:
    if not isinstance(symbol, str):
        return Prices({})
    path = CACHE / "yahoo" / f"{symbol}.json.gz"
    return Prices(json.loads(gzip.decompress(path.read_bytes())) if path.exists() else {})


def _profile(cik) -> dict:
    if pd.isna(cik):
        return {}
    path = CACHE / "sec_profile" / f"CIK{int(cik):010d}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def build(cfg: dict | None = None, workers: int = 4) -> pd.DataFrame:
    cfg = cfg or load_config()
    m = universe.load_membership(ROOT / cfg["universe"]["membership"])
    uni = pd.read_csv(ROOT / cfg["universe"]["resolved"]).set_index("ticker")
    spy = _load_prices(cfg["labels"]["benchmark"])
    rf = _load_prices(cfg["labels"]["risk_free"]).df["close"]
    horizons = {"y5": cfg["labels"]["horizon_years"], "y1": cfg["labels"]["short_horizon_years"]}
    dd_margin = cfg["labels"]["dd_margin"]
    min_cap = (cfg["features"]["min_market_cap"], cfg["features"]["max_market_cap"])

    jobs = [(d, universe.members_on(m, d)) for d in universe.decision_dates(cfg)]
    ctx = (uni, spy, rf, horizons, dd_margin, min_cap)
    with ProcessPoolExecutor(workers) as ex:
        parts = list(ex.map(_cohort_rows, jobs, [ctx] * len(jobs)))
    panel = pd.DataFrame([r for part in parts for r in part])
    panel["usable"] = panel.has_fundamentals & panel.has_prices & panel.cap_ok
    return add_cross_sectional(panel)


def _cohort_rows(job, ctx) -> list[dict]:
    d, tickers = job
    uni, spy, rf, horizons, dd_margin, min_cap = ctx
    facts_cache: dict = {}
    price_cache: dict = {}
    rows = []
    for t in tickers:
        u = uni.loc[t] if t in uni.index else None
        cik = u["cik"] if u is not None else np.nan
        sym = u["yahoo"] if u is not None else None
        if cik not in facts_cache:
            facts_cache[cik] = _load_facts(cik)
        if sym not in price_cache:
            price_cache[sym] = _load_prices(sym)
        fa, p = facts_cache[cik], price_cache[sym]
        prof = _profile(cik)
        row = {
            "date": d.date(),
            "cohort": d.year,
            "ticker": t,
            "yahoo": sym,
            "cik": cik,
            "name": prof.get("name") or (u["name"] if u is not None else None),
            "sic": prof.get("sic"),
            "sector": features.sector_from_sic(prof.get("sic")),
            "resolve_method": u["method"] if u is not None else "unresolved",
            "left_index": u["left_index"] if u is not None else None,
            "exit_reason": u["exit_reason"] if u is not None else None,
        }
        # prices must start well before the date, or the symbol belongs to a newer
        # company (ticker reuse) or the stock is a recent spin-off
        has_prices = p.ok and p.first_date is not None and p.first_date <= d - pd.Timedelta(days=30)
        p_use = p if has_prices else Prices({})
        feats = (
            features.compute(fa, p_use, spy, d)
            if fa is not None
            else {
                **dict.fromkeys(features.FUNDAMENTAL + features.PRICE, np.nan),
                "lynch_category": "unknown",
            }
        )
        row.update(feats)
        row["has_fundamentals"] = fa is not None and np.isfinite(
            feats.get("years_of_history", np.nan)
        )
        row["has_prices"] = has_prices
        cap = feats["market_cap"]
        row["cap_ok"] = bool(np.isfinite(cap) and min_cap[0] <= cap <= min_cap[1])
        for key, years in horizons.items():
            lab = (
                labels.compute(p_use, spy, rf, d, years, dd_margin)
                if has_prices
                else dict.fromkeys(labels.ALL, np.nan)
            )
            row.update({f"{key}_{k}": v for k, v in lab.items()})
        rows.append(row)
    return rows


def add_cross_sectional(panel: pd.DataFrame) -> pd.DataFrame:
    """Labels relative to the cohort: percentile ranks, sector-relative return, quintiles."""
    out = panel.copy()
    for key in ("y5", "y1"):
        lab = out[f"{key}_cagr"].where(out.usable)
        g = out.assign(_lab=lab).groupby("cohort")
        for name in labels.CONTINUOUS:
            col = f"{key}_{name}"
            out[f"{col}_pct"] = out[col].where(out.usable).groupby(out.cohort).rank(pct=True)
        sector_med = out.assign(_lab=lab).groupby(["cohort", "sector"])["_lab"].transform("median")
        out[f"{key}_excess_vs_sector"] = lab - sector_med
        out[f"{key}_top_quintile"] = (
            (out[f"{key}_sortino_pct"] > 0.8).astype(float).where(out[f"{key}_sortino_pct"].notna())
        )
        del g

    # own-history valuation: earnings yield now versus its median at earlier decision dates
    out = out.sort_values(["cik", "date"])
    hist = out.groupby("cik")["earnings_yield"].transform(
        lambda s: s.shift(1).expanding(min_periods=3).median()
    )
    out["ey_vs_own_median"] = out["earnings_yield"] - hist
    return out.sort_values(["date", "ticker"]).reset_index(drop=True)
