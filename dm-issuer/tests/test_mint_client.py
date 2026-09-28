"""Phase I — mint_client: mock HTTP tests for the Cashu mint REST client
(spec §5 DM-MINT-1 + §3 of the bolt11 quote endpoints).

The MintClient receives an ``http_client`` callable per request that
returns an object exposing ``request(method, url, ...)
-> MockResponse(status_code, json_body, text)``.  Tests inject mocks that
emulate the Cashu API responses for the quote endpoints.
"""
import asyncio
import json
from typing import Optional

import pytest

from tollgate_dm_issuer.mint_client import (
    MintClient,
    MintError,
    Quote,
    QuoteState,
)


class MockResponse:
    def __init__(self, status_code: int, json_body: Optional[dict] = None,
                 text: str = ""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text or (json.dumps(json_body) if json_body else "")

    def json(self) -> dict:
        return self._json


class MockHttp:
    """Records requests and returns scripted responses based on URL/method."""

    def __init__(self):
        self.calls = []
        self.responses: dict[tuple[str, str], list[MockResponse]] = {}

    def set(self, method: str, path_regex: str, *responses: MockResponse):
        self.responses.setdefault((method.upper(), path_regex), []).extend(responses)

    async def request(self, method: str, url: str, **kwargs):
        path = url
        for (m, regex), responses in list(self.responses.items()):
            if m != method.upper():
                continue
            try:
                import re as _re
                mid_regex = regex
                if regex in url:  # exact substring match
                    if responses:
                        r = responses.pop(0) if len(responses) > 1 else responses[0]
                        self.calls.append((method.upper(), url, kwargs))
                        return r
            except Exception as exc:
                raise RuntimeError(f"MockHttp regex error: {exc}") from exc
        self.calls.append((method.upper(), url, kwargs))
        raise RuntimeError(f"MockHttp: unexpected request {method} {url}")


@pytest.fixture
def http():
    return MockHttp()


@pytest.fixture
def client(http):
    return MintClient(base_url="https://mint.example.test",
                     http_request=http.request,
                     retries=3, backoff_base_secs=0.0, timeout=1.0)


class TestCreateQuote:
    @pytest.mark.asyncio
    async def test_returns_quote_id_on_200(self, client, http):
        http.set("POST", "/v1/mint/quote/bolt11",
                 MockResponse(200, {"quote": "q-abc", "amount": 5000,
                                    "state": "UNPAID"}))
        q = await client.create_quote(5000)
        assert isinstance(q, Quote)
        assert q.quote_id == "q-abc"
        assert q.state == QuoteState.UNPAID

    @pytest.mark.asyncio
    async def test_request_body_includes_amount_and_sat_unit(self, client, http):
        http.set("POST", "/v1/mint/quote/bolt11",
                 MockResponse(200, {"quote": "q1", "state": "UNPAID"}))
        await client.create_quote(7500)
        method, url, kwargs = http.calls[-1]
        assert method == "POST"
        assert url == "https://mint.example.test/v1/mint/quote/bolt11"
        body = kwargs.get("json", {})
        assert body.get("amount") == 7500
        assert body.get("unit") == "sat"

    @pytest.mark.asyncio
    async def test_5xx_retries_then_succeeds(self, client, http):
        http.set("POST", "/v1/mint/quote/bolt11",
                 MockResponse(503), MockResponse(200, {"quote": "q1",
                                                       "state": "UNPAID"}))
        q = await client.create_quote(1000)
        assert q.quote_id == "q1"

    @pytest.mark.asyncio
    async def test_5xx_exhausts_retries_raises_mint_error(self, client, http):
        http.set("POST", "/v1/mint/quote/bolt11",
                 MockResponse(500), MockResponse(500),
                 MockResponse(500), MockResponse(500))
        with pytest.raises(MintError):
            await client.create_quote(1000)

    @pytest.mark.asyncio
    async def test_4xx_raises_mint_error_immediately(self, client, http):
        http.set("POST", "/v1/mint/quote/bolt11",
                 MockResponse(400, {"detail": "bad amount"}))
        with pytest.raises(MintError):
            await client.create_quote(1000)


class TestGetQuoteState:
    @pytest.mark.asyncio
    async def test_returns_quotestate_paid(self, client, http):
        http.set("GET", "/v1/mint/quote/bolt11/q1",
                 MockResponse(200, {"quote": "q1", "state": "PAID",
                                    "amount": 1000}))
        state = await client.get_quote_state("q1")
        assert state == QuoteState.PAID

    @pytest.mark.asyncio
    async def test_returns_quotestate_unpaid(self, client, http):
        http.set("GET", "/v1/mint/quote/bolt11/q2",
                 MockResponse(200, {"quote": "q2", "state": "UNPAID"}))
        state = await client.get_quote_state("q2")
        assert state == QuoteState.UNPAID

    @pytest.mark.asyncio
    async def test_404_raises_mint_error(self, client, http):
        http.set("GET", "/v1/mint/quote/bolt11/q-missing",
                 MockResponse(404, {"detail": "not found"}))
        with pytest.raises(MintError):
            await client.get_quote_state("q-missing")


class TestWaitPaid:
    @pytest.mark.asyncio
    async def test_polls_until_paid(self, client, http):
        http.set("GET", "/v1/mint/quote/bolt11/q3",
                 MockResponse(200, {"state": "UNPAID"}),
                 MockResponse(200, {"state": "UNPAID"}),
                 MockResponse(200, {"state": "PAID"}))
        ok = await client.wait_paid("q3", max_tries=5, interval_s=0.0)
        assert ok is True

    @pytest.mark.asyncio
    async def test_exhausts_max_tries_returns_false(self, client, http):
        http.set("GET", "/v1/mint/quote/bolt11/q4",
                 MockResponse(200, {"state": "UNPAID"}),
                 MockResponse(200, {"state": "UNPAID"}),
                 MockResponse(200, {"state": "UNPAID"}))
        ok = await client.wait_paid("q4", max_tries=3, interval_s=0.0)
        assert ok is False
