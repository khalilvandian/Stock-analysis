"""The watch list: config/watchlist.toml is the master copy (edited by hand and by the evening
run), mirrored into the database's user layer (user_watchlist, user_watchlist_peer,
user_eps_override), which the ingest job reads to fetch the watch list's stocks and peers.

    from stock_analysis.watchlist import load, sync
    cfg = load()
    sync(data, cfg)        # data = stock_analysis.data.Data.open()
"""

from __future__ import annotations

import math
import tomllib
from pathlib import Path

from .db import ROOT

CONFIG = ROOT / "config" / "watchlist.toml"


def load(path: Path = CONFIG) -> dict:
    with Path(path).open("rb") as f:
        cfg = tomllib.load(f)
    cfg.setdefault("timezone", "Europe/Rome")
    for s in cfg["stock"]:
        s["symbol"] = s["symbol"].upper()
        s["peers"] = [p.upper() for p in s.get("peers", [])]
        s.setdefault("eps_override", [])
        s.setdefault("stakes_per_share", 0.0)
    return cfg


def stocks_for_db(cfg: dict) -> list[dict]:
    """The config's stocks in the shape Data.set_watchlist takes."""
    return [
        {
            "symbol": s["symbol"],
            "target_pe": s.get("target_pe"),
            "target_note": s.get("target_note"),
            "stakes_per_share": s.get("stakes_per_share") or None,
            "peers": s["peers"],
            "eps_override": [
                {"reported": str(o["reported"]), "eps": o["eps"], "reason": o.get("reason")}
                for o in s["eps_override"]
            ],
        }
        for s in cfg["stock"]
    ]


def symbols(cfg: dict) -> list[str]:
    """Every stock on the list and every peer."""
    return sorted({x for s in cfg["stock"] for x in [s["symbol"], *s["peers"]]})


def number(v) -> float:
    """A float, with a blank (None or NaN from the database) as 0."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(x) else x


def text(v) -> str:
    return v if isinstance(v, str) else ""


def sync(data, cfg: dict | None = None) -> bool:
    """Mirror the config into the user tables when they differ; True if anything changed."""
    cfg = cfg or load()
    want = stocks_for_db(cfg)
    have = data.watchlist()
    peers = data.sql("SELECT symbol, peer, position FROM user_watchlist_peer")
    overrides = data.sql("SELECT symbol, reported, eps, reason FROM user_eps_override")

    def norm_stocks(rows):
        return sorted(
            (r["symbol"], number(r["target_pe"]), text(r.get("target_note")),
             number(r.get("stakes_per_share")))
            for r in rows
        )  # fmt: skip

    same = (
        norm_stocks(want) == norm_stocks(have.to_dict("records"))
        and [s["symbol"] for s in want] == list(have.sort_values("position")["symbol"])
        and sorted((s["symbol"], p, i) for s in want for i, p in enumerate(s["peers"], 1))
        == sorted(peers.itertuples(index=False, name=None))
        and sorted(
            (s["symbol"], o["reported"], round(float(o["eps"]), 6), text(o.get("reason")))
            for s in want
            for o in s["eps_override"]
        )
        == sorted(
            (r.symbol, str(r.reported)[:10], round(float(r.eps), 6), text(r.reason))
            for r in overrides.itertuples()
        )
    )
    if same:
        return False
    data.set_watchlist(want)
    return True
