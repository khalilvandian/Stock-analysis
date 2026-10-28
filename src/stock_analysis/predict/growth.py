"""Growth labels: how steadily did the investment, and the business, compound after the date?

Babak (2026-10-28): the final goal is long-term, predictable growth. These labels are
continuous and describe the 5 years after the decision date in two ways.

Price (total return, dividends reinvested), from a straight-line fit of log value on time:
  trend_growth      annual growth rate of the fitted line (exp(slope) - 1)
  trend_r2          how closely the value followed that line (1 = a perfectly steady climb)
  k_ratio           slope / its standard error (Kestner's K-ratio): growth per unit of
                    wobble around the trend; high only when growth is both fast and steady
  steady_growth     trend_growth x trend_r2: growth counted only to the extent it was steady
  excess_trend      trend_growth minus the S&P 500's trend_growth over the same days
  win_12m           share of rolling 12-month periods with a positive return
  worst_12m         worst rolling 12-month return (the bad year you had to sit through)
  underwater        share of days spent more than 10% below the previous peak

Business (SEC annual reports filed up to today, the fiscal years after the date):
  eps_cagr_fwd      EPS growth per year over the next 5 fiscal years
  revenue_cagr_fwd  revenue growth per year over the next 5 fiscal years
  eps_r2_fwd        steadiness of EPS growth (R2 of log EPS on time, positive EPS only)
  eps_down_years    years out of 5 in which EPS fell
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from stock_analysis.predict.features import fundamentals
from stock_analysis.predict.labels import drawdowns, window_ok
from stock_analysis.predict.prices import Prices
from stock_analysis.predict.sec import Facts

PRICE = [
    "trend_growth",
    "trend_r2",
    "k_ratio",
    "steady_growth",
    "excess_trend",
    "win_12m",
    "worst_12m",
    "underwater",
]
BUSINESS = ["eps_cagr_fwd", "revenue_cagr_fwd", "eps_r2_fwd", "eps_down_years"]
ALL = PRICE + BUSINESS


def log_trend(values: pd.Series) -> tuple[float, float, float]:
    """Slope per year, R2 and t-statistic of a straight-line fit of log(values) on time."""
    y = np.log(values.to_numpy(dtype=float))
    t = (values.index - values.index[0]).days.to_numpy() / 365.25
    if len(y) < 3 or np.ptp(t) == 0:
        return np.nan, np.nan, np.nan
    slope, intercept = np.polyfit(t, y, 1)
    resid = y - (slope * t + intercept)
    ss_res = float((resid**2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    se = math.sqrt(ss_res / (len(y) - 2) / ((t - t.mean()) ** 2).sum()) if ss_res > 0 else np.nan
    return float(slope), r2, float(slope / se) if se and se > 0 else np.nan


def price_growth(p: Prices, spy: Prices, asof, years: int) -> dict:
    out = dict.fromkeys(PRICE, np.nan)
    start = pd.Timestamp(asof)
    end = start + pd.DateOffset(years=years)
    if not p.ok:
        return out
    s0, b0 = p.on(start), spy.on(start)
    s = p.window(start + pd.Timedelta(days=1), end)
    b = spy.window(start + pd.Timedelta(days=1), end)
    if s0 is None or b0 is None or not window_ok(s, start, end, years):
        return out
    s = pd.concat([pd.Series([s0], index=[start]), s])
    b = pd.concat([pd.Series([b0], index=[start]), b])
    m = s.resample("ME").last()
    slope, r2, _ = log_trend(s)
    _, _, t_monthly = log_trend(m)  # monthly points: daily ones are too autocorrelated
    bslope, _, _ = log_trend(b)
    growth = math.exp(slope) - 1
    roll = (m / m.shift(12) - 1).dropna()
    out.update(
        trend_growth=growth,
        trend_r2=r2,
        k_ratio=t_monthly / math.sqrt(len(m)) if np.isfinite(t_monthly) else np.nan,
        steady_growth=growth * max(r2, 0.0),
        excess_trend=growth - (math.exp(bslope) - 1),
        win_12m=float((roll > 0).mean()) if len(roll) else np.nan,
        worst_12m=float(roll.min()) if len(roll) else np.nan,
        underwater=float((drawdowns(s) < -0.10).mean()),
    )
    return out


def business_growth(facts: Facts, splits: pd.Series, asof, years: int, today) -> dict:
    """Growth of the business in the fiscal years after `asof`, from today's filings."""
    out = dict.fromkeys(BUSINESS, np.nan)
    f = fundamentals(facts, today, splits)
    if f is None:
        return out
    asof = pd.Timestamp(asof)
    eps, rev = f["eps"].dropna(), f["revenue"].dropna()
    # FY0 = the last fiscal year whose 10-K was normally out by the decision date
    base_end = asof - pd.Timedelta(days=60)

    def window(s: pd.Series) -> pd.Series | None:
        before = s[s.index <= base_end]
        if before.empty:
            return None
        w = s[s.index >= before.index[-1]].iloc[: years + 1]
        return w if len(w) == years + 1 else None

    e = window(eps)
    if e is not None:
        if e.iloc[0] > 0 and e.iloc[-1] > 0:
            out["eps_cagr_fwd"] = (e.iloc[-1] / e.iloc[0]) ** (1 / years) - 1
        if (e > 0).all():
            out["eps_r2_fwd"] = log_trend(e)[1]
        out["eps_down_years"] = float((e.diff().dropna() < 0).sum())
    r = window(rev)
    if r is not None and r.iloc[0] > 0 and r.iloc[-1] > 0:
        out["revenue_cagr_fwd"] = (r.iloc[-1] / r.iloc[0]) ** (1 / years) - 1
    return out
