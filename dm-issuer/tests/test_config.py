import os
import json
from pathlib import Path

import pytest

from tollgate_dm_issuer.config import (
    Config,
    WhitelistEntry,
    DEFAULT_CONFIG,
    load_config,
)


def test_default_config_values():
    cfg = DEFAULT_CONFIG
    assert cfg.min_request_sats == 100
    assert cfg.max_requests_per_hour == 6
    cfg2 = Config.from_dict({})
    assert cfg2 == cfg


def test_whitelist_entry_lookup_returns_none_for_unknown_npub():
    cfg = Config.from_dict({"whitelist": []})
    assert cfg.whitelist_entry("npub1unknown") is None


def test_whitelist_entry_lookup_per_npub_overrides_defaults():
    npub_felix = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
    npub_sitarani = "npub1dtm05wf2nqy2fnjnc694rvknsc5xsu0z0p4phryds9qqgefdcvcq7neuy4"
    raw = {
        "whitelist": [
            {"npub": npub_felix, "daily_cap_sats": 2000, "max_request_sats": 2000},
            {"npub": npub_sitarani, "daily_cap_sats": 500000, "max_request_sats": 10000},
        ],
        "defaults": {"daily_cap_sats": 2000, "max_request_sats": 2000},
    }
    cfg = Config.from_dict(raw)
    fe = cfg.whitelist_entry(npub_felix)
    assert fe.npub == npub_felix
    assert fe.daily_cap_sats == 2000
    assert fe.max_request_sats == 2000
    si = cfg.whitelist_entry(npub_sitarani)
    assert si.daily_cap_sats == 500000
    assert si.max_request_sats == 10000
    assert si.max_request_sats == cfg.effective_max_request_sats(si.npub, registry_ceiling=10000)


def test_effective_max_request_clamps_to_registry_ceiling():
    npub_felix = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
    cfg = Config.from_dict({
        "whitelist": [{"npub": npub_felix, "daily_cap_sats": 2000, "max_request_sats": 2000}],
    })
    assert cfg.effective_max_request_sats(npub_felix, registry_ceiling=10000) == 2000
    assert cfg.effective_max_request_sats(npub_felix, registry_ceiling=500) == 500


def test_relays_must_include_two_public_relays():
    with pytest.raises(ValueError):
        Config.from_dict({"relays": ["ws://127.0.0.1:7777"]})
    cfg = Config.from_dict({
        "relays": [
            "wss://relay.damus.io",
            "wss://nos.lol",
            "ws://127.0.0.1:7777",
        ]
    })
    assert len(cfg.relays) == 3


def test_load_config_from_file(tmp_path: Path):
    npub = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
    raw = {
        "relays": ["wss://relay.damus.io", "wss://nos.lol", "ws://127.0.0.1:7777"],
        "mint_url": "https://mint.example.test",
        "whitelist": [{"npub": npub, "daily_cap_sats": 1000, "max_request_sats": 500}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    cfg = load_config(str(path))
    assert cfg.mint_url == "https://mint.example.test"
    assert cfg.whitelist_entry(npub).daily_cap_sats == 1000


def test_load_config_env_override_for_nsec_var_name(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ISSUER_NSEC", "nsec1dummy1234567890")
    npub = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
    raw = {
        "relays": ["wss://relay.damus.io", "wss://nos.lol"],
        "whitelist": [{"npub": npub}],
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(raw))
    cfg = load_config(str(path))
    assert cfg.issuer_nsec_env == "ISSUER_NSEC"
