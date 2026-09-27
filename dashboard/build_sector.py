"""Build dashboard/sector.html from data/sector/utilities.csv.

Usage: uv run python analysis/sector.py && uv run python dashboard/build_sector.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MEDIAN_COLS = [
    "net_debt_to_ebitda",
    "ebitda_to_interest",
    "revenue_cagr_3y",
    "eps_cagr_3y",
    "fcf_yield",
    "net_margin",
    "pe_ttm",
    "ev_to_ebitda",
    "dividend_yield",
    "vs_52w_high",
    "analyst_upside",
    "price_vs_fair_value",
]


def clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def main() -> None:
    df = pd.read_csv(ROOT / "data/sector/utilities.csv", index_col=0)
    df.loc[df["ebitda"] <= 0, ["net_debt_to_ebitda", "ev_to_ebitda"]] = float("nan")
    df["data_flag"] = df["data_flag"].fillna("")
    meta = json.loads((ROOT / "data/sector/_meta.json").read_text())

    def summarise(g: pd.DataFrame) -> dict:
        out = {c: clean(float(g[c].median())) for c in MEDIAN_COLS}
        out.update(
            count=len(g),
            market_cap=float(g["market_cap"].sum()),
            profitable=float((g["net_income"] > 0).mean()),
            negative_fcf=float((g["free_cf"] < 0).mean()),
        )
        return out

    groups = {k: summarise(g) for k, g in df.groupby("industry")}
    groups["All utilities"] = summarise(df)
    rows = [
        {"symbol": s, **{k: clean(v) for k, v in r.items()}}
        for s, r in df.sort_values("market_cap", ascending=False).iterrows()
    ]
    data = {"asOf": meta["fetched_at"][:10], "rows": rows, "groups": groups}
    template = (ROOT / "dashboard/sector_template.html").read_text()
    html = template.replace(
        "/*__DATA__*/null", json.dumps(data, separators=(",", ":"), default=clean)
    )
    (ROOT / "dashboard/sector.html").write_text(html)
    print(f"wrote dashboard/sector.html ({len(html) / 1024:.0f} KB, {len(rows)} companies)")


if __name__ == "__main__":
    main()
