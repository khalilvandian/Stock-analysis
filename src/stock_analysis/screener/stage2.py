"""Stage 2 of the market screener: rank the Stage 1 survivors by how cheap they are.

Takes Stage 1's output (stage1.py, in the same run) and ranks the companies
Stage 1 passed. Settings in config/screeners.toml. Every input is in the database.

  1. Cheap price: the stock's own cheap multiple (bottom quarter of its yearly P/E over
     10 fiscal years, on average monthly closes and TradingView diluted EPS, capped at the
     sector median) times today's EPS. For the stocks near the top, Yahoo's adjusted EPS
     replaces diluted EPS where it has at least 6 years (the watch list's method).
  2. Rank inside each region and sector by price against the cheap price, lowest first.
     Below it = "cheap"; within 15% above = "close". Technicals (trend, RSI, 52-week
     range, TradingView rating) are shown for timing, not used in the ranking.
  3. US stocks' latest-year EPS is checked against the SEC filings in the database; a
     mismatch is flagged.

Nothing is written here: stock_analysis.screener.run saves the run in the database.

Usage: uv run python -m stock_analysis.screener.stage2 [--no-adjusted]   # Stage 1 and 2, printed
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from .. import nightly as w
from .. import stocks
from .common import load_config, to_usd

# The columns Stage 2 needs from Stage 1: the contract between the two stages
NEEDS = [
    "status",
    "region",
    "sector",
    "type",
    "category",
    "description",
    "symbol",
    "close",
    "currency",
    "fx_fund",
    "fx_price",
    "price_fund",
    "eps",
    "market_cap_basic",
    "earnings_per_share_diluted_fy_h",
    "fiscal_period_fy_h",
    "fiscal_period_end_fy",
    "enterprise_value_ebitda_ttm",
    "free_cash_flow_ttm",
    "cash_f_operating_activities_ttm",
    "capital_expenditures_ttm",
    "net_cash",
    "net_debt_to_ebitda",
    "eps_growth_median",
    "flags",
    "filled",
    "SMA50",
    "SMA200",
    "RSI",
    "price_52_week_high",
    "price_52_week_low",
    "Recommend.All",
]


def check_stage1(d: pd.DataFrame) -> pd.DataFrame:
    """Stage 1's output; refuses to go on if a column Stage 2 needs is missing."""
    missing = [c for c in NEEDS if c not in d.columns]
    if missing:
        raise RuntimeError(f"Stage 1 output lacks {missing}")
    return d


CASH_FLOW_ITEMS = {
    "cash_f_operating_activities_ttm": "operating_cf",
    "capital_expenditures_ttm": "capex",
    "free_cash_flow_ttm": "free_cf",
}


def fill_cash_flows(d: pd.DataFrame, rows: pd.Index, data) -> None:
    """Fill blank cash flows of the listed stocks from the database (last twelve months)."""
    gaps = d.loc[rows, list(CASH_FLOW_ITEMS)].isna().any(axis=1)
    todo = gaps[gaps].index
    if len(todo):
        t = stocks.ttm(data, d.loc[todo, "symbol"].dropna().unique())
        if len(t):
            t["free_cf"] = t.get("operating_cf") + t.get("capex")
        for idx in todo:
            sym = d.loc[idx, "symbol"]
            if sym not in t.index:
                continue
            for col, item in CASH_FLOW_ITEMS.items():
                v = t.loc[sym].get(item)
                if pd.isna(d.loc[idx, col]) and pd.notna(v):
                    d.loc[idx, col] = float(v) / d.loc[idx, "fx_fund"]
                    d.loc[idx, "filled"] += f"{col} (database); "
    to_usd(d)


# --- step 4: cheap price -------------------------------------------------------------


def monthly_prices(data, symbols: list[str], years: int) -> pd.DataFrame:
    """Monthly closes (split-adjusted), one column per symbol, from the database."""
    start = (pd.Timestamp.today() - pd.DateOffset(years=years + 2)).strftime("%Y-%m-%d")
    return stocks.monthly_closes(data, symbols, start)


def fiscal_pe(
    prices: pd.Series, eps_h: list, years_h: list, fy_end: pd.Timestamp, n: int
) -> pd.DataFrame:
    """Yearly P/E: average monthly close over each fiscal year / that year's EPS.

    `eps_h` and `years_h` are newest first (TradingView's yearly history); `fy_end` is the
    end date of the latest fiscal year. Prices must be in the EPS currency.
    """
    rows = []
    prices = prices.dropna()
    latest = years_h[0] if years_h else None
    for k, (year, eps) in enumerate(zip(years_h[:n], eps_h[:n], strict=False)):
        if eps is None or year is None:
            continue
        # count back by the year labels, so a year missing from the list can't shift the
        # price window of every year after it
        back = int(latest) - int(year) if latest is not None else k
        end = fy_end - pd.DateOffset(years=back)
        window = prices[(prices.index > end - pd.DateOffset(years=1)) & (prices.index <= end)]
        if len(window) < 9:
            continue
        avg = float(window.mean())
        rows.append({"year": int(year), "avg_price": avg, "eps": eps})
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["year", "avg_price", "eps", "pe"])
    out["pe"] = (out["avg_price"] / out["eps"]).where(out["eps"] > 0)
    return out


def cheap_multiple(pe: pd.Series, percentile: float, min_years: int) -> float:
    """The stock's own cheap P/E: a low percentile of its positive yearly P/Es."""
    pe = pe.dropna()
    pe = pe[pe > 0]
    if len(pe) < min_years:
        return np.nan
    return float(pe.quantile(percentile))


def add_cheap_price(d: pd.DataFrame, prices: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    n, pct, need = cfg["history_years"], cfg["cheap_percentile"], cfg["min_history_years"]
    out = {}
    for idx, r in d.iterrows():
        sym = r["symbol"]
        if sym not in prices.columns or not isinstance(r["earnings_per_share_diluted_fy_h"], list):
            continue
        fy_end = pd.to_datetime(r["fiscal_period_end_fy"], unit="s", errors="coerce")
        if pd.isna(fy_end):
            continue
        px = prices[sym] * r["fx_price"] / r["fx_fund"]
        h = fiscal_pe(px, r["earnings_per_share_diluted_fy_h"], r["fiscal_period_fy_h"], fy_end, n)
        out[idx] = {
            "pe_years": int(h["pe"].notna().sum()),
            "pe_median_10y": float(h["pe"].median()) if h["pe"].notna().any() else np.nan,
            "pe_low_10y": float(h["pe"].min()) if h["pe"].notna().any() else np.nan,
            "cheap_pe": cheap_multiple(h["pe"], pct, need),
        }
    h = pd.DataFrame.from_dict(out, orient="index")
    for c in ("pe_years", "pe_median_10y", "pe_low_10y", "cheap_pe"):
        d[c] = h[c] if c in h else np.nan
    d["eps_basis"] = "diluted"
    set_cheap_price(d)
    return d


def set_cheap_price(d: pd.DataFrame) -> None:
    """Cheap multiple = the lower of the stock's own cheap P/E and its sector's median P/E.

    The sector cap keeps a stock whose whole history was priced for hyper-growth (Amazon,
    Netflix) from looking cheap at a multiple its peers never get.
    """
    d["pe_now"] = (d["price_fund"] / d["eps"]).where(d["eps"] > 0)
    d["sector_pe"] = d.groupby(["region", "sector"])["pe_now"].transform("median")
    d["cheap_basis"] = np.where(d["cheap_pe"] > d["sector_pe"], "sector median", "own history")
    d["cheap_multiple"] = d[["cheap_pe", "sector_pe"]].min(axis=1).where(d["cheap_pe"].notna())
    d.loc[d["cheap_multiple"].isna(), "cheap_basis"] = ""
    # cheap price in the trading currency
    d["cheap_price"] = d["cheap_multiple"] * d["eps"] * d["fx_fund"] / d["fx_price"]
    d.loc[d["eps"] <= 0, "cheap_price"] = np.nan
    d["vs_cheap"] = d["close"] / d["cheap_price"] - 1


def adjusted_eps_plausible(adjusted: float, diluted: float) -> bool:
    """Adjusted EPS within a factor of 2 of diluted EPS.

    Further apart is almost always a data problem (a split Yahoo hasn't applied to its
    earnings history, or EPS in a different currency), not one-off items.
    """
    if not (diluted > 0 and adjusted > 0):
        return False
    return 0.5 <= adjusted / diluted <= 2.0


def adjusted_refine(d: pd.DataFrame, rows: pd.Index, cfg: dict, data) -> None:
    """Swap in Yahoo's adjusted EPS (and its own adjusted P/E history) where it has 6+ years.

    Same method as the watch list: quarterly reported EPS, trailing four quarters, yearly
    P/E on the calendar-year average price.
    """
    pct, need = cfg["cheap_percentile"], cfg["min_history_years"]
    syms = d.loc[rows, "symbol"].dropna()
    start = (pd.Timestamp.today() - pd.DateOffset(years=cfg["history_years"] + 2)).date()
    closes = stocks.closes(data, syms.unique(), start) if len(syms) else pd.DataFrame()
    earnings = stocks.earnings(data, syms.unique()) if len(syms) else pd.DataFrame()

    def one(sym: str) -> dict | None:
        if sym not in closes.columns:
            return None
        px = closes[sym].dropna()
        q = w.quarterly_eps(stocks.earnings_dates(earnings[earnings["symbol"] == sym]))
        if px.empty or len(q) < 8:
            return None
        ttm = w.trailing_eps(q)
        if len(ttm) < 5 or ttm.iloc[-1] <= 0:
            return None
        yearly = w.yearly_pe(px, ttm, years=cfg["history_years"])
        if yearly.empty:
            return None
        return {"eps": float(ttm.iloc[-1]), "pe": yearly["pe"]}

    results = {idx: one(sym) for idx, sym in syms.items()}
    for idx, res in results.items():
        if not res:
            continue
        cheap = cheap_multiple(res["pe"], pct, need)
        if np.isnan(cheap):
            continue
        # Yahoo's EPS is per share in the trading currency
        r = d.loc[idx]
        eps = res["eps"] * r["fx_price"] / r["fx_fund"]
        if not adjusted_eps_plausible(eps, r["eps"]):
            d.loc[idx, "flags"] += f"Yahoo adjusted EPS {res['eps']:.2f} ignored (vs diluted); "
            continue
        d.loc[idx, ["eps", "cheap_pe", "eps_basis"]] = [eps, cheap, "adjusted"]
        d.loc[idx, "pe_median_10y"] = float(res["pe"].median())
        d.loc[idx, "pe_low_10y"] = float(res["pe"].min())
        d.loc[idx, "pe_years"] = int(res["pe"].notna().sum())
    set_cheap_price(d)


# --- step 5: ranking and technicals --------------------------------------------------


def technicals(d: pd.DataFrame) -> None:
    c, s50, s200 = d["close"], d["SMA50"], d["SMA200"]
    trend = np.where(
        (c > s200) & (s50 > s200),
        "uptrend",
        np.where((c < s200) & (s50 < s200), "downtrend", "mixed"),
    )
    d["trend"] = np.where(s200.isna(), "", trend)
    d["rsi_read"] = np.select(
        [d["RSI"] < 30, d["RSI"] > 70], ["oversold", "overbought"], default=""
    )
    rng = d["price_52_week_high"] - d["price_52_week_low"]
    d["in_52w_range"] = ((c - d["price_52_week_low"]) / rng).where(rng > 0)
    rec = d["Recommend.All"]
    d["tv_rating"] = np.select(
        [rec >= 0.5, rec >= 0.1, rec <= -0.5, rec <= -0.1],
        ["strong buy", "buy", "strong sell", "sell"],
        default="neutral",
    )
    d.loc[rec.isna(), "tv_rating"] = ""


def label(vs_cheap: float, close: float) -> str:
    if pd.isna(vs_cheap):
        return ""
    if vs_cheap <= 0:
        return "cheap"
    return "close" if vs_cheap <= close else ""


def peer_measures(d: pd.DataFrame) -> None:
    """P/E and EV/EBITDA against the median of the same region and sector."""
    g = d.groupby(["region", "sector"])
    d["pe_vs_sector"] = d["pe_now"] / g["pe_now"].transform("median") - 1
    ev = d["enterprise_value_ebitda_ttm"].where(d["enterprise_value_ebitda_ttm"] > 0)
    d["ev_ebitda_vs_sector"] = ev / ev.groupby([d["region"], d["sector"]]).transform("median") - 1
    d["fcf_yield"] = d["free_cash_flow_ttm"] / d["market_cap_basic"]


def reason(r: pd.Series) -> str:
    bits = [f"{r['pe_now']:.1f}x P/E vs cheap {r['cheap_multiple']:.1f}x ({r['cheap_basis']})"]
    if pd.notna(r.get("pe_median_10y")):
        bits.append(f"10-yr median {r['pe_median_10y']:.1f}x")
    if r.get("net_cash"):
        bits.append("net cash")
    elif pd.notna(r.get("net_debt_to_ebitda")):
        bits.append(f"net debt {r['net_debt_to_ebitda']:.1f}x EBITDA")
    if pd.notna(r.get("eps_growth_median")):
        bits.append(f"EPS growth median {r['eps_growth_median']:.0%}/yr")
    if r.get("trend"):
        bits.append(r["trend"])
    return ", ".join(bits)


def rank(d: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Top N per region and sector among passing stocks that are cheap or close to it."""
    ok = d[(d["status"] == "pass") & (d["vs_cheap"] <= cfg["close_to_cheap"])].copy()
    ok = ok.sort_values("vs_cheap")
    ok["rank_in_sector"] = ok.groupby(["region", "sector"]).cumcount() + 1
    top = ok[ok["rank_in_sector"] <= cfg["top_per_sector"]].copy()
    top["cheapness"] = [label(v, cfg["close_to_cheap"]) for v in top["vs_cheap"]]
    top["why"] = top.apply(reason, axis=1)
    return top.sort_values(["region", "sector", "rank_in_sector"])


# --- step 6: SEC cross-check ---------------------------------------------------------


def _latest(values, int_: bool = True):
    """The newest entry of a yearly history list, or None (blank or not a list)."""
    if not isinstance(values, list | tuple) or not values or values[0] is None:
        return None
    return int(values[0]) if int_ else float(values[0])


def split_factor_since(splits: pd.DataFrame, symbol, year: int) -> float:
    """Product of the stock's splits after the end of calendar `year` (1 if none).

    A split after the year's 10-K leaves the SEC's EPS for that year on the old share basis.
    """
    if not isinstance(symbol, str) or splits is None or splits.empty:
        return 1.0
    s = splits[(splits["symbol"] == symbol) & (splits["date"] > pd.Timestamp(f"{year}-12-31"))]
    s = s[s["split_ratio"] > 0]
    return float(s["split_ratio"].prod()) if len(s) else 1.0


Q_SEC_EPS = """
SELECT c.symbol, f.fiscal_year, f.value FROM v_fundamental_latest f
JOIN core_company c ON c.company_id = f.company_id
WHERE f.item = 'eps_diluted' AND f.period_type = 'FY' AND f.source LIKE 'sec%'
  AND c.symbol IN ({symbols})"""


def sec_check(d: pd.DataFrame, rows: pd.Index, data) -> None:
    """Flag US stocks whose latest-year diluted EPS differs from their SEC filing by over
    10%, after putting the SEC figure on today's share basis."""
    d["sec_eps"] = d.get("sec_eps", np.nan)
    syms = d.loc[rows, "symbol"].dropna().unique()
    if not len(syms):
        return
    filed = stocks.query(data, Q_SEC_EPS, syms, size=100)
    splits = stocks.splits(data, syms)
    sec_by = (
        {(r.symbol, int(r.fiscal_year)): float(r.value) for r in filed.itertuples()}
        if len(filed)
        else {}
    )
    for idx in rows:
        r = d.loc[idx]
        year = _latest(r["fiscal_period_fy_h"])
        if r["region"] != "US" or year is None:
            continue
        sec = sec_by.get((r["symbol"], year))
        tv = _latest(r["earnings_per_share_diluted_fy_h"], int_=False)
        if sec is None or tv is None:
            continue
        if abs(sec - tv) > 0.1 * max(abs(sec), 0.01):
            # SEC values are as filed; TradingView's are split-adjusted
            sec /= split_factor_since(splits, r["symbol"], year)
        d.loc[idx, "sec_eps"] = sec
        if abs(sec - tv) > 0.1 * max(abs(sec), 0.01):
            d.loc[idx, "flags"] += f"EPS {year}: TradingView {tv:.2f} vs SEC {sec:.2f}; "


# --- run -----------------------------------------------------------------------------


def run(
    d: pd.DataFrame, cfg: dict, adjusted: bool = True, data=None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cheap price, technicals and ranking for Stage 1's passes. Returns (all, top)."""
    data = data or stocks.default_data()
    d = check_stage1(d).copy()
    passed = d[d["status"] == "pass"]
    prices = monthly_prices(data, passed["symbol"].dropna().tolist(), cfg["history_years"])
    d = add_cheap_price(d, prices, cfg)
    technicals(d)
    peer_measures(d)
    if adjusted:
        # refine the closest names: enough per sector that a swap in order is caught
        near = d[(d["status"] == "pass") & d["vs_cheap"].notna()].sort_values("vs_cheap")
        near = near.groupby(["region", "sector"]).head(cfg["top_per_sector"] * 3).index
        adjusted_refine(d, near, cfg, data)
        peer_measures(d)
    top = rank(d, cfg)
    sec_check(d, top.index, data)
    fill_cash_flows(d, top.index, data)
    peer_measures(d)  # free cash flow yield with the filled cash flows
    return d, rank(d, cfg)


SHOW = [
    "description",
    "category",
    "close",
    "currency",
    "cap_usd_bn",
    "pe_now",
    "cheap_multiple",
    "cheap_basis",
    "cheap_price",
    "vs_cheap",
    "cheapness",
    "eps_basis",
    "trend",
    "tv_rating",
]


def main() -> None:
    from . import stage1

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-adjusted", action="store_true", help="skip Yahoo adjusted EPS")
    args = ap.parse_args()
    cfg = load_config()
    _, top = run(stage1.run(cfg), cfg, adjusted=not args.no_adjusted)
    pd.set_option("display.width", 250)
    print("Stage 2: cheapest Stage 1 survivors per sector (nothing saved)")
    for (region, sector), g in top.groupby(["region", "sector"]):
        print(f"{region} / {sector}")
        print(g[SHOW].round(2).to_string(header=False))


if __name__ == "__main__":
    main()
