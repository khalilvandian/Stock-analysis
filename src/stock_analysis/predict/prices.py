"""Daily prices from Yahoo Finance's chart API, cached under .cache/predict/yahoo/.

`adjclose` includes reinvested dividends and splits (total return); `close` is adjusted for
splits only. `actual_price()` undoes the later splits to get the price that was really
quoted on a day, which is what must be multiplied by the share count SEC reported then.

Yahoo only keeps stocks that still trade. Delisted companies (most acquisitions and
bankruptcies) have no history, which is the main source of survivorship bias here; see
docs/PREDICT.md.
"""

from __future__ import annotations

import gzip
import json
import time

import httpx
import numpy as np
import pandas as pd

from stock_analysis.predict import CACHE

UA = {"User-Agent": "Mozilla/5.0"}
START = 1072915200  # 2004-01-01


def fetch_chart(symbol: str, client: httpx.Client, refresh: bool = False) -> dict | None:
    path = CACHE / "yahoo" / f"{symbol}.json.gz"
    if path.exists() and not refresh:
        return json.loads(gzip.decompress(path.read_bytes()))
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {
        "interval": "1d",
        "period1": START,
        "period2": int(time.time()),
        "events": "div|split",
        "includeAdjustedClose": "true",
    }
    for attempt in range(4):
        r = client.get(url, params=params, headers=UA)
        if r.status_code == 200:
            res = r.json()["chart"]["result"]
            data = res[0] if res else None
            break
        if r.status_code == 404:
            data = None
            break
        time.sleep(2 + 3 * attempt)
    else:
        return None
    out = {"symbol": symbol, "ok": False}
    if data and data.get("timestamp"):
        q = data["indicators"]["quote"][0]
        adj = data["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
        ev = data.get("events", {})
        out = {
            "symbol": symbol,
            "ok": True,
            "name": data["meta"].get("longName") or data["meta"].get("shortName"),
            "currency": data["meta"].get("currency"),
            "t": data["timestamp"],
            "close": q["close"],
            "adjclose": adj,
            "splits": [
                [s["date"], s["numerator"], s["denominator"]] for s in ev.get("splits", {}).values()
            ],
            "dividends": [[d["date"], d["amount"]] for d in ev.get("dividends", {}).values()],
        }
    path.write_bytes(gzip.compress(json.dumps(out).encode()))
    return out


def _dated(stamps: list, values: list) -> pd.Series:
    idx = pd.DatetimeIndex(pd.to_datetime(stamps, unit="s")).normalize()
    s = pd.Series(values, index=idx, dtype=float).sort_index()
    return s.groupby(level=0).prod() if s.index.has_duplicates else s


class Prices:
    def __init__(self, chart: dict):
        self.ok = bool(chart and chart.get("ok"))
        if not self.ok:
            self.df = pd.DataFrame(columns=["close", "adjclose"])
            self.splits = _dated([], [])
            self.dividends = _dated([], [])
            return
        idx = pd.to_datetime(chart["t"], unit="s").normalize()
        df = pd.DataFrame({"close": chart["close"], "adjclose": chart["adjclose"]}, index=idx)
        df = df[~df.index.duplicated(keep="last")].dropna()
        self.df = df[df.close > 0]
        sp = [x for x in chart.get("splits") or [] if x[2]]
        self.splits = _dated([d for d, _, _ in sp], [n / m for _, n, m in sp])
        dv = chart.get("dividends") or []
        self.dividends = _dated([d for d, _ in dv], [a for _, a in dv])

    @property
    def first_date(self):
        return self.df.index[0] if self.ok and len(self.df) else None

    def on(self, day, col: str = "adjclose", max_gap_days: int = 7) -> float | None:
        """Last value on or before `day`, if it is no older than `max_gap_days`."""
        s = self.df[col].loc[: pd.Timestamp(day)]
        if s.empty or (pd.Timestamp(day) - s.index[-1]).days > max_gap_days:
            return None
        return float(s.iloc[-1])

    def actual_price(self, day) -> float | None:
        """Price as quoted on `day` (Yahoo's close is adjusted for later splits)."""
        c = self.on(day, "close")
        if c is None:
            return None
        later = self.splits[self.splits.index > pd.Timestamp(day)]
        return c * float(np.prod(later.values)) if len(later) else c

    def dividends_ttm(self, day) -> float:
        """Split-adjusted dividends per share paid in the 12 months to `day`."""
        d = pd.Timestamp(day)
        return float(self.dividends.loc[d - pd.DateOffset(years=1) : d].sum())

    def window(self, start, end, col: str = "adjclose") -> pd.Series:
        return self.df[col].loc[pd.Timestamp(start) : pd.Timestamp(end)]
