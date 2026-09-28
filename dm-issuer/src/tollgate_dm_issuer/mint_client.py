"""MintClient — REST client for the Cashu mint bolt11 quote endpoints
(spec §5 DM-MINT-1).

The quote-handoff mode (Q2 resolution) only needs:
* ``POST /v1/mint/quote/bolt11`` ``{"amount": N, "unit": "sat"}`` — create a
  quote, return ``quote_id``.
* ``GET /v1/mint/quote/bolt11/{quote_id}`` — read the ``state`` field for
  pre/post-PAID verification.

Five-of-the-ten mint steps are removed in quote-handoff mode (blinded
messages, /v1/mint/bolt11, unblind, token serialisation, swap) — they live in
the user's wallet instead.  This module talks to the mint over plain HTTPS
via a pluggable transport; in production we use ``httpx.AsyncClient``;
tests inject a coroutine accepting the same shape: ``async (method, url,
**kwargs) -> ResponseLike`` where ``ResponseLike`` has ``status_code`` and
``json()``.

Long-running operations use simple exponential backoff:
- ``create_quote`` retries on 5xx up to ``retries`` times.
- ``wait_paid`` polls up to ``max_tries`` with ``interval_s``.
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger(__name__)


class QuoteState(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    ISSUED = "ISSUED"
    UNKNOWN = "UNKNOWN"


class Quote:
    __slots__ = ("quote_id", "state", "amount", "expiry", "raw")

    def __init__(self, quote_id: str, state: str, amount: Optional[int] = None,
                 expiry: Optional[int] = None, raw: Optional[dict] = None):
        self.quote_id = quote_id
        self.state = _parse_state(state)
        self.amount = amount
        self.expiry = expiry
        self.raw = raw or {}


class MintError(Exception):
    """Raised on mint API failures after retries are exhausted."""

    def __init__(self, message: str, *, status_code: Optional[int] = None,
                 path: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.path = path


HttpRequest = Callable[..., Awaitable[Any]]


def _parse_state(raw: Optional[str]) -> QuoteState:
    if not raw:
        return QuoteState.UNKNOWN
    if not isinstance(raw, str):
        return QuoteState.UNKNOWN
    upper = raw.upper()
    try:
        return QuoteState(upper)
    except ValueError:
        return QuoteState.UNKNOWN


class MintClient:
    """Async REST client for ``POST /v1/mint/quote/bolt11`` (create)
    and ``GET /v1/mint/quote/bolt11/{quote_id}`` (state probe).

    Parameters mirror the spec defaults from config.py:
    * ``base_url`` — Cashu mint public URL (https://mint.orangesync.tech).
    * ``http_request`` — pluggable transport.
    * ``retries`` — 3 attempts on 5xx for create_quote.
    * ``backoff_base_secs`` — base for exponential backoff on retries.
    """

    def __init__(self, *, base_url: str,
                 http_request: Optional[HttpRequest] = None,
                 retries: int = 3, backoff_base_secs: float = 1.0,
                 timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._http = http_request or _default_http_factory(timeout)
        self._retries = max(1, retries)
        self._backoff_base = max(0.0, backoff_base_secs)
        self._timeout = float(timeout)

    @property
    def base_url(self) -> str:
        return self._base_url

    async def create_quote(self, amount_sats: int) -> Quote:
        if amount_sats <= 0:
            raise MintError("amount must be positive", path="create_quote")
        url = f"{self._base_url}/v1/mint/quote/bolt11"
        body = {"amount": amount_sats, "unit": "sat"}
        last_exc: Optional[MintError] = None
        for attempt in range(self._retries):
            try:
                resp = await self._http("POST", url, json=body, timeout=self._timeout)
            except Exception as exc:
                log.warning("create_quote transport failure attempt=%d: %s", attempt, exc)
                last_exc = MintError(f"transport failure: {exc}", path=url)
                if attempt + 1 < self._retries:
                    await asyncio.sleep(self._backoff_base * (2 ** attempt))
                continue
            status = getattr(resp, "status_code", 0)
            if status in (200, 201):
                data = _safe_json(resp)
                qid = data.get("quote") or data.get("quote_id")
                if not qid:
                    last_exc = MintError("missing quote id", status_code=status, path=url)
                    if attempt + 1 < self._retries:
                        await asyncio.sleep(self._backoff_base * (2 ** attempt))
                    continue
                state_raw = data.get("state", "UNPAID")
                return Quote(qid, state_raw,
                             amount=int(data.get("amount", 0)) or amount_sats,
                             expiry=data.get("expiry"),
                             raw=data)
            if 400 <= status < 500 and status != 429:
                raise MintError(f"mint rejected quote: status={status}",
                                 status_code=status, path=url)
            log.warning("create_quote 5xx attempt=%d status=%d", attempt, status)
            last_exc = MintError(f"mint 5xx status={status}",
                                  status_code=status, path=url)
            if attempt + 1 < self._retries:
                await asyncio.sleep(self._backoff_base * (2 ** attempt))
        raise last_exc or MintError("create_quote failed", path=url)

    async def get_quote_state(self, quote_id: str) -> QuoteState:
        url = f"{self._base_url}/v1/mint/quote/bolt11/{quote_id}"
        try:
            resp = await self._http("GET", url, timeout=self._timeout)
        except Exception as exc:
            raise MintError(f"transport failure: {exc}", path=url) from exc
        status = getattr(resp, "status_code", 0)
        if status != 200:
            raise MintError(f"non-200 status={status}",
                            status_code=status, path=url)
        data = _safe_json(resp)
        return _parse_state(data.get("state"))

    async def wait_paid(self, quote_id: str, *, max_tries: int = 10,
                        interval_s: float = 0.5) -> bool:
        """Poll ``get_quote_state`` until PAID or until ``max_tries`` exhausted."""
        for _ in range(max_tries):
            try:
                state = await self.get_quote_state(quote_id)
                if state == QuoteState.PAID:
                    return True
            except MintError as exc:
                log.warning("wait_paid poll error quote_id=%s: %s", quote_id, exc)
            await asyncio.sleep(interval_s)
        return False


def _safe_json(resp: Any) -> dict:
    json_fn = getattr(resp, "json", None)
    if not callable(json_fn):
        return {}
    try:
        data = json_fn()
        if isinstance(data, dict):
            return data
    except Exception as exc:
        log.warning("response.json() failure: %s", exc)
    return {}


def _default_http_factory(timeout: float) -> HttpRequest:
    """Return a coroutine using ``httpx.AsyncClient`` for production."""
    import json as _json
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx required for default MintClient transport") from exc

    _client_holder: dict[str, Any] = {}

    def _get_client():
        if "c" not in _client_holder:
            _client_holder["c"] = httpx.AsyncClient(timeout=timeout)
        return _client_holder["c"]

    async def _request(method: str, url: str, *, json=None, timeout=None):
        return await _get_client().request(method, url, json=json, timeout=timeout)

    return _request
