import hashlib
import json
import time
import pytest
from tollgate_mint_orchestrator.event_validator import (
    EventValidator,
    _compute_event_id,
    _verify_signature,
    _verify_schnorr_fallback,
    _get_tag,
    SUPPORTED_UNITS,
)
from tollgate_mint_orchestrator.mint_registry import MintRegistry


def _make_registry(tmp_path, hex_pubkey=None):
    path = str(tmp_path / "registry.json")
    reg = MintRegistry(path)
    reg.add_mint({
        "npub": "npub1abc",
        "hex_pubkey": hex_pubkey or ("a" * 64),
        "subdomain": "test",
        "url": "https://test.mints.example",
        "rest_port": 3338,
        "grpc_port": 50051,
        "container_name": "mint-test",
        "created_at": "2026-01-01T00:00:00Z",
    })
    return reg


def _make_event(**overrides):
    defaults = {
        "id": "e" * 64,
        "pubkey": "a" * 64,
        "created_at": int(time.time()),
        "kind": 38010,
        "tags": [
            ["t", "mint-approval"],
            ["mint", "https://test.mints.example"],
            ["quote", "quote-123"],
            ["amount", "100"],
            ["unit", "sat"],
        ],
        "content": "test approval",
        "sig": "f" * 128,
    }
    defaults.update(overrides)
    return defaults


class TestGetTag:
    def test_finds_tag(self):
        tags = [["t", "mint-approval"], ["mint", "https://example.com"]]
        assert _get_tag(tags, "t") == "mint-approval"
        assert _get_tag(tags, "mint") == "https://example.com"

    def test_returns_none_for_missing(self):
        tags = [["t", "mint-approval"]]
        assert _get_tag(tags, "mint") is None

    def test_handles_short_tags(self):
        tags = [["t"]]
        assert _get_tag(tags, "t") is None

    def test_handles_empty_tags(self):
        assert _get_tag([], "t") is None


class TestComputeEventId:
    def test_produces_valid_sha256_hex(self):
        event = _make_event()
        event_id = _compute_event_id(event)
        assert len(event_id) == 64
        assert all(c in "0123456789abcdef" for c in event_id)

    def test_serialization_format(self):
        event = _make_event()
        expected_serialized = json.dumps(
            [0, event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        expected_id = hashlib.sha256(expected_serialized.encode("utf-8")).hexdigest()
        assert _compute_event_id(event) == expected_id


class TestVerifySignature:
    def test_returns_false_for_mismatched_id(self):
        from pynostr.key import PrivateKey
        pk = PrivateKey()
        event = {
            "id": "0" * 64,
            "pubkey": pk.public_key.hex(),
            "created_at": int(time.time()),
            "kind": 38010,
            "tags": [["t", "mint-approval"]],
            "content": "test",
            "sig": "f" * 128,
        }
        assert _verify_signature(event) is False

    def test_returns_false_on_exception(self):
        event = {"pubkey": None, "created_at": None, "kind": None, "tags": None, "content": None, "sig": None, "id": "x"}
        assert _verify_signature(event) is False

    def test_valid_signature_with_real_key(self):
        from pynostr.key import PrivateKey
        from pynostr.event import Event

        pk = PrivateKey()
        evt = Event(
            pubkey=pk.public_key.hex(),
            created_at=int(time.time()),
            kind=38010,
            tags=[["t", "mint-approval"]],
            content="test approval",
        )
        evt.sign(pk.hex())

        event = {
            "id": evt.id,
            "pubkey": evt.pubkey,
            "created_at": evt.created_at,
            "kind": evt.kind,
            "tags": evt.tags,
            "content": evt.content,
            "sig": evt.sig,
        }
        assert _verify_signature(event) is True

    def test_invalid_signature_detected(self):
        from pynostr.key import PrivateKey
        from pynostr.event import Event

        pk = PrivateKey()
        evt = Event(
            pubkey=pk.public_key.hex(),
            created_at=int(time.time()),
            kind=38010,
            tags=[["t", "mint-approval"]],
            content="test approval",
        )
        evt.sign(pk.hex())

        event = {
            "id": evt.id,
            "pubkey": evt.pubkey,
            "created_at": evt.created_at,
            "kind": evt.kind,
            "tags": evt.tags,
            "content": "tampered content",
            "sig": evt.sig,
        }
        assert _verify_signature(event) is False


class TestVerifySchnorrFallback:
    def test_handles_exception_gracefully(self):
        result = _verify_schnorr_fallback("not_hex", "not_hex", "not_hex")
        assert result in (True, False)


class TestEventValidatorFull:
    def test_valid_event_with_real_signature(self, tmp_path):
        from pynostr.key import PrivateKey
        from pynostr.event import Event

        pk = PrivateKey()
        reg = _make_registry(tmp_path, hex_pubkey=pk.public_key.hex())
        v = EventValidator(reg, approval_ttl_secs=300)

        evt = Event(
            pubkey=pk.public_key.hex(),
            created_at=int(time.time()),
            kind=38010,
            tags=[
                ["t", "mint-approval"],
                ["mint", "https://test.mints.example"],
                ["quote", "quote-123"],
                ["amount", "100"],
                ["unit", "sat"],
            ],
            content="test approval",
        )
        evt.sign(pk.hex())

        event = {
            "id": evt.id,
            "pubkey": evt.pubkey,
            "created_at": evt.created_at,
            "kind": evt.kind,
            "tags": evt.tags,
            "content": evt.content,
            "sig": evt.sig,
        }

        result = v.validate(event)
        assert result.valid is True
        assert result.quote_id == "quote-123"
        assert result.amount == 100
        assert result.unit == "sat"
        assert result.mint is not None
        assert result.mint["subdomain"] == "test"

    def test_valid_result_has_mint_data(self, tmp_path):
        from pynostr.key import PrivateKey
        from pynostr.event import Event

        pk = PrivateKey()
        reg = _make_registry(tmp_path, hex_pubkey=pk.public_key.hex())
        v = EventValidator(reg, approval_ttl_secs=300)

        evt = Event(
            pubkey=pk.public_key.hex(),
            created_at=int(time.time()),
            kind=38010,
            tags=[
                ["t", "mint-approval"],
                ["mint", "https://test.mints.example"],
                ["quote", "q-456"],
                ["amount", "500"],
                ["unit", "usd"],
            ],
            content="approve",
        )
        evt.sign(pk.hex())

        event = {
            "id": evt.id,
            "pubkey": evt.pubkey,
            "created_at": evt.created_at,
            "kind": evt.kind,
            "tags": evt.tags,
            "content": evt.content,
            "sig": evt.sig,
        }

        result = v.validate(event)
        assert result.valid
        assert result.mint["url"] == "https://test.mints.example"
        assert result.mint["rest_port"] == 3338
        assert result.mint["grpc_port"] == 50051

    def test_future_event_passes_ttl(self, tmp_path):
        from pynostr.key import PrivateKey
        from pynostr.event import Event

        pk = PrivateKey()
        reg = _make_registry(tmp_path, hex_pubkey=pk.public_key.hex())
        v = EventValidator(reg, approval_ttl_secs=300)

        evt = Event(
            pubkey=pk.public_key.hex(),
            created_at=int(time.time()) + 200,
            kind=38010,
            tags=[
                ["t", "mint-approval"],
                ["mint", "https://test.mints.example"],
                ["quote", "q-future"],
                ["amount", "100"],
                ["unit", "sat"],
            ],
            content="future approval",
        )
        evt.sign(pk.hex())

        event = {
            "id": evt.id,
            "pubkey": evt.pubkey,
            "created_at": evt.created_at,
            "kind": evt.kind,
            "tags": evt.tags,
            "content": evt.content,
            "sig": evt.sig,
        }

        result = v.validate(event)
        assert result.valid is True
