"""Phase I — grpc_payer: mock gRPC stub tests for the PAID-marking path
(spec §5 DM-MINT-2, §7.1).

The GrpcPayer takes a stub factory (callable producing a ``CdkMintStub``-
shaped object) so tests can inject mocks.  The real constructor wires
``grpc.aio.insecure_channel`` + ``cdk_mint_rpc_pb2_grpc.CdkMintStub``.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import grpc
import pytest

from tollgate_dm_issuer.grpc_payer import GrpcPayer


def _make_stub(happy: bool = True, error_code=grpc.StatusCode.UNAVAILABLE,
               error_per_call_indices: tuple[int, ...] = ()):
    """Build a MagicMock stub whose UpdateNut04Quote is an AsyncMock.

    ``error_per_call_indices`` lets callers specify which calls raise.
    All other calls succeed.  Call index 0 is the first call.
    """
    counter = {"n": 0}

    async def _call(request, metadata=None, timeout=None):
        idx = counter["n"]
        counter["n"] += 1
        if idx in error_per_call_indices:
            raise grpc.aio.AioRpcError(
                code=error_code,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
                details="simulated rpc failure",
            )
        if not happy:
            raise grpc.aio.AioRpcError(
                code=error_code,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
                details="simulated rpc failure",
            )
        return MagicMock()

    stub = MagicMock()
    stub.UpdateNut04Quote = AsyncMock(side_effect=_call)
    stub._call_counter = counter
    return stub


class TestMarkQuotePaidHappy:
    @pytest.mark.asyncio
    async def test_returns_true_on_ok(self):
        stub = _make_stub(happy=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.mark_quote_paid("q1")
        assert ok is True
        stub.UpdateNut04Quote.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_request_carries_paid_state(self):
        stub = _make_stub(happy=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        await payer.mark_quote_paid("quote-abc")
        call = stub.UpdateNut04Quote.await_args
        assert call.kwargs["request"].quote_id == "quote-abc"
        assert call.kwargs["request"].state == "PAID"

    @pytest.mark.asyncio
    async def test_metadata_has_cdk_protocol_version(self):
        stub = _make_stub(happy=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        await payer.mark_quote_paid("q1")
        call = stub.UpdateNut04Quote.await_args
        metadata = dict(call.kwargs.get("metadata", []) or [])
        assert metadata.get("x-cdk-protocol-version") == "1.0.0"


class TestRetries:
    @pytest.mark.asyncio
    async def test_unavailable_then_ok_returns_true(self):
        stub = _make_stub(happy=True, error_per_call_indices=(0, 1))
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.mark_quote_paid("q1")
        assert ok is True
        assert stub._call_counter["n"] == 3

    @pytest.mark.asyncio
    async def test_unavailable_all_retries_returns_false(self):
        stub = _make_stub(happy=False,
                          error_code=grpc.StatusCode.UNAVAILABLE)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=3,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.mark_quote_paid("q1")
        assert ok is False
        assert stub._call_counter["n"] >= 3


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_invalid_argument_treated_as_success(self):
        stub = _make_stub(happy=False,
                          error_code=grpc.StatusCode.INVALID_ARGUMENT)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.mark_quote_paid("already-paid-q")
        assert ok is True

    @pytest.mark.asyncio
    async def test_failed_precondition_treated_as_success(self):
        stub = _make_stub(happy=False,
                          error_code=grpc.StatusCode.FAILED_PRECONDITION)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.mark_quote_paid("q1")
        assert ok is True


class TestApproveFallback:
    @pytest.mark.asyncio
    async def test_fallback_called_after_grpc_failures(self):
        stub = _make_stub(happy=False, error_code=grpc.StatusCode.UNAVAILABLE)
        fallback = AsyncMock(return_value=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=1,
                          backoff_base_secs=0.0, timeout=1.0,
                          fallback_approve=fallback)
        ok = await payer.mark_quote_paid("q1")
        assert ok is True
        fallback.assert_awaited_once_with("q1")

    @pytest.mark.asyncio
    async def test_fallback_failure_returns_false(self):
        stub = _make_stub(happy=False, error_code=grpc.StatusCode.UNAVAILABLE)
        fallback = AsyncMock(return_value=False)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=1,
                          backoff_base_secs=0.0, timeout=1.0,
                          fallback_approve=fallback)
        ok = await payer.mark_quote_paid("q1")
        assert ok is False


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_get_info_ok_returns_true(self):
        stub = MagicMock()
        stub.GetInfo = AsyncMock(return_value=MagicMock())
        payer = GrpcPayer(stub_factory=lambda: stub, retries=1,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.health()
        assert ok is True

    @pytest.mark.asyncio
    async def test_get_info_unavailable_returns_false(self):
        stub = MagicMock()
        stub.GetInfo = AsyncMock(
            side_effect=grpc.aio.AioRpcError(
                code=grpc.StatusCode.UNAVAILABLE,
                initial_metadata=grpc.aio.Metadata(),
                trailing_metadata=grpc.aio.Metadata(),
                details="down",
            )
        )
        payer = GrpcPayer(stub_factory=lambda: stub, retries=1,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.health()
        assert ok is False


class TestClose:
    @pytest.mark.asyncio
    async def test_close_does_not_raise_with_injected_factory(self):
        stub = _make_stub(happy=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=1,
                          backoff_base_secs=0.0, timeout=1.0)
        await payer.close()

    @pytest.mark.asyncio
    async def test_close_idempotent(self):
        stub = _make_stub(happy=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=1,
                          backoff_base_secs=0.0, timeout=1.0)
        await payer.close()
        await payer.close()

    @pytest.mark.asyncio
    async def test_close_after_mark_paid(self):
        stub = _make_stub(happy=True)
        payer = GrpcPayer(stub_factory=lambda: stub, retries=4,
                          backoff_base_secs=0.0, timeout=1.0)
        ok = await payer.mark_quote_paid("q1")
        assert ok is True
        await payer.close()
