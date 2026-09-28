"""Coverage gap: mint_client.py — _parse_state edge cases, transport-failure
paths, _safe_json edge cases, _default_http_factory."""
from __future__ import annotations

import sys
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from tollgate_dm_issuer.mint_client import (
    MintClient,
    MintError,
    Quote,
    QuoteState,
    _default_http_factory,
    _parse_state,
    _safe_json,
)


class TestParseState:
    def test_empty_string_returns_unknown(self):
        assert _parse_state("") == QuoteState.UNKNOWN

    def test_none_returns_unknown(self):
        assert _parse_state(None) == QuoteState.UNKNOWN

    def test_non_string_returns_unknown(self):
        assert _parse_state(12345) == QuoteState.UNKNOWN

    def test_unknown_string_returns_unknown(self):
        assert _parse_state("ZZZ") == QuoteState.UNKNOWN

    def test_case_insensitive_match(self):
        assert _parse_state("paid") == QuoteState.PAID
        assert _parse_state("unpaid") == QuoteState.UNPAID


class TestBaseUrlProperty:
    def test_base_url_strips_trailing_slash(self):
        c = MintClient(base_url="https://x.test/")
        assert c.base_url == "https://x.test"

    def test_base_url_left_alone_when_no_slash(self):
        c = MintClient(base_url="https://x.test")
        assert c.base_url == "https://x.test"


class TestCreateQuoteErrorPaths:
    @pytest.mark.asyncio
    async def test_amount_le_zero_raises_mint_error(self):
        c = MintClient(base_url="https://x.test",
                       http_request=AsyncMock(), retries=1)
        with pytest.raises(MintError, match="amount must be positive"):
            await c.create_quote(0)
        with pytest.raises(MintError):
            await c.create_quote(-5)

    @pytest.mark.asyncio
    async def test_transport_failure_raises_mint_error_after_retries(self, monkeypatch):
        c = MintClient(base_url="https://x.test",
                       http_request=AsyncMock(side_effect=ConnectionError("down")),
                       retries=2, backoff_base_secs=0.0)
        monkeypatch.setattr("tollgate_dm_issuer.mint_client.asyncio.sleep", AsyncMock())
        with pytest.raises(MintError, match="transport failure"):
            await c.create_quote(1000)

    @pytest.mark.asyncio
    async def test_missing_quote_id_in_response_retries_then_raises(self):
        c = MintClient(base_url="https://x.test",
                       http_request=AsyncMock(return_value=MagicMock(status_code=200)),
                       retries=2, backoff_base_secs=0.0)
        # json() returns empty dict — no quote id
        with pytest.raises(MintError, match="missing quote id"):
            await c.create_quote(1000)

    @pytest.mark.asyncio
    async def test_429_treated_as_retryable_not_4xx_hard_fail(self):
        responses = [MagicMock(status_code=429), MagicMock(status_code=429)]
        c = MintClient(base_url="https://x.test",
                       http_request=AsyncMock(side_effect=responses),
                       retries=2, backoff_base_secs=0.0)
        with pytest.raises(MintError):
            await c.create_quote(1000)


class TestGetQuoteStateErrorPaths:
    @pytest.mark.asyncio
    async def test_transport_failure_raises_mint_error(self):
        c = MintClient(base_url="https://x.test",
                       http_request=AsyncMock(side_effect=ConnectionError("down")),
                       retries=1)
        with pytest.raises(MintError, match="transport failure"):
            await c.get_quote_state("q1")

    @pytest.mark.asyncio
    async def test_non_200_raises_mint_error(self):
        c = MintClient(base_url="https://x.test",
                       http_request=AsyncMock(return_value=MagicMock(status_code=503)),
                       retries=1)
        with pytest.raises(MintError, match="non-200"):
            await c.get_quote_state("q1")


class TestWaitPaidContinuesOnMintError:
    @pytest.mark.asyncio
    async def test_wait_paid_returns_false_after_max_tries(self):
        call_count = {"n": 0}

        async def _fail(*args, **kwargs):
            call_count["n"] += 1
            raise MintError("transient", path="/x")

        c = MintClient(base_url="https://x.test",
                       http_request=_fail, retries=1)
        ok = await c.wait_paid("q1", max_tries=2, interval_s=0.0)
        assert ok is False
        assert call_count["n"] >= 2


class TestSafeJson:
    def test_no_json_callable_returns_empty_dict(self):
        class NoJson:
            status_code = 200

        assert _safe_json(NoJson()) == {}

    def test_json_raises_returns_empty_dict(self):
        class Raises:
            status_code = 200

            def json(self):
                raise ValueError("parse")

        assert _safe_json(Raises()) == {}

    def test_json_returns_non_dict_returns_empty(self):
        class ReturnsList:
            status_code = 200

            def json(self):
                return ["not", "a", "dict"]

        assert _safe_json(ReturnsList()) == {}

    def test_json_returns_dict_passes_through(self):
        class ReturnsDict:
            status_code = 200

            def json(self):
                return {"a": 1}

        assert _safe_json(ReturnsDict()) == {"a": 1}


class TestDefaultHttpFactory:
    def test_raises_runtime_error_when_httpx_not_installed(self, monkeypatch):
        real_import = __import__

        def fake_import(name, *args, **kwargs):
            if name == "httpx":
                raise ImportError("mocked: no httpx")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        with pytest.raises(RuntimeError, match="httpx required"):
            _default_http_factory(10.0)

    @pytest.mark.asyncio
    async def test_returns_lazy_request_callable(self):
        if "httpx" not in sys.modules:
            pytest.skip("httpx not installed")

        fake_client = MagicMock()
        fake_client.request = AsyncMock(return_value=MagicMock(status_code=200))

        fake_httpx = MagicMock()
        fake_httpx.AsyncClient = MagicMock(return_value=fake_client)

        old = sys.modules.get("httpx")
        sys.modules["httpx"] = fake_httpx
        try:
            request_fn = _default_http_factory(5.0)
            await request_fn("GET", "https://x.test/p", json=None, timeout=1.0)
            fake_client.request.assert_called_once_with(
                "GET", "https://x.test/p", json=None, timeout=1.0,
            )
        finally:
            if old is not None:
                sys.modules["httpx"] = old
            else:
                del sys.modules["httpx"]


class TestQuoteInit:
    def test_quote_with_no_state_defaults_to_unknown(self):
        q = Quote("q1", "")
        assert q.state == QuoteState.UNKNOWN

    def test_quote_with_none_state_defaults_to_unknown(self):
        q = Quote("q1", None)
        assert q.state == QuoteState.UNKNOWN

    def test_quote_with_amount_and_expiry(self):
        q = Quote("q1", "PAID", amount=500, expiry=1700000000,
                  raw={"x": 1})
        assert q.quote_id == "q1"
        assert q.state == QuoteState.PAID
        assert q.amount == 500
        assert q.expiry == 1700000000
        assert q.raw == {"x": 1}

    def test_quote_with_no_raw_defaults_to_empty_dict(self):
        q = Quote("q1", "PAID")
        assert q.raw == {}
