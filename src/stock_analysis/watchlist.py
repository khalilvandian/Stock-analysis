"""The watch list, kept in the database (user_watchlist, user_watchlist_peer,
user_eps_override). It is changed through the application's operations (issue #60,
docs/APPLICATION.md), which check and record every change:

    python -m claude app watchlist-set SYMBOL --reason "..." --target-pe 20

    from stock_analysis.watchlist import load
    stocks = load(data)        # data = stock_analysis.data.Data.open()
"""

from __future__ import annotations

import math

TIMEZONE = "Europe/Rome"  # the dated file names and the labels of the runs


def number(v) -> float:
    """A float, with a blank (None or NaN from the database) as 0."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(x) else x


def text(v) -> str:
    return v if isinstance(v, str) else ""


def load(data) -> list[dict]:
    """The stocks in list order: symbol, peers, target_pe, target_note, stakes_per_share and
    eps_override [{reported, eps, reason}]."""
    w = data.watchlist()
    peers = data.sql("SELECT symbol, peer, position FROM user_watchlist_peer ORDER BY position")
    over = data.sql("SELECT symbol, reported, eps, reason FROM user_eps_override")
    out = []
    for r in w.sort_values("position").itertuples():
        out.append(
            {
                "symbol": r.symbol,
                "peers": peers.loc[peers["symbol"] == r.symbol, "peer"].tolist(),
                "target_pe": number(r.target_pe),
                "target_note": text(r.target_note),
                "stakes_per_share": number(r.stakes_per_share),
                "eps_override": [
                    {
                        "reported": str(o.reported)[:10],
                        "eps": float(o.eps),
                        "reason": text(o.reason),
                    }
                    for o in over[over["symbol"] == r.symbol].itertuples()
                ],
            }
        )
    return out
