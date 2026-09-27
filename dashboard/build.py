"""Build dashboard/index.html from the saved data and dashboard/template.html.

Usage: uv run python dashboard/build.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "analysis"))

import compare  # noqa: E402
import debt  # noqa: E402
import debt_to_ebitda  # noqa: E402
import valuation  # noqa: E402

PEERS = ["CEG", "VST", "NRG", "TLN", "NEE", "DUK", "SO"]
BN = 1e9


def clean(obj):
    """Replace NaN/inf with None so the result is valid JSON."""
    if isinstance(obj, dict):
        return {k: clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [clean(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if hasattr(obj, "item"):
        return clean(obj.item())
    return obj


def weekly_prices() -> dict:
    closes = {s: debt.load(s, "prices_daily")["Adj Close"] for s in PEERS}
    df = pd.DataFrame(closes)
    df.index = pd.to_datetime(df.index)
    df = df[df.index >= df["CEG"].first_valid_index()].resample("W-FRI").last().dropna(how="all")
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
        "series": {s: [None if pd.isna(v) else round(v, 2) for v in df[s]] for s in PEERS},
    }


def ceg_debt() -> dict:
    annual = debt.leverage("CEG", "annual")
    quarterly = debt.leverage("CEG", "quarterly")
    rows = []
    for d, r in annual.iterrows():
        rows.append({"label": f"FY{d.year}", **r.to_dict()})
    for d, r in quarterly[quarterly.index > annual.index.max()].iterrows():
        rows.append({"label": f"Q{(d.month - 1) // 3 + 1} {d.year}", **r.to_dict()})
    for r in rows:
        for k in list(r):
            if k != "label" and abs(r[k] or 0) > 1e6:
                r[k] = r[k] / BN
    return {"rows": rows}


def ceg_income() -> list:
    inc = debt.load("CEG", "income_annual")
    out = []
    for d, r in inc.iterrows():
        if pd.isna(r.get("Total Revenue")):
            continue
        out.append(
            {
                "year": d.year,
                "revenue": r["Total Revenue"] / BN,
                "ebitda": r["EBITDA"] / BN,
                "net_income": r["Net Income"] / BN,
                "eps": r["Diluted EPS"],
            }
        )
    return out


def main() -> None:
    lev_hist = {s: debt_to_ebitda.ratios(s)["net_debt/ebitda"].to_dict() for s in PEERS}
    info = json.loads((ROOT / "data/CEG/info.json").read_text())
    data = {
        "asOf": json.loads((ROOT / "data/CEG/_meta.json").read_text())["fetched_at"][:10],
        "prices": weekly_prices(),
        "compare": {s: compare.metrics(s) for s in PEERS},
        "valuation": {s: valuation.snapshot(s) for s in PEERS},
        "leverageHistory": lev_hist,
        "cegDebt": ceg_debt(),
        "cegIncome": ceg_income(),
        "cegInfo": {
            k: info.get(k)
            for k in ["longName", "sector", "industry", "fullTimeEmployees", "longBusinessSummary"]
        },
    }
    payload = json.dumps(clean(data), separators=(",", ":"))
    template = (ROOT / "dashboard/template.html").read_text()
    out = template.replace("/*__DATA__*/null", payload)
    (ROOT / "dashboard/index.html").write_text(out)
    print(f"wrote dashboard/index.html ({len(out) / 1024:.0f} KB)")


if __name__ == "__main__":
    import os

    os.chdir(ROOT)
    main()
