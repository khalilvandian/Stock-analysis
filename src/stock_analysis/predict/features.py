"""Point-in-time features (inputs) for one company on one decision date.

Fundamentals come from the latest 10-K filed before the date (sec.Facts.annual), prices
from Yahoo up to the date. Names follow config/metrics.toml where the metric exists there;
the extra ones (asset growth, accruals, momentum, volatility, ...) are standard factors from
the academic literature and are documented in docs/PREDICT.md.

Every ratio is defined so that it exists for most companies: yields (earnings / price)
rather than multiples (price / earnings) where earnings can be negative, and cover ratios
capped at 50x, as in the metrics dictionary.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from stock_analysis.predict.prices import Prices
from stock_analysis.predict.sec import FLOW_TAGS, INSTANT_TAGS, Facts

CAP = 50.0
TAX = 0.21

FUNDAMENTAL = [
    # size and price
    "market_cap",
    "log_market_cap",
    "enterprise_value",
    # valuation
    "pe_ttm",
    "earnings_yield",
    "price_to_book",
    "book_to_market",
    "price_to_sales",
    "sales_yield",
    "ev_to_ebitda",
    "ebitda_to_ev",
    "fcf_yield",
    "dividend_yield",
    "buyback_yield",
    "shareholder_yield",
    # debt and liquidity
    "cash_to_short_term_debt",
    "cash_to_long_term_debt",
    "cash_to_total_debt",
    "net_debt_to_ebitda",
    "interest_cover",
    "debt_to_equity",
    "debt_to_assets",
    "net_cash_to_market_cap",
    "current_ratio",
    # profitability
    "net_margin",
    "gross_margin",
    "operating_margin",
    "fcf_margin",
    "roe",
    "roa",
    "roic",
    "ocf_to_assets",
    "accruals",
    "capex_to_revenue",
    "rnd_to_revenue",
    "payout_ratio",
    # growth and stability
    "revenue_growth_median",
    "revenue_cagr_3y",
    "eps_growth_median",
    "eps_cagr_3y",
    "ocf_growth_median",
    "ebitda_cagr_3y",
    "margin_change_avg",
    "asset_growth",
    "share_change",
    "eps_vs_5y_peak",
    "loss_now",
    "eps_big_drops",
    "roa_volatility",
    "years_of_history",
    # scores
    "piotroski_f",
    "altman_z",
]
PRICE = [
    "mom_12_1",
    "mom_6m",
    "ret_1m",
    "vol_1y",
    "beta_3y",
    "max_dd_3y",
    "price_vs_200d",
    "price_vs_52w_high",
    "excess_return_3y",
]
CATEGORICAL = ["sector", "lynch_category"]


def _div(a, b, cap: float | None = None, pos_den: bool = False):
    if a is None or b is None or not np.isfinite(a) or not np.isfinite(b) or b == 0:
        return np.nan
    if pos_den and b <= 0:
        return np.nan
    v = a / b
    return min(v, cap) if cap is not None else v


def _last(s: pd.Series, k: int = 0):
    return float(s.iloc[-1 - k]) if len(s) > k else np.nan


def _yoy(s: pd.Series, positive_base: bool = True) -> pd.Series:
    prev = s.shift(1)
    g = s / prev - 1
    if positive_base:
        g = g[prev > 0]
    return g.dropna()


def _cagr(s: pd.Series, years: int = 3):
    if len(s) <= years:
        return np.nan
    a, b = s.iloc[-1 - years], s.iloc[-1]
    if a <= 0 or b <= 0:
        return np.nan
    return (b / a) ** (1 / years) - 1


def _consecutive(s: pd.Series) -> pd.Series:
    """Keep only the run of roughly annual period ends that ends with the latest one."""
    if len(s) < 2:
        return s
    keep = [s.index[-1]]
    for d in reversed(s.index[:-1]):
        if 300 <= (keep[-1] - d).days <= 430:
            keep.append(d)
        else:
            break
    return s.loc[sorted(keep)]


PER_SHARE = {"eps"}
SHARE_COUNTS = {"diluted_shares"}


def split_factor(splits: pd.Series, after, asof) -> float:
    """Product of stock splits after `after` up to `asof` (2.0 for a 2-for-1 split)."""
    if splits is None or splits.empty or pd.isna(after):
        return 1.0
    s = splits[(splits.index > pd.Timestamp(after)) & (splits.index <= pd.Timestamp(asof))]
    return float(np.prod(s.values)) if len(s) else 1.0


def fundamentals(
    facts: Facts, asof, splits: pd.Series | None = None
) -> dict[str, pd.Series] | None:
    """Annual series known on `asof`, aligned to fiscal year ends; None if stale or empty.

    Per-share values and share counts are restated for splits made after the filing they
    came from (so EPS growth is not distorted by a 4-for-1 split).
    """
    asof = pd.Timestamp(asof)
    flows = {}
    for k, tags in FLOW_TAGS.items():
        df = facts.annual(tags, asof, instant=False, with_filed=True)
        v = df["val"].astype(float)
        if len(df) and (k in PER_SHARE or k in SHARE_COUNTS):
            f = df["filed"].map(lambda x: split_factor(splits, x, asof))
            v = v / f if k in PER_SHARE else v * f
        flows[k] = v
    anchor = flows["net_income"] if len(flows["net_income"]) else flows["revenue"]
    if anchor.empty or (asof - anchor.index[-1]).days > 550:
        return None  # no 10-K in the last ~18 months: company not filing (or not yet)
    ends = _consecutive(anchor).index
    out = {}
    for k, s in flows.items():
        out[k] = s.reindex(ends)
    for k, tags in INSTANT_TAGS.items():
        s = facts.annual(tags, asof, instant=True)
        if s.empty:
            out[k] = pd.Series(np.nan, index=ends)
            continue
        idx = s.index.get_indexer(ends, method="nearest", tolerance=pd.Timedelta(days=10))
        out[k] = pd.Series([s.iloc[i] if i >= 0 else np.nan for i in idx], index=ends)
    return out


def _debt(f: dict[str, pd.Series]) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Short-term, long-term and total debt per year; missing tags mean no debt reported."""
    st = f["debt_current"].copy()
    alt_st = f["lt_debt_current"].fillna(0) + f["short_borrowings"].fillna(0)
    st = st.where(st.notna(), alt_st)
    lt = f["lt_debt_noncurrent"].copy()
    alt_lt = f["lt_debt_total"] - f["lt_debt_current"].fillna(0)
    lt = lt.where(lt.notna(), alt_lt).fillna(0)
    return st, lt, st + lt


def piotroski(f: dict[str, pd.Series], shares: pd.Series) -> float:
    """Piotroski (2000) F-score from the last two fiscal years (NaN if under 3 years)."""
    a = f["assets"]
    if len(a) < 3 or a.iloc[-3:].isna().any():
        return np.nan
    ni, ocf, rev = f["net_income"], f["operating_cf"], f["revenue"]
    roa = ni / a.shift(1)
    lev = f["lt_debt_noncurrent"].fillna(0) / a
    cr = f["current_assets"] / f["current_liabilities"]
    gm = f["gross_profit"] / rev
    turn = rev / a.shift(1)
    tests = [
        _last(roa) > 0,
        _last(ocf) > 0,
        _last(roa) > _last(roa, 1),
        _last(ocf) / _last(a, 1) > _last(roa),
        _last(lev) <= _last(lev, 1),
        _last(cr) > _last(cr, 1),
        _last(shares) <= _last(shares, 1) * 1.005,
        _last(gm) > _last(gm, 1),
        _last(turn) > _last(turn, 1),
    ]
    return float(sum(bool(t) for t in tests))


def lynch_category(eps: pd.Series, eps_growth_median: float, ptb: float, net_cash_mc: float):
    """Simplified Lynch category from config/metrics.toml (no cyclical-industry list)."""
    e = eps.dropna()
    if e.empty:
        return "unknown"
    last5 = e.iloc[-5:]
    if last5.max() <= 0:
        return "no_profit"
    loss_now = e.iloc[-1] <= 0
    vs_peak = e.iloc[-1] / last5.max() - 1
    if loss_now or vs_peak < -0.5:
        return "turnaround"
    drops = int((_yoy(e) < -0.3).sum())
    fast = np.isfinite(eps_growth_median) and eps_growth_median >= 0.20
    if drops >= 3 and not fast:
        return "cyclical"
    if (np.isfinite(ptb) and ptb < 1) or (np.isfinite(net_cash_mc) and net_cash_mc > 0.3):
        return "asset_play"
    if fast:
        return "fast_grower"
    if np.isfinite(eps_growth_median) and eps_growth_median >= 0.08:
        return "stalwart"
    return "slow_grower"


def price_features(p: Prices, spy: Prices, asof) -> dict:
    d = pd.Timestamp(asof)
    out = dict.fromkeys(PRICE, np.nan)
    s = p.window(d - pd.DateOffset(years=3, days=10), d)
    if len(s) < 200:
        return out
    m = s.resample("ME").last()

    def at(offset_months):
        x = s.loc[: d - pd.DateOffset(months=offset_months)]
        return float(x.iloc[-1]) if len(x) else np.nan

    now = float(s.iloc[-1])
    out["mom_12_1"] = at(1) / at(12) - 1
    out["mom_6m"] = now / at(6) - 1
    out["ret_1m"] = now / at(1) - 1
    last_year = s.loc[d - pd.DateOffset(years=1) :]
    out["vol_1y"] = float(np.log(last_year).diff().std() * math.sqrt(252))
    out["max_dd_3y"] = float(-(s / s.cummax() - 1).min())
    close = p.window(d - pd.DateOffset(years=1, days=10), d, "close")
    if len(close) >= 200:
        out["price_vs_200d"] = float(close.iloc[-1] / close.iloc[-200:].mean() - 1)
        out["price_vs_52w_high"] = float(
            close.iloc[-1] / close.loc[d - pd.DateOffset(years=1) :].max() - 1
        )
    b = spy.window(d - pd.DateOffset(years=3, days=10), d).resample("ME").last()
    r = pd.concat([m.pct_change(), b.pct_change()], axis=1, join="inner").dropna()
    if len(r) >= 24:
        cov = np.cov(r.iloc[:, 0], r.iloc[:, 1])
        out["beta_3y"] = float(cov[0, 1] / cov[1, 1])
    if (d - s.index[0]).days >= 3 * 365 - 20:
        bs = spy.window(s.index[0], d)
        if len(bs):
            out["excess_return_3y"] = float(
                (now / s.iloc[0]) ** (1 / 3) - (bs.iloc[-1] / bs.iloc[0]) ** (1 / 3)
            )
    return out


def compute(facts: Facts, p: Prices, spy: Prices, asof) -> dict:
    """All features for one company on one date (NaN where not computable)."""
    out: dict = dict.fromkeys(FUNDAMENTAL + PRICE, np.nan)
    out["lynch_category"] = "unknown"
    asof = pd.Timestamp(asof)
    price = p.actual_price(asof) if p.ok else None
    so = facts.shares_outstanding(asof)
    shares_out = so[0] * split_factor(p.splits, so[1], asof) if so else None
    mcap = price * shares_out if price and shares_out else np.nan
    out["market_cap"] = mcap
    out["log_market_cap"] = math.log(mcap) if mcap and mcap > 0 else np.nan
    if p.ok:
        out.update(price_features(p, spy, asof))
        adj_price = p.on(asof, "close")
        if adj_price:
            out["dividend_yield"] = p.dividends_ttm(asof) / adj_price

    f = fundamentals(facts, asof, p.splits if p.ok else None)
    if f is None:
        return out
    rev, ni, eps = f["revenue"], f["net_income"], f["eps"]
    ocf, capex = f["operating_cf"], f["capex"].fillna(0)
    ebitda = f["operating_income"] + f["d_and_a"].fillna(0)
    fcf = ocf - capex
    st, lt, debt = _debt(f)
    cash = f["cash"].fillna(0) + f["short_investments"].fillna(0)
    net_debt = debt - cash
    equity = f["equity"]
    assets = f["assets"]
    liab = f["liabilities"].where(
        f["liabilities"].notna(), f["liabilities_and_equity"] - f["equity_incl_nci"]
    )
    shares = f["diluted_shares"]

    R, NI, OCF, FCF, EB = (_last(x) for x in (rev, ni, ocf, fcf, ebitda))
    ND, EQ, A = _last(net_debt), _last(equity), _last(assets)
    INT = _last(f["interest"])
    years = int(rev.notna().sum() or ni.notna().sum())
    out["years_of_history"] = years

    ev = mcap + ND if np.isfinite(mcap) and np.isfinite(ND) else np.nan
    out["enterprise_value"] = ev
    out["pe_ttm"] = _div(mcap, NI, pos_den=True)
    out["earnings_yield"] = _div(NI, mcap)
    out["price_to_book"] = _div(mcap, EQ, pos_den=True)
    out["book_to_market"] = _div(EQ, mcap)
    out["price_to_sales"] = _div(mcap, R, pos_den=True)
    out["sales_yield"] = _div(R, mcap)
    out["ev_to_ebitda"] = _div(ev, EB, pos_den=True)
    out["ebitda_to_ev"] = _div(EB, ev, pos_den=True)
    out["fcf_yield"] = _div(FCF, mcap)
    out["buyback_yield"] = _div(_last(f["buybacks"].fillna(0)), mcap)
    out["shareholder_yield"] = _div(
        _last(f["buybacks"].fillna(0)) + _last(f["dividends_paid"].fillna(0)), mcap
    )

    ST, LT, D = _last(st), _last(lt), _last(debt)
    C = _last(cash)
    out["cash_to_short_term_debt"] = CAP if ST == 0 else _div(C, ST, CAP)
    out["cash_to_long_term_debt"] = CAP if LT == 0 else _div(C, LT, CAP)
    out["cash_to_total_debt"] = CAP if D == 0 else _div(C, D, CAP)
    out["net_debt_to_ebitda"] = 0.0 if np.isfinite(ND) and ND <= 0 else _div(ND, EB, pos_den=True)
    no_interest = not np.isfinite(INT) or INT <= 0
    out["interest_cover"] = CAP if no_interest else _div(EB, INT, CAP)
    out["debt_to_equity"] = _div(D, EQ, pos_den=True)
    out["debt_to_assets"] = _div(D, A, pos_den=True)
    out["net_cash_to_market_cap"] = _div(-ND, mcap)
    out["current_ratio"] = _div(_last(f["current_assets"]), _last(f["current_liabilities"]), CAP)

    avg_eq = np.nanmean([EQ, _last(equity, 1)]) if len(equity) > 1 else EQ
    avg_a = np.nanmean([A, _last(assets, 1)]) if len(assets) > 1 else A
    out["net_margin"] = _div(NI, R, pos_den=True)
    out["gross_margin"] = _div(_last(f["gross_profit"]), R, pos_den=True)
    out["operating_margin"] = _div(_last(f["operating_income"]), R, pos_den=True)
    out["fcf_margin"] = _div(FCF, R, pos_den=True)
    out["roe"] = _div(NI, avg_eq, pos_den=True)
    out["roa"] = _div(NI, avg_a, pos_den=True)
    out["roic"] = _div(_last(f["operating_income"]) * (1 - TAX), D + EQ, pos_den=True)
    out["ocf_to_assets"] = _div(OCF, avg_a, pos_den=True)
    out["accruals"] = _div(NI - OCF, avg_a, pos_den=True)
    out["capex_to_revenue"] = _div(_last(capex), R, pos_den=True)
    out["rnd_to_revenue"] = _div(_last(f["rnd"].fillna(0)), R, pos_den=True)
    out["payout_ratio"] = _div(_last(f["dividends_paid"].fillna(0)), NI, pos_den=True)

    last5 = slice(-6, None)
    rg = _yoy(rev)[last5]
    eg = _yoy(eps)[last5]
    og = _yoy(ocf)[last5]
    out["revenue_growth_median"] = float(rg.median()) if len(rg) else np.nan
    out["revenue_cagr_3y"] = _cagr(rev.dropna())
    out["eps_growth_median"] = float(eg.median()) if len(eg) else np.nan
    out["eps_cagr_3y"] = _cagr(eps.dropna())
    out["ocf_growth_median"] = float(og.median()) if len(og) else np.nan
    out["ebitda_cagr_3y"] = _cagr(ebitda.dropna())
    margin = (ni / rev).where(rev > 0)
    mc = margin.diff().dropna()[-5:]
    out["margin_change_avg"] = float(mc.mean()) if len(mc) else np.nan
    out["asset_growth"] = _div(A, _last(assets, 1), pos_den=True) - 1 if len(assets) > 1 else np.nan
    out["share_change"] = (
        _div(_last(shares), _last(shares, 1), pos_den=True) - 1 if len(shares) > 1 else np.nan
    )
    e = eps.dropna()
    if len(e):
        peak = e.iloc[-5:].max()
        out["eps_vs_5y_peak"] = e.iloc[-1] / peak - 1 if peak > 0 else np.nan
        out["loss_now"] = float(e.iloc[-1] <= 0)
        out["eps_big_drops"] = float((_yoy(e) < -0.3).sum())
    roa_series = (ni / assets.shift(1)).dropna()[-5:]
    out["roa_volatility"] = float(roa_series.std()) if len(roa_series) >= 3 else np.nan

    out["piotroski_f"] = piotroski(f, shares)
    wc = _last(f["current_assets"]) - _last(f["current_liabilities"])
    L = _last(liab)
    if np.isfinite(A) and A > 0 and np.isfinite(L) and L > 0 and np.isfinite(mcap):
        re_ = _last(f["retained_earnings"])
        ebit = _last(f["operating_income"])
        parts = [
            1.2 * wc / A if np.isfinite(wc) else 0.0,
            1.4 * re_ / A if np.isfinite(re_) else 0.0,
            3.3 * ebit / A if np.isfinite(ebit) else np.nan,
            0.6 * mcap / L,
            1.0 * R / A if np.isfinite(R) else np.nan,
        ]
        out["altman_z"] = float(sum(parts)) if all(np.isfinite(parts)) else np.nan
    out["lynch_category"] = lynch_category(
        eps, out["eps_growth_median"], out["price_to_book"], out["net_cash_to_market_cap"]
    )
    return out


def sector_from_sic(sic: int | None) -> str:
    """Broad sector from the SEC SIC code (close to, not identical with, GICS sectors)."""
    if sic is None or not np.isfinite(sic):
        return "Unknown"
    s = int(sic)
    ranges = [
        ((1300, 1399), "Energy"),
        ((2900, 2999), "Energy"),
        ((1200, 1299), "Energy"),
        ((4610, 4619), "Energy"),
        ((4920, 4925), "Energy"),
        ((2830, 2836), "Health care"),
        ((3840, 3851), "Health care"),
        ((8000, 8099), "Health care"),
        ((5047, 5047), "Health care"),
        ((5122, 5122), "Health care"),
        ((6324, 6324), "Health care"),
        ((8731, 8734), "Health care"),
        ((6798, 6798), "Real estate"),
        ((6500, 6553), "Real estate"),
        ((6000, 6799), "Financials"),
        ((4900, 4919), "Utilities"),
        ((4926, 4949), "Utilities"),
        ((4960, 4991), "Utilities"),
        ((4800, 4899), "Communication"),
        ((2710, 2799), "Communication"),
        ((7810, 7819), "Communication"),
        ((7370, 7379), "Technology"),
        ((3570, 3579), "Technology"),
        ((3660, 3699), "Technology"),
        ((3820, 3829), "Technology"),
        ((3600, 3629), "Technology"),
        ((3630, 3659), "Consumer discretionary"),
        ((2000, 2199), "Consumer staples"),
        ((2840, 2844), "Consumer staples"),
        ((5400, 5499), "Consumer staples"),
        ((5140, 5149), "Consumer staples"),
        ((5912, 5912), "Consumer staples"),
        ((5331, 5331), "Consumer staples"),
        ((5399, 5399), "Consumer staples"),
        ((100, 999), "Consumer staples"),
        ((3710, 3716), "Consumer discretionary"),
        ((2200, 2399), "Consumer discretionary"),
        ((2500, 2599), "Consumer discretionary"),
        ((3140, 3149), "Consumer discretionary"),
        ((3940, 3949), "Consumer discretionary"),
        ((5000, 5999), "Consumer discretionary"),
        ((7000, 7099), "Consumer discretionary"),
        ((7900, 7999), "Consumer discretionary"),
        ((8200, 8299), "Consumer discretionary"),
        ((1500, 1799), "Consumer discretionary"),
        ((1000, 1199), "Materials"),
        ((1400, 1499), "Materials"),
        ((2400, 2499), "Materials"),
        ((2600, 2699), "Materials"),
        ((2800, 2899), "Materials"),
        ((3000, 3099), "Materials"),
        ((3200, 3399), "Materials"),
        ((3400, 3569), "Industrials"),
        ((3580, 3599), "Industrials"),
        ((3700, 3799), "Industrials"),
        ((3800, 3819), "Industrials"),
        ((4000, 4799), "Industrials"),
        ((4950, 4959), "Industrials"),
        ((7300, 7369), "Industrials"),
        ((7380, 7389), "Industrials"),
        ((8700, 8748), "Industrials"),
    ]
    for (lo, hi), name in ranges:
        if lo <= s <= hi:
            return name
    return "Other"
