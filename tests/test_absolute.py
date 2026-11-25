from stock_analysis import stocks
from stock_analysis.absolute import columns, load_config


def test_every_configured_value_exists_in_the_rows():
    have = set(stocks.row_columns())
    missing = [c["column"] for c in columns(load_config()) if c["column"] not in have]
    assert not missing, f"add these to stock_analysis/stocks.py or fix the config: {missing}"


def test_config_units_are_known():
    assert {c["unit"] for c in columns(load_config())} <= {"$", "$bn"}


def test_history_names_exist_in_the_history():
    wanted = {c.get("history", c["column"]) for c in columns(load_config())} - {""}
    have = set(stocks.HISTORY_NAMES)
    assert wanted <= have, f"missing from stocks.history: {wanted - have}"
