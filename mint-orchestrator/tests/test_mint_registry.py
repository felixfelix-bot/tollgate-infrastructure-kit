import json
import os
import tempfile
from tollgate_mint_orchestrator.mint_registry import MintRegistry, MintEntry


def _make_entry(**overrides):
    defaults = {
        "npub": "npub1abc1234567890abcdef",
        "hex_pubkey": "<redacted>",
        "subdomain": "abc123456789",
        "url": "https://abc123456789.mints.test",
        "rest_port": 3338,
        "grpc_port": 50051,
        "container_name": "mint-abc123456789",
        "created_at": "2026-05-15T12:00:00Z",
        "max_single_issuance": 10000,
        "max_balance": 1000000,
    }
    defaults.update(overrides)
    return defaults


class TestMintRegistry:
    def test_load_empty(self, tmp_path):
        reg = MintRegistry.load(str(tmp_path / "registry.json"))
        assert reg.mints == []

    def test_load_existing(self, tmp_path):
        path = str(tmp_path / "registry.json")
        data = {"mints": [_make_entry()]}
        with open(path, "w") as f:
            json.dump(data, f)
        reg = MintRegistry.load(path)
        assert len(reg.mints) == 1
        assert reg.mints[0].subdomain == "abc123456789"

    def test_save_and_reload(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry())
        reg2 = MintRegistry.load(path)
        assert len(reg2.mints) == 1

    def test_get_mint_by_url(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry())
        found = reg.get_mint_by_url("https://abc123456789.mints.test")
        assert found is not None
        assert found.subdomain == "abc123456789"

    def test_get_mint_by_url_not_found(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        assert reg.get_mint_by_url("https://nonexistent.mints.test") is None

    def test_get_mint_by_subdomain(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry())
        found = reg.get_mint_by_subdomain("abc123456789")
        assert found is not None

    def <redacted>(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry())
        found = reg.get_mint_by_hex_pubkey(
            "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
        assert found is not None

    def test_add_mint_replaces_existing(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry())
        reg.add_mint(_make_entry(rest_port=9999))
        assert len(reg.mints) == 1
        assert reg.mints[0].rest_port == 9999

    def test_remove_mint(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry(subdomain="abc"))
        reg.add_mint(_make_entry(subdomain="def", hex_pubkey="11" * 32))
        reg.remove_mint("abc")
        assert len(reg.mints) == 1
        assert reg.mints[0].subdomain == "def"

    def test_list_mints(self, tmp_path):
        path = str(tmp_path / "registry.json")
        reg = MintRegistry(path)
        reg.add_mint(_make_entry(subdomain="abc"))
        reg.add_mint(_make_entry(subdomain="def", hex_pubkey="11" * 32))
        assert len(reg.list_mints()) == 2

    def test_derive_subdomain(self):
        sub = MintRegistry.derive_subdomain("npub1abc1234567890abcdef")
        assert sub == "abc123456789"

    def test_next_ports_empty(self):
        assert MintRegistry.next_ports([]) == (3338, 50051)

    def test_next_ports_existing(self):
        entries = [MintEntry(**_make_entry(rest_port=3338, grpc_port=50051))]
        assert MintRegistry.next_ports(entries) == (3339, 50052)
