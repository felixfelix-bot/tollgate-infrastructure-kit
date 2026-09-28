"""Coverage gap: nostr_io.py — error paths in send_dm and _unwrap_giftwrap,
plus the no-relay fallback in the production relay factory."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from pynostr.key import PrivateKey

from tollgate_dm_issuer.nostr_io import (
    KIND_GIFTWRAP,
    KIND_SEAL,
    NostrIO,
    _build_giftwrap,
    _default_fetch_factory,
    _default_publish_factory,
    _unwrap_giftwrap,
)


def _gen_keys():
    sk = PrivateKey()
    return sk, sk.public_key.hex(), sk.public_key.npub


class TestDefaults:
    def test_lookback_default_secs_property(self):
        sk, _, _ = _gen_keys()
        io = NostrIO(
            issuer_pubkey_hex=sk.public_key.hex(),
            issuer_privkey_hex=sk.hex(),
            relays=["ws://test"],
            fetch_giftwraps=lambda ts: asyncio.sleep(0, result=[]),
            publish_event=lambda ev: asyncio.sleep(0, result=True),
            lookback_default_secs=12345,
        )
        assert io.lookback_default_secs == 12345


class TestScanDmFetchFailure:
    @pytest.mark.asyncio
    async def test_fetch_raises_returns_empty_list(self):
        sk, _, _ = _gen_keys()

        async def _boom(since_ts):
            raise ConnectionError("relay offline")

        io = NostrIO(
            issuer_pubkey_hex=sk.public_key.hex(),
            issuer_privkey_hex=sk.hex(),
            relays=["ws://test"],
            fetch_giftwraps=_boom,
            publish_event=lambda ev: asyncio.sleep(0, result=True),
        )
        messages = await io.scan_dms_since(0)
        assert messages == []

    @pytest.mark.asyncio
    async def test_scan_continues_past_unwrap_exception(self):
        sk, pub_hex, _ = _gen_keys()
        good_ts = int(time.time())
        good = _build_giftwrap(sk.hex(), pub_hex, "ecash 1", good_ts).to_dict()
        bad = {"kind": "not-an-int", "id": "broken"}

        async def _fetch(since_ts):
            return [bad, good]

        io = NostrIO(
            issuer_pubkey_hex=pub_hex,
            issuer_privkey_hex=sk.hex(),
            relays=["ws://test"],
            fetch_giftwraps=_fetch,
            publish_event=lambda ev: asyncio.sleep(0, result=True),
        )
        msgs = await io.scan_dms_since(0)
        assert len(msgs) == 1


class TestSendDmErrorPaths:
    @pytest.mark.asyncio
    async def test_send_dm_without_privkey_returns_false(self):
        sk, _, _ = _gen_keys()
        io = NostrIO(
            issuer_pubkey_hex=sk.public_key.hex(),
            issuer_privkey_hex=None,
            relays=["ws://test"],
            fetch_giftwraps=lambda ts: asyncio.sleep(0, result=[]),
            publish_event=lambda ev: asyncio.sleep(0, result=True),
        )
        ok = await io.send_dm(sk.public_key.npub, "ecash 1")
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_dm_invalid_recipient_npub_returns_false(self):
        sk, _, _ = _gen_keys()
        io = NostrIO(
            issuer_pubkey_hex=sk.public_key.hex(),
            issuer_privkey_hex=sk.hex(),
            relays=["ws://test"],
            fetch_giftwraps=lambda ts: asyncio.sleep(0, result=[]),
            publish_event=lambda ev: asyncio.sleep(0, result=True),
        )
        ok = await io.send_dm("nsec1invalid", "ecash 1")
        assert ok is False

    @pytest.mark.asyncio
    async def test_send_dm_publish_raises_returns_false(self):
        sk, _, _ = _gen_keys()

        async def _raise(ev):
            raise RuntimeError("relay closed")

        io = NostrIO(
            issuer_pubkey_hex=sk.public_key.hex(),
            issuer_privkey_hex=sk.hex(),
            relays=["ws://test"],
            fetch_giftwraps=lambda ts: asyncio.sleep(0, result=[]),
            publish_event=_raise,
            retries=2, backoff_base_secs=0.0,
        )
        ok = await io.send_dm(sk.public_key.npub, "ecash 1")
        assert ok is False


class TestUnwrapGiftwrapNegativePaths:
    def test_wrong_kind_returns_none(self):
        sk, pub_hex, _ = _gen_keys()
        result = _unwrap_giftwrap({"kind": 9999}, sk.hex(), pub_hex)
        assert result is None

    def test_no_issuer_priv_hex_returns_none(self):
        sk, _, _ = _gen_keys()
        result = _unwrap_giftwrap({"kind": KIND_GIFTWRAP}, None, sk.public_key.hex())
        assert result is None

    def test_missing_ephemeral_pubkey_returns_none(self):
        sk, _, _ = _gen_keys()
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": "", "content": "x",
             "tags": [["p", sk.public_key.hex()]]},
            sk.hex(), sk.public_key.hex(),
        )
        assert result is None

    def test_missing_content_returns_none(self):
        sk, _, _ = _gen_keys()
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": sk.public_key.hex(), "content": "",
             "tags": [["p", sk.public_key.hex()]]},
            sk.hex(), sk.public_key.hex(),
        )
        assert result is None

    def test_issuer_pubkey_not_in_p_tags_returns_none(self):
        sk, other, _ = _gen_keys()
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": other, "content": "x",
             "tags": [["p", other]]},
            sk.hex(), sk.public_key.hex(),
        )
        assert result is None

    def test_decrypt_giftwrap_failure_returns_none(self):
        sk, pub_hex, _ = _gen_keys()
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": sk.public_key.hex(),
             "content": "gibberish?iv=cafe",
             "tags": [["p", pub_hex]]},
            sk.hex(), pub_hex,
        )
        assert result is None

    def test_seal_kind_wrong_returns_none(self):
        sk, pub_hex, _ = _gen_keys()
        wrong_seal = json.dumps({"kind": 9999, "pubkey": sk.public_key.hex()})
        ct = sk.encrypt_message(wrong_seal, pub_hex)
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": sk.public_key.hex(),
             "content": ct,
             "tags": [["p", pub_hex]]},
            sk.hex(), pub_hex,
        )
        assert result is None

    def test_seal_missing_publisher_returns_none(self):
        sk, pub_hex, _ = _gen_keys()
        seal_dict = {"kind": KIND_SEAL, "pubkey": "", "content": "x"}
        ct = sk.encrypt_message(json.dumps(seal_dict), pub_hex)
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": sk.public_key.hex(),
             "content": ct,
             "tags": [["p", pub_hex]]},
            sk.hex(), pub_hex,
        )
        assert result is None

    def test_unverified_seal_returns_none(self):
        sender_sk, sender_pub_hex, _ = _gen_keys()
        issuer_sk, issuer_pub_hex, _ = _gen_keys()
        bogus_seal = {
            "kind": KIND_SEAL,
            "pubkey": sender_pub_hex,
            "content": "not-a-real-seal-content",
            "tags": [],
            "id": "deadbeef" + "0" * 56,
            "sig": "ff" * 64,
            "created_at": int(time.time()),
        }
        gw_ct = sender_sk.encrypt_message(json.dumps(bogus_seal), issuer_pub_hex)
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": sender_pub_hex,
             "content": gw_ct,
             "tags": [["p", issuer_pub_hex]]},
            issuer_sk.hex(), issuer_pub_hex,
        )
        assert result is None

    def test_decrypt_seal_content_failure_returns_none(self):
        sender_sk, sender_pub_hex, _ = _gen_keys()
        issuer_sk, issuer_pub_hex, _ = _gen_keys()
        # Build a valid seal from sender but with garbage content (not a rumor cipher)
        bogus_seal_event = {
            "kind": KIND_SEAL,
            "pubkey": sender_pub_hex,
            "content": "garbage-seal?iv=f00d",
            "created_at": int(time.time()),
        }
        bogus_seal_event["id"] = "0" * 64
        bogus_seal_event["sig"] = "0" * 128
        # Sign the seal properly so verify() passes
        from pynostr.event import Event
        evt = Event(**{k: v for k, v in bogus_seal_event.items()})
        evt.compute_id()
        evt.sign(sender_sk.hex())
        # Re-encrypt the seal JSON to issuer
        gw_ct = sender_sk.encrypt_message(json.dumps(evt.to_dict()), issuer_pub_hex)
        result = _unwrap_giftwrap(
            {"kind": KIND_GIFTWRAP, "pubkey": sender_pub_hex,
             "content": gw_ct,
             "tags": [["p", issuer_pub_hex]]},
            issuer_sk.hex(), issuer_pub_hex,
        )
        assert result is None


class TestDefaultFactoryNoRelays:
    @pytest.mark.asyncio
    async def test_default_fetch_factory_empty_relays_returns_empty(self):
        fetch = _default_fetch_factory("pubkey", "privhex", [], scan_timeout_secs=1.0)
        result = await fetch(0)
        assert result == []

    @pytest.mark.asyncio
    async def test_default_publish_factory_empty_relays_returns_false(self):
        publish = _default_publish_factory("privhex", [])
        ok = await publish({"kind": 1059, "content": "x"})
        assert ok is False
