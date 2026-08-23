"""Coverage gap: __main__.py — main entry point, _build_components,
_build_fallback_approve, _run_ops_server (spec §10).
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock

import pytest

from pynostr.key import PrivateKey


def _clear_main_module():
    import importlib
    if "tollgate_dm_issuer.__main__" in sys.modules:
        del sys.modules["tollgate_dm_issuer.__main__"]


class TestIssuerPrivkeyHex:
    def _reload(self, monkeypatch):
        _clear_main_module()
        import importlib
        import tollgate_dm_issuer.__main__ as entry_mod
        importlib.reload(entry_mod)
        return entry_mod

    def test_returns_none_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("ISSUER_NSEC", raising=False)
        entry = self._reload(monkeypatch)
        assert entry._issuer_privkey_hex() is None

    def test_returns_none_when_env_empty(self, monkeypatch):
        monkeypatch.setenv("ISSUER_NSEC", "  ")
        entry = self._reload(monkeypatch)
        assert entry._issuer_privkey_hex() is None

    def test_returns_hex_when_env_is_hex_string(self, monkeypatch):
        sk = PrivateKey()
        monkeypatch.setenv("ISSUER_NSEC", sk.hex())
        entry = self._reload(monkeypatch)
        assert entry._issuer_privkey_hex() == sk.hex()

    def test_returns_hex_when_env_is_nsec(self, monkeypatch):
        sk = PrivateKey()
        monkeypatch.setenv("ISSUER_NSEC", sk.nsec)
        entry = self._reload(monkeypatch)
        assert entry._issuer_privkey_hex() == sk.hex()

    def test_returns_none_when_nsec_is_invalid(self, monkeypatch, caplog):
        monkeypatch.setenv("ISSUER_NSEC", "nsec1invalid")
        entry = self._reload(monkeypatch)
        import logging
        with caplog.at_level(logging.ERROR, logger="tollgate_dm_issuer"):
            assert entry._issuer_privkey_hex() is None


class TestBuildFallbackApprove:
    @staticmethod
    def _install_fake_aiohttp(monkeypatch, status):
        mock_response = MagicMock()
        mock_response.status = status

        mock_post_cm = MagicMock()
        mock_post_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_post_cm.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_post_cm)

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        fake = MagicMock()
        fake.ClientSession = MagicMock(return_value=mock_session_cm)
        fake.ClientTimeout = MagicMock()
        monkeypatch.setitem(sys.modules, "aiohttp", fake)
        return mock_session

    async def test_approve_returns_true_on_200(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod
        session = self._install_fake_aiohttp(monkeypatch, 200)
        approve = entry_mod._build_fallback_approve("http://x/approve")
        ok = await approve("q123")
        assert ok is True
        session.post.assert_called_once()
        _, kwargs = session.post.call_args
        assert kwargs["json"] == {"quote_id": "q123"}

    async def test_approve_returns_true_on_201(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod
        self._install_fake_aiohttp(monkeypatch, 201)
        approve = entry_mod._build_fallback_approve("http://x/approve")
        ok = await approve("q9")
        assert ok is True

    async def test_approve_returns_false_on_500(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod
        self._install_fake_aiohttp(monkeypatch, 500)
        approve = entry_mod._build_fallback_approve("http://x/approve")
        ok = await approve("q1")
        assert ok is False


class TestRunOpsServer:
    def test_runs_uvicorn_with_app(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod

        call_count = {"server_run": 0}

        class _FakeServer:
            def __init__(self, config):
                self.config = config

            def run(self):
                call_count["server_run"] += 1

        mock_uvicorn = MagicMock()
        mock_uvicorn.Config = MagicMock(return_value=MagicMock())
        mock_uvicorn.Server = _FakeServer

        monkeypatch.setattr(entry_mod, "uvicorn", mock_uvicorn)

        from tollgate_dm_issuer.ops import Metrics
        entry_mod._run_ops_server(Metrics(), host="127.0.0.1", port=9999)

        mock_uvicorn.Config.assert_called_once()
        kwargs = mock_uvicorn.Config.call_args.kwargs
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 9999
        assert call_count["server_run"] == 1


class TestBuildComponents:
    def test_builds_full_deps_from_env(self, monkeypatch, tmp_path):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod
        from tollgate_dm_issuer.dispatcher import DispatcherDeps

        sk = PrivateKey()
        monkeypatch.setenv("ISSUER_NSEC", sk.hex())
        monkeypatch.setenv("DM_ISSUER_DB_PATH", str(tmp_path / "comp.db"))
        monkeypatch.setenv("ISSUER_CONFIG_PATH", "")

        deps = entry_mod._build_components()
        assert isinstance(deps, DispatcherDeps)
        assert deps.config is not None
        assert deps.journal is not None
        assert deps.policy is not None
        assert deps.metrics is not None
        assert deps.nostr_io is not None
        assert deps.mint_client is not None
        assert deps.grpc_payer is not None

    def test_fallback_via_config(self, monkeypatch, tmp_path):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod
        import json as _json

        sk = PrivateKey()
        monkeypatch.setenv("ISSUER_NSEC", sk.hex())
        monkeypatch.setenv("DM_ISSUER_DB_PATH", str(tmp_path / "comp.db"))
        cfg_path = tmp_path / "config.json"
        cfg_path.write_text(_json.dumps({
            "relays": ["wss://relay.damus.io", "wss://nos.lol"],
            "approve_fallback_url": "http://127.0.0.1:50057/approve",
        }))
        monkeypatch.setenv("ISSUER_CONFIG_PATH", str(cfg_path))

        deps = entry_mod._build_components()
        assert deps.grpc_payer._fallback is not None


class TestMainEntry:
    def _patch_main(self, monkeypatch, run_forever_coro):
        import tollgate_dm_issuer.__main__ as entry_mod
        from tollgate_dm_issuer.grpc_payer import GrpcPayer

        grpc_payer = GrpcPayer(
            stub_factory=lambda: MagicMock(),
            retries=1, backoff_base_secs=0.0,
        )
        grpc_payer.close = AsyncMock()

        cfg = MagicMock()
        cfg.ops_host = "127.0.0.1"
        cfg.ops_port = 9999
        deps = MagicMock()
        deps.config = cfg
        deps.grpc_payer = grpc_payer

        monkeypatch.setattr(entry_mod, "_build_components", lambda: deps)

        async def _rf():
            return await run_forever_coro

        dispatcher = MagicMock()
        dispatcher.run_forever = _rf
        dispatcher.request_stop = MagicMock()

        monkeypatch.setattr(entry_mod, "Dispatcher", MagicMock(return_value=dispatcher))
        monkeypatch.setattr(entry_mod, "_run_ops_server", MagicMock())

        return dispatcher, grpc_payer, deps

    def test_main_completes_on_normal_exit(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod

        async def _normal():
            return None

        dispatcher, grpc_payer, _ = self._patch_main(monkeypatch, _normal())
        entry_mod.main()

        dispatcher.request_stop.assert_called_once()
        grpc_payer.close.assert_awaited_once()

    def test_main_handles_keyboard_interrupt(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod

        async def _kb():
            raise KeyboardInterrupt()

        dispatcher, grpc_payer, _ = self._patch_main(monkeypatch, _kb())
        entry_mod.main()

        dispatcher.request_stop.assert_called_once()
        grpc_payer.close.assert_awaited_once()

    def test_main_handles_grpc_close_failure(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod

        async def _normal():
            return None

        dispatcher, grpc_payer, _ = self._patch_main(monkeypatch, _normal())
        grpc_payer.close = AsyncMock(side_effect=RuntimeError("boom"))
        entry_mod.main()

        dispatcher.request_stop.assert_called_once()
        grpc_payer.close.assert_awaited_once()

    def test_main_skips_close_when_not_grpcpayer(self, monkeypatch):
        _clear_main_module()
        import tollgate_dm_issuer.__main__ as entry_mod

        async def _normal():
            return None

        # Patch _build_components to return deps without a GrpcPayer instance
        async def _no_close_run():
            return None

        dispatcher_holder = MagicMock()
        dispatcher_holder.run_forever = _no_close_run
        dispatcher_holder.request_stop = MagicMock()

        cfg = MagicMock()
        cfg.ops_host = "127.0.0.1"
        cfg.ops_port = 9999
        deps = MagicMock()
        deps.config = cfg
        deps.grpc_payer = MagicMock()  # not GrpcPayer — close() must be skipped

        monkeypatch.setattr(entry_mod, "_build_components", lambda: deps)
        monkeypatch.setattr(entry_mod, "Dispatcher", MagicMock(return_value=dispatcher_holder))
        monkeypatch.setattr(entry_mod, "_run_ops_server", MagicMock())

        entry_mod.main()

        dispatcher_holder.request_stop.assert_called_once()
        deps.grpc_payer.close.assert_not_called()
