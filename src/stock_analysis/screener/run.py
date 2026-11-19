"""Market screener: both stages in a row, saved in the database.

Stage 1 (analysis/stage1.py) keeps the companies with good financial statements, judged by
their kind of business and Peter Lynch's category. Stage 2 (analysis/stage2.py) ranks only
those by how cheap they are and lists the top 3 per sector. Both read only the database
(the ingest job's TradingView snapshot, prices, earnings dates and core values).

The run is saved as one row of out_screener_run (one per day; a second run the same day
replaces it) and its results in out_screener_result: stage 1 for every company screened,
stage 2 for the top per sector, the main columns in their own fields and every other one
in detail_json. The market report, the site's Screener page and the email read it there.

Usage (the nightly analyses run it after the ingest, stock_analysis.nightly):
    uv run python -m stock_analysis.screener               # both stages, saved
    uv run python -m stock_analysis.screener --no-adjusted # skip the adjusted-EPS refinement
    uv run python -m stock_analysis.screener --dry-run     # print only, save nothing
"""

from __future__ import annotations

import argparse
import json
from datetime import date

import numpy as np
import pandas as pd

from .. import stocks
from . import stage1, stage2
from .common import load_config

MAIN = ["sector", "category", "status", "rank_in_sector", "close", "cheap_price"]
SOURCE = "stock_analysis.screener"


def plain(v):
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not np.isfinite(v):
        return None
    if isinstance(v, list | tuple | dict):
        return None
    return None if v is pd.NA or v is pd.NaT else v


def result_rows(d: pd.DataFrame, stage: int) -> list[dict]:
    """The rows of out_screener_result for one stage (the yearly history lists left out)."""
    keep = [c for c in d.columns if not c.endswith("_fy_h") and c != "indexes"]
    out = []
    for tv_symbol, r in d[keep].iterrows():
        detail = {k: plain(v) for k, v in r.items() if k not in MAIN and k != "symbol"}
        detail["tv_symbol"] = tv_symbol
        rank = r.get("rank_in_sector")
        out.append(
            {
                "stage": stage,
                "symbol": r.get("symbol") or str(tv_symbol).split(":")[-1],
                **{c: plain(r.get(c)) for c in MAIN if c != "rank_in_sector"},
                "rank_in_sector": int(rank) if pd.notna(rank) else None,
                "detail_json": json.dumps(detail, default=str),
            }
        )
    seen, unique = set(), []
    for row in out:
        if row["symbol"] not in seen:
            seen.add(row["symbol"])
            unique.append(row)
    return unique


def run(adjusted: bool = True, data=None, save: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run both stages and (unless save is False) record the run. Returns (every company,
    the top per sector).

    The nightly analyses (stock_analysis.nightly) call this before the market numbers, which
    list the top per sector from the database.
    """
    data = data or stocks.default_data()
    cfg = load_config()
    s1 = stage1.run(cfg, data)
    d, top = stage2.run(s1, cfg, adjusted=adjusted, data=data)
    if save:
        rows = result_rows(d, 1) + result_rows(top, 2)
        data.save_screener_run(date.today().isoformat(), cfg["universe"]["index"], SOURCE, rows)
    return d, top


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-adjusted", action="store_true", help="skip Yahoo adjusted EPS")
    ap.add_argument("--dry-run", action="store_true", help="print only, save nothing")
    args = ap.parse_args()
    d, top = run(adjusted=not args.no_adjusted, save=not args.dry_run)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print("Stage 1: good financial statements, by Lynch category")
    print(stage1.counts(d, "category").to_string())
    print()
    print(stage1.counts(d, "sector").to_string())
    print("\nStage 2: cheapest Stage 1 survivors per sector")
    for (region, sector), g in top.groupby(["region", "sector"]):
        print(f"{region} / {sector}")
        print(g[stage2.SHOW].round(2).to_string(header=False))
    if not args.dry_run:
        print(f"\nSaved the run of {date.today().isoformat()} in the database")


if __name__ == "__main__":
    main()
