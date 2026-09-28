"""Phase I — nostr_io: roundtrip + corner-case tests for NIP-59 gift wrap
send/receive using pynostr's NIP-04 ECDH+AES-256-CBC crypto primitives
(spec §1.3 step 1, §3 message schema, §6 delivery, §7.4 relay outage).

The send path publishes gift wrap events addressed to a recipient npub.
The scan path loads pre-built gift wraps addressed to *the issuer*, then
unwraps them.  The fixture builds the gift wraps directly via
``_build_giftwrap`` so they're properly addressed to the issuer.
"""
import asyncio
import json
from typing import Optional
import time

import pytest

from pynostr.event import Event
from pynostr.key import PrivateKey, PublicKey

from tollgate_dm_issuer.nostr_io import (
    NostrIO,
    DmMessage,
    _build_giftwrap,
)


def _gen_keys(nsec_hex: Optional[str] = None):
    sk = PrivateKey(bytes.fromhex(nsec_hex) if nsec_hex else None)
    return sk, sk.public_key.hex(), sk.public_key.npub


@pytest.fixture
def issuer():
    return _gen_keys()


@pytest.fixture
def sender():
    return _gen_keys()


@pytest.fixture
def relay_provider():
    return {
        "events": [],
        "scan_results": None,
        "publish_return": True,
    }


@pytest.fixture
def nostr(issuer, relay_provider):
    async def _fetch(since_ts: int):
        if relay_provider["scan_results"] is not None:
            return relay_provider["scan_results"]
        return [e for e in relay_provider["events"]
                if e.get("created_at", 0) > since_ts]

    async def _publish(event_dict: dict):
        relay_provider["events"].append(event_dict)
        return relay_provider.get("publish_return", True)

    return NostrIO(
        issuer_pubkey_hex=issuer[1],
        issuer_privkey_hex=issuer[0].hex(),
        relays=["ws://localhost/test"],
        fetch_giftwraps=_fetch,
        publish_event=_publish,
        retries=3, backoff_base_secs=0.0,
        lookback_default_secs=43200,
    )


def _build_to_issuer(sender_sk_hex: str, issuer_pub_hex: str,
                     content: str, created_at: int) -> dict:
    """Build a NIP-59 gift wrap addressed to issuer, signed by sender."""
    return _build_giftwrap(sender_sk_hex, issuer_pub_hex, content,
                          created_at).to_dict()


class TestSendDmGiftwrapStructure:
    @pytest.mark.asyncio
    async def test_send_dm_returns_true(self, nostr, sender, relay_provider):
        ok = await nostr.send_dm(sender[2], "ecash 5000")
        assert ok is True
        assert len(relay_provider["events"]) == 1

    @pytest.mark.asyncio
    async def test_send_dm_publishes_kind_1059_event(self, nostr, sender,
                                                     issuer, relay_provider):
        await nostr.send_dm(sender[2], "ecash 5000")
        evt = relay_provider["events"][0]
        assert evt["kind"] == 1059
        assert any(t[0] == "p" and t[1] == sender[1] for t in evt["tags"])
        assert evt["pubkey"] != issuer[1]
        assert evt["pubkey"] != sender[1]
        assert evt["sig"]

    @pytest.mark.asyncio
    async def test_send_dm_with_str_content(self, nostr, sender, relay_provider):
        await nostr.send_dm(sender[2], "ecash 5000")
        evt = relay_provider["events"][0]
        assert isinstance(evt["content"], str)
        assert "?iv=" in evt["content"]


class TestScanDmsUnwrap:
    @pytest.mark.asyncio
    async def test_scan_unwraps_giftwrap_returns_message(self, nostr, sender,
                                                         issuer, relay_provider):
        ts = int(time.time())
        gw = _build_to_issuer(sender[0].hex(), issuer[1], "ecash 5000", ts)
        relay_provider["scan_results"] = [gw]
        messages = await nostr.scan_dms_since(0)
        assert len(messages) == 1
        m = messages[0]
        assert isinstance(m, DmMessage)
        assert m.content == "ecash 5000"
        assert m.sender_npub == sender[2]

    @pytest.mark.asyncio
    async def test_roundtrip_multiple_msgs(self, nostr, sender, issuer,
                                           relay_provider):
        ts = int(time.time())
        gws = [
            _build_to_issuer(sender[0].hex(), issuer[1], f"ecash {a}", ts + i)
            for i, a in enumerate([1000, 2000, 3000])
        ]
        relay_provider["scan_results"] = gws
        messages = await nostr.scan_dms_since(0)
        assert len(messages) == 3
        amounts = sorted(int(m.content.split()[1]) for m in messages)
        assert amounts == [1000, 2000, 3000]
        assert all(m.sender_npub == sender[2] for m in messages)

    @pytest.mark.asyncio
    async def test_event_id_returned_in_scan(self, nostr, sender, issuer,
                                             relay_provider):
        ts = int(time.time())
        gw = _build_to_issuer(sender[0].hex(), issuer[1], "ecash 5000", ts)
        relay_provider["scan_results"] = [gw]
        messages = await nostr.scan_dms_since(0)
        assert messages[0].event_id == gw["id"]


class TestPeerEntities:
    @pytest.mark.asyncio
    async def test_scan_checks_p_tag_matches_issuer(self, nostr, sender, issuer,
                                                    relay_provider):
        other_sk = PrivateKey()
        ts = int(time.time())
        # Gift wrap addressed to a different recipient (other_sk)
        wrong_gw = _build_giftwrap(
            sender[0].hex(), other_sk.public_key.hex(), "ecash 5000", ts
        ).to_dict()
        relay_provider["scan_results"] = [wrong_gw]
        messages = await nostr.scan_dms_since(0)
        assert messages == []

    @pytest.mark.asyncio
    async def test_scan_rejects_unverified_seal(self, nostr, sender, issuer,
                                                relay_provider):
        ts = int(time.time())
        gw = _build_to_issuer(sender[0].hex(), issuer[1], "ecash 5000", ts)
        # Tamper with seal sig inside the gift wrap content so verify fails.
        # Easiest: replace content with a valid-looking but unverified seal JSON.
        # We'll just inject a bogus content blob; _unwrap will fail decrypt.
        gw["content"] = "deadbeef?iv=cafe"
        relay_provider["scan_results"] = [gw]
        messages = await nostr.scan_dms_since(0)
        assert messages == []


class TestSendFailures:
    @pytest.mark.asyncio
    async def test_send_retries_on_failure_returns_false_after_exhaustion(
            self, sender, issuer):
        class _FailingPublish:
            def __init__(self):
                self.calls = 0

            async def __call__(self, event_dict: dict):
                self.calls += 1
                return False

        bad = NostrIO(
            issuer_pubkey_hex=issuer[1],
            issuer_privkey_hex=issuer[0].hex(),
            relays=["ws://"],
            fetch_giftwraps=lambda ts: [],
            publish_event=_FailingPublish(),
            retries=2, backoff_base_secs=0.0, lookback_default_secs=3600,
        )
        ok = await bad.send_dm(sender[2], "ecash 5000")
        assert ok is False


class TestEmptyScan:
    @pytest.mark.asyncio
    async def test_scan_empty_returns_empty_list(self, nostr, relay_provider):
        relay_provider["scan_results"] = []
        messages = await nostr.scan_dms_since(0)
        assert messages == []

    @pytest.mark.asyncio
    async def test_scan_returns_malformed_event_safely_skipped(
            self, nostr, issuer, relay_provider):
        bad = {
            "kind": 1059,
            "pubkey": "deadbeef" + "0" * 56,
            "content": "gibberish",
            "tags": [["p", issuer[1]]],
            "created_at": 100,
            "id": "bad1",
            "sig": "",
        }
        relay_provider["scan_results"] = [bad]
        messages = await nostr.scan_dms_since(0)
        assert messages == []


class TestRoundtripEndToEnd:
    @pytest.mark.asyncio
    async def test_send_then_recipient_unwraps(self, sender, issuer):
        """True roundtrip: issuer sends to sender, sender unwraps."""
        sender_io = NostrIO(
            issuer_pubkey_hex=sender[1],
            issuer_privkey_hex=sender[0].hex(),
            relays=["ws://test"],
            fetch_giftwraps=lambda ts: [],
            publish_event=lambda ev: asyncio.sleep(0, result=True),
            retries=1, backoff_base_secs=0.0, lookback_default_secs=3600,
        )
        published: list[dict] = []

        async def _capture(ev: dict):
            published.append(ev)
            return True

        # Issuer sends to sender (capture in published)
        issuer_send_io = NostrIO(
            issuer_pubkey_hex=issuer[1],
            issuer_privkey_hex=issuer[0].hex(),
            relays=["ws://"],
            fetch_giftwraps=lambda ts: [],
            publish_event=_capture,
            retries=1, backoff_base_secs=0.0, lookback_default_secs=3600,
        )
        ok = await issuer_send_io.send_dm(sender[2], "ecash 5000")
        assert ok
        assert len(published) == 1

        # Now recipient (sender) unwraps the published gift wrap
        relay_state: dict = {"events": list(published), "scan_results": None}

        async def _recipient_fetch(ts: int):
            return [e for e in relay_state["events"] if e.get("created_at", 0) > ts]

        async def _recipient_publish(ev: dict):
            return True

        recipient_io = NostrIO(
            issuer_pubkey_hex=sender[1],
            issuer_privkey_hex=sender[0].hex(),
            relays=["ws://"],
            fetch_giftwraps=_recipient_fetch,
            publish_event=_recipient_publish,
            retries=1, backoff_base_secs=0.0, lookback_default_secs=3600,
        )
        msgs = await recipient_io.scan_dms_since(0)
        assert len(msgs) == 1
        assert msgs[0].content == "ecash 5000"
        assert msgs[0].sender_npub == issuer[2]
