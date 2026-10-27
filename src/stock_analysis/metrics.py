"""The metrics dictionary (config/metrics.toml): pick a set of metrics, build each stock's vector.

    from stock_analysis import metrics
    d = metrics.load()
    ids = metrics.select(d, "proposed")             # a named set, or a list of ids
    frame = pd.read_csv("data/peers/medtech.csv", index_col=0)
    v = metrics.build_vectors(frame, ids, source="sector", dictionary=d)
    s = metrics.standardize(v, d)                   # 0-100 percentiles, higher = better

`source` says which table the frame is: "sector" (analysis/sector.py, data/sector/*.csv and
data/peers/*.csv), "stage1" (data/screener/stage1.csv; .cache/screener/stage1_full.pkl has
every Stage 1 column), "stage2" (data/screener/top.csv) or
"watchlist" (key_numbers() rows). Metrics the table doesn't have are worked out from other
metrics where the formula allows (DERIVED), otherwise left blank.

Usage:
    uv run python -m stock_analysis.metrics list [--set proposed]
    uv run python -m stock_analysis.metrics doc        # rewrite docs/METRICS.md
    uv run python -m stock_analysis.metrics vector data/peers/medtech.csv --source sector
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/metrics.toml"
DOC = ROOT / "docs/METRICS.md"
SOURCES = ("sector", "stage1", "stage2", "watchlist")
VECTOR_STATUS = ("core", "candidate", "context", "derived")
UNITS = {"$bn", "$", "x", "fraction", "pp", "score", "count", "bool", "category"}

# Metrics that are plain arithmetic on other metrics, for tables that lack the column
DERIVED = {
    "net_debt": lambda v: v["total_debt"] - v["cash"],
    "enterprise_value": lambda v: v["market_cap"] + v["net_debt"],
    "net_margin": lambda v: v["net_income"] / v["revenue"].where(v["revenue"] > 0),
    "fcf_yield": lambda v: v["free_cf"] / v["market_cap"],
    "price_to_sales": lambda v: v["market_cap"] / v["revenue"].where(v["revenue"] > 0),
    "cash_to_total_debt": lambda v: v["cash"] / v["total_debt"].replace(0, np.nan),
    "net_cash_to_market_cap": lambda v: -v["net_debt"] / v["market_cap"],
    "pe_vs_own_median": lambda v: v["pe_adj"] / v["pe_median_10y"] - 1,
}


def load(path: Path = CONFIG) -> dict:
    with open(path, "rb") as f:
        d = tomllib.load(f)
    d["by_id"] = {m["id"]: m for m in d["metric"]}
    return d


def select(d: dict, spec: str | list[str] | None = None) -> list[str]:
    """Metric ids for a named set, an explicit list, a group name or vector status, or all."""
    if spec is None or spec == "all":
        return [m["id"] for m in d["metric"]]
    if isinstance(spec, str):
        if spec in d["sets"]:
            spec = d["sets"][spec]
        elif spec in d["groups"]:
            return [m["id"] for m in d["metric"] if m["group"] == spec]
        elif spec in VECTOR_STATUS:
            return [m["id"] for m in d["metric"] if m["vector"] == spec]
        else:
            raise KeyError(f"no set, group or vector status called {spec!r}")
    unknown = [i for i in spec if i not in d["by_id"]]
    if unknown:
        raise KeyError(f"not in the dictionary: {unknown}")
    return list(spec)


def _source(metric: dict, source: str) -> tuple[str | None, float]:
    s = metric.get("sources", {}).get(source)
    if isinstance(s, dict):
        return s["column"], s.get("scale", 1.0)
    return s, 1.0


def raw_values(frame: pd.DataFrame, source: str, d: dict) -> pd.DataFrame:
    """Every metric the table has, under its metric id, in the dictionary's units."""
    out = {}
    for m in d["metric"]:
        col, scale = _source(m, source)
        if col and col in frame:
            s = frame[col]
            out[m["id"]] = s * scale if scale != 1.0 else s
    v = pd.DataFrame(out, index=frame.index)
    for mid, f in DERIVED.items():
        if mid not in v:
            try:
                v[mid] = f(v)
            except KeyError:
                pass
    return v


def build_vectors(
    frame: pd.DataFrame,
    ids: list[str],
    source: str,
    dictionary: dict | None = None,
    one_hot: bool = True,
) -> pd.DataFrame:
    """One row per stock, one column per chosen metric. Booleans become 0/1; a category
    becomes one 0/1 column per value (`lynch_category=fast_grower`) unless one_hot=False.
    Metrics the table can't supply are blank columns, so every vector has the same shape."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    d = dictionary or load()
    ids = select(d, ids)
    v = raw_values(frame, source, d)
    cols = {}
    for mid in ids:
        s = v[mid] if mid in v else pd.Series(np.nan, index=frame.index)
        unit = d["by_id"][mid]["unit"]
        if unit == "category" and one_hot:
            for value in sorted(s.dropna().unique()):
                cols[f"{mid}={value}"] = (s == value).astype(float).where(s.notna())
            continue
        if unit == "bool":
            s = s.map({True: 1.0, False: 0.0, "True": 1.0, "False": 0.0})
        elif unit != "category":
            s = pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan)
        cols[mid] = s
    return pd.DataFrame(cols, index=frame.index)


def standardize(vectors: pd.DataFrame, d: dict, method: str = "percentile") -> pd.DataFrame:
    """Put metrics on one scale within the group of stocks given.

    percentile: 0-100, with lower-is-better metrics reversed so 100 is always best.
    zscore: (value - mean) / std, sign reversed the same way.
    Metrics with no direction (size, a category) and one-hot columns are left as they are.
    """
    out = vectors.copy()
    for col in vectors:
        m = d["by_id"].get(col)
        if m is None or m["better"] == "none" or m["unit"] in ("category", "bool"):
            continue
        sign = 1 if m["better"] == "higher" else -1
        s = vectors[col] * sign
        if method == "percentile":
            out[col] = s.rank(pct=True) * 100
        elif method == "zscore":
            out[col] = (s - s.mean()) / s.std()
        else:
            raise ValueError("method must be 'percentile' or 'zscore'")
    return out


# --- the readable version -------------------------------------------------------------


def _fmt(value, unit: str) -> str:
    if isinstance(value, bool) or isinstance(value, str):
        return str(value)
    if unit == "$bn":
        return f"${value:,.3g}bn" if abs(value) < 100 else f"${value:,.0f}bn"
    if unit == "$":
        return f"${value:,.2f}"
    if unit == "x":
        return f"{value:.2f}x"
    if unit in ("fraction", "pp"):
        return f"{value * 100:+.1f}{' pp' if unit == 'pp' else '%'}"
    return f"{value:g}"


def _sources_text(m: dict) -> str:
    parts = []
    for k, s in m.get("sources", {}).items():
        col = s["column"] if isinstance(s, dict) else s
        parts.append(f"{k}: `{col}`")
    return "; ".join(parts) or "computed from the formula"


def doc(d: dict) -> str:
    """docs/METRICS.md: the summary list, then one entry per metric."""
    lines = [
        "# Metrics dictionary",
        "",
        "Generated from `config/metrics.toml` by `uv run python -m stock_analysis.metrics doc`;"
        " edit the TOML, not this file. Report 14 explains the choices to make.",
        "",
        d["meta"]["example_note"],
        "",
        "Vector status: **core** = proposed for the first vector, **candidate** = worth"
        " considering, **context** = needed to read the others, **derived** = depends on a"
        " peer group or a model.",
        "",
        "## Summary",
        "",
    ]
    for g, title in d["groups"].items():
        ms = [m for m in d["metric"] if m["group"] == g]
        lines += [f"**{title}** ({len(ms)})", ""]
        lines += ["| Metric | Formula | Better | Vector |", "|---|---|---|---|"]
        for m in ms:
            name = f"[{m['name']}](#{m['id'].replace('_', '-')})"
            lines.append(f"| {name} | {m['formula']} | {m['better']} | {m['vector']} |")
        lines.append("")
    lines += ["## Named sets", ""]
    for name, ids in d["sets"].items():
        lines.append(f"- **{name}** ({len(ids)}): {', '.join(f'`{i}`' for i in ids)}")
    lines += ["", "## Left out", ""]
    lines += [f"- **{k}**: {v}" for k, v in d["excluded"].items()]
    lines += ["", "## Detail", ""]
    for g, title in d["groups"].items():
        lines += [f"### {title}", ""]
        for m in (m for m in d["metric"] if m["group"] == g):
            ex = m["example"]
            lines += [
                f'<a id="{m["id"].replace("_", "-")}"></a>',
                f"#### {m['name']} (`{m['id']}`)",
                "",
                m["definition"],
                "",
                f"- **Formula:** {m['formula']}",
                f"- **Unit:** {m['unit']}; **better:** {m['better']}; **period:** {m['period']}",
                f"- **Source:** {_sources_text(m)}",
                f"- **Used in:** {'; '.join(m['used_in'])}",
                f"- **Example ({ex['symbol']}, {ex['as_of']}):** "
                f"{_fmt(ex['value'], m['unit'])} = {ex['working']}",
                f"- **Vector:** {m['vector']}",
            ]
            if m.get("notes"):
                lines.append(f"- **Note:** {m['notes']}")
            lines.append("")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list", help="print the metrics")
    ls.add_argument("--set", default=None, help="set, group or vector status")
    sub.add_parser("doc", help="rewrite docs/METRICS.md")
    vec = sub.add_parser("vector", help="print the vectors for a table of stocks")
    vec.add_argument("file", help="CSV, e.g. data/peers/medtech.csv")
    vec.add_argument("--source", default="sector", choices=SOURCES)
    vec.add_argument("--set", default="proposed")
    vec.add_argument("--standardize", choices=["percentile", "zscore"])
    vec.add_argument("symbols", nargs="*")
    args = ap.parse_args()
    d = load()
    if args.cmd == "list":
        for i in select(d, args.set):
            m = d["by_id"][i]
            print(f"{i:34} {m['group']:17} {m['vector']:10} {m['formula']}")
    elif args.cmd == "doc":
        DOC.write_text(doc(d) + "\n")
        print(f"wrote {DOC.relative_to(ROOT)}")
    else:
        frame = pd.read_csv(args.file, index_col=0)
        v = build_vectors(frame, args.set, args.source, d)
        if args.standardize:
            v = standardize(v, d, args.standardize)
        if args.symbols:
            v = v.loc[[s for s in v.index if s in args.symbols or s.split(":")[-1] in args.symbols]]
        pd.set_option("display.width", 250)
        print(v.round(3).T.to_string())


if __name__ == "__main__":
    main()
