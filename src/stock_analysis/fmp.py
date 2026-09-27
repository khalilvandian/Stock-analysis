"""Minimal client for the Financial Modeling Prep (FMP) API."""

from __future__ import annotations

import os
from typing import Any

import httpx
from dotenv import load_dotenv

BASE_URL = "https://financialmodelingprep.com/stable"


class FMPClient:
    """Thin wrapper around FMP's `stable` endpoints.

    The API key is read from the ``FMP_API_KEY`` environment variable (or a local
    ``.env`` file) unless passed explicitly.
    """

    def __init__(self, api_key: str | None = None, *, timeout: float = 10.0) -> None:
        load_dotenv()
        self.api_key = api_key or os.environ.get("FMP_API_KEY")
        if not self.api_key:
            raise RuntimeError("FMP_API_KEY is not set")
        self._http = httpx.Client(base_url=BASE_URL, timeout=timeout)

    def get(self, endpoint: str, **params: Any) -> Any:
        """GET an endpoint (e.g. ``"quote"``) and return the decoded JSON."""
        response = self._http.get(endpoint, params={**params, "apikey": self.api_key})
        response.raise_for_status()
        return response.json()

    def quote(self, symbol: str) -> dict[str, Any]:
        """Latest quote for a single symbol."""
        data = self.get("quote", symbol=symbol)
        if not data:
            raise ValueError(f"No quote returned for {symbol!r}")
        return data[0]

    def historical_prices(self, symbol: str, **params: Any) -> list[dict[str, Any]]:
        """End-of-day price history. Accepts optional ``from``/``to`` dates."""
        return self.get("historical-price-eod/full", symbol=symbol, **params)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FMPClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
