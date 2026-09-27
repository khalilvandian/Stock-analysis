import httpx
import pytest
import respx

from stock_analysis.fmp import BASE_URL, FMPClient


@respx.mock
def test_quote_sends_api_key_and_returns_first_item():
    route = respx.get(f"{BASE_URL}/quote").mock(
        return_value=httpx.Response(200, json=[{"symbol": "AAPL", "price": 100.0}])
    )
    with FMPClient(api_key="test-key") as client:
        quote = client.quote("AAPL")

    assert quote == {"symbol": "AAPL", "price": 100.0}
    params = route.calls.last.request.url.params
    assert params["symbol"] == "AAPL"
    assert params["apikey"] == "test-key"


@respx.mock
def test_quote_raises_on_empty_response():
    respx.get(f"{BASE_URL}/quote").mock(return_value=httpx.Response(200, json=[]))
    with FMPClient(api_key="test-key") as client, pytest.raises(ValueError):
        client.quote("NOPE")


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.setattr("stock_analysis.fmp.load_dotenv", lambda: None)
    with pytest.raises(RuntimeError):
        FMPClient()
