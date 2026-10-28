"""Candidate "goodness" labels: what happened to an investment made on the decision date.

All labels use total return (dividends reinvested) over the `years` after the date and
compare with the S&P 500 (SPY, also total return) over exactly the same days. A label is
only computed when the full window is in the data; stocks that were delisted during the
window have no Yahoo prices at all (see docs/PREDICT.md, survivorship).

Continuous labels (higher is better):
  cagr               annual total return
  excess_cagr        cagr minus the S&P 500's cagr
  rel_wealth         end value relative to the same money in the S&P 500, minus 1
  sharpe             (return - T-bill) / volatility, from monthly returns
  sortino            (return - T-bill) / downside deviation (only falls count as risk)
  calmar             cagr / worst peak-to-trough fall
  martin             (cagr - T-bill) / ulcer index (depth and length of all drawdowns)
  info_ratio         excess return over the index / tracking error
Risk measures (lower is better): vol, downside_dev, max_dd, ulcer, dd_vs_index.
Binary labels: beat_index, good (beat the index AND max_dd <= index max_dd + margin).
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from stock_analysis.predict.prices import Prices

CONTINUOUS = [
    "cagr",
    "excess_cagr",
    "rel_wealth",
    "sharpe",
    "sortino",
    "calmar",
    "martin",
    "info_ratio",
]
RISK = ["vol", "downside_dev", "max_dd", "ulcer", "dd_vs_index"]
BINARY = ["beat_index", "good"]
ALL = CONTINUOUS + RISK + BINARY


def drawdowns(p: pd.Series) -> pd.Series:
    """Fall from the running peak on each day (0 at a new high, -0.3 = 30% below the peak)."""
    return p / p.cummax() - 1


def window_ok(s: pd.Series, start: pd.Timestamp, end: pd.Timestamp, years: int) -> bool:
    if s.empty:
        return False
    return (
        (s.index[0] - start).days <= 7
        and (end - s.index[-1]).days <= 7
        and len(s) >= 0.9 * 252 * years
    )


def compute(
    p: Prices, spy: Prices, rf: pd.Series, asof, years: int, dd_margin: float = 0.15
) -> dict:
    """Labels for an investment on `asof` held `years` years. `rf` = T-bill yield in %."""
    out = dict.fromkeys(ALL, np.nan)
    start = pd.Timestamp(asof)
    end = start + pd.DateOffset(years=years)
    if not p.ok:
        return out
    s0 = p.on(start)
    b0 = spy.on(start)
    s = p.window(start + pd.Timedelta(days=1), end)
    b = spy.window(start + pd.Timedelta(days=1), end)
    if s0 is None or b0 is None or not window_ok(s, start, end, years):
        return out
    s = pd.concat([pd.Series([s0], index=[start]), s])
    b = pd.concat([pd.Series([b0], index=[start]), b])

    tr = s.iloc[-1] / s.iloc[0]
    btr = b.iloc[-1] / b.iloc[0]
    cagr = tr ** (1 / years) - 1
    bcagr = btr ** (1 / years) - 1
    rf_ann = float(rf.loc[start:end].mean() / 100) if len(rf.loc[start:end]) else 0.0

    m = s.resample("ME").last()
    bm = b.resample("ME").last()
    r = m.pct_change().dropna()
    br = bm.pct_change().dropna()
    rf_m = (1 + rf_ann) ** (1 / 12) - 1
    ex = r - rf_m
    vol = float(r.std() * math.sqrt(12))
    downside = float(math.sqrt((np.minimum(ex, 0) ** 2).mean()) * math.sqrt(12))
    active = (r - br).dropna()
    te = float(active.std() * math.sqrt(12))

    dd = drawdowns(s)
    max_dd = float(-dd.min())
    index_dd = float(-drawdowns(b).min())
    ulcer = float(math.sqrt((dd**2).mean()))

    out.update(
        cagr=cagr,
        excess_cagr=cagr - bcagr,
        rel_wealth=tr / btr - 1,
        sharpe=float(ex.mean() * 12 / vol) if vol > 0 else np.nan,
        sortino=float(ex.mean() * 12 / downside) if downside > 0 else np.nan,
        calmar=cagr / max_dd if max_dd > 0 else np.nan,
        martin=(cagr - rf_ann) / ulcer if ulcer > 0 else np.nan,
        info_ratio=float(active.mean() * 12 / te) if te > 0 else np.nan,
        vol=vol,
        downside_dev=downside,
        max_dd=max_dd,
        ulcer=ulcer,
        dd_vs_index=max_dd - index_dd,
        beat_index=float(cagr > bcagr),
        good=float(cagr > bcagr and max_dd <= index_dd + dd_margin),
    )
    return out
