"""Build dashboard/absolute.html: absolute values across the utilities sector.

Reads the value list from config/absolute_values.toml, latest values from
data/sector/utilities.csv and yearly history from data/sector/history.csv.

Usage: uv run python dashboard/build_absolute.py
"""

from __future__ import annotations

import json
import math
import tomllib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
FIRST_PANEL_YEAR, LAST_PANEL_YEAR = 2018, 2025


def clean(v):
    if isinstance(v, float) and not math.isfinite(v):
        return None
    return v


def main() -> None:
    groups = tomllib.loads((ROOT / "config/absolute_values.toml").read_text())["group"]
    values = [
        v | {"group": g["name"], "history": v.get("history", v["column"])}
        for g in groups
        for v in g["values"]
    ]
    latest = pd.read_csv(ROOT / "data/sector/utilities.csv", index_col=0)
    latest["data_flag"] = latest["data_flag"].fillna("")
    hist = pd.read_csv(ROOT / "data/sector/history.csv")
    hist["year"] = hist["fiscal_year_end"].str[:4].astype(int)
    hist = hist[hist["year"] <= LAST_PANEL_YEAR]

    # {symbol: {history_column: {year: value}}}
    history: dict = {}
    for (sym, col), g in hist.groupby(["symbol", "column"]):
        history.setdefault(sym, {})[col] = {
            str(y): round(float(v), 4) for y, v in zip(g["year"], g["value"], strict=True)
        }

    # Sector totals over time for a constant panel: companies reporting every year
    years = list(range(FIRST_PANEL_YEAR, LAST_PANEL_YEAR + 1))
    usd_filers = set(latest.index[latest["data_flag"] == ""])
    totals: dict = {"all": {}, "usd": {}}
    for v in values:
        col = v["history"]
        if not col or v["unit"] != "$bn":
            continue
        wide = hist[hist["column"] == col].pivot_table(
            index="symbol", columns="year", values="value", aggfunc="last"
        )
        panel = wide.reindex(columns=years).dropna()
        for scope, p in (("all", panel), ("usd", panel[panel.index.isin(usd_filers)])):
            totals[scope][col] = {
                "companies": len(p),
                "sum": {str(y): round(float(p[y].sum()), 3) for y in years},
                "median": {str(y): round(float(p[y].median()), 4) for y in years},
            }

    cols = ["name", "industry", "country", "currency", "data_flag"] + [v["column"] for v in values]
    rows = [
        {"symbol": s, **{k: clean(r[k]) for k in cols}}
        for s, r in latest[cols].sort_values("market_cap", ascending=False).iterrows()
    ]
    meta = json.loads((ROOT / "data/sector/_meta.json").read_text())
    data = {
        "asOf": meta["fetched_at"][:10],
        "values": values,
        "rows": rows,
        "history": history,
        "totals": totals,
        "panelYears": [str(y) for y in years],
    }
    html = (
        (ROOT / "dashboard/absolute_template.html")
        .read_text()
        .replace("/*__DATA__*/null", json.dumps(data, separators=(",", ":"), default=clean))
    )
    (ROOT / "dashboard/absolute.html").write_text(html)
    print(f"wrote dashboard/absolute.html ({len(html) / 1024:.0f} KB, {len(rows)} companies)")


if __name__ == "__main__":
    main()
