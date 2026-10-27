import numpy as np
import pandas as pd
import pytest

from stock_analysis import metrics

ROOT = metrics.ROOT
# Columns made at run time by analysis/screen.py rather than saved by sector.py
SCREEN_COLUMNS = {"debt_score", "quality_score", "cheap_score", "total_score", "pe_rel", "ev_rel",
                  "pe_change_expected"}  # fmt: skip


@pytest.fixture(scope="module")
def d():
    return metrics.load()


def test_ids_are_unique(d):
    ids = [m["id"] for m in d["metric"]]
    assert len(ids) == len(set(ids))


def test_every_metric_is_complete(d):
    for m in d["metric"]:
        for key in ("name", "group", "unit", "better", "period", "definition", "formula"):
            assert m.get(key) not in (None, ""), f"{m['id']}: {key}"
        assert m["group"] in d["groups"], m["id"]
        assert m["unit"] in metrics.UNITS, m["id"]
        assert m["better"] in ("higher", "lower", "none"), m["id"]
        assert m["vector"] in metrics.VECTOR_STATUS, m["id"]
        assert m["used_in"], m["id"]
        assert {"symbol", "value", "as_of", "working"} <= set(m["example"]), m["id"]


def test_sets_name_known_metrics(d):
    for name, ids in d["sets"].items():
        assert metrics.select(d, name) == ids
    with pytest.raises(KeyError):
        metrics.select(d, ["not_a_metric"])


def test_sector_columns_exist():
    d = metrics.load()
    header = set(pd.read_csv(ROOT / "data/peers/medtech.csv", nrows=0).columns)
    screen_src = (ROOT / "analysis/screen.py").read_text()
    for m in d["metric"]:
        col, _ = metrics._source(m, "sector")
        if col in SCREEN_COLUMNS:
            assert f'"{col}"' in screen_src, col
        elif col:
            assert col in header, f"{m['id']}: sector column {col} missing"


def test_build_vectors_maps_scales_and_derives(d):
    frame = pd.DataFrame(
        {
            "return_on_equity_fq": [15.5, 8.0],
            "category": ["fast_grower", "stalwart"],
            "loss_now": [False, True],
            "net_debt_usd_bn": [12.0, -1.0],
            "cap_usd_bn": [60.0, 10.0],
            "cash_to_short_term_debt": [0.3, np.inf],
        },
        index=["NYSE:BSX", "NYSE:XYZ"],
    )
    ids = ["roe", "lynch_category", "loss_now", "net_cash_to_market_cap",
           "cash_to_short_term_debt", "altman_z"]  # fmt: skip
    v = metrics.build_vectors(frame, ids, "stage1", d)
    assert v.loc["NYSE:BSX", "roe"] == pytest.approx(0.155)
    assert v.loc["NYSE:BSX", "lynch_category=fast_grower"] == 1.0
    assert v.loc["NYSE:XYZ", "lynch_category=fast_grower"] == 0.0
    assert v.loc["NYSE:XYZ", "loss_now"] == 1.0
    assert v.loc["NYSE:BSX", "net_cash_to_market_cap"] == pytest.approx(-0.2)
    assert v.loc["NYSE:XYZ", "cash_to_short_term_debt"] == 50.0  # no debt: inf -> ceiling
    assert v["altman_z"].isna().all()  # not in the table: blank column, same shape
    raw = metrics.build_vectors(frame, ["cash_to_short_term_debt"], "stage1", d, clip=False)
    assert np.isnan(raw.loc["NYSE:XYZ", "cash_to_short_term_debt"])  # unclipped inf: blank


def test_clip_net_debt_at_zero_and_cover_at_50(d):
    frame = pd.DataFrame(
        {
            "net_debt_to_ebitda": [-3.0, 2.0, np.nan],
            "interest_cover": [400.0, 8.0, np.inf],
            "net_debt_to_avg_ebitda": [-1.0, 3.0, 1.0],
        },
        index=["net_cash", "levered", "no_debt"],
    )
    ids = ["net_debt_to_ebitda", "interest_cover", "net_debt_to_avg_ebitda"]
    v = metrics.build_vectors(frame, ids, "stage1", d)
    assert v["net_debt_to_ebitda"].tolist()[:2] == [0.0, 2.0]
    assert np.isnan(v.loc["no_debt", "net_debt_to_ebitda"])
    assert v["interest_cover"].tolist() == [50.0, 8.0, 50.0]
    assert v["net_debt_to_avg_ebitda"].tolist() == [0.0, 3.0, 1.0]


def test_cash_growth_is_context_not_proposed(d):
    for mid in ("cash_growth_avg", "cash_growth_median"):
        assert d["by_id"][mid]["vector"] == "context"
        assert mid not in d["sets"]["proposed"]


def test_standardize_puts_best_at_100(d):
    v = pd.DataFrame({"net_debt_to_ebitda": [1.0, 3.0], "interest_cover": [2.0, 9.0]})
    s = metrics.standardize(v, d)
    assert s["net_debt_to_ebitda"].tolist() == [100.0, 50.0]  # lower is better
    assert s["interest_cover"].tolist() == [50.0, 100.0]


def test_doc_is_up_to_date(d):
    assert metrics.DOC.read_text() == metrics.doc(d) + "\n", (
        "run: python -m stock_analysis.metrics doc"
    )
