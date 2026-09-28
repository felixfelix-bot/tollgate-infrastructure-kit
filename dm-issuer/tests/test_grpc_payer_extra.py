"""Coverage gap: grpc_payer.py — target/stub_factory init branches, health
failure paths, approve fallback exception."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from tollgate_dm_issuer.grpc_payer import GrpcPayer, _build_default_stub


class TestInitBranches:
    def test_target_only_uses_default_stub_factory(self):
        p = GrpcPayer(target="127.0.0.1:50055",
                      retries=2, backoff_base_secs=0.0)
        assert p.target == "127.0.0.1:50055"

    def test_stub_factory_overrides_default(self):
        stub = MagicMock()
        p = GrpcPayer(stub_factory=lambda: stub,
                      target="127.0.0.1:9999",
                      retries=2, backoff_base_secs=0.0)
        # When stub_factory is given, _target is set to the provided target or `<injected>`
        assert p.target == "127.0.0.1:9999"

    def test_stub_factory_without_target_uses_injected_marker(self):
        stub = MagicMock()
        p = GrpcPayer(stub_factory=lambda: stub,
                      retries=2, backoff_base_secs=0.0)
        assert p.target == "<injected>"

    def test_raises_value_error_when_neither_target_nor_factory(self):
        with pytest.raises(ValueError, match="Either target or stub_factory"):
            GrpcPayer(retries=1, backoff_base_secs=0.0)


class TestHealthFailures:
    @pytest.mark.asyncio
    async def test_health_non_grpc_exception_returns_false(self):
        stub = MagicMock()
        stub.GetInfo = AsyncMock(side_effect=RuntimeError("oops"))
        p = GrpcPayer(stub_factory=lambda: stub,
                      retries=1, backoff_base_secs=0.0, timeout=1.0)
        ok = await p.health()
        assert ok is False

    @pytest.mark.asyncio
    async def test_health_aio_rpc_error_returns_false(self):
        stub = MagicMock()
        stub.GetInfo = AsyncMock(side_effect=grpc.aio.AioRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details="down",
        ))
        p = GrpcPayer(stub_factory=lambda: stub,
                      retries=1, backoff_base_secs=0.0, timeout=1.0)
        ok = await p.health()
        assert ok is False


class TestApproveFallbackException:
    @pytest.mark.asyncio
    async def test_fallback_raises_returns_false(self):
        async def _boom(quote_id):
            raise RuntimeError("approve-db-down")

        stub = MagicMock()
        stub.UpdateNut04Quote = AsyncMock(side_effect=grpc.aio.AioRpcError(
            code=grpc.StatusCode.UNAVAILABLE,
            initial_metadata=grpc.aio.Metadata(),
            trailing_metadata=grpc.aio.Metadata(),
            details="down",
        ))
        p = GrpcPayer(stub_factory=lambda: stub,
                      retries=1, backoff_base_secs=0.0,
                      fallback_approve=_boom)
        ok = await p.mark_quote_paid("q1")
        assert ok is False


class TestBuildDefaultStub:
    def test_builds_stub_adapter_with_methods(self):
        # Build a stub adapter against a non-resolving target — we should be
        # able to instantiate the helper class without performing any I/O.
        adapter = _build_default_stub("127.0.0.1:9")
        assert hasattr(adapter, "UpdateNut04Quote")
        assert hasattr(adapter, "GetInfo")
        # The channel object is held internally; we don't exercise it.
        assert hasattr(adapter, "_channel")
        # Cleanup the underlying channel (best-effort)
        try:
            adapter._channel.close()
        except Exception:
            pass
