import asyncio
import json
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tollgate_mint_approve.cli import (
    _hex_from_npub,
    _hex_from_nsec,
    _derive_npub_hex,
    _sign_event,
    approve,
    SUPPORTED_UNITS,
)


class TestHexFromNpub:
    def test_npub_decoded(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        npub = pk.public_key.bech32()
        expected_hex = pk.public_key.hex()
        result = _hex_from_npub(npub)
        assert result == expected_hex


class TestHexFromNsec:
    def test_nsec_decoded(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        nsec = pk.bech32()
        expected_hex = pk.hex()
        result = _hex_from_nsec(nsec)
        assert result == expected_hex


class TestDeriveNpubHex:
    def test_derives_from_hex(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        expected = pk.public_key.hex()
        result = _derive_npub_hex(pk.hex())
        assert result == expected


class TestSignEvent:
    def test_produces_signed_event(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        event = {
            "pubkey": pk.public_key.hex(),
            "created_at": 1000000,
            "kind": 38010,
            "tags": [["t", "mint-approval"]],
            "content": "test",
        }
        signed = _sign_event(event, pk.hex())
        assert "id" in signed
        assert "sig" in signed
        assert "pubkey" in signed
        assert len(signed["id"]) == 64
        assert len(signed["sig"]) == 128

    def test_deterministic_id(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        event = {
            "pubkey": pk.public_key.hex(),
            "created_at": 1000000,
            "kind": 38010,
            "tags": [["t", "mint-approval"]],
            "content": "test",
        }
        s1 = _sign_event(event, pk.hex())
        s2 = _sign_event(event, pk.hex())
        assert s1["id"] == s2["id"]

    def test_preserves_event_fields(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        event = {
            "pubkey": pk.public_key.hex(),
            "created_at": 1000000,
            "kind": 38010,
            "tags": [["t", "mint-approval"], ["mint", "https://test.mints.example"]],
            "content": "test approval",
        }
        signed = _sign_event(event, pk.hex())
        assert signed["kind"] == 38010
        assert signed["content"] == "test approval"
        assert len(signed["tags"]) == 2


class TestPublishEvent:
    @pytest.mark.asyncio
    async def test_publish_sends_event_message(self):
        from tollgate_mint_approve.cli import _publish_event

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        mock_ws.recv = AsyncMock(return_value=json.dumps(["OK", "evt123", True, ""]))
        mock_ws.__aenter__ = AsyncMock(return_value=mock_ws)
        mock_ws.__aexit__ = AsyncMock(return_value=None)

        event = {"id": "evt123", "kind": 38010}

        with patch("tollgate_mint_approve.cli.websockets.connect", return_value=mock_ws):
            result = await _publish_event(event, "ws://localhost:7777")

        mock_ws.send.assert_called_once()
        sent = json.loads(mock_ws.send.call_args[0][0])
        assert sent[0] == "EVENT"
        assert sent[1] == event
        assert result == ["OK", "evt123", True, ""]

    @pytest.mark.asyncio
    async def test_publish_handles_connection_error(self):
        from tollgate_mint_approve.cli import _publish_event

        with patch("tollgate_mint_approve.cli.websockets.connect", side_effect=OSError("refused")):
            with pytest.raises(OSError):
                await _publish_event({"id": "x"}, "ws://localhost:7777")


class TestApprove:
    def test_returns_1_without_nsec(self):
        args = MagicMock()
        args.nsec = None
        with patch.dict("os.environ", {}, clear=True):
            result = approve(args)
        assert result == 1

    def test_builds_correct_event_and_publishes(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()

        args = MagicMock()
        args.nsec = pk.bech32()
        args.mint = "https://test.mints.example"
        args.quote = "quote-123"
        args.amount = 100
        args.unit = "sat"
        args.relay = "ws://localhost:7777"

        mock_response = ["OK", "evt-id", True, ""]

        with patch("tollgate_mint_approve.cli._publish_event", new_callable=AsyncMock, return_value=mock_response) as mock_pub:
            with patch("tollgate_mint_approve.cli.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                result = approve(args)

        assert result == 0
        call_args = mock_pub.call_args[0]
        signed_event = call_args[0]
        assert signed_event["kind"] == 38010
        tags = signed_event["tags"]
        tag_map = {t[0]: t[1] for t in tags}
        assert tag_map["t"] == "mint-approval"
        assert tag_map["mint"] == "https://test.mints.example"
        assert tag_map["quote"] == "quote-123"
        assert tag_map["amount"] == "100"
        assert tag_map["unit"] == "sat"

    def test_uses_env_nsec(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()

        args = MagicMock()
        args.nsec = None
        args.mint = "https://test.mints.example"
        args.quote = "quote-123"
        args.amount = 100
        args.unit = "sat"
        args.relay = "ws://localhost:7777"

        mock_response = ["OK", "evt-id", True, ""]

        with patch.dict("os.environ", {"NSEC": pk.bech32()}):
            with patch("tollgate_mint_approve.cli._publish_event", new_callable=AsyncMock, return_value=mock_response):
                with patch("tollgate_mint_approve.cli.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                    result = approve(args)

        assert result == 0

    def test_handles_publish_error(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()

        args = MagicMock()
        args.nsec = pk.bech32()
        args.mint = "https://test.mints.example"
        args.quote = "quote-123"
        args.amount = 100
        args.unit = "sat"
        args.relay = "ws://localhost:7777"

        with patch("tollgate_mint_approve.cli._publish_event", new_callable=AsyncMock, side_effect=OSError("connection refused")):
            with patch("tollgate_mint_approve.cli.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                result = approve(args)

        assert result == 1

    def test_uses_default_relay(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()

        args = MagicMock()
        args.nsec = pk.bech32()
        args.mint = "https://test.mints.example"
        args.quote = "quote-123"
        args.amount = 100
        args.unit = "sat"
        args.relay = None

        mock_response = ["OK", "evt-id", True, ""]

        with patch.dict("os.environ", {}, clear=True):
            with patch("tollgate_mint_approve.cli._publish_event", new_callable=AsyncMock, return_value=mock_response) as mock_pub:
                with patch("tollgate_mint_approve.cli.asyncio.run", side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                    approve(args)

            relay_used = mock_pub.call_args[0][1]
            assert relay_used == "wss://relay.orangesync.tech"


class TestMain:
    def test_main_parses_args(self):
        from tollgate_mint_approve.cli import main
        from pynostr.key import PrivateKey
        pk = PrivateKey()

        with patch("sys.argv", ["tollgate-mint-approve", "--mint", "https://test.mints.example", "--quote", "q1", "--amount", "100", "--unit", "sat", "--nsec", pk.bech32()]):
            with patch("tollgate_mint_approve.cli.approve", return_value=0) as mock_approve:
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0
                args_passed = mock_approve.call_args[0][0]
                assert args_passed.mint == "https://test.mints.example"
                assert args_passed.quote == "q1"
                assert args_passed.amount == 100
                assert args_passed.unit == "sat"
