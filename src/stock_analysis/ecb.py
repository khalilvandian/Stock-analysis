"""Exchange rates from the European Central Bank (free, no key)."""

from __future__ import annotations

import io

import httpx
import pandas as pd

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A"


def usd_per_unit(client: httpx.Client | None = None) -> dict[str, float]:
    """US dollars per one unit of each currency, at the ECB's latest reference rates.

    Includes EUR, USD and GBX (pence, a hundredth of a pound).
    """
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        r = client.get(URL, params={"lastNObservations": 1, "format": "csvdata"})
        r.raise_for_status()
    finally:
        if own:
            client.close()
    d = pd.read_csv(io.StringIO(r.text))
    per_eur = d.groupby("CURRENCY")["OBS_VALUE"].last().astype(float)  # units per euro
    per_eur["EUR"] = 1.0
    usd = per_eur["USD"]
    rates = {c: usd / v for c, v in per_eur.items()}
    rates["GBX"] = rates["GBP"] / 100
    return rates
