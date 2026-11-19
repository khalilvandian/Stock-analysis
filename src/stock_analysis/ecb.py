"""The European Central Bank's reference rates (free, no key): the address the ingest job
fetches them from (ingest/market.py, raw_ecb_rate). Scripts read the rates from the database
(stock_analysis.stocks.fx_rates)."""

URL = "https://data-api.ecb.europa.eu/service/data/EXR/D..EUR.SP00.A"
