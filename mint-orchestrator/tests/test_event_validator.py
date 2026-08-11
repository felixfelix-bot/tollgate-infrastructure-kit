import time
import json
from tollgate_mint_orchestrator.event_validator import EventValidator, _compute_event_id, SUPPORTED_UNITS
from tollgate_mint_orchestrator.mint_registry import MintRegistry, MintEntry


def _make_registry(tmp_path, mints=None):
    path = str(tmp_path / "registry.json")
    reg = MintRegistry(path)
    if mints is None:
        mints = [{
            "npub": "npub1abc",
            "hex_pubkey": "a" * 64,
            "subdomain": "test",
            "url": "https://test.mints.example",
            "rest_port": 3338,
            "grpc_port": 50051,
            "container_name": "mint-test",
            "created_at": "2026-01-01T00:00:00Z",
        }]
    for m in mints:
        reg.add_mint(m)
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


class TestComputeEventId:
    def test_deterministic(self):
        event = _make_event()
        id1 = _compute_event_id(event)
        id2 = _compute_event_id(event)
        assert id1 == id2

    def test_changes_with_content(self):
        event1 = _make_event(content="foo")
        event2 = _make_event(content="bar")
        assert _compute_event_id(event1) != _compute_event_id(event2)


class TestEventValidator:
    def test_valid_kind_check(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        result = v.validate(_make_event(kind=1))
        assert not result.valid
        assert "kind" in result.error

    def test_missing_t_tag(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["x", "other"]])
        result = v.validate(event)
        assert not result.valid
        assert "t tag" in result.error

    def test_missing_mint_tag(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["quote", "q1"], ["amount", "100"], ["unit", "sat"]])
        result = v.validate(event)
        assert not result.valid
        assert "mint tag" in result.error

    def test_unknown_mint(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://unknown.mints.example"], ["quote", "q1"], ["amount", "100"], ["unit", "sat"]])
        result = v.validate(event)
        assert not result.valid
        assert "unknown mint" in result.error

    def test_missing_quote_tag(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://test.mints.example"], ["amount", "100"], ["unit", "sat"]])
        result = v.validate(event)
        assert not result.valid
        assert "quote" in result.error

    def test_missing_amount_tag(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://test.mints.example"], ["quote", "q1"], ["unit", "sat"]])
        result = v.validate(event)
        assert not result.valid
        assert "amount" in result.error

    def test_invalid_amount(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://test.mints.example"], ["quote", "q1"], ["amount", "abc"], ["unit", "sat"]])
        result = v.validate(event)
        assert not result.valid
        assert "integer" in result.error

    def test_negative_amount(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://test.mints.example"], ["quote", "q1"], ["amount", "-5"], ["unit", "sat"]])
        result = v.validate(event)
        assert not result.valid
        assert "positive" in result.error

    def test_missing_unit_tag(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://test.mints.example"], ["quote", "q1"], ["amount", "100"]])
        result = v.validate(event)
        assert not result.valid
        assert "unit" in result.error

    def test_unsupported_unit(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(tags=[["t", "mint-approval"], ["mint", "https://test.mints.example"], ["quote", "q1"], ["amount", "100"], ["unit", "btc"]])
        result = v.validate(event)
        assert not result.valid
        assert "unsupported unit" in result.error

    def test_wrong_pubkey(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg)
        event = _make_event(pubkey="b" * 64)
        result = v.validate(event)
        assert not result.valid
        assert "pubkey" in result.error

    def test_authorized_approver_accepted(self, tmp_path):
        reg = _make_registry(tmp_path)
        approver_key = "c" * 64
        v = EventValidator(reg, authorized_approvers=[approver_key])
        event = _make_event(pubkey=approver_key)
        result = v.validate(event)
        assert result.valid or "signature" in (result.error or "")

    def test_unauthorized_approver_rejected(self, tmp_path):
        reg = _make_registry(tmp_path)
        approver_key = "c" * 64
        v = EventValidator(reg, authorized_approvers=[approver_key])
        event = _make_event(pubkey="d" * 64)
        result = v.validate(event)
        assert not result.valid
        assert "authorized approvers" in result.error

    def test_expired_event(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg, approval_ttl_secs=300)
        event = _make_event(created_at=int(time.time()) - 600)
        result = v.validate(event)
        assert not result.valid
        assert "TTL" in result.error

    def test_all_supported_units(self, tmp_path):
        reg = _make_registry(tmp_path)
        v = EventValidator(reg, approval_ttl_secs=300)
        for unit in SUPPORTED_UNITS:
            event = _make_event(tags=[
                ["t", "mint-approval"],
                ["mint", "https://test.mints.example"],
                ["quote", "q1"],
                ["amount", "100"],
                ["unit", unit],
            ])
            result = v.validate(event)
            if result.valid:
                assert result.unit == unit
            else:
                assert result.error in ("invalid event signature", "TTL exceeded") or "signature" in result.error
