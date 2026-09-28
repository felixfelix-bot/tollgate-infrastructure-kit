"""Configuration loader for the DM issuer (quote-handoff mode).

Default values are sourced from ``dm-auto-issuance-spec.md`` §4 (DM-CFG-1..3,
DM-CFG-4). The config object is immutable after construction so the poller,
policy engine and journal all observe a single consistent snapshot.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional


_ISSUER_NPUB = "npub1ac2r0qy6hws6fxn7eulewnnlesacertzuq4v9mhyywcu7phslcrsdrvykw"
_RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "ws://127.0.0.1:7777",
]
_PUBLIC_RELAY_PREFIXES = ("wss://", "ws://", "wsps://", "ssl://")


@dataclass(frozen=True)
class WhitelistEntry:
    npub: str
    daily_cap_sats: int
    max_request_sats: int
    note: Optional[str] = None

    @classmethod
    def from_dict(cls, raw: dict, defaults: dict) -> "WhitelistEntry":
        daily_cap_sats = int(raw.get("daily_cap_sats", defaults.get("daily_cap_sats", 2000)))
        max_request_sats = int(raw.get("max_request_sats", defaults.get("max_request_sats", 2000)))
        return cls(
            npub=raw["npub"],
            daily_cap_sats=daily_cap_sats,
            max_request_sats=max_request_sats,
            note=raw.get("note"),
        )

    def to_dict(self) -> dict:
        return {
            "npub": self.npub,
            "daily_cap_sats": self.daily_cap_sats,
            "max_request_sats": self.max_request_sats,
            "note": self.note,
        }


def _is_public_relay(url: str) -> bool:
    if not url:
        return False
    lowered = url.lower()
    if lowered.startswith(("ws://127.", "ws://localhost", "ws://[::1]")):
        return False
    if lowered.startswith("ws://0.") or "0.0.0.0" in lowered:
        return False
    return lowered.startswith(_PUBLIC_RELAY_PREFIXES)


@dataclass(frozen=True)
class Config:
    issuer_npub: str = _ISSUER_NPUB
    issuer_nsec_env: str = "ISSUER_NSEC"
    relays: tuple = tuple(_RELAYS)
    mint_url: str = "https://mint.orangesync.tech"
    mint_grpc_host: str = "127.0.0.1"
    mint_grpc_port: int = 50055
    approve_fallback_url: str = "http://127.0.0.1:50057/approve"
    whitelist: tuple = ()
    defaults: dict = field(default_factory=lambda: {
        "daily_cap_sats": 2000,
        "max_request_sats": 2000,
    })
    min_request_sats: int = 100
    max_requests_per_hour: int = 6
    global_daily_cap_sats: int = 600000
    registry_max_single_issuance: int = 10000
    poll_seconds: int = 20
    stale_request_secs: int = 600
    dm_lookback_default_secs: int = 43200
    dm_retries: int = 5
    dm_backoff_base_secs: int = 30
    grpc_retries: int = 4
    grpc_backoff_base_secs: int = 2
    quote_ttl_secs: int = 900
    verify_before_send: bool = False
    ops_host: str = "127.0.0.1"
    ops_port: int = 8095

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        cfg = copy.deepcopy(DEFAULT_CONFIG.__dict__)
        if "issuer_npub" in raw:
            cfg["issuer_npub"] = raw["issuer_npub"]
        if "issuer_nsec_env" in raw:
            cfg["issuer_nsec_env"] = raw["issuer_nsec_env"]
        if "relays" in raw:
            cfg["relays"] = tuple(raw["relays"])
        if "mint_url" in raw:
            cfg["mint_url"] = raw["mint_url"]
        if "mint_grpc_host" in raw:
            cfg["mint_grpc_host"] = raw["mint_grpc_host"]
        if "mint_grpc_port" in raw:
            cfg["mint_grpc_port"] = int(raw["mint_grpc_port"])
        if "approve_fallback_url" in raw:
            cfg["approve_fallback_url"] = raw["approve_fallback_url"]
        cfg["defaults"] = dict(raw.get("defaults", cfg["defaults"]))
        entries = [WhitelistEntry.from_dict(r, cfg["defaults"]) for r in raw.get("whitelist", [])]
        cfg["whitelist"] = tuple(entries)
        for int_key in (
            "min_request_sats",
            "max_requests_per_hour",
            "global_daily_cap_sats",
            "registry_max_single_issuance",
            "poll_seconds",
            "stale_request_secs",
            "dm_lookback_default_secs",
            "dm_retries",
            "dm_backoff_base_secs",
            "grpc_retries",
            "grpc_backoff_base_secs",
            "quote_ttl_secs",
            "ops_port",
        ):
            if int_key in raw:
                cfg[int_key] = int(raw[int_key])
        for str_key in ("ops_host", "approve_fallback_url"):
            if str_key in raw:
                cfg[str_key] = raw[str_key]
        if "verify_before_send" in raw:
            cfg["verify_before_send"] = bool(raw["verify_before_send"])
        cfg["relays"] = tuple(cfg["relays"])
        instance = cls(**cfg)
        instance.validate()
        return instance

    def validate(self) -> None:
        public = [r for r in self.relays if _is_public_relay(r)]
        if len(public) < 2:
            raise ValueError(
                "config.relays must include at least two public relays "
                "(the local strfry at 127.0.0.1:7777 is loopback-only and "
                "cannot receive user DMs — spec DM-CFG-4)"
            )
        if self.min_request_sats <= 0:
            raise ValueError("min_request_sats must be > 0")
        if self.max_requests_per_hour <= 0:
            raise ValueError("max_requests_per_hour must be > 0")
        if self.global_daily_cap_sats <= 0:
            raise ValueError("global_daily_cap_sats must be > 0")

    @property
    def grpc_target(self) -> str:
        return f"{self.mint_grpc_host}:{self.mint_grpc_port}"

    def whitelist_entry(self, npub: str) -> Optional[WhitelistEntry]:
        for entry in self.whitelist:
            if entry.npub == npub:
                return entry
        return None

    def effective_max_request_sats(self, npub: str, registry_ceiling: int) -> int:
        entry = self.whitelist_entry(npub)
        if entry is None:
            return min(registry_ceiling, self.defaults["max_request_sats"])
        return min(entry.max_request_sats, registry_ceiling, self.registry_max_single_issuance)

    def issuer_nsec(self) -> Optional[str]:
        return os.environ.get(self.issuer_nsec_env)

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        d["whitelist"] = [e.to_dict() for e in self.whitelist]
        d["relays"] = list(self.relays)
        d["defaults"] = dict(self.defaults)
        return d


DEFAULT_CONFIG = Config()


def load_config(path: str | os.PathLike) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    raw = json.loads(p.read_text())
    return Config.from_dict(raw)


def load_config_or_default(path: Optional[str | os.PathLike]) -> Config:
    if not path:
        return DEFAULT_CONFIG
    try:
        return load_config(path)
    except FileNotFoundError:
        return DEFAULT_CONFIG
