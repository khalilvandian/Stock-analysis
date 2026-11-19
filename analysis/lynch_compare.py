"""Compare Stage 1's Lynch categories with the proposed rules of report 16.

Reads Stage 1's full output (.cache/screener/stage1_full.pkl, written by
`analysis/stage1.py`), classifies every company again with the proposed rules and prints
how many companies move between categories, the biggest companies that move, and how many
growth names sit close to a cut-off. Stage 1 itself is not changed.

Proposed rules (report 16, section 3):
  - growth = average of the 3-, 4- and 5-year compound EPS growth rates (Validea's reading
    of Lynch), falling back to today's median yearly growth when a start year is a loss
  - stalwart from 10% (was 8%), fast grower from 20%, and a fast grower's revenue must also
    grow at least 10% a year over 5 years (otherwise stalwart)
  - cyclical by history: EPS fell more than 30% in a year when revenue also fell more than
    5%, in 2 or more of the last 10 years, whatever the growth rate
  - asset play: price below book only counts with debt/equity at most 1; the net-cash test
    is not used for the Finance sector (deposits and client cash are not spare cash)

Usage: uv run python analysis/lynch_compare.py [--csv PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen_common import STAGE1_FULL, load_config  # noqa: E402
from stage1 import apply_screeners  # noqa: E402

PROPOSED = {
    "stalwart_growth": 0.10,
    "fast_growth": 0.20,
    "fast_revenue_growth": 0.10,
    "cyclical_joint_drops": 2,
    "cyclical_eps_drop": 0.30,
    "cyclical_revenue_drop": 0.05,
    "asset_max_debt_to_equity": 1.0,
    "borderline": 0.02,
}


def _newest(values, n: int) -> list:
    return list(values[:n]) if isinstance(values, list | tuple) else []


def cagr(values, n: int) -> float:
    """Compound yearly growth from n fiscal years ago to the latest (both must be > 0)."""
    v = _newest(values, n + 1)
    if len(v) <= n or v[0] is None or v[n] is None or v[0] <= 0 or v[n] <= 0:
        return np.nan
    return (v[0] / v[n]) ** (1 / n) - 1


def growth_345(values) -> float:
    """Average of the 3-, 4- and 5-year compound growth rates; blank unless all three exist."""
    rates = [cagr(values, n) for n in (3, 4, 5)]
    return float(np.mean(rates)) if not any(np.isnan(rates)) else np.nan


def joint_drops(eps, revenue, p: dict, n: int = 11) -> int:
    """Years in the last 10 when EPS and revenue both fell (EPS by more than 30%)."""
    e, r = _newest(eps, n), _newest(revenue, n)
    count = 0
    for i in range(min(len(e), len(r)) - 1):
        en, eo, rn, ro = e[i], e[i + 1], r[i], r[i + 1]
        if None in (en, eo, rn, ro) or eo <= 0 or ro <= 0:
            continue
        if en / eo - 1 < -p["cyclical_eps_drop"] and rn / ro - 1 < -p["cyclical_revenue_drop"]:
            count += 1
    return count


def band(g: pd.Series, stalwart: float, fast: float) -> np.ndarray:
    return np.select([g >= fast, g >= stalwart, g.notna()], ["fast", "stalwart", "slow"], "")


def proposed_category(d: pd.DataFrame, lynch: dict, p: dict = PROPOSED) -> pd.DataFrame:
    """The proposed category, the growth number it used and a borderline flag."""
    eps_h, rev_h = d["earnings_per_share_diluted_fy_h"], d["total_revenue_fy_h"]
    out = pd.DataFrame(index=d.index)
    out["eps_growth_345"] = eps_h.map(growth_345)
    out["revenue_cagr_5y"] = rev_h.map(lambda v: cagr(v, 5))
    out["joint_drops_10y"] = [joint_drops(e, r, p) for e, r in zip(eps_h, rev_h, strict=False)]
    g = out["eps_growth_345"].fillna(d["eps_growth_median"])
    out["growth_used"] = g
    asset = (
        (d["price_book_fq"] > 0)
        & (d["price_book_fq"] < lynch["asset_price_to_book"])
        & ~(d["debt_to_equity"] > p["asset_max_debt_to_equity"])
    ) | ((d["net_cash_to_cap"] > lynch["asset_net_cash"]) & (d["sector"] != "Finance"))
    conditions = [
        d["no_profit_5y"] == True,  # noqa: E712
        d["industry"].isin(lynch["cyclical_industries"]),
        (d["loss_now"] == True) | (d["eps_vs_5y_peak"] < -lynch["turnaround_drop"]),  # noqa: E712
        out["joint_drops_10y"] >= p["cyclical_joint_drops"],
        asset,
        (g >= p["fast_growth"]) & ~(out["revenue_cagr_5y"] < p["fast_revenue_growth"]),
        g >= p["stalwart_growth"],
        g.notna(),
    ]
    names = ["no_profit", "cyclical", "turnaround", "cyclical", "asset_play", "fast_grower"]
    names += ["stalwart", "slow_grower"]
    out["proposed"] = np.select(conditions, names, default="")
    growth = out["proposed"].isin(["fast_grower", "stalwart", "slow_grower"])
    near = ((g - p["stalwart_growth"]).abs() < p["borderline"]) | (
        (g - p["fast_growth"]).abs() < p["borderline"]
    )
    disagree = band(d["eps_growth_median"], p["stalwart_growth"], p["fast_growth"]) != band(
        out["eps_growth_345"], p["stalwart_growth"], p["fast_growth"]
    )
    out["borderline"] = growth & (near | (disagree & out["eps_growth_345"].notna()))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="write every company's current and proposed category here")
    args = ap.parse_args()
    cfg = load_config()
    lynch = cfg["lynch"]
    d = pd.read_pickle(STAGE1_FULL)
    d = d.join(proposed_category(d, lynch))
    # Stage 1's rules again, with each company judged by its proposed category
    rerun = apply_screeners(d.assign(category=d["proposed"]).copy(), cfg)
    d["status_proposed"] = rerun["status"]
    d["current"] = d["category"].replace("", "(blank)")
    d["proposed"] = d["proposed"].replace("", "(blank)")
    d["cap_usd_bn"] = (d["market_cap_basic"] * d["fx_price"] / 1e9).round(1)
    pd.set_option("display.width", 200)
    print(f"{len(d)} companies; {(d['current'] != d['proposed']).sum()} change category\n")
    print(pd.crosstab(d["current"], d["proposed"], margins=True).to_string(), "\n")
    growth = d["proposed"].isin(["fast_grower", "stalwart", "slow_grower"])
    print(pd.crosstab(d["status"], d["status_proposed"], margins=True).to_string(), "\n")
    print(f"Borderline growth names: {d.loc[growth, 'borderline'].sum()} of {growth.sum()}\n")
    cols = [
        "name", "industry", "cap_usd_bn", "current", "proposed", "eps_growth_median",
        "eps_growth_345", "revenue_cagr_5y", "joint_drops_10y", "eps_big_drops_10y", "status",
        "status_proposed",
    ]  # fmt: skip
    moved = d[d["current"] != d["proposed"]].sort_values("cap_usd_bn", ascending=False)
    print(moved[cols].head(40).round(3).to_string(index=False))
    if args.csv:
        d[cols + ["borderline"]].round(4).to_csv(args.csv, index=False)
        print(f"\nSaved {args.csv}")


if __name__ == "__main__":
    main()
