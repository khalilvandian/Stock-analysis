"""Predictive analysis of S&P 500 stocks: which inputs at year t predict a "good" investment
over years t+1..t+5? (issue #10, report 15, docs/PREDICT.md)

Steps (each one caches its result, so later steps can be rerun alone):
  resolve   historical S&P 500 members -> SEC CIK and Yahoo symbol (data/predict/universe.csv)
  download  SEC company facts, SEC profiles and Yahoo prices into .cache/predict/
  build     point-in-time panel of features and labels (data/predict/panel.csv.gz)
  study     compare the candidate labels (data/predict/results/label_*.csv)
  models    correlations and walk-forward models (data/predict/results/*.csv, figures)
  behaviour how the 5-year holdings were distributed, and the shapes of their paths
  all       everything above

Usage: uv run python analysis/predict.py all
"""

from __future__ import annotations

import argparse
import warnings

import numpy as np
import pandas as pd

from stock_analysis.predict import DATA, ROOT, behaviour, load_config, models, study
from stock_analysis.predict.dataset import _load_prices, add_growth_labels, build
from stock_analysis.predict.download import download_all, resolve_universe

PANEL = DATA / "panel.csv.gz"
RESULTS = DATA / "results"
FIGURES = ROOT / "reports/figures/15"

# reference palette (dataviz skill): blue, orange, aqua; text and surface
BLUE, ORANGE, AQUA, GREY = "#2a78d6", "#eb6834", "#1baf7a", "#a3a29c"
YELLOW, MAGENTA = "#eda100", "#e87ba4"
INK, INK2, SURFACE = "#0b0b0b", "#52514e", "#fcfcfb"


def load_panel() -> pd.DataFrame:
    return pd.read_csv(PANEL, low_memory=False)


def _save(df: pd.DataFrame, name: str, index: bool = True) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    df.to_csv(RESULTS / f"{name}.csv", index=index, float_format="%.4f")


def run_study(panel: pd.DataFrame) -> None:
    u = panel[panel.usable & panel.y5_cagr.notna()]
    _save(study.label_correlations(u), "label_correlations")
    vw, share = study.volatile_winners(u)
    vw["volatile_winner_share_of_top_fifth"] = share
    _save(vw, "label_volatile_winners", index=False)
    _save(study.regime_dependence(u), "label_by_cohort")
    _save(study.persistence(u).rename("persistence").to_frame(), "label_persistence")
    _save(study.learnability(u), "label_learnability", index=False)
    # sensitivity of the primary label to the drawdown margin
    rows = []
    for margin in (0.0, 0.10, 0.15, 0.20, 0.30):
        good = (u.y5_excess_cagr > 0) & (u.y5_dd_vs_index <= margin)
        rows.append(
            {
                "dd_margin": margin,
                "base_rate": good.mean(),
                "avg_excess_cagr_of_good": u.y5_excess_cagr[good].mean(),
                "avg_max_dd_of_good": u.y5_max_dd[good].mean(),
                "share_of_beaters_kept": good.sum() / (u.y5_excess_cagr > 0).sum(),
            }
        )
    _save(pd.DataFrame(rows), "label_margin_sensitivity", index=False)

    # growth labels (Babak, 2026-10-28: the goal is long-term predictable growth)
    fixed = models.fixed_score(u, models.FIXED_SCORES["Quality + calm"])
    _save(study.growth_label_study(u, fixed), "growth_labels", index=False)
    q = fixed.groupby(u.cohort).transform(
        lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1
    )
    cols = [f"y5_{c}" for c in study.GROWTH_LABELS]
    _save(u.groupby(q)[cols].median().rename_axis("quality_calm_fifth"), "growth_by_quality_calm")


def run_models(panel: pd.DataFrame, cfg: dict) -> None:
    seed = cfg["experiments"]["seed"]
    min_train = cfg["experiments"]["min_train_cohorts"]
    u = panel[panel.usable]
    u5 = u[u.y5_cagr.notna()]
    u1 = u[u.y1_cagr.notna()]

    # 1. univariate correlations (in-sample, descriptive)
    for lab, df in [
        ("y5_good", u5),
        ("y5_martin", u5),
        ("y5_excess_cagr", u5),
        ("y5_max_dd", u5),
        ("y1_excess_cagr", u1),
    ]:
        _save(models.univariate_ic(df, lab), f"ic_{lab}", index=False)
    top = models.univariate_ic(u5, "y5_good").feature.head(12).tolist()
    q = pd.DataFrame({f: models.quintile_table(u5, f, "y5_good") for f in top}).T
    q.columns = [f"Q{int(c)}" for c in q.columns]
    _save(q, "quintiles_y5_good")
    qe = pd.DataFrame({f: models.quintile_table(u5, f, "y5_excess_cagr") for f in top}).T
    qe.columns = [f"Q{int(c)}" for c in qe.columns]
    _save(qe, "quintiles_y5_excess_cagr")

    # Babak's strict screen as a ready-made rule
    s = models.strict_screen(u5)
    screen = u5.groupby(s).agg(
        rows=("y5_good", "size"),
        good_rate=("y5_good", "mean"),
        beat_index_rate=("y5_beat_index", "mean"),
        avg_excess_cagr=("y5_excess_cagr", "mean"),
        avg_max_dd=("y5_max_dd", "mean"),
    )
    screen.index = screen.index.map({0.0: "fails strict screen", 1.0: "passes strict screen"})
    _save(screen, "strict_screen_y5")

    # 2. walk-forward models
    jobs = [
        ("y5_good", u5, 5, "classification"),
        ("y5_martin", u5, 5, "regression"),
        ("y5_excess_cagr", u5, 5, "regression"),
        ("y1_good", u1, 1, "classification"),
        ("y1_excess_cagr", u1, 1, "regression"),
        ("y5_k_ratio", u5, 5, "regression"),
    ]
    for lab, df, h, kind in jobs:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            sc, preds = models.walk_forward(df, lab, h, kind, seed=seed, min_train=min_train)
        _save(sc, f"wf_scores_{lab}", index=False)
        _save(models.summarise(sc), f"wf_summary_{lab}")
        preds.to_csv(RESULTS / f"wf_predictions_{lab}.csv.gz", index=False)

    # single-feature baselines for the primary label (no fitting: rank by the feature)
    rows = []
    for f, sign in [
        ("vol_1y", -1),
        ("beta_3y", -1),
        ("max_dd_3y", -1),
        ("piotroski_f", 1),
        ("earnings_yield", 1),
        ("mom_12_1", 1),
        ("roa", 1),
    ]:
        for t in models.test_cohorts(u5, 5, min_train):
            g = u5[u5.cohort == t]
            x = (sign * g[f]).fillna((sign * g[f]).median())
            from sklearn.metrics import roc_auc_score

            rows.append({"feature": f, "cohort": t, "auc": roc_auc_score(g.y5_good, x)})
    base = pd.DataFrame(rows).groupby("feature").auc.agg(["mean", "min", "max"])
    _save(base.sort_values("mean", ascending=False), "baselines_y5_good")

    # fixed, unfitted scores (every cohort is out of sample for the weights)
    summary = []
    for name, spec in models.FIXED_SCORES.items():
        ev = models.evaluate_score(u5, models.fixed_score(u5, spec))
        ev.insert(0, "score", name)
        summary.append(ev)
    ev = pd.concat(summary)
    _save(ev, "fixed_scores_y5", index=False)
    tests = models.test_cohorts(u5, 5, min_train)
    agg = pd.concat(
        {
            "all cohorts 2010-2021": ev.groupby("score").mean(numeric_only=True),
            "test cohorts 2016-2021": ev[ev.cohort.isin(tests)]
            .groupby("score")
            .mean(numeric_only=True),
        }
    ).drop(columns="cohort")
    _save(agg, "fixed_scores_y5_summary")

    # 3. what the models use
    for lab, df, h, kind in jobs[:3]:
        _save(models.importance(df, lab, h, kind, seed, min_train), f"importance_{lab}")

    # 4. an interpretable tree on all labelled rows (rules, not a forecast)
    from sklearn.tree import DecisionTreeClassifier, export_text

    X = models.design(u5)
    tree = DecisionTreeClassifier(max_depth=3, min_samples_leaf=150, random_state=seed)
    tree.fit(X, u5.y5_good)
    (RESULTS / "tree_y5_good.txt").write_text(
        export_text(tree, feature_names=list(X.columns), show_weights=True)
    )

    # 5. survivorship: how many members have no outcome, and how index leavers did
    cov = panel.groupby("cohort").apply(
        lambda g: pd.Series(
            {
                "members": len(g),
                "usable": int(g.usable.sum()),
                "no_prices": int((~g.has_prices).sum()),
                "no_prices_share": (~g.has_prices).mean(),
                "left_index_later_with_prices": int((g.left_index.notna() & g.has_prices).sum()),
            }
        )
    )
    _save(cov, "coverage")
    lv = (
        u5.assign(left=u5.left_index.notna())
        .groupby("left")
        .agg(
            rows=("y5_good", "size"),
            good_rate=("y5_good", "mean"),
            avg_excess_cagr=("y5_excess_cagr", "mean"),
            avg_max_dd=("y5_max_dd", "mean"),
        )
    )
    lv.index = lv.index.map({False: "still in the index", True: "left the index later"})
    _save(lv, "leavers_y5")
    figures(panel)


def _plt():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.edgecolor": GREY,
            "axes.labelcolor": INK2,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.grid": True,
            "grid.color": "#e6e5e0",
            "grid.linewidth": 0.6,
        }
    )
    return plt


def figures(panel: pd.DataFrame) -> None:
    plt = _plt()

    # learnability by label
    L = pd.read_csv(RESULTS / "label_learnability.csv")
    gb = L[L.model == "Gradient boosting"].set_index("label").ic
    names = {k: v for k, v in study.CANDIDATES.items()}
    gb = gb.sort_values()
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = [BLUE if k in ("good", "martin") else GREY for k in gb.index]
    ax.barh([names[k] for k in gb.index], gb.values, color=colors, height=0.6)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("Out-of-sample rank correlation, prediction vs outcome")
    fig.suptitle(
        "How learnable is each label? Gradient boosting, test years 2016-2021",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "label_learnability.png", dpi=150)
    plt.close(fig)

    # out-of-sample AUC per cohort for the primary label
    sc = pd.read_csv(RESULTS / "wf_scores_y5_good.csv")
    fig, ax = plt.subplots(figsize=(7, 4))
    for m, c in [("Gradient boosting", BLUE), ("Logistic (L2)", ORANGE)]:
        s = sc[sc.model == m]
        ax.plot(s.cohort, s.auc, marker="o", color=c, linewidth=2, markersize=6, label=m)
    fx = pd.read_csv(RESULTS / "fixed_scores_y5.csv")
    fx = fx[(fx.score == "Quality + calm") & fx.cohort.isin(sc.cohort.unique())]
    ax.plot(
        fx.cohort,
        fx.auc_good,
        marker="o",
        color=AQUA,
        linewidth=2,
        markersize=6,
        label="Quality + calm score (fixed, 4 features)",
    )
    ax.axhline(0.5, color=INK2, linewidth=0.8, linestyle="--")
    ax.text(sc.cohort.min(), 0.505, "no skill", color=INK2, fontsize=9)
    ax.set_xlabel("Decision year (outcome judged over the next 5 years)")
    ax.set_ylabel("AUC")
    ax.set_title('Out-of-sample AUC for "good investment"', loc="left", color=INK, fontsize=11)
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIGURES / "auc_by_cohort.png", dpi=150)
    plt.close(fig)

    # good-rate by quintile of the strongest features
    q = pd.read_csv(RESULTS / "quintiles_y5_good.csv", index_col=0).head(6)
    fig, axes = plt.subplots(2, 3, figsize=(9, 5), sharey=True)
    for ax, (f, row) in zip(axes.ravel(), q.iterrows(), strict=False):
        ax.bar(range(1, 6), row.values, color=BLUE, width=0.7)
        ax.set_title(f, fontsize=10, color=INK)
        ax.set_xticks(range(1, 6))
        ax.set_xticklabels(["low", "", "", "", "high"])
    for ax in axes[:, 0]:
        ax.set_ylabel('Share "good"')
    fig.suptitle(
        'Share of "good" 5-year outcomes by quintile of each feature',
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "quintiles_good.png", dpi=150)
    plt.close(fig)


def run_behaviour(panel: pd.DataFrame, cfg: dict) -> None:
    """How the 5-year holdings behaved: distributions, path shapes, cohorts, sectors."""
    u = panel[panel.usable & panel.y5_cagr.notna()].copy()
    paths = behaviour.paths(u, _load_prices)
    u = u.loc[paths.index]
    u["shape"] = [
        behaviour.shape(paths.loc[i].to_numpy(), u.at[i, "y5_trend_r2"], u.at[i, "y5_max_dd"])
        for i in u.index
    ]
    spy = _load_prices(cfg["labels"]["benchmark"])
    spy_paths = pd.DataFrame(
        {
            c: behaviour.path(spy, pd.Timestamp(d))
            for c, d in u.groupby("cohort").date.first().items()
        }
    ).T
    _save(behaviour.distribution(u), "behaviour_distribution", index=False)
    _save(behaviour.wealth_bands(u), "behaviour_wealth_bands")
    _save(
        behaviour.concentration(u).rename("share_of_total_gain").to_frame(),
        "behaviour_concentration",
    )
    _save(behaviour.by_cohort(u), "behaviour_by_cohort")
    _save(behaviour.by_sector(u), "behaviour_by_sector")
    _save(behaviour.shape_table(u), "behaviour_shapes")
    _save(
        pd.crosstab(u.cohort, u["shape"], normalize="index")[list(behaviour.SHAPES)],
        "behaviour_shapes_by_cohort",
    )
    _save(behaviour.persistence_of_shape(u), "behaviour_shape_persistence")
    u[["cohort", "ticker", "name", "sector", "shape"]].to_csv(
        RESULTS / "behaviour_holdings.csv", index=False
    )
    behaviour_figures(u, paths, spy_paths)


def behaviour_figures(u: pd.DataFrame, paths: pd.DataFrame, spy_paths: pd.DataFrame) -> None:
    plt = _plt()
    months = paths.columns.to_numpy()

    # 1. fan chart of every 5-year path
    fig, ax = plt.subplots(figsize=(8, 4.8))
    q = paths.quantile([0.1, 0.25, 0.5, 0.75, 0.9]).T
    ax.fill_between(months, q[0.1], q[0.9], color=BLUE, alpha=0.15, linewidth=0, label="middle 80%")
    ax.fill_between(
        months, q[0.25], q[0.75], color=BLUE, alpha=0.3, linewidth=0, label="middle 50%"
    )
    ax.plot(months, q[0.5], color=BLUE, linewidth=2, label="median stock")
    ax.plot(
        months, spy_paths.median(), color=ORANGE, linewidth=2, label="S&P 500 (median start year)"
    )
    ax.set_yscale("log")
    ticks = [0.5, 0.75, 1, 1.5, 2, 3]
    ax.set_yticks(ticks, [f"${t:g}" for t in ticks])
    ax.minorticks_off()
    ax.set_xticks(range(0, 61, 12), [f"year {k}" for k in range(6)])
    ax.set_ylabel("Value of $1 (log scale)")
    ax.legend(frameon=False, loc="upper left")
    ax.set_title(
        f"Every 5-year holding of an S&P 500 member, 2010-2021 starts ({len(paths):,})",
        loc="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "behaviour_fan.png", dpi=150)
    plt.close(fig)

    # 2. distributions of the main measures, with the S&P 500 (median over start years)
    spy = {
        "y5_cagr": (u.y5_cagr - u.y5_excess_cagr).groupby(u.cohort).median().median(),
        "y5_max_dd": (u.y5_max_dd - u.y5_dd_vs_index).groupby(u.cohort).median().median(),
    }
    panels = [
        ("y5_cagr", "Total return per year", 100, (-0.4, 0.6)),
        ("y5_max_dd", "Worst fall from a peak", 100, (0, 1)),
        ("y5_worst_12m", "Worst 12-month return", 100, (-0.9, 0.3)),
        ("y5_trend_r2", "Steadiness of the climb (R²)", 1, (0, 1)),
        ("y5_k_ratio", "K-ratio (growth per unit of wobble)", 1, (-3, 7)),
        ("y5_revenue_cagr_fwd", "Revenue growth per year", 100, (-0.2, 0.4)),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.6))
    for ax, (col, title, scale, lim) in zip(axes.ravel(), panels, strict=True):
        s = u[col].dropna().clip(*lim)
        ax.hist(s * scale, bins=40, color=BLUE, edgecolor=SURFACE, linewidth=0.5)
        med = u[col].median()
        ax.axvline(med * scale, color=INK, linewidth=1.2)
        ax.text(
            med * scale,
            ax.get_ylim()[1] * 0.95,
            f" median {med * scale:.{0 if scale == 100 else 2}f}{'%' if scale == 100 else ''}",
            color=INK,
            fontsize=8,
            va="top",
        )
        if col in spy:
            ax.axvline(spy[col] * scale, color=ORANGE, linewidth=1.5, linestyle="--")
            ax.text(
                spy[col] * scale,
                ax.get_ylim()[1] * 0.6,
                f" S&P 500 {spy[col] * 100:.0f}%",
                color=INK2,
                fontsize=8,
                va="top",
            )
        ax.set_title(title + (" (%)" if scale == 100 else ""), loc="left", fontsize=10, color=INK)
        ax.set_yticks([])
        ax.grid(False)
    fig.suptitle(
        "How the 4,457 five-year holdings were distributed (end bars hold values beyond the axis)",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "behaviour_distributions.png", dpi=150)
    plt.close(fig)

    # 3. the five shapes: median path and middle half
    fig, axes = plt.subplots(1, 5, figsize=(12, 3.4), sharey=True)
    names = {
        "steady_climb": "Steady climb",
        "bumpy_climb": "Bumpy climb",
        "faded": "Rose then faded",
        "round_trip": "Round trip",
        "decline": "Decline",
    }
    for ax, k in zip(axes, behaviour.SHAPES, strict=True):
        pk = paths[u["shape"] == k]
        q = pk.quantile([0.25, 0.5, 0.75]).T
        ax.fill_between(months, q[0.25], q[0.75], color=BLUE, alpha=0.25, linewidth=0)
        ax.plot(months, q[0.5], color=BLUE, linewidth=2)
        ax.plot(months, spy_paths.median(), color=ORANGE, linewidth=1.2, linestyle="--")
        ax.axhline(1, color=INK2, linewidth=0.6)
        ax.set_yscale("log")
        ax.set_yticks(ticks, [f"${t:g}" for t in ticks])
        ax.minorticks_off()
        ax.set_xticks(range(0, 61, 12), [str(k) for k in range(6)])
        ax.set_title(
            f"{names[k]}\n{len(pk) / len(paths):.0%} of holdings",
            loc="left",
            fontsize=10,
            color=INK,
        )
        ax.set_xlabel("years")
    axes[0].set_ylabel("Value of $1 (median, middle half)")
    fig.suptitle(
        "Five shapes of a 5-year holding (dashed: S&P 500)",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
    )
    fig.tight_layout()
    fig.savefig(FIGURES / "behaviour_shapes.png", dpi=150)
    plt.close(fig)

    # 4. shapes by start year
    t = pd.crosstab(u.cohort, u["shape"], normalize="index")[list(behaviour.SHAPES)]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bottom = np.zeros(len(t))
    for k, c in zip(behaviour.SHAPES, [AQUA, BLUE, YELLOW, MAGENTA, ORANGE], strict=True):
        ax.bar(
            t.index,
            t[k],
            bottom=bottom,
            color=c,
            width=0.8,
            label=names[k],
            edgecolor=SURFACE,
            linewidth=1,
        )
        bottom += t[k].to_numpy()
    ax.set_xticks(t.index)
    ax.set_ylabel("Share of holdings")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.1), fontsize=9)
    ax.set_title(
        "Shape of the next 5 years, by start year (June 30)", loc="left", color=INK, fontsize=11
    )
    ax.grid(False)
    fig.tight_layout()
    fig.savefig(FIGURES / "behaviour_by_cohort.png", dpi=150)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "step", choices=["resolve", "download", "build", "study", "models", "behaviour", "all"]
    )
    args = ap.parse_args()
    cfg = load_config()
    if args.step in ("resolve", "all"):
        uni = resolve_universe(cfg)
        print(uni.method.str.split(":").str[0].value_counts().to_string())
    if args.step in ("download", "all"):
        download_all(pd.read_csv(ROOT / cfg["universe"]["resolved"]), cfg)
    if args.step in ("build", "all"):
        panel = add_growth_labels(build(cfg), cfg)
        panel.to_csv(PANEL, index=False, float_format="%.6g")
        print(f"panel: {len(panel)} rows, {int(panel.usable.sum())} usable -> {PANEL}")
    if args.step in ("study", "all"):
        run_study(load_panel())
    if args.step in ("models", "all"):
        np.random.seed(cfg["experiments"]["seed"])
        run_models(load_panel(), cfg)
        print(f"results -> {RESULTS}, figures -> {FIGURES}")
    if args.step in ("behaviour", "all"):
        run_behaviour(load_panel(), cfg)


if __name__ == "__main__":
    main()
