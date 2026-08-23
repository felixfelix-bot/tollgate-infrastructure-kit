"""GrpcPayer — gRPC client for ``CdkMint.UpdateNut04Quote`` (spec §5 DM-MINT-2).

Wraps the vendored ``cdk_mint_rpc_pb2_grpc.CdkMintStub`` and exposes a
single async method ``mark_quote_paid(quote_id)`` that performs the PAID
marking with retries, exponential backoff, and optional fallback path
through the auth-processor approve hook (DM-MINT-3, /approve).

The payer never crashes its caller on transient failures — it returns
``False`` instead, letting the dispatcher journal a ``FAILED`` state.
Errors are logged via the module logger.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

import grpc

from .cdk_mint_rpc_pb2 import GetInfoRequest, UpdateNut04QuoteRequest

log = logging.getLogger(__name__)

CDK_PROTOCOL_VERSION = "1.0.0"
_PAID = "PAID"
_IDEMPOTENT_CODES = frozenset({
    grpc.StatusCode.INVALID_ARGUMENT,
    grpc.StatusCode.FAILED_PRECONDITION,
})

StubFactory = Callable[[], object]
ApproveFn = Callable[[str], Awaitable[bool]]


class GrpcPayer:
    """Async helper around ``CdkMint.UpdateNut04Quote``.

    Parameters mirror config.py:
    * ``target`` — ``"host:port"`` string for the gRPC server.
    * ``retries`` — max attempts before giving up (4 per spec §7.1).
    * ``backoff_base_secs`` — base for ``base * 2^n`` seconds.
    * ``fallback_approve`` — optional ``async (quote_id) -> bool``.

    The ``stub_factory`` parameter is a 0-arg callable returning an object
    exposing ``UpdateNut04Quote(request, metadata=..., timeout=...)``
    (and optionally ``GetInfo(request, ...)``).  Tests pass mocks; in
    production the default factory wires the real CdkMintStub.
    """

    def __init__(
        self,
        *,
        target: Optional[str] = None,
        stub_factory: Optional[StubFactory] = None,
        retries: int = 4,
        backoff_base_secs: float = 2.0,
        timeout: float = 5.0,
        fallback_approve: Optional[ApproveFn] = None,
    ) -> None:
        if stub_factory is None and target is None:
            raise ValueError("Either target or stub_factory must be provided")
        if stub_factory is None:
            self._target = target or "127.0.0.1:50055"
            self._stub_factory: StubFactory = lambda: _build_default_stub(self._target)
        else:
            self._stub_factory = stub_factory
            self._target = target or "<injected>"
        self._retries = max(1, retries)
        self._backoff_base = max(0.0, backoff_base_secs)
        self._timeout = float(timeout)
        self._fallback = fallback_approve

    @property
    def target(self) -> str:
        return self._target

    async def mark_quote_paid(self, quote_id: str) -> bool:
        """Mark a quote PAID via ``UpdateNut04Quote``.

        Returns True on success (or idempotent-already-paid codes), False on
        persistent failure.  When ``fallback_approve`` is supplied and the
        gRPC path exhausts retries, the fallback is invoked once.
        """
        for attempt in range(self._retries):
            try:
                stub = self._stub_factory()
                req = UpdateNut04QuoteRequest(quote_id=quote_id, state=_PAID)
                await stub.UpdateNut04Quote(
                    request=req,
                    metadata=(("x-cdk-protocol-version", CDK_PROTOCOL_VERSION),),
                    timeout=self._timeout,
                )
                log.info("UpdateNut04Quote OK quote_id=%s attempt=%d", quote_id, attempt)
                return True
            except grpc.aio.AioRpcError as exc:
                code = exc.code()
                if code in _IDEMPOTENT_CODES:
                    log.info("UpdateNut04Quote idempotent-success quote_id=%s code=%s",
                             quote_id, code)
                    return True
                log.warning("UpdateNut04Quote failure quote_id=%s attempt=%d code=%s",
                            quote_id, attempt, code)
                if attempt + 1 < self._retries:
                    await asyncio.sleep(self._backoff_base * (2 ** attempt))
                continue
        if self._fallback is not None:
            log.warning("Falling back to approve-hook quote_id=%s", quote_id)
            try:
                ok = await self._fallback(quote_id)
                if ok:
                    log.info("Approve-hook OK quote_id=%s", quote_id)
                    return True
                log.error("Approve-hook returned False quote_id=%s", quote_id)
                return False
            except Exception as exc:
                log.error("Approve-hook error quote_id=%s: %s", quote_id, exc)
                return False
        return False

    async def health(self) -> bool:
        """Readiness probe: call ``GetInfo`` once. Returns True on OK."""
        try:
            stub = self._stub_factory()
            await stub.GetInfo(GetInfoRequest(), timeout=self._timeout)
            return True
        except grpc.aio.AioRpcError as exc:
            log.warning("GetInfo failure code=%s %s", exc.code(), exc.details())
            return False
        except Exception as exc:
            log.warning("GetInfo error: %s", exc)
            return False


def _build_default_stub(target: str) -> object:
    """Build a real CdkMintStub backed by a per-call gRPC channel."""
    from .cdk_mint_rpc_pb2_grpc import CdkMintStub

    class _StubAdapter:
        def __init__(self) -> None:
            self._channel = grpc.aio.insecure_channel(target)
            self._stub = CdkMintStub(self._channel)

        async def UpdateNut04Quote(self, request, *, metadata=None, timeout=None):
            return await self._stub.UpdateNut04Quote(
                request, metadata=metadata, timeout=timeout)

        async def GetInfo(self, request, *, metadata=None, timeout=None):
            return await self._stub.GetInfo(
                request, metadata=metadata, timeout=timeout)

    return _StubAdapter()
