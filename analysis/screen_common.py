"""Paths, settings and US-dollar columns shared by Stage 1 and Stage 2 of the screener."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config/screeners.toml"
OUT = ROOT / "data/screener"
CACHE = ROOT / ".cache/screener"
# Stage 1's full output (with the yearly history lists), read by Stage 2
STAGE1_FULL = CACHE / "stage1_full.pkl"

# Absolute values shown first, in US dollars (billions) or per share in the trading currency
ABSOLUTE = {
    "close": "Price",
    "cap_usd_bn": "Market value ($bn)",
    "total_debt_usd_bn": "Total debt ($bn)",
    "net_debt_usd_bn": "Net debt ($bn)",
    "short_term_debt_usd_bn": "Short-term debt ($bn)",
    "long_term_debt_usd_bn": "Long-term debt ($bn)",
    "cash_usd_bn": "Cash ($bn)",
    "revenue_usd_bn": "Revenue 12m ($bn)",
    "ebitda_usd_bn": "EBITDA 12m ($bn)",
    "net_income_usd_bn": "Net income 12m ($bn)",
    "eps": "EPS 12m",
    "ocf_usd_bn": "Operating cash flow ($bn)",
    "capex_usd_bn": "Capex ($bn)",
    "fcf_usd_bn": "Free cash flow ($bn)",
}
USD_FIELDS = {
    "market_cap_basic": "cap_usd_bn",
    "total_debt_fq": "total_debt_usd_bn",
    "net_debt_fq": "net_debt_usd_bn",
    "short_term_debt_fq": "short_term_debt_usd_bn",
    "long_term_debt_fq": "long_term_debt_usd_bn",
    "cash_n_short_term_invest_fq": "cash_usd_bn",
    "total_revenue_ttm": "revenue_usd_bn",
    "ebitda_ttm": "ebitda_usd_bn",
    "net_income_ttm": "net_income_usd_bn",
    "cash_f_operating_activities_ttm": "ocf_usd_bn",
    "capital_expenditures_ttm": "capex_usd_bn",
    "free_cash_flow_ttm": "fcf_usd_bn",
}


def load_config(path: Path = CONFIG) -> dict:
    with path.open("rb") as f:
        return tomllib.load(f)


def to_usd(d: pd.DataFrame) -> None:
    """(Re)compute the US-dollar billions columns from the statement-currency figures."""
    for src, dst in USD_FIELDS.items():
        d[dst] = d[src] * d["fx_fund"] / 1e9
