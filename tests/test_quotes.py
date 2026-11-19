"""Intraday quotes (issue #35): TradingView's rows, the hourly fetch into raw_tv_quote and
v_quote_latest, and the web API's public GET /quotes. HTTP is mocked with respx; the database
tests use the local PostgreSQL test database and skip without it."""

from __future__ import annotations

import json

import httpx
import pandas as pd
import pytest
from test_db import api, empty_db, pg_url  # noqa: F401  (fixtures)
from test_ingest import tv_rows

from stock_analysis import tradingview
from stock_analysis.db import frame
from stock_analysis.ingest import market, quotes

SCAN = tradingview.SCAN_URL.format(market="america")  # the index snapshot
LOOKUP = tradingview.SCAN_URL.format(market="global")  # the quotes, any exchange


def tv_quotes(prices: dict[str, float | None], session: str = "market") -> dict:
    data = [
        {"s": f"NYSE:{s}", "d": [s, p, 1.5, 0.3, 1000, "USD", "delayed_streaming_900", session]}
        for s, p in prices.items()
    ]
    return {"totalCount": len(data), "data": data}


def scan_mock(respx_mock, answers: list[dict]) -> list[dict]:
    """The index snapshot (the US screener) and the lookups (the global one, one answer per
    call, in order). Returns the lookups' request bodies."""
    asked: list[dict] = []

    def reply(request: httpx.Request) -> httpx.Response:
        asked.append(json.loads(request.content))
        return httpx.Response(200, json=answers[min(len(asked), len(answers)) - 1])

    respx_mock.post(SCAN).mock(return_value=httpx.Response(200, json=tv_rows(["AAA", "BBB"])))
    respx_mock.post(LOOKUP).mock(side_effect=reply)
    return asked


def test_delay_from_the_update_mode() -> None:
    assert tradingview.delay_seconds("delayed_streaming_900") == 900
    assert tradingview.delay_seconds("streaming") == 0
    assert tradingview.delay_seconds(None) == 0


def test_rows_without_a_price_are_left_out() -> None:
    d = pd.DataFrame(tv_quotes({"AAA": 10.0, "BBB": None, "CCC": 0})["data"])
    d = pd.DataFrame(d["d"].tolist(), index=d["s"], columns=quotes.FIELDS)
    rows = quotes.quote_rows(d)
    assert rows["symbol"].tolist() == ["AAA"]
    assert rows.loc[0, "delay_s"] == 900 and rows.loc[0, "session"] == "market"


@pytest.fixture()
def fresh(pg_url: str):  # noqa: F811
    db = empty_db(pg_url)
    db.migrate()
    yield db
    db.close()


def with_members(db) -> None:
    with db.begin() as conn, httpx.Client() as http:
        market.load_constituents(conn, http, "america", "SP:SPX")


def test_quotes_are_stored_once_per_change_of_price(fresh, respx_mock) -> None:
    asked = scan_mock(
        respx_mock,
        [tv_quotes({"AAA": 10.0, "BBB": 20.0}), tv_quotes({"AAA": 10.0, "BBB": 20.0}),
         tv_quotes({"AAA": 11.0, "BBB": 20.0}, session="post_market")],
    )  # fmt: skip
    with_members(fresh)
    first = quotes.fetch_quotes(fresh, http=httpx.Client())
    assert first["status"] == "ok" and first["stored"] == 2
    assert asked[0]["symbols"]["tickers"] == ["NYSE:AAA", "NYSE:BBB"]  # the index, not ZZZ
    assert quotes.fetch_quotes(fresh, http=httpx.Client())["status"] == "unchanged"
    assert quotes.fetch_quotes(fresh, http=httpx.Client())["stored"] == 2
    with fresh.connect() as conn:
        latest = frame(conn, "SELECT symbol, price, session, price_at FROM v_quote_latest")
        kept = frame(conn, "SELECT COUNT(*) AS n FROM raw_payload p JOIN raw_fetch f "
                     "USING (fetch_id) WHERE f.source = 'tradingview_quotes'")  # fmt: skip
    latest = latest.set_index("symbol")
    assert latest.loc["AAA", "price"] == 11.0
    assert latest.loc["AAA", "session"] == "post_market"
    assert pd.isna(latest.loc["AAA", "price_at"])  # after the close: the latest close
    assert kept["n"][0] == 2


def test_every_company_in_the_database_is_quoted(fresh, respx_mock) -> None:
    """Not only the index: a company that left it, or another share class, is in core_company
    and keeps its price; one with no listing anywhere is left out."""
    asked = scan_mock(respx_mock, [tv_quotes({"AAA": 10.0, "BBB": 20.0, "OLD": 5.0})])
    with_members(fresh)
    with fresh.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO core_company (symbol, name, exchange, currency) VALUES "
            "('OLD', 'Left the index', 'NYSE', 'USD'), ('AAA', 'AAA Corp', 'NYSE', 'USD'), "
            "('NOEX', 'No listing', NULL, 'USD')"
        )
    assert quotes.fetch_quotes(fresh, http=httpx.Client())["stored"] == 3
    assert asked[0]["symbols"]["tickers"] == ["NYSE:AAA", "NYSE:BBB", "NYSE:OLD"]
    with fresh.connect() as conn:
        stored = frame(conn, "SELECT symbol FROM raw_tv_quote ORDER BY symbol")
    assert stored["symbol"].tolist() == ["AAA", "BBB", "OLD"]


def test_a_sample_and_a_failure(fresh, respx_mock) -> None:
    asked = scan_mock(respx_mock, [tv_quotes({"BBB": 20.0})])
    with_members(fresh)
    assert quotes.fetch_quotes(fresh, ["bbb"], http=httpx.Client())["stored"] == 1
    assert asked[0]["symbols"]["tickers"] == ["NYSE:BBB"]
    respx_mock.post(LOOKUP).mock(return_value=httpx.Response(429))
    out = quotes.fetch_quotes(fresh, http=httpx.Client())
    assert out["status"] == "error" and "429" in out["error"]
    with fresh.connect() as conn:
        errors = frame(conn, "SELECT status FROM raw_fetch WHERE source = 'tradingview_quotes' "
                       "AND status = 'error'")  # fmt: skip
    assert len(errors) == 1


def test_api_serves_the_latest_quotes_without_a_key(fresh, api, respx_mock) -> None:  # noqa: F811
    scan_mock(respx_mock, [tv_quotes({"AAA": 10.0, "BBB": 20.0})])
    with_members(fresh)
    quotes.fetch_quotes(fresh, http=httpx.Client())
    origin = {"Origin": "https://khalilvandian.github.io"}
    answer = api.get("/quotes", headers=origin)
    assert answer.status_code == 200
    assert answer.headers["access-control-allow-origin"] == origin["Origin"]
    body = answer.json()
    assert body["columns"] == ["price", "change_pct", "session", "price_at", "delay_s", "currency"]
    assert body["quotes"]["AAA"][:3] == [10.0, 1.5, "market"]
    assert body["quotes"]["AAA"][4:] == [900, "USD"]
    assert body["fetched_at"]
    other = api.get("/quotes", headers={"Origin": "https://example.com"})
    assert "access-control-allow-origin" not in other.headers
    assert api.post("/query", json={"sql": "SELECT 1"}).status_code == 401  # still keyed
