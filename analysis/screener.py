"""Market screener: both stages in a row.

Stage 1 (analysis/stage1.py) keeps the companies with good financial statements, judged by
their kind of business and Peter Lynch's category. Stage 2 (analysis/stage2.py) ranks only
those by how cheap they are and lists the top 3 per sector. Each stage also runs on its
own; they share nothing but Stage 1's output file.

Writes data/screener/stage1.csv, data/screener/top.csv and data/screener/YYYY-MM-DD.csv
(every company with both stages' columns).

Usage:
    uv run python analysis/screener.py               # both stages, a few minutes
    uv run python analysis/screener.py --no-adjusted # skip the adjusted-EPS refinement
    uv run python analysis/screener.py --refresh     # ignore today's cached downloads
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stage1  # noqa: E402
import stage2  # noqa: E402
from screen_common import OUT, ROOT, load_config  # noqa: E402


def run(adjusted: bool = True, refresh: bool = False) -> tuple[pd.DataFrame, pd.DataFrame, Path]:
    """Run and save both stages. Returns (every company, the top per sector, dated CSV).

    The evening run (analysis/watchlist.py) calls this before the market report, which
    lists the top per sector from data/screener/top.csv.
    """
    cfg = load_config()
    d = stage1.run(cfg, refresh=refresh)
    stage1.save(d)
    d, top = stage2.run(stage2.load_stage1(), cfg, adjusted=adjusted)
    stage2.save(top)
    path = OUT / f"{date.today().isoformat()}.csv"
    d[[c for c in d.columns if not c.endswith("_fy_h")]].round(4).to_csv(path)
    return d, top, path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-adjusted", action="store_true", help="skip Yahoo adjusted EPS")
    ap.add_argument("--refresh", action="store_true", help="download again, ignore today's cache")
    args = ap.parse_args()
    d, top, path = run(adjusted=not args.no_adjusted, refresh=args.refresh)

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
    print(f"\nSaved {path.relative_to(ROOT)}, data/screener/stage1.csv and top.csv")


if __name__ == "__main__":
    main()
