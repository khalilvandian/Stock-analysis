"""Enterprise DCF: unlevered free cash flow (FCFF) discounted at WACC.

Enterprise value = PV of FCFF + terminal value. Equity value = enterprise
value - net debt. Per-share value = equity value / shares outstanding.

Starting FCFF:
- Power producers: guided free cash flow before growth (after interest) plus
  after-tax interest, which removes the effect of debt.
- Regulated utilities: after-tax operating profit (NOPAT = EBIT x (1 - tax))
  for the last 12 months, less the reinvestment growth requires:
  FCFF = NOPAT x (1 - growth / ROIC), with ROIC = NOPAT / (debt + book equity).
  Their reported FCF is negative because growth capex exceeds cash flow.

WACC = E/(D+E) x cost of equity + D/(D+E) x cost of debt x (1 - tax), using
market value of equity, book value of debt, CAPM cost of equity with
Blume-adjusted beta, and a cost of debt of the risk-free rate plus a spread
for each company's credit rating.

Usage: uv run python analysis/dcf_firm.py (from the repo root)
"""

from __future__ import annotations

import pandas as pd
from compare import metrics
from dcf import (
    COMPANIES,
    RISK_FREE,
    TERMINAL_GROWTH,
    Company,
    cash_flows,
    cost_of_equity,
    info,
    present_value,
)
from debt import load

TAX = 0.21
# Spread over Treasuries by credit rating (approximate, investment grade to BB-)
DEBT_SPREAD = {
    "CEG": 0.013,  # Baa1 / BBB+
    "VST": 0.018,  # BBB- area
    "NRG": 0.025,  # BB+ area
    "TLN": 0.035,  # BB- area
    "NEE": 0.012,
    "DUK": 0.012,
    "SO": 0.013,
}
SCENARIOS = {
    "ipp": {"bear": 0.0, "base": 0.04, "bull": 0.08},
    "utility": {"bear": 0.02, "base": 0.04, "bull": 0.06},
}


def inputs(c: Company) -> dict:
    m, i = metrics(c.symbol), info(c.symbol)
    debt, net_debt = m["total_debt"], m["net_debt"]
    ebitda = net_debt / m["net_debt/ebitda"]  # TTM EBITDA, $bn
    interest = ebitda / m["ebitda/interest"]
    equity = i["marketCap"] / 1e9
    ke = cost_of_equity(i["beta"])
    kd = RISK_FREE + DEBT_SPREAD[c.symbol]
    wacc = equity / (equity + debt) * ke + debt / (equity + debt) * kd * (1 - TAX)
    if c.kind == "ipp":
        after_tax_interest = interest * (1 - TAX)
        base = c.base + after_tax_interest
        guided = [g + after_tax_interest for g in c.guided]
    else:
        inc = load(c.symbol, "income_quarterly").sort_index()
        ebit = inc["EBIT"].dropna().iloc[-4:].sum() / 1e9
        base, guided = ebit * (1 - TAX), []
        bs = load(c.symbol, "balance_sheet_quarterly").dropna(subset=["Total Debt"]).iloc[-1]
        roic = base * 1e9 / (bs["Total Debt"] + bs["Stockholders Equity"])
    return {
        "equity": equity,
        "debt": debt,
        "net_debt": net_debt,
        "ebitda": ebitda,
        "ke": ke,
        "kd": kd,
        "wacc": wacc,
        "base": base,
        "guided": guided,
        "shares": i["sharesOutstanding"],
        "price": i["currentPrice"],
        "roic": roic if c.kind == "utility" else None,
    }


def value(c: Company, g1: float, wacc: float | None = None, tg: float = TERMINAL_GROWTH) -> dict:
    x = inputs(c)
    w = wacc if wacc is not None else x["wacc"]
    firm = Company(c.symbol, "ipp", x["base"], c.source, x["guided"])
    flows = cash_flows(firm, x["base"], g1)
    if x["roic"] is None:
        ev = present_value(flows, w, tg)
    else:
        # flows are NOPAT; subtract the reinvestment each year's growth needs
        prev = [x["base"] / (1 + g1), *flows[:-1]]
        fcff = [n * (1 - (n / p - 1) / x["roic"]) for n, p in zip(flows, prev, strict=True)]
        terminal = flows[-1] * (1 + tg) * (1 - tg / x["roic"]) / (w - tg)
        ev = sum(f / (1 + w) ** (t + 1) for t, f in enumerate(fcff)) + terminal / (1 + w) ** len(
            fcff
        )
    equity = ev - x["net_debt"]
    return {"ev": ev, "equity": equity, "per_share": equity * 1e9 / x["shares"]}


def implied_growth(c: Company) -> float:
    price = inputs(c)["price"]
    lo, hi = -0.30, 0.60
    for _ in range(80):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if value(c, mid)["per_share"] < price else (lo, mid)
    return (lo + hi) / 2


def table() -> pd.DataFrame:
    rows = {}
    for c in (c for c in COMPANIES if c.kind == "ipp"):
        x = inputs(c)
        scen = SCENARIOS[c.kind]
        v = {k: value(c, g) for k, g in scen.items()}
        rows[c.symbol] = {
            "price": x["price"],
            "fcff_start_$bn": x["base"],
            "cost_of_equity": x["ke"],
            "cost_of_debt_after_tax": x["kd"] * (1 - TAX),
            "debt_weight": x["debt"] / (x["debt"] + x["equity"]),
            "wacc": x["wacc"],
            "ev_base_$bn": v["base"]["ev"],
            "net_debt_$bn": x["net_debt"],
            "equity_base_$bn": v["base"]["equity"],
            "value_bear": v["bear"]["per_share"],
            "value_base": v["base"]["per_share"],
            "value_bull": v["bull"]["per_share"],
            "price_vs_base": x["price"] / v["base"]["per_share"] - 1,
            "implied_growth": implied_growth(c),
            "implied_ev/ebitda": v["base"]["ev"] / x["ebitda"],
        }
    return pd.DataFrame(rows)


def utility_check() -> pd.DataFrame:
    """Why the enterprise DCF fails for utilities: ROIC vs WACC and no-growth value."""
    rows = {}
    for c in (c for c in COMPANIES if c.kind == "utility"):
        x = inputs(c)
        no_growth_equity = x["base"] / x["wacc"] - x["net_debt"]
        rows[c.symbol] = {
            "price": x["price"],
            "nopat_$bn": x["base"],
            "roic": x["roic"],
            "wacc": x["wacc"],
            "no_growth_value": no_growth_equity * 1e9 / x["shares"],
        }
    return pd.DataFrame(rows)


def sensitivity(symbol: str = "CEG") -> pd.DataFrame:
    c = next(x for x in COMPANIES if x.symbol == symbol)
    waccs = [0.075, 0.08, 0.085, 0.09, 0.095, 0.10]
    tgs = [0.015, 0.02, 0.025, 0.03, 0.035]
    return pd.DataFrame(
        {f"{tg:.1%}": [value(c, 0.04, w, tg)["per_share"] for w in waccs] for tg in tgs},
        index=[f"{w:.1%}" for w in waccs],
    )


if __name__ == "__main__":
    pd.set_option("display.width", 220)
    t = table()
    pct = {
        "cost_of_equity",
        "cost_of_debt_after_tax",
        "debt_weight",
        "wacc",
        "price_vs_base",
        "implied_growth",
    }
    out = t.copy().astype(object)
    for r in t.index:
        out.loc[r] = [f"{v:.1%}" if r in pct else f"{v:,.2f}" for v in t.loc[r]]
    print(out.to_string())
    u = utility_check()
    print("\nUtilities: enterprise DCF not meaningful (ROIC below WACC)\n")
    print(u.to_string(float_format=lambda v: f"{v:,.3f}"))
    print("\nCEG value per share, base growth: WACC (rows) x terminal growth (cols)\n")
    print(sensitivity().round(0).to_string())
