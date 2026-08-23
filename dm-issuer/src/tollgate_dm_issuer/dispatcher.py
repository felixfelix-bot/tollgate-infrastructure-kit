"""Dispatcher — the poller loop wiring all Phase I components (spec §1.3).

Pipeline (single DM):
1. ``parse_dm_request(content)``         → PlainRequest | JsonRequest | ParseError
2. ``policy.check(npub, amount, ...)``    → Decision(allow | reject | silent_drop |
                                            not_whitelisted)
3. ``journal.insert_request(...)``       → request_id (state=REQUESTED)
4. ``mint_client.create_quote(amount)``  → quote_id
5. ``journal.cas_state(REQUESTED→QUOTED)``
6. ``grpc_payer.mark_quote_paid(qid)``   → True / False
7. ``journal.cas_state(QUOTED→PAID)``
8. (optional) ``mint_client.wait_paid(qid)`` (when verify_before_send)
9. ``nostr_io.send_dm(npub, quote_id)``   → True
10. ``journal.cas_state(PAID→DELIVERED)`` + ``mark_delivered``
11. ``policy.commit_usage(npub, amount)``

Cursor persisted in KV (``last_dm_scan_at``, RFC3339 ISO timestamp).  Errors
are caught per-DM and journaled as ``FAILED`` (spec §7.5).
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from .config import Config
from .journal import (
    DELIVERED,
    FAILED,
    PAID,
    QUOTED,
    REJECTED,
    REQUESTED,
    Journal,
    iso,
    parse_iso,
    request_id_for,
)
from .mint_client import MintError, QuoteState
from .nostr_io import DmMessage, NostrIO
from .ops import Metrics
from .parse import ParseError, parse_dm_request
from .policy import DecisionKind, PolicyEngine

log = logging.getLogger(__name__)

CURSOR_KEY = "last_dm_scan_at"


class MintClientLike(Protocol):
    async def create_quote(self, amount_sats: int): ...
    async def get_quote_state(self, quote_id: str) -> QuoteState: ...
    async def wait_paid(self, quote_id: str,*, max_tries: int = 10,
                        interval_s: float = 0.5) -> bool: ...


class GrpcPayerLike(Protocol):
    async def mark_quote_paid(self, quote_id: str) -> bool: ...


class NostrIOLike(Protocol):
    async def scan_dms_since(self, since_ts: int) -> list[DmMessage]: ...
    async def send_dm(self, recipient_npub: str, content: str,
                      *, created_at: Optional[int] = None) -> bool: ...


@dataclass
class DispatcherDeps:
    config: Config
    journal: Journal
    policy: PolicyEngine
    metrics: Metrics
    nostr_io: NostrIOLike
    mint_client: MintClientLike
    grpc_payer: GrpcPayerLike


class Dispatcher:
    """Async poller that orchestrates a single DM through the full pipeline."""

    def __init__(self, deps: DispatcherDeps,
                 *, sleep_fn: Optional[object] = None) -> None:
        self._deps = deps
        self._sleep = sleep_fn or asyncio.sleep
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    @property
    def stopped(self) -> bool:
        return self._stop

    async def poll_once(self) -> int:
        """Run a single scan → dispatch cycle. Returns the number of DMs
        successfully delivered this cycle."""
        since_ts = self._compute_since_ts()
        now = datetime.now(timezone.utc)
        try:
            messages = await self._deps.nostr_io.scan_dms_since(since_ts)
        except Exception as exc:
            log.error("scan_dms_since failed: %s", exc)
            self._deps.metrics.observe_request_error() if False else None
            return 0
        delivered = 0
        for msg in messages:
            if self._stop:
                break
            try:
                ok = await self._handle_one(msg, now)
                if ok:
                    delivered += 1
            except Exception as exc:
                log.exception("unhandled error processing event %s: %s",
                              msg.event_id, exc)
                self._deps.metrics.observe_request_error()
        self._deps.journal.set_kv(CURSOR_KEY, iso(now))
        return delivered

    def _compute_since_ts(self) -> int:
        raw = self._deps.journal.get_kv(CURSOR_KEY)
        if raw:
            try:
                ts = parse_iso(raw)
                return int(ts.timestamp())
            except Exception:
                log.warning("corrupt cursor %r, falling back to lookback", raw)
        back = int(time.time()) - self._deps.config.dm_lookback_default_secs
        return max(0, back)

    async def _handle_one(self, msg: DmMessage, now: datetime) -> bool:
        if self._deps.journal.is_event_processed(msg.event_id):
            log.debug("skip already-processed event_id=%s", msg.event_id)
            return False
        self._deps.metrics.observe_request_started()
        try:
            amount, request_id = self._maybe_accept(msg, now)
        except _Handled as exc:
            self._deps.metrics.observe_request_error()
            log.info("rejected event_id=%s code=%s", msg.event_id, exc.code)
            return False
        if amount is None:
            self._deps.metrics.observe_request_delivered(0)
            return False
        try:
            quote_id = await self._deps.mint_client.create_quote(amount)
        except MintError as exc:
            log.error("create_quote failed: %s", exc)
            self._deps.journal.cas_state(request_id, REQUESTED, FAILED,
                                         error_code="MINT_CREATE_FAILED")
            self._deps.metrics.observe_request_error()
            return False
        cas_quoted = self._deps.journal.cas_state(
            request_id, REQUESTED, QUOTED, quote_id=quote_id.quote_id,
            ts=now)
        if not cas_quoted:
            log.error("CAS REQUESTED→QUOTED failed rid=%s", request_id)
            self._deps.metrics.observe_request_error()
            return False
        ok_paid = await self._deps.grpc_payer.mark_quote_paid(quote_id.quote_id)
        if not ok_paid:
            self._deps.journal.cas_state(request_id, QUOTED, FAILED,
                                         error_code="GRPC_MARK_UNPAID")
            self._deps.metrics.observe_request_error()
            return False
        self._deps.journal.cas_state(request_id, QUOTED, PAID, ts=now)
        if self._deps.config.verify_before_send:
            try:
                await self._deps.mint_client.wait_paid(quote_id.quote_id)
            except MintError as exc:
                log.warning("verify wait_paid failed (continuing): %s", exc)
        sent = await self._deps.nostr_io.send_dm(
            msg.sender_npub, quote_id.quote_id, created_at=int(now.timestamp()))
        if not sent:
            log.error("send_dm failed for rid=%s", request_id)
            self._deps.metrics.observe_request_error()
            return False
        cas_delivered = self._deps.journal.cas_state(
            request_id, PAID, DELIVERED, ts=now)
        if not cas_delivered:
            log.error("CAS PAID→DELIVERED failed rid=%s", request_id)
            self._deps.metrics.observe_request_error()
            return False
        self._deps.journal.mark_delivered(request_id, ts=now)
        self._deps.policy.commit_usage(msg.sender_npub, amount, now)
        self._deps.metrics.observe_request_delivered(amount)
        return True

    def _maybe_accept(self, msg: DmMessage, now: datetime):
        """Parse + policy. Returns (amount, request_id) or raises _Handled."""
        try:
            parsed = parse_dm_request(msg.content)
        except ParseError as exc:
            raise _Handled(code=f"PARSE_{exc.code}")
        amount = int(parsed.amount)
        decision = self._deps.policy.check(
            npub=msg.sender_npub, amount=amount,
            now=now, created_at=datetime.fromtimestamp(
                msg.created_at_ts or msg.received_at_ts, tz=timezone.utc),
            event_id=msg.event_id,
        )
        if decision.kind == DecisionKind.SILENT_DROP:
            self._deps.journal.mark_event_processed(msg.event_id, time.time())
            raise _Handled(code="SILENT_DROP")
        if decision.kind in (DecisionKind.NOT_WHITELISTED,
                              DecisionKind.REJECTED):
            self._maybe_reply_rejection(msg, decision, now)
            self._deps.journal.mark_event_processed(msg.event_id, time.time())
            raise _Handled(code=decision.code or decision.kind.value)
        request_id = self._deps.journal.insert_request(
            event_id=msg.event_id, npub=msg.sender_npub, amount=amount, ts=now)
        self._deps.journal.mark_event_processed(msg.event_id, time.time())
        return amount, request_id

    def _maybe_reply_rejection(self, msg: DmMessage,
                                decision, now: datetime) -> None:
        if decision.kind == DecisionKind.NOT_WHITELISTED:
            loop = asyncio.get_event_loop()
            try:
                loop.create_task(self._deps.nostr_io.send_dm(
                    msg.sender_npub,
                    (decision.message or "not whitelisted"),
                ))
            except Exception as exc:
                log.warning("send reply failed: %s", exc)
        elif decision.code in ("STALE_REQUEST", "RATE_LIMITED",
                                "DAILY_CAP_EXCEEDED", "GLOBAL_CAP_EXCEEDED",
                                "AMOUNT_INVALID"):
            loop = asyncio.get_event_loop()
            try:
                body = {
                    "error": decision.code,
                    "message": decision.message,
                    "retry_after_secs": decision.retry_after_secs,
                }
                loop.create_task(self._deps.nostr_io.send_dm(
                    msg.sender_npub, _compact_json(body),
                ))
            except Exception as exc:
                log.warning("send reply failed: %s", exc)

    async def run_forever(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.request_stop)
            except NotImplementedError:
                pass
        while not self._stop:
            self._deps.metrics.observe_heartbeat()
            await self.poll_once()
            await self._sleep(self._deps.config.poll_seconds)


def _compact_json(obj: dict) -> str:
    import json as _json
    return _json.dumps(obj, separators=(",", ":"), sort_keys=True)


class _Handled(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
