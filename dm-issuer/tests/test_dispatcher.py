"""Phase E — dispatcher: tests with mock Nostr/Nostr/Mint/Grpc for the
single-poll happy path + edge cases (parse error, policy reject, mint fail,
gRPC fail, Nostr send fail).
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock

import pytest

from pynostr.key import PrivateKey

from tollgate_dm_issuer.config import Config, WhitelistEntry
from tollgate_dm_issuer.dispatcher import Dispatcher, DispatcherDeps
from tollgate_dm_issuer.journal import DELIVERED, FAILED, InMemoryJournal
from tollgate_dm_issuer.nostr_io import DmMessage
from tollgate_dm_issuer.ops import Metrics
from tollgate_dm_issuer.policy import PolicyEngine


NPUB_FELIX = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
NPUB_FELIX_2 = "npub1dtm05wf2nqy2fnjnc694rvknsc5xsu0z0p4phryds9qqgefdcvcq7neuy4"
WHITELIST_FELIX = (
    WhitelistEntry(npub=NPUB_FELIX, daily_cap_sats=100_000,
                   max_request_sats=10_000),
    WhitelistEntry(npub=NPUB_FELIX_2, daily_cap_sats=100_000,
                   max_request_sats=10_000),
)


class FakeMintQuote:
    def __init__(self, quote_id: str):
        self.quote_id = quote_id


class FakeMint:
    def __init__(self, *, quote_id: str = "q-default",
                 fail_create: bool = False,
                 fail_wait_paid: bool = False):
        self._qid = quote_id
        self._fail_create = fail_create
        self._fail_wait = fail_wait_paid
        from tollgate_dm_issuer.mint_client import MintError
        self._MintError = MintError
        self.create_calls: list[int] = []
        self.wait_paid_calls: list[str] = []

    async def create_quote(self, amount_sats: int):
        self.create_calls.append(amount_sats)
        if self._fail_create:
            raise self._MintError("synthetic failure")
        return FakeMintQuote(self._qid)

    async def get_quote_state(self, quote_id: str):
        from tollgate_dm_issuer.mint_client import QuoteState
        return QuoteState.PAID

    async def wait_paid(self, quote_id: str, *, max_tries=10, interval_s=0.5):
        self.wait_paid_calls.append(quote_id)
        if self._fail_wait:
            raise self._MintError("wait paid failed")
        return True


class FakeNostr:
    def __init__(self, *, scan_messages: list[DmMessage] = (),
                 send_returns: bool = True):
        self._messages = list(scan_messages)
        self._send_ok = send_returns
        self.sent: list[tuple[str, str]] = []

    async def scan_dms_since(self, since_ts: int) -> list[DmMessage]:
        return list(self._messages)

    async def send_dm(self, recipient_npub: str, content: str,
                      *, created_at: Optional[int] = None) -> bool:
        self.sent.append((recipient_npub, content))
        return self._send_ok


class FakeGrpc:
    def __init__(self, *, ok: bool = True):
        self._ok = ok
        self.mark_calls: list[str] = []

    async def mark_quote_paid(self, quote_id: str) -> bool:
        self.mark_calls.append(quote_id)
        return self._ok


def _dm(content: str, sender_npub: str = NPUB_FELIX,
        event_id: str = "evt-1",
        created_at: Optional[int] = None) -> DmMessage:
    if created_at is None:
        import time as _t
        created_at = int(_t.time())
    return DmMessage(event_id=event_id, sender_npub=sender_npub,
                     content=content,
                     received_at_ts=created_at + 1,
                     created_at_ts=created_at)


def _make_dispatcher(*, scan_messages=(), send_returns=True,
                       mint_fail=False, grpc_ok=True, verify=False):
    cfg = Config(
        issuer_npub="npub1ac2r0qy6hws6fxn7eulewnnlesacertzuq4v9mhyywcu7phslcrsdrvykw",
        whitelist=WHITELIST_FELIX,
        verify_before_send=verify,
    )
    journal = InMemoryJournal()
    policy = PolicyEngine(config=cfg, journal=journal)
    metrics = Metrics()
    nostr = FakeNostr(scan_messages=scan_messages,
                       send_returns=send_returns)
    mint = FakeMint(fail_create=mint_fail)
    grpc = FakeGrpc(ok=grpc_ok)
    deps = DispatcherDeps(config=cfg, journal=journal, policy=policy,
                          metrics=metrics, nostr_io=nostr, mint_client=mint,
                          grpc_payer=grpc)
    d = Dispatcher(deps)
    return d, locals()


class TestPollOnceHappyPath:
    @pytest.mark.asyncio
    async def test_happy_path_single_delivery(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg])
        delivered = await d.poll_once()
        assert delivered == 1
        assert len(ctx["nostr"].sent) == 1
        recipient, content = ctx["nostr"].sent[0]
        assert recipient == NPUB_FELIX
        assert content.startswith("q-default")
        assert ctx["mint"].create_calls == [5000]
        assert ctx["grpc"].mark_calls == ["q-default"]
        assert ctx["metrics"].requests_total == 1
        assert ctx["metrics"].sats_issued_total == 5000
        assert ctx["metrics"].errors_total == 0

    @pytest.mark.asyncio
    async def test_happy_path_json_request(self):
        body = json.dumps({
            "type": "ecash_request", "schema_version": 1,
            "amount": 800, "nonce": "abc123",
        })
        msg = _dm(body)
        d, ctx = _make_dispatcher(scan_messages=[msg])
        delivered = await d.poll_once()
        assert delivered == 1


class TestEventDedup:
    @pytest.mark.asyncio
    async def test_already_processed_event_skipped(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg, msg])
        delivered = await d.poll_once()
        assert delivered == 1
        assert len(ctx["nostr"].sent) == 1


class TestParseErrors:
    @pytest.mark.asyncio
    async def test_invalid_format_records_error_no_send(self):
        msg = _dm("hello world")
        d, ctx = _make_dispatcher(scan_messages=[msg])
        delivered = await d.poll_once()
        assert delivered == 0
        assert len(ctx["nostr"].sent) == 0
        assert ctx["metrics"].errors_total == 1


class TestPolicyRejects:
    @pytest.mark.asyncio
    async def test_unwhitelisted_npub_silent_or_reply(self):
        msg = _dm("ecash 5000",
                   sender_npub="npub1unknownuser" + "0" * 40)
        d, ctx = _make_dispatcher(scan_messages=[msg])
        delivered = await d.poll_once()
        assert delivered == 0
        assert not ctx["mint"].create_calls

    @pytest.mark.asyncio
    async def test_below_min_request_rejected(self):
        msg = _dm("ecash 5")
        d, ctx = _make_dispatcher(scan_messages=[msg])
        delivered = await d.poll_once()
        assert delivered == 0
        assert not ctx["mint"].create_calls


class TestMintFailure:
    @pytest.mark.asyncio
    async def test_mint_create_failure_journals_FAILED(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg], mint_fail=True)
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 1
        rid = ctx["journal"]._by_event.get(msg.event_id)
        row = ctx["journal"].fetch_request(rid)
        assert row.state == FAILED
        assert row.error_code == "MINT_CREATE_FAILED"


class TestGrpcFailure:
    @pytest.mark.asyncio
    async def test_grpc_mark_paid_failure_journals_FAILED(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg], grpc_ok=False)
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 1
        rid = ctx["journal"]._by_event.get(msg.event_id)
        row = ctx["journal"].fetch_request(rid)
        assert row.state == FAILED
        assert row.error_code == "GRPC_MARK_UNPAID"


class TestSendFailure:
    @pytest.mark.asyncio
    async def test_nostr_send_failure_no_commit_usage(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg], send_returns=False)
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 1
        rid = ctx["journal"]._by_event.get(msg.event_id)
        row = ctx["journal"].fetch_request(rid)
        assert row.state != DELIVERED


class TestCursor:
    @pytest.mark.asyncio
    async def test_cursor_advances_after_poll(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg])
        await d.poll_once()
        cur = ctx["journal"].get_kv("last_dm_scan_at")
        assert cur is not None
        ts = datetime.fromisoformat(cur)
        assert ts.tzinfo is not None


class TestVerifyBeforeSend:
    @pytest.mark.asyncio
    async def test_verify_path_calls_wait_paid(self):
        msg = _dm("ecash 5000")
        d, ctx = _make_dispatcher(scan_messages=[msg], verify=True)
        delivered = await d.poll_once()
        assert delivered == 1
        assert ctx["mint"].wait_paid_calls == ["q-default"]


class TestMultipleMessages:
    @pytest.mark.asyncio
    async def test_three_messages_all_delivered(self):
        msgs = [
            _dm("ecash 1000", event_id=f"e{i}")
            for i in range(3)
        ]
        d, ctx = _make_dispatcher(scan_messages=msgs)
        delivered = await d.poll_once()
        assert delivered == 3
        assert ctx["metrics"].sats_issued_total == 3000


class TestEmptyScan:
    @pytest.mark.asyncio
    async def test_empty_scan_no_errors(self):
        d, ctx = _make_dispatcher(scan_messages=[])
        delivered = await d.poll_once()
        assert delivered == 0
        assert ctx["metrics"].errors_total == 0
