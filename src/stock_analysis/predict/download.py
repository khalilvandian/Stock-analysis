"""Download (and cache) SEC company facts, SEC profiles and Yahoo prices for the universe."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx
import pandas as pd

from stock_analysis.predict import ROOT, load_config, sec, universe
from stock_analysis.predict.prices import fetch_chart


def resolve_universe(cfg: dict | None = None) -> pd.DataFrame:
    cfg = cfg or load_config()
    m = universe.load_membership(ROOT / cfg["universe"]["membership"])
    changes = pd.read_csv(ROOT / cfg["universe"]["changes"])
    overrides = pd.read_csv(ROOT / "data/predict/universe_overrides.csv")
    tickers = sorted(
        set().union(*[universe.members_on(m, d) for d in universe.decision_dates(cfg)])
    )
    with httpx.Client(timeout=60) as client:

        def first(cik):
            data = sec.fetch_facts(cik, client)
            return sec.Facts(data).first_annual_filed() if data else None

        out = universe.resolve(
            m, changes, tickers, client, first_annual_filed=first, overrides=overrides
        )
    out.to_csv(ROOT / cfg["universe"]["resolved"], index=False)
    return out


def download_all(uni: pd.DataFrame, cfg: dict | None = None) -> None:
    cfg = cfg or load_config()
    ciks = sorted({int(c) for c in uni.cik.dropna()})
    symbols = sorted({s for s in uni.yahoo.dropna()})
    symbols += [cfg["labels"]["benchmark"], cfg["labels"]["risk_free"]]
    with httpx.Client(timeout=60) as client:
        # SEC allows 10 requests per second: keep it sequential with a short pause
        for c in ciks:
            sec.fetch_facts(c, client)
            sec.fetch_profile(c, client)
        with ThreadPoolExecutor(2) as ex:
            list(ex.map(lambda s: fetch_chart(s, client), symbols))
