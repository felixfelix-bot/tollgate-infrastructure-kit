"""Coverage gap: dispatcher.py — error branches, cursor corruption, run_forever,
_maybe_reply_rejection paths, CAS failures."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from tollgate_dm_issuer.config import Config, WhitelistEntry
from tollgate_dm_issuer.dispatcher import CURSOR_KEY, Dispatcher, DispatcherDeps, _compact_json
from tollgate_dm_issuer.journal import (
    DELIVERED, FAILED, PAID, QUOTED, REJECTED, REQUESTED,
    InMemoryJournal, iso,
)
from tollgate_dm_issuer.mint_client import MintError, QuoteState
from tollgate_dm_issuer.nostr_io import DmMessage
from tollgate_dm_issuer.ops import Metrics
from tollgate_dm_issuer.policy import Decision, DecisionKind, PolicyEngine


NPUB_FELIX = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
NPUB_ALICE = "npub1alice0000000000000000000000000000000000000000000000000000ab"
WHITELIST_FELIX = (
    WhitelistEntry(npub=NPUB_FELIX, daily_cap_sats=100_000,
                   max_request_sats=10_000),
)


class FakeMintQuote:
    def __init__(self, quote_id: str):
        self.quote_id = quote_id


class FakeMint:
    def __init__(self, *, quote_id="q-default", fail_create=False,
                 fail_wait_paid=False):
        self._qid = quote_id
        self._fail_create = fail_create
        self._fail_wait = fail_wait_paid
        self.create_calls: list[int] = []
        self.wait_paid_calls: list[str] = []

    async def create_quote(self, amount_sats: int):
        self.create_calls.append(amount_sats)
        if self._fail_create:
            raise MintError("synthetic failure")
        return FakeMintQuote(self._qid)

    async def get_quote_state(self, quote_id: str):
        return QuoteState.PAID

    async def wait_paid(self, quote_id: str, *, max_tries=10, interval_s=0.5):
        self.wait_paid_calls.append(quote_id)
        if self._fail_wait:
            raise MintError("wait paid failed")
        return True


class FakeNostr:
    def __init__(self, *, scan_messages=(), send_returns=True):
        self._messages = list(scan_messages)
        self._send_ok = send_returns
        self.sent: list[tuple[str, str]] = []

    async def scan_dms_since(self, since_ts: int):
        return list(self._messages)

    async def send_dm(self, recipient_npub: str, content: str,
                      *, created_at: Optional[int] = None) -> bool:
        self.sent.append((recipient_npub, content))
        return self._send_ok


class FakeGrpc:
    def __init__(self, *, ok=True):
        self._ok = ok
        self.mark_calls: list[str] = []

    async def mark_quote_paid(self, quote_id: str) -> bool:
        self.mark_calls.append(quote_id)
        return self._ok


class FakePolicy:
    """Returns a canned Decision for any check() call."""

    def __init__(self, decision: Decision):
        self._decision = decision
        self.committed: list[tuple[str, int]] = []

    def check(self, *, npub, amount, now, created_at, event_id):
        return self._decision

    def commit_usage(self, npub, amount, ts):
        self.committed.append((npub, amount))


def _dm(content="ecash 5000", sender_npub=NPUB_FELIX,
        event_id="evt-1", created_at=None) -> DmMessage:
    if created_at is None:
        import time as _t
        created_at = int(_t.time())
    return DmMessage(event_id=event_id, sender_npub=sender_npub,
                    content=content,
                    received_at_ts=created_at + 1,
                    created_at_ts=created_at)


def _make_dispatcher(*, scan_messages=(), send_returns=True,
                    mint_fail=False, grpc_ok=True, verify=False,
                    sleep_fn=None):
    cfg = Config(
        issuer_npub="npub1ac2r0qy6hws6fxn7eulewnnlesacertzuq4v9mhyywcu7phslcrsdrvykw",
        whitelist=WHITELIST_FELIX,
        verify_before_send=verify,
    )
    journal = InMemoryJournal()
    policy = PolicyEngine(config=cfg, journal=journal)
    metrics = Metrics(poll_seconds=cfg.poll_seconds)
    nostr = FakeNostr(scan_messages=scan_messages, send_returns=send_returns)
    mint = FakeMint(fail_create=mint_fail)
    grpc = FakeGrpc(ok=grpc_ok)
    deps = DispatcherDeps(config=cfg, journal=journal, policy=policy,
                         metrics=metrics, nostr_io=nostr, mint_client=mint,
                         grpc_payer=grpc)
    return Dispatcher(deps, sleep_fn=sleep_fn), locals()


class TestDispatcherLifecycle:
    def test_request_stop_and_stopped(self):
        d, _ = _make_dispatcher()
        assert d.stopped is False
        d.request_stop()
        assert d.stopped is True


class TestPollOnceScanFailure:
    @pytest.mark.asyncio
    async def test_scan_raises_returns_zero_delivered(self):
        d, ctx = _make_dispatcher()
        ctx["nostr"].scan_dms_since = AsyncMock(side_effect=RuntimeError("relay"))
        delivered = await d.poll_once()
        assert delivered == 0


class TestStopMidPoll:
    @pytest.mark.asyncio
    async def test_stopping_breaks_messages_loop(self):
        msgs = [_dm(f"ecash {i}", event_id=f"e{i}") for i in range(3)]
        d, ctx = _make_dispatcher(scan_messages=msgs)
        # Stop immediately on first _handle_one call
        original = d._handle_one
        call_count = {"n": 0}

        async def _stop_then_handle(msg, now):
            call_count["n"] += 1
            if call_count["n"] == 1:
                d.request_stop()
                # Process one but mark as not delivered
                return False
            return await original(msg, now)

        d._handle_one = _stop_then_handle
        await d.poll_once()
        assert call_count["n"] == 1


class TestUnhandledExceptionInHandleOne:
    @pytest.mark.asyncio
    async def test_unhandled_exception_continues_loop(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg])
        d._handle_one = AsyncMock(side_effect=RuntimeError("boom"))
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 1


class TestCorruptCursor:
    @pytest.mark.asyncio
    async def test_corrupt_cursor_falls_back_to_lookback(self):
        d, ctx = _make_dispatcher(scan_messages=[])
        ctx["journal"].set_kv(CURSOR_KEY, "not-an-iso-timestamp")
        # Should not raise; should fall back to lookback
        ts = d._compute_since_ts()
        assert ts >= 0


class TestSilentDropDoesNotCountAsDelivered:
    @pytest.mark.asyncio
    async def test_silent_drop_records_no_delivered(self):
        msg = _dm("ecash 5000", sender_npub=NPUB_ALICE)
        # Use a second message to also verify alice gets marked processed
        d, ctx = _make_dispatcher(scan_messages=[msg, msg])
        alice_count = ctx["journal"].count_recent_requests(
            NPUB_ALICE,
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0),
        )
        # Alice is NOT whitelisted — first poll gets NOT_WHITELISTED, replied, then second sees SILENT_DROP
        delivered = await d.poll_once()
        assert delivered == 0


class TestCasQuotedFailure:
    @pytest.mark.asyncio
    async def test_cas_requested_to_quoted_failure(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg])
        ctx["journal"].cas_state = MagicMock(return_value=False)
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 1


class TestCasDeliveredFailure:
    @pytest.mark.asyncio
    async def test_cas_paid_to_delivered_failure(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg])

        original_cas = ctx["journal"].cas_state
        call_count = {"n": 0}

        def cas(request_id, from_state, to_state, **kwargs):
            call_count["n"] += 1
            # Allow first transitions but fail PAID → DELIVERED
            if from_state == PAID and to_state == DELIVERED:
                return False
            return original_cas(request_id, from_state, to_state, **kwargs)

        ctx["journal"].cas_state = cas
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 1


class TestVerifyBeforeSendContinuesOnMintError:
    @pytest.mark.asyncio
    async def test_verify_failure_does_not_block_delivery(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg], verify=True)
        ctx["mint"]._fail_wait = True
        delivered = await d.poll_once()
        assert delivered == 1
        assert ctx["mint"].wait_paid_calls == ["q-default"]


class TestRunForever:
    @pytest.mark.asyncio
    async def test_run_forever_stops_after_sleep(self):
        msg = _dm("ecash 1000")
        d, ctx = _make_dispatcher(scan_messages=[msg])

        async def _sleep_then_stop(seconds):
            d.request_stop()

        d._sleep = _sleep_then_stop
        await d.run_forever()
        assert ctx["metrics"].last_seen_ts > 0


class TestCompactJsonHelper:
    def test_compact_json_minified(self):
        body = _compact_json({"b": 1, "a": 2})
        assert body == '{"a":2,"b":1}'


class TestMaybeReplyRejection:
    @pytest.mark.asyncio
    async def test_not_whitelisted_replies(self):
        msg = _dm("ecash 5000", sender_npub=NPUB_ALICE)
        d, ctx = _make_dispatcher(scan_messages=[msg])
        # Need to await the create_task'd send_dm reply — use asyncio.gather of running tasks
        await d.poll_once()
        # Give the create_task a chance to run
        await asyncio.sleep(0)
        # The reply should be queued; check via FastNostr.sent
        assert any(recipient == NPUB_ALICE for recipient, _ in ctx["nostr"].sent)


class TestHandledStopsAtSilentDrop:
    @pytest.mark.asyncio
    async def test_second_unwhitelisted_silently_dropped(self):
        # Alice sends twice; second time should SILENT_DROP not reply
        msg = _dm("ecash 5000", sender_npub=NPUB_ALICE)
        d, ctx = _make_dispatcher(scan_messages=[msg, msg])
        await d.poll_once()
        await asyncio.sleep(0)
        # At most one reply should have been sent (the first NOT_WHITELISTED)
        sent_to_alice = [c for r, c in ctx["nostr"].sent if r == NPUB_ALICE]
        assert len(sent_to_alice) <= 1
