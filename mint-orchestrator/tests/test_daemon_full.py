import asyncio
import os
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from tollgate_mint_orchestrator.mint_registry import MintEntry, MintRegistry
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


class TestEnv:
    def test_returns_default(self):
        from tollgate_mint_orchestrator.daemon import _env, DEFAULTS
        key = "ORCHESTRATOR_API_PORT"
        os.environ.pop(key, None)
        assert _env(key) == DEFAULTS[key]

    def test_returns_env_var(self):
        from tollgate_mint_orchestrator.daemon import _env
        key = "ORCHESTRATOR_API_PORT"
        os.environ[key] = "9999"
        try:
            assert _env(key) == "9999"
        finally:
            del os.environ[key]


class TestGetGrpcClient:
    @pytest.mark.asyncio
    async def test_creates_and_caches_client(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _grpc_clients, _get_grpc_client
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        mint_entry = reg.mints[0]

        with patch("tollgate_mint_orchestrator.daemon.MintGrpcClient") as MockClient:
            mock_instance = AsyncMock()
            MockClient.return_value = mock_instance

            client = await _get_grpc_client(mint_entry)
            assert client is mock_instance
            mock_instance.connect.assert_called_once()

            MockClient.reset_mock()
            client2 = await _get_grpc_client(mint_entry)
            assert client2 is mock_instance
            MockClient.assert_not_called()

        _grpc_clients.clear()

    @pytest.mark.asyncio
    async def test_separate_clients_per_subdomain(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _grpc_clients, _get_grpc_client
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        reg.add_mint({
            "npub": "npub1def",
            "hex_pubkey": "b" * 64,
            "subdomain": "other",
            "url": "https://other.mints.example",
            "rest_port": 3339,
            "grpc_port": 50052,
            "container_name": "mint-other",
            "created_at": "2026-01-02T00:00:00Z",
        })

        with patch("tollgate_mint_orchestrator.daemon.MintGrpcClient") as MockClient:
            mock1 = AsyncMock()
            mock2 = AsyncMock()
            MockClient.side_effect = [mock1, mock2]

            c1 = await _get_grpc_client(reg.mints[0])
            c2 = await _get_grpc_client(reg.mints[1])
            assert c1 is mock1
            assert c2 is mock2
            assert len(_grpc_clients) == 2

        _grpc_clients.clear()


class TestHandleEvent:
    @pytest.mark.asyncio
    async def test_valid_event_successful_approval(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        validator = EventValidator(reg, approval_ttl_secs=300)
        event = _make_event()

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock()
        mock_client.update_nut04_quote = AsyncMock(return_value=True)

        with patch("tollgate_mint_orchestrator.daemon._get_grpc_client", return_value=mock_client):
            with patch("tollgate_mint_orchestrator.event_validator._verify_signature", return_value=True):
                await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is True
        assert entries[0]["quote_id"] == "quote-123"
        mock_client.update_nut04_quote.assert_called_once_with("quote-123", "PAID")

    @pytest.mark.asyncio
    async def test_grpc_update_failure(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        validator = EventValidator(reg, approval_ttl_secs=300)
        event = _make_event()

        mock_client = AsyncMock()
        mock_client.update_nut04_quote = AsyncMock(return_value=False)

        with patch("tollgate_mint_orchestrator.daemon._get_grpc_client", return_value=mock_client):
            with patch("tollgate_mint_orchestrator.event_validator._verify_signature", return_value=True):
                await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is False
        assert "gRPC update failed" in entries[0]["error"]

    @pytest.mark.asyncio
    async def test_invalid_event_kind(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        validator = EventValidator(reg, approval_ttl_secs=300)
        event = _make_event(kind=1)

        await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is False

    @pytest.mark.asyncio
    async def test_invalid_event_wrong_pubkey(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        validator = EventValidator(reg, approval_ttl_secs=300)
        event = _make_event(pubkey="b" * 64)

        await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is False

    @pytest.mark.asyncio
    async def test_authorized_approver_accepted(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        approver_key = "c" * 64
        validator = EventValidator(reg, approval_ttl_secs=300, authorized_approvers=[approver_key])
        event = _make_event(pubkey=approver_key)

        mock_client = AsyncMock()
        mock_client.update_nut04_quote = AsyncMock(return_value=True)

        with patch("tollgate_mint_orchestrator.daemon._get_grpc_client", return_value=mock_client):
            with patch("tollgate_mint_orchestrator.event_validator._verify_signature", return_value=True):
                await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is True

    @pytest.mark.asyncio
    async def test_unauthorized_approver_rejected(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _handle_event, _grpc_clients
        _grpc_clients.clear()

        reg = _make_registry(tmp_path)
        audit = AuditLogger(str(tmp_path / "audit.jsonl"))
        approver_key = "c" * 64
        validator = EventValidator(reg, approval_ttl_secs=300, authorized_approvers=[approver_key])
        event = _make_event(pubkey="d" * 64)

        await _handle_event(event, validator, reg, audit)

        entries = audit.read_recent()
        assert len(entries) == 1
        assert entries[0]["success"] is False
        assert "authorized approvers" in entries[0]["error"]


class TestRunDaemon:
    @pytest.mark.asyncio
    async def test_run_daemon_lifecycle(self, tmp_path):
        from tollgate_mint_orchestrator.daemon import _grpc_clients
        _grpc_clients.clear()

        registry_path = str(tmp_path / "registry.json")
        audit_path = str(tmp_path / "audit.jsonl")

        env = {
            "ORCHESTRATOR_RELAY_URL": "ws://localhost:7777",
            "ORCHESTRATOR_REGISTRY_PATH": registry_path,
            "ORCHESTRATOR_AUDIT_LOG_PATH": audit_path,
            "ORCHESTRATOR_API_HOST": "127.0.0.1",
            "ORCHESTRATOR_API_PORT": "0",
            "ORCHESTRATOR_APPROVAL_TTL_SECS": "300",
            "ORCHESTRATOR_LOG_LEVEL": "warning",
        }

        with patch.dict(os.environ, env, clear=False):
            mock_api = AsyncMock()
            mock_api.start = AsyncMock()
            mock_api.stop = AsyncMock()

            mock_subscriber = AsyncMock()
            mock_subscriber.start = AsyncMock()
            mock_subscriber.stop = AsyncMock()

            with patch("tollgate_mint_orchestrator.daemon.OrchestratorAPI", return_value=mock_api):
                with patch("tollgate_mint_orchestrator.daemon.NostrSubscriber", return_value=mock_subscriber):
                    with patch("tollgate_mint_orchestrator.daemon.MintRegistry") as MockReg:
                        MockReg.load.return_value = MintRegistry(registry_path)

                        with patch("tollgate_mint_orchestrator.daemon._handle_event"):
                            from tollgate_mint_orchestrator.daemon import run_daemon

                            async def run_and_stop():
                                task = asyncio.create_task(run_daemon())
                                await asyncio.sleep(0.2)
                                task.cancel()
                                try:
                                    await task
                                except asyncio.CancelledError:
                                    pass

                            await run_and_stop()

            mock_api.start.assert_called()
            mock_subscriber.stop.assert_called()
            mock_api.stop.assert_called()


class TestMain:
    def test_main_calls_asyncio_run(self):
        from tollgate_mint_orchestrator import daemon

        with patch("tollgate_mint_orchestrator.daemon.asyncio.run") as mock_run:
            daemon.main()
            mock_run.assert_called_once()