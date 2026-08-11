import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from tollgate_mint_orchestrator.mint_registry import MintRegistry
from tollgate_mint_orchestrator.event_validator import EventValidator
from tollgate_mint_orchestrator.audit_log import AuditLogger


def _make_registry(tmp_path):
    path = str(tmp_path / "registry.json")
    reg = MintRegistry(path)
    reg.add_mint({
        "npub": "npub1abc",
        "hex_pubkey": "a" * 64,
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


import pytest


class TestDaemon:
    @pytest.mark.asyncio
    async def test_handle_invalid_event(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event
        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        validator = EventValidator(reg, approval_ttl_secs=300)

        event = _make_event(kind=1)
        await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is False

    @pytest.mark.asyncio
    async def test_handle_event_grpc_not_connected(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        validator = EventValidator(reg, approval_ttl_secs=300)

        event = _make_event()

        mock_client = AsyncMock()
        mock_client.update_nut04_quote = AsyncMock(return_value=False)
        mock_client.connect = AsyncMock()

        with patch("tollgate_mint_orchestrator.daemon._get_grpc_client", return_value=mock_client):
            with patch("tollgate_mint_orchestrator.event_validator._verify_signature", return_value=True):
                await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert any(e["success"] is False for e in entries)