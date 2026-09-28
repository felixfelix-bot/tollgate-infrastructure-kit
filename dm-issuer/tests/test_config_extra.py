"""Coverage gap: config.py — to_dict roundtrip, public-relay classifier,
_validate branches, issuer_nsec env access, load_config_or_default paths."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import pytest

from tollgate_dm_issuer.config import (
    Config,
    DEFAULT_CONFIG,
    WhitelistEntry,
    _is_public_relay,
    load_config,
    load_config_or_default,
)


NPUB_FELIX = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
NPUB_S = "npub1dtm05wf2nqy2fnjnc694rvknsc5xsu0z0p4phryds9qqgefdcvcq7neuy4"


class TestIsPublicRelay:
    @pytest.mark.parametrize("url,expected", [
        ("wss://relay.damus.io", True),
        ("ws://nos.lol", True),
        ("wsps://relay.example", True),
        ("ssl://relay.example", True),
        ("ws://127.0.0.1:7777", False),
        ("ws://localhost:7777", False),
        ("ws://[::1]:7777", False),
        ("ws://0.0.0.0:7777", False),
        ("ws://0.1.2.3:7777", False),
        ("", False),
        ("not-a-url", False),
    ])
    def test_classifier(self, url, expected):
        assert _is_public_relay(url) is expected


class TestWhitelistEntryToDict:
    def test_to_dict_roundtrip(self):
        e = WhitelistEntry(npub=NPUB_FELIX, daily_cap_sats=1000,
                           max_request_sats=500, note="test entry")
        d = e.to_dict()
        assert d == {
            "npub": NPUB_FELIX,
            "daily_cap_sats": 1000,
            "max_request_sats": 500,
            "note": "test entry",
        }

    def test_to_dict_without_note(self):
        e = WhitelistEntry(npub=NPUB_FELIX, daily_cap_sats=1000,
                           max_request_sats=500)
        d = e.to_dict()
        assert d["note"] is None


class TestConfigInit:
    def test_default_config_to_dict(self):
        d = DEFAULT_CONFIG.to_dict()
        assert d["issuer_npub"] == DEFAULT_CONFIG.issuer_npub
        assert isinstance(d["relays"], list)
        assert isinstance(d["whitelist"], list)
        assert isinstance(d["defaults"], dict)

    def test_grpc_target_property(self):
        cfg = Config.from_dict({
            "mint_grpc_host": "10.0.0.5",
            "mint_grpc_port": 50070,
        })
        assert cfg.grpc_target == "10.0.0.5:50070"

    def test_issuer_nsec_returns_env_value(self, monkeypatch):
        monkeypatch.setenv("ISSUER_NSEC", "abc123")
        assert DEFAULT_CONFIG.issuer_nsec() == "abc123"

    def test_issuer_nsec_returns_none_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("ISSUER_NSEC", raising=False)
        assert DEFAULT_CONFIG.issuer_nsec() is None

    def test_custom_issuer_nsec_env_var(self, monkeypatch):
        monkeypatch.setenv("CUSTOM_NSEC", "xyz999")
        cfg = Config.from_dict({"issuer_nsec_env": "CUSTOM_NSEC"})
        assert cfg.issuer_nsec() == "xyz999"


class TestValidateErrors:
    def test_min_request_sats_must_be_positive(self):
        with pytest.raises(ValueError, match="min_request_sats"):
            Config.from_dict({"min_request_sats": 0})

    def test_max_requests_per_hour_must_be_positive(self):
        with pytest.raises(ValueError, match="max_requests_per_hour"):
            Config.from_dict({"max_requests_per_hour": 0})

    def test_global_daily_cap_must_be_positive(self):
        with pytest.raises(ValueError, match="global_daily_cap_sats"):
            Config.from_dict({"global_daily_cap_sats": -5})


class TestFromDictPaths:
    def test_issuer_nsec_env_override(self):
        cfg = Config.from_dict({"issuer_nsec_env": "CUSTOM_VAR"})
        assert cfg.issuer_nsec_env == "CUSTOM_VAR"

    def test_mint_url_override(self):
        cfg = Config.from_dict({"mint_url": "https://mint.test"})
        assert cfg.mint_url == "https://mint.test"

    def test_mint_grpc_host_override(self):
        cfg = Config.from_dict({"mint_grpc_host": "10.0.0.99"})
        assert cfg.mint_grpc_host == "10.0.0.99"

    def test_mint_grpc_port_override(self):
        cfg = Config.from_dict({"mint_grpc_port": 51000})
        assert cfg.mint_grpc_port == 51000

    def test_approve_fallback_url_override(self):
        cfg = Config.from_dict({"approve_fallback_url": "http://helper:5555"})
        assert cfg.approve_fallback_url == "http://helper:5555"

    def test_int_keys_override(self):
        cfg = Config.from_dict({
            "poll_seconds": 50,
            "stale_request_secs": 900,
            "dm_lookback_default_secs": 86400,
            "dm_retries": 7,
            "dm_backoff_base_secs": 15,
            "grpc_retries": 6,
            "grpc_backoff_base_secs": 5,
            "quote_ttl_secs": 1800,
            "registry_max_single_issuance": 5000,
            "min_request_sats": 50,
            "max_requests_per_hour": 12,
            "global_daily_cap_sats": 1_000_000,
        })
        assert cfg.poll_seconds == 50
        assert cfg.stale_request_secs == 900
        assert cfg.dm_lookback_default_secs == 86400
        assert cfg.dm_retries == 7
        assert cfg.dm_backoff_base_secs == 15
        assert cfg.grpc_retries == 6
        assert cfg.grpc_backoff_base_secs == 5
        assert cfg.quote_ttl_secs == 1800
        assert cfg.registry_max_single_issuance == 5000
        assert cfg.min_request_sats == 50
        assert cfg.max_requests_per_hour == 12
        assert cfg.global_daily_cap_sats == 1_000_000

    def test_ops_host_and_port_override(self):
        cfg = Config.from_dict({"ops_host": "0.0.0.0", "ops_port": 9090})
        assert cfg.ops_host == "0.0.0.0"
        assert cfg.ops_port == 9090

    def test_verify_before_send_override(self):
        cfg = Config.from_dict({"verify_before_send": True})
        assert cfg.verify_before_send is True

    def test_defaults_override(self):
        cfg = Config.from_dict({
            "defaults": {"daily_cap_sats": 3000, "max_request_sats": 1500},
        })
        assert cfg.defaults["daily_cap_sats"] == 3000
        assert cfg.defaults["max_request_sats"] == 1500


class TestLoadConfigOrDefault:
    def test_none_path_returns_default(self):
        assert load_config_or_default(None) is DEFAULT_CONFIG

    def test_empty_path_returns_default(self):
        assert load_config_or_default("") is DEFAULT_CONFIG

    def test_missing_file_returns_default(self, tmp_path: Path):
        path = tmp_path / "does-not-exist.json"
        assert load_config_or_default(str(path)) is DEFAULT_CONFIG

    def test_existing_file_loads_properly(self, tmp_path: Path):
        raw = {
            "relays": ["wss://relay.damus.io", "wss://nos.lol"],
            "mint_url": "https://mint.test",
            "whitelist": [
                {"npub": NPUB_FELIX, "daily_cap_sats": 5000},
            ],
        }
        path = tmp_path / "config.json"
        path.write_text(json.dumps(raw))
        cfg = load_config_or_default(str(path))
        assert cfg.mint_url == "https://mint.test"
        assert cfg.whitelist_entry(NPUB_FELIX).daily_cap_sats == 5000


class TestLoadConfigMissingFile:
    def test_missing_file_raises_filenotfound(self, tmp_path: Path):
        path = tmp_path / "missing.json"
        with pytest.raises(FileNotFoundError):
            load_config(str(path))
