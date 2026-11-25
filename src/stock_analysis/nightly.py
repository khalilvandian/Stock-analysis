"""The nightly analyses (issue #33): everything the evening run used to compute, done on the
server right after the ingest's build and stored in the database, so the scheduled Claude
session only reads it, writes its interpretation and renders the PDFs.

    python -m stock_analysis.db nightly [--target server-writer]   # by hand
    (the ingest job runs it after the build: `nightly = true` in config/ingest.toml)

1. The market screener (Stage 1 then Stage 2) -> out_screener_run, out_screener_result.
2. Per watch-list stock (the database's watch list, user_*): its row, yearly history,
   prices, adjusted EPS by quarter, next report, the peers' rows and the key numbers
   -> out_stock_numbers (one row per stock and day, the inputs as JSON).
3. The market report's numbers: indices, sectors, breadth and the screener's top per sector
   -> out_market_numbers.

The same functions compute a stock or the market on the fly when a stored result is missing
or older than the last build (analysis/watchlist.py, analysis/market.py).
"""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from . import stocks
from . import watchlist as wl
from .db import ROOT

MARKET_CONFIG = ROOT / "config" / "market.toml"
SCREENER_CONFIG = ROOT / "config" / "screeners.toml"
YEARS = 10


def now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def plain(v):
    """A value the database (and the web API's JSON) takes: no NaN or numpy types."""
    if v is None:
        return None
    if isinstance(v, np.generic):
        v = v.item()
    if isinstance(v, float) and not np.isfinite(v):
        return None
    return v


# --- adjusted EPS and P/E history ----------------------------------------------------


def quarterly_eps(dates: pd.DataFrame, overrides: list[dict] | None = None) -> pd.Series:
    """Reported (adjusted) EPS by report date, one value per quarter, oldest first.

    `dates` is in yfinance's get_earnings_dates() shape (stocks.earnings_dates). Duplicate
    rows for the same report are dropped; overrides replace the EPS of the quarter reported
    on that date.
    """
    s = dates["Reported EPS"].dropna()
    s.index = pd.to_datetime(s.index, utc=True).tz_convert(None).normalize()
    s = s[~s.index.duplicated(keep="first")].sort_index()
    # two reports within 30 days are the same quarter (a re-dated entry); keep the later one
    keep = ~(pd.Series(s.index, index=s.index).diff(-1).abs() < pd.Timedelta(days=30))
    s = s[keep.values]
    for o in overrides or []:
        day = pd.Timestamp(o["reported"]).normalize()
        if day in s.index:
            s[day] = float(o["eps"])
    return s.astype(float)


def trailing_eps(q: pd.Series) -> pd.Series:
    """Sum of the last four quarters at each report date (only when the four are consecutive)."""
    ttm = q.rolling(4).sum()
    span = pd.Series(q.index, index=q.index).diff(3)
    return ttm[span <= pd.Timedelta(days=400)].dropna()


def daily_pe(prices: pd.Series, ttm: pd.Series) -> pd.Series:
    """Price divided by the trailing adjusted EPS known on each day; blank when EPS <= 0."""
    eps = ttm.reindex(prices.index.union(ttm.index)).ffill().reindex(prices.index)
    return (prices / eps.where(eps > 0)).dropna()


def yearly_pe(prices: pd.Series, ttm: pd.Series, years: int = YEARS) -> pd.DataFrame:
    """Per calendar year: average price, full-year adjusted EPS, P/E on the average price.

    Full-year EPS is the trailing EPS at the first report after the year ends (the Q4 report,
    for calendar-year companies).
    """
    last = prices.index.max().year
    rows = []
    for y in range(last - years, last):
        after = ttm[(ttm.index > f"{y}-12-31") & (ttm.index <= f"{y + 1}-04-30")]
        p = prices[prices.index.year == y]
        if after.empty or p.empty:
            continue
        eps = float(after.iloc[0])
        rows.append(
            {
                "year": y,
                "avg_price": float(p.mean()),
                "eps": eps,
                "pe": float(p.mean()) / eps if eps > 0 else np.nan,
            }
        )
    return pd.DataFrame(rows).set_index("year") if rows else pd.DataFrame()


def next_report(dates: pd.DataFrame, now: pd.Timestamp) -> tuple[pd.Timestamp | None, float]:
    future = dates[dates["Reported EPS"].isna()].copy()
    future.index = pd.to_datetime(future.index, utc=True).tz_convert(None)
    future = future[future.index >= now].sort_index()
    if future.empty:
        return None, np.nan
    return future.index[0], float(future["EPS Estimate"].iloc[0])


# --- data ----------------------------------------------------------------------------


def has_price(row: dict) -> bool:
    """A usable price: present, a number and above zero (NaN is truthy, so test it)."""
    try:
        return float(row.get("price")) > 0
    except (TypeError, ValueError):
        return False


def load_inputs(data, stock_list: list[dict], now: pd.Timestamp) -> dict:
    """Everything the run reads from the database, in a few bulk queries: the rows of the
    stocks and their peers, and the stocks' prices, earnings dates and yearly history."""
    symbols = sorted({x for s in stock_list for x in [s["symbol"], *s["peers"]]})
    own = [s["symbol"] for s in stock_list]
    table = stocks.rows(data, symbols)
    ok = table[table["error"].isna()] if "error" in table else table
    rows = {sym: {"symbol": sym, **r.drop(labels="error", errors="ignore").to_dict()}
            for sym, r in ok.iterrows()}  # fmt: skip
    start = (now - pd.DateOffset(years=YEARS + 1)).strftime("%Y-%m-%d")
    return {
        "rows": rows,
        "missing": sorted(set(symbols) - set(rows)),
        "closes": stocks.closes(data, own, start),
        "earnings": stocks.earnings(data, own),
        "history": stocks.history(data, own),
    }


def gather(stock: dict, inputs: dict, now: pd.Timestamp) -> dict:
    sym = stock["symbol"]
    rows = inputs["rows"]
    if sym not in rows or sym not in inputs["closes"]:
        raise RuntimeError(f"{sym} is not in the database yet: the ingest fetches it next")
    e = inputs["earnings"]
    dates = stocks.earnings_dates(e[e["symbol"] == sym])
    prices = inputs["closes"][sym].dropna()
    q = quarterly_eps(dates, stock["eps_override"])
    ttm = trailing_eps(q)
    peers = pd.DataFrame([rows[s] for s in [sym, *stock["peers"]] if s in rows])
    peers = peers.set_index("symbol")
    peers["data_flag"] = ""
    nxt, nxt_est = next_report(dates, now)
    h = inputs["history"]
    return {
        "stock": stock,
        "row": rows[sym],
        "prices": prices,
        "quarters": q,
        "ttm": ttm,
        "years": h[h["symbol"] == sym],
        "peers": peers,
        "next_report": nxt,
        "next_estimate": nxt_est,
    }


def key_numbers(d: dict) -> dict:
    """The few numbers that go in the summary, the dated list and the evening message."""
    stock, row, prices, ttm = d["stock"], d["row"], d["prices"], d["ttm"]
    price = float(row["price"]) if has_price(row) else float(prices.iloc[-1])
    eps = float(ttm.iloc[-1]) if not ttm.empty else np.nan
    yearly = yearly_pe(prices, ttm)
    median = float(yearly["pe"].median()) if not yearly.empty else np.nan
    # Equity stakes (stakes_per_share) are kept out of the P/E: the price paid for the
    # business is the price less the stakes, and the entry price adds them back.
    stakes = wl.number(stock.get("stakes_per_share"))
    # target_pe is optional (Babak, 2026-11-12): blank or 0 means no target, no entry price
    target = float(stock.get("target_pe") or np.nan)
    entry = target * eps + stakes if eps > 0 and np.isfinite(target) else np.nan
    q = d["quarters"]
    eps_next = (
        eps - float(q.iloc[-4]) + d["next_estimate"]
        if len(q) >= 4 and np.isfinite(d["next_estimate"])
        else np.nan
    )
    return {
        "price": price,
        "price_date": prices.index[-1].date().isoformat(),
        "eps_adj_ttm": eps,
        "pe_adj": (price - stakes) / eps if eps > 0 else np.nan,
        "pe_median_10y": median,
        "pe_median_5y": float(yearly["pe"].tail(5).median()) if not yearly.empty else np.nan,
        "pe_low_10y": float(yearly["pe"].min()) if not yearly.empty else np.nan,
        "pe_high_10y": float(yearly["pe"].max()) if not yearly.empty else np.nan,
        "target_pe": target,
        "entry_price": entry,
        "to_entry": entry / price - 1 if np.isfinite(entry) else np.nan,
        "next_report": d["next_report"].date().isoformat() if d["next_report"] is not None else "",
        "next_estimate": d["next_estimate"],
        "stakes_per_share": stakes,
        "entry_after_next": target * eps_next + stakes if eps_next > 0 else np.nan,
    }


# --- the market report's numbers ---------------------------------------------------------


def instruments() -> tuple[dict[str, str], dict[str, str]]:
    cfg = tomllib.loads(MARKET_CONFIG.read_text(encoding="utf-8"))
    return cfg["markets"], cfg["sectors"]


def closes(data, symbols: list[str], years: int = 2) -> pd.DataFrame:
    start = (pd.Timestamp.today() - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
    return stocks.market_closes(data, symbols, start).dropna(how="all")


def moves(px: pd.DataFrame) -> pd.DataFrame:
    """Level, 1-day, 1-month and year-to-date change, and distance from the 52-week high."""
    last = px.ffill().iloc[-1]
    year = px[px.index >= px.index[-1] - pd.DateOffset(years=1)]
    ytd = px[px.index.year == px.index[-1].year]
    month = px[px.index >= px.index[-1] - pd.DateOffset(months=1)]
    return pd.DataFrame(
        {
            "last": last,
            "day": last / px.ffill().iloc[-2] - 1,
            "month": last / month.bfill().iloc[0] - 1,
            "ytd": last / ytd.bfill().iloc[0] - 1,
            "from_high": last / year.max() - 1,
        }
    )


# Per current index member: the latest close, its 200-day average and its 52-week range.
Q_BREADTH = """
WITH m AS (SELECT company_id FROM core_index_member WHERE end_date IS NULL),
p AS (
    SELECT p.company_id, p.date, p.close,
           ROW_NUMBER() OVER (PARTITION BY p.company_id ORDER BY p.date DESC) AS rn
    FROM core_price_daily p JOIN m ON m.company_id = p.company_id
    WHERE p.date >= CURRENT_DATE - 400
)
SELECT company_id,
       MAX(CASE WHEN rn = 1 THEN close END) AS last,
       MAX(CASE WHEN rn = 1 THEN date END) AS last_date,
       AVG(CASE WHEN rn <= 200 THEN close END) AS ma200,
       MAX(CASE WHEN rn <= 252 THEN close END) AS high52,
       MIN(CASE WHEN rn <= 252 THEN close END) AS low52
FROM p GROUP BY company_id"""


def breadth(data) -> dict:
    b = data.sql(Q_BREADTH)
    for c in ("last", "ma200", "high52", "low52"):
        b[c] = b[c].astype(float)
    b = b[b["last"].notna()]
    return {
        "above_200d": float((b["last"] > b["ma200"]).mean()) if len(b) else np.nan,
        "near_high": int((b["last"] >= b["high52"] * 0.98).sum()),
        "near_low": int((b["last"] <= b["low52"] * 1.02).sum()),
        "count": len(b),
        "date": str(b["last_date"].max()) if len(b) else "",
    }


def load_screener(data) -> tuple[pd.DataFrame, dict]:
    """The market screener's latest top per sector (stage 2 of the newest run), cheapest
    first, and Stage 1's counts. The nightly analyses refresh both after the ingest."""
    run_date, s1, top = stocks.screener_run(data)
    if run_date is None:
        return pd.DataFrame(), {}
    if "vs_cheap" in top:
        top = top.sort_values("vs_cheap")
    info = {
        "date": run_date,
        "screened": len(s1),
        "passed": int((s1["status"] == "pass").sum()),
        "listed": len(top),
        "sectors": int(top["sector"].nunique()) if len(top) else 0,
        # stale: older than the newest prices (the night's screener failed)
        "stale": run_date < str(newest_price(data) or run_date),
    }
    with SCREENER_CONFIG.open("rb") as f:
        cfg = tomllib.load(f)
    info |= {"top_n": cfg["top_per_sector"], "close": cfg["close_to_cheap"]}
    return top, info


def newest_price(data) -> str | None:
    v = data.sql("SELECT MAX(date) AS d FROM core_price_daily")["d"]
    return str(v.iloc[0])[:10] if len(v) and v.iloc[0] is not None else None


def market_numbers(data) -> dict:
    """Everything the market report shows but Claude's notes: the instruments' moves, the
    sector ETFs', breadth, and the screener's top per sector with its counts."""
    markets, sectors = instruments()
    px = closes(data, list(markets) + list(sectors))
    m = moves(px[[s for s in markets if s in px]]).reindex(list(markets))
    sec = moves(px[[s for s in sectors if s in px]])
    b = breadth(data)
    top, info = load_screener(data)
    return {
        "markets": m,
        "sectors": sec,
        "breadth": b,
        "top": top,
        "screener": info,
        "price_date": b["date"] or (px.index[-1].date().isoformat() if len(px) else ""),
    }


# --- what the numbers depend on ------------------------------------------------------


def stock_key(stock: dict) -> str:
    """What a stock's numbers depend on in the watch list (a changed target, peer group or
    EPS correction means they must be computed again)."""
    keep = {
        "symbol": stock["symbol"],
        "peers": list(stock.get("peers", [])),
        "target_pe": wl.number(stock.get("target_pe")),
        "stakes_per_share": wl.number(stock.get("stakes_per_share")),
        "eps_override": sorted(
            (str(o["reported"])[:10], round(float(o["eps"]), 6))
            for o in stock.get("eps_override", [])
        ),
    }
    return json.dumps(keep, sort_keys=True)


# --- storing and reading the results ------------------------------------------------------


def _series(s: pd.Series) -> dict:
    return {"index": [str(i)[:10] for i in s.index], "values": [plain(v) for v in s.to_numpy()]}


def _unseries(d: dict) -> pd.Series:
    return pd.Series(d["values"], index=pd.to_datetime(d["index"]), dtype=float)


def _frame(df: pd.DataFrame) -> dict:
    return {"index": [str(i) for i in df.index], "records": df.to_dict("records")}


def _unframe(d: dict, index_name: str | None = None) -> pd.DataFrame:
    df = pd.DataFrame(d["records"], index=d["index"])
    df.index.name = index_name
    return df


def to_json(obj) -> str:
    """JSON with NaN and infinity kept (a ratio of zero debt is infinite, and that passes)."""
    return json.dumps(obj, default=lambda v: plain(v) if not isinstance(v, float) else v)


def pack_stock(d: dict) -> dict:
    """gather()'s result as JSON-ready data."""
    return {
        "stock": d["stock"],
        "row": {k: (v.item() if isinstance(v, np.generic) else v) for k, v in d["row"].items()},
        "prices": _series(d["prices"]),
        "quarters": _series(d["quarters"]),
        "ttm": _series(d["ttm"]),
        "years": d["years"].to_dict("records"),
        "peers": _frame(d["peers"]),
        "next_report": d["next_report"].date().isoformat()
        if d["next_report"] is not None
        else None,
        "next_estimate": plain(d["next_estimate"]),
    }


def unpack_stock(p: dict) -> dict:
    return {
        "stock": p["stock"],
        "row": p["row"],
        "prices": _unseries(p["prices"]),
        "quarters": _unseries(p["quarters"]),
        "ttm": _unseries(p["ttm"]),
        "years": pd.DataFrame(
            p["years"], columns=["symbol", "fiscal_year_end", "column", "value", "source"]
        ),
        "peers": _unframe(p["peers"], "symbol"),
        "next_report": pd.Timestamp(p["next_report"]) if p["next_report"] else None,
        "next_estimate": np.nan if p["next_estimate"] is None else float(p["next_estimate"]),
    }


def pack_market(n: dict) -> dict:
    top = n["top"]
    keep = [c for c in top.columns if not c.endswith("_fy_h")] if len(top) else []
    return {
        "markets": _frame(n["markets"]),
        "sectors": _frame(n["sectors"]),
        "breadth": n["breadth"],
        "top": _frame(top[keep]) if len(top) else {"index": [], "records": []},
        "screener": n["screener"],
        "price_date": n["price_date"],
    }


def unpack_market(p: dict) -> dict:
    return {
        "markets": _unframe(p["markets"]),
        "sectors": _unframe(p["sectors"]),
        "breadth": p["breadth"],
        "top": _unframe(p["top"]),
        "screener": p["screener"],
        "price_date": p["price_date"],
    }


def save_stock_numbers(data, rows: list[dict]) -> None:
    """rows: {symbol, as_of, stock_key, payload}; a rerun the same day replaces the day's."""
    if not rows:
        return
    stamp = now_utc()
    steps = [
        ("DELETE FROM out_stock_numbers WHERE symbol = :symbol AND as_of = :as_of",
         [{"symbol": r["symbol"], "as_of": r["as_of"]} for r in rows]),
        ("INSERT INTO out_stock_numbers (symbol, as_of, computed_at, stock_key, payload_json) "
         "VALUES (:symbol, :as_of, :t, :stock_key, :payload)",
         [{**r, "t": stamp, "payload": to_json(r["payload"])} for r in rows]),
    ]  # fmt: skip
    data.write_steps(steps)


def save_market_numbers(data, as_of: str, payload: dict) -> None:
    data.write_steps(
        [
            ("DELETE FROM out_market_numbers WHERE as_of = :as_of", [{"as_of": as_of}]),
            (
                "INSERT INTO out_market_numbers (as_of, computed_at, payload_json) "
                "VALUES (:as_of, :t, :payload)",
                [{"as_of": as_of, "t": now_utc(), "payload": to_json(payload)}],
            ),
        ]
    )


def last_build(data) -> str:
    v = data.sql("SELECT MAX(finished_at) AS t FROM core_build WHERE status = 'ok'")["t"]
    return str(v.iloc[0]) if len(v) and v.iloc[0] is not None else ""


def stored_stocks(data, stock_list: list[dict]) -> dict[str, dict]:
    """The stored numbers of each stock that are still good: computed after the last build
    and for the stock's current watch-list settings. Unpacked, by symbol."""
    if not stock_list:
        return {}
    rows = stocks.query(
        data,
        "SELECT DISTINCT ON (symbol) symbol, computed_at, stock_key, payload_json "
        "FROM out_stock_numbers WHERE symbol IN ({symbols}) ORDER BY symbol, computed_at DESC",
        [s["symbol"] for s in stock_list],
    )
    built = last_build(data)
    want = {s["symbol"]: stock_key(s) for s in stock_list}
    out = {}
    for r in rows.itertuples() if len(rows) else []:
        if str(r.computed_at) >= built and r.stock_key == want.get(r.symbol):
            out[r.symbol] = unpack_stock(json.loads(r.payload_json))
    return out


def stored_market(data) -> dict | None:
    """The stored market numbers if computed after the last build."""
    r = data.sql(
        "SELECT computed_at, payload_json FROM out_market_numbers ORDER BY computed_at DESC LIMIT 1"
    )
    if r.empty or str(r["computed_at"].iloc[0]) < last_build(data):
        return None
    return unpack_market(json.loads(r["payload_json"].iloc[0]))


# --- the nightly run -----------------------------------------------------------------------


def compute_stocks(data, stock_list: list[dict], now: pd.Timestamp | None = None):
    """gather() for each stock, from the database. Returns ({symbol: gathered}, {symbol:
    error}, the peers the database lacks)."""
    now = now or pd.Timestamp(datetime.now(UTC).replace(tzinfo=None))
    inputs = load_inputs(data, stock_list, now)
    done, failed = {}, {}
    for s in stock_list:
        try:
            done[s["symbol"]] = gather(s, inputs, now)
        except Exception as exc:  # noqa: BLE001 - one stock doesn't stop the others
            failed[s["symbol"]] = str(exc)
    return done, failed, inputs["missing"]


def run(data, screener: bool = True) -> dict:
    """The nightly analyses: the screener, the watch list's numbers, the market numbers."""
    summary: dict = {}
    if screener:
        from .screener import run as run_screener

        try:
            d, top = run_screener(data=data)
            summary["screener"] = {"screened": len(d), "listed": len(top)}
        except Exception as exc:  # noqa: BLE001 - the rest still runs
            summary["screener_error"] = repr(exc)[:300]
    stock_list = wl.load(data)
    done, failed, missing = compute_stocks(data, stock_list)
    keys = {s["symbol"]: stock_key(s) for s in stock_list}
    save_stock_numbers(
        data,
        [
            {
                "symbol": sym,
                "as_of": g["prices"].index[-1].date().isoformat(),
                "stock_key": keys[sym],
                "payload": pack_stock(g),
            }
            for sym, g in done.items()
        ],
    )
    summary["stocks"] = {"computed": sorted(done), "failed": failed, "peers_missing": missing}
    try:
        n = market_numbers(data)
        save_market_numbers(data, n["price_date"] or now_utc()[:10], pack_market(n))
        summary["market"] = {"price_date": n["price_date"]}
    except Exception as exc:  # noqa: BLE001
        summary["market_error"] = repr(exc)[:300]
    return summary
