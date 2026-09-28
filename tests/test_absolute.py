import pandas as pd
from analysis_absolute import DATA, columns, load_config


def test_every_configured_value_exists_in_sector_data():
    header = pd.read_csv(DATA, nrows=0, index_col=0).columns
    missing = [c["column"] for c in columns(load_config()) if c["column"] not in header]
    assert not missing, f"add these to analysis/sector.py or fix the config: {missing}"


def test_config_units_are_known():
    assert {c["unit"] for c in columns(load_config())} <= {"$", "$bn"}


def test_history_names_exist_in_history_data():
    from analysis_absolute import HISTORY

    have = set(pd.read_csv(HISTORY, usecols=["column"])["column"])
    wanted = {c.get("history", c["column"]) for c in columns(load_config())} - {""}
    assert wanted <= have, f"missing from history.csv: {wanted - have}"
