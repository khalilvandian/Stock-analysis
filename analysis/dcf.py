"""Discounted cash flow comparison: CEG vs power-producer peers and utilities.

Power producers (IPPs) are valued on free cash flow to equity using each
company's own "free cash flow before growth" (FCFbG) guidance: operating cash
flow after interest, maintenance capex and nuclear fuel, but before growth
projects. Regulated utilities have negative free cash flow by design (grid
capex funded by new debt and equity), so they are valued on dividends instead.

Cash flows are discounted at the cost of equity (CAPM with Blume-adjusted
beta). Each company gets bear / base / bull growth for five years, a
five-year linear fade, then a terminal growth rate. A reverse DCF solves for
the five-year growth rate the current share price implies.

Usage: uv run python analysis/dcf.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

RISK_FREE = 0.0518  # US 10-year Treasury yield, 2026-09-25 (^TNX)
EQUITY_PREMIUM = 0.05
TERMINAL_GROWTH = 0.025
SCENARIOS = {"bear": 0.0, "base": 0.04, "bull": 0.08}
UTILITY_SCENARIOS = {"bear": 0.04, "base": 0.06, "bull": 0.075}


@dataclass
class Company:
    symbol: str
    kind: str  # "ipp" (FCFE) or "utility" (dividends)
    base: float  # $bn cash to equity in year 1, or dividend per share for utilities
    source: str
    guided: list[float] = field(default_factory=list)  # extra guided years ($bn) after year 1


COMPANIES = [
    Company(
        "CEG", "ipp", 4.2, "FCFbG $8.4bn across 2026-27; $11.5-13bn across 2028-29", [6.1, 6.1]
    ),
    Company("VST", "ipp", 4.325, "2026 adjusted FCFbG guidance $3.925-4.725bn"),
    Company("NRG", "ipp", 3.05, "2026 FCFbG guidance $2.8-3.3bn (incl. LS Power assets)"),
    Company(
        "TLN", "ipp", 1.275, "2026 adjusted FCF guidance $1.2-1.35bn (raised, incl. Cornerstone)"
    ),
    Company("NEE", "utility", np.nan, "current dividend per share"),
    Company("DUK", "utility", np.nan, "current dividend per share"),
    Company("SO", "utility", np.nan, "current dividend per share"),
]


def info(symbol: str) -> dict:
    return json.loads((Path("data") / symbol / "info.json").read_text())


def cost_of_equity(beta: float) -> float:
    adjusted = 0.67 * beta + 0.33
    return RISK_FREE + adjusted * EQUITY_PREMIUM


def cash_flows(c: Company, base: float, g1: float, years: int = 10) -> list[float]:
    """Explicit cash flows: guided years, then g1 for five years, then a linear fade to terminal."""
    flows = [base, *c.guided]
    while len(flows) < years:
        i = len(flows) - len(c.guided) - 1  # years since guidance ended
        g = g1 if i < 5 else g1 + (TERMINAL_GROWTH - g1) * (i - 4) / 5
        flows.append(flows[-1] * (1 + g))
    return flows


def present_value(flows: list[float], ke: float, tg: float = TERMINAL_GROWTH) -> float:
    pv = sum(cf / (1 + ke) ** (t + 1) for t, cf in enumerate(flows))
    terminal = flows[-1] * (1 + tg) / (ke - tg)
    return pv + terminal / (1 + ke) ** len(flows)


def per_share(c: Company, g1: float, ke: float, tg: float = TERMINAL_GROWTH) -> float:
    i = info(c.symbol)
    if c.kind == "utility":
        return present_value(cash_flows(c, dividend(c), g1), ke, tg)
    return present_value(cash_flows(c, c.base, g1), ke, tg) * 1e9 / i["sharesOutstanding"]


def dividend(c: Company) -> float:
    i = info(c.symbol)
    return i.get("dividendRate") or i["currentPrice"] * i["dividendYield"] / 100


def implied_growth(c: Company, price: float, ke: float) -> float:
    lo, hi = -0.30, 0.60
    for _ in range(80):
        mid = (lo + hi) / 2
        if per_share(c, mid, ke) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def table() -> pd.DataFrame:
    rows = {}
    for c in COMPANIES:
        i = info(c.symbol)
        price, beta = i["currentPrice"], i["beta"]
        ke = cost_of_equity(beta)
        scen = UTILITY_SCENARIOS if c.kind == "utility" else SCENARIOS
        values = {k: per_share(c, g, ke) for k, g in scen.items()}
        base_cf = dividend(c) * i["sharesOutstanding"] / 1e9 if c.kind == "utility" else c.base
        rows[c.symbol] = {
            "method": "dividends" if c.kind == "utility" else "FCFE (FCFbG)",
            "price": price,
            "cost_of_equity": ke,
            "cash_to_equity_$bn": base_cf,
            "cash_yield": base_cf * 1e9 / i["marketCap"],
            "value_bear": values["bear"],
            "value_base": values["base"],
            "value_bull": values["bull"],
            "base_vs_price": values["base"] / price - 1,
            "implied_growth": implied_growth(c, price, ke),
            "base_growth": scen["base"],
        }
    return pd.DataFrame(rows)


def sensitivity(symbol: str = "CEG") -> pd.DataFrame:
    c = next(x for x in COMPANIES if x.symbol == symbol)
    kes = [0.09, 0.095, 0.10, 0.105, 0.11, 0.115, 0.12]
    tgs = [0.015, 0.02, 0.025, 0.03, 0.035]
    grid = {f"{tg:.1%}": [per_share(c, SCENARIOS["base"], ke, tg) for ke in kes] for tg in tgs}
    return pd.DataFrame(grid, index=[f"{ke:.1%}" for ke in kes])


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    t = table()
    pct = ["cost_of_equity", "cash_yield", "base_vs_price", "implied_growth", "base_growth"]
    shown = t.copy().astype(object)
    for r in t.index:
        for col in t.columns:
            v = t.loc[r, col]
            if isinstance(v, str):
                continue
            shown.loc[r, col] = f"{v:.1%}" if r in pct else f"{v:,.2f}"
    print(shown.to_string())
    print("\nCEG value per share, base growth: cost of equity (rows) x terminal growth (cols)\n")
    print(sensitivity().round(0).to_string())
    for c in COMPANIES:
        print(f"{c.symbol}: {c.source}")
