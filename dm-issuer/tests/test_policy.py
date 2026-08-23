from datetime import datetime, timezone, timedelta
import pytest

from tollgate_dm_issuer.config import Config, WhitelistEntry, DEFAULT_CONFIG
from tollgate_dm_issuer.policy import (
    Decision,
    DecisionKind,
    PolicyEngine,
)
from tollgate_dm_issuer.journal import InMemoryJournal, Journal


NPUB_FELIX = "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
NPUB_SITARANI = "npub1dtm05wf2nqy2fnjnc694rvknsc5xsu0z0p4phryds9qqgefdcvcq7neuy4"
NPUB_ATK = "npub1unknownattacker0000000000000000000000000000000000000000000000"


@pytest.fixture
def config():
    return Config.from_dict({
        "relays": ["wss://relay.damus.io", "wss://nos.lol", "ws://127.0.0.1:7777"],
        "whitelist": [
            {"npub": NPUB_FELIX, "daily_cap_sats": 2000, "max_request_sats": 2000},
            {"npub": NPUB_SITARANI, "daily_cap_sats": 500000, "max_request_sats": 10000},
        ],
        "defaults": {"daily_cap_sats": 2000, "max_request_sats": 2000},
        "global_daily_cap_sats": 600000,
        "min_request_sats": 100,
        "max_requests_per_hour": 6,
        "registry_max_single_issuance": 10000,
        "stale_request_secs": 600,
    })


@pytest.fixture
def journal():
    return InMemoryJournal()


@pytest.fixture
def policy(config, journal):
    return PolicyEngine(config=config, journal=journal)


def now():
    return datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


class TestWhitelist:
    def test_unknown_npub_not_whitelisted(self, policy):
        d = policy.check(NPUB_ATK, amount=100, now=now(), created_at=now(), event_id="e1")
        assert d.kind == DecisionKind.NOT_WHITELISTED
        assert d.code == "NOT_WHITELISTED"

    def test_unknown_npub_rate_limited_once_per_day(self, policy):
        policy.check(NPUB_ATK, amount=100, now=now(), created_at=now(), event_id="e1")
        d2 = policy.check(NPUB_ATK, amount=100, now=now(), created_at=now(), event_id="e2")
        assert d2.kind == DecisionKind.SILENT_DROP


class TestAmountValidation:
    def test_below_min_rejected(self, policy):
        d = policy.check(NPUB_FELIX, amount=99, now=now(), created_at=now(), event_id="e1")
        assert d.kind == DecisionKind.REJECTED
        assert d.code == "AMOUNT_INVALID"

    def test_above_max_request_rejected(self, policy):
        d = policy.check(NPUB_SITARANI, amount=10_001, now=now(), created_at=now(), event_id="e1")
        assert d.kind == DecisionKind.REJECTED
        assert d.code == "AMOUNT_INVALID"

    def test_clamped_to_registry_ceiling(self, policy):
        d = policy.check(NPUB_SITARANI, amount=10_000, now=now(), created_at=now(), event_id="e1")
        assert d.kind == DecisionKind.ALLOW

    def test_felix_max_2000(self, policy):
        d = policy.check(NPUB_FELIX, amount=2_000, now=now(), created_at=now(), event_id="e1")
        assert d.kind == DecisionKind.ALLOW
        d2 = policy.check(NPUB_FELIX, amount=2_001, now=now(), created_at=now(), event_id="e2")
        assert d2.code == "AMOUNT_INVALID"


class TestHourlyRateLimit:
    def test_six_in_hour_allowed_seventh_rejected(self, policy):
        ts = now()
        for i in range(6):
            d = policy.check(NPUB_FELIX, amount=100, now=ts, created_at=ts, event_id=f"ok{i}")
            assert d.kind == DecisionKind.ALLOW, f"iteration {i}: {d}"
        d = policy.check(NPUB_FELIX, amount=100, now=ts, created_at=ts, event_id="ok6")
        assert d.kind == DecisionKind.REJECTED
        assert d.code == "RATE_LIMITED"


class TestDailyCap:
    def test_felix_daily_cap_2000(self, policy):
        ts = now()
        d1 = policy.check(NPUB_FELIX, amount=1000, now=ts, created_at=ts, event_id="e1")
        assert d1.kind == DecisionKind.ALLOW
        policy.commit_usage(NPUB_FELIX, 1000, ts)
        d2 = policy.check(NPUB_FELIX, amount=1500, now=ts, created_at=ts, event_id="e2")
        assert d2.kind == DecisionKind.REJECTED
        assert d2.code == "DAILY_CAP_EXCEEDED"
        assert d2.retry_after_secs is not None and d2.retry_after_secs > 0

    def test_utc_rollover_clears_cap(self, policy):
        ts = now()
        policy.commit_usage(NPUB_FELIX, 2000, ts)
        next_day = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
        d = policy.check(NPUB_FELIX, amount=1000, now=next_day, created_at=next_day, event_id="e2")
        assert d.kind == DecisionKind.ALLOW


class TestGlobalCap:
    def test_global_cap_exceeded(self, monkeypatch: pytest.MonkeyPatch, journal: InMemoryJournal):
        tight_cfg = Config.from_dict({
            "relays": ["wss://relay.damus.io", "wss://nos.lol", "ws://127.0.0.1:7777"],
            "whitelist": [
                {"npub": NPUB_FELIX, "daily_cap_sats": 2000, "max_request_sats": 2000},
                {"npub": NPUB_SITARANI, "daily_cap_sats": 500000, "max_request_sats": 10000},
            ],
            "global_daily_cap_sats": 20_000,
            "min_request_sats": 100,
            "max_requests_per_hour": 6,
            "registry_max_single_issuance": 10000,
        })
        p = PolicyEngine(config=tight_cfg, journal=journal)
        ts = now()
        p.commit_usage(NPUB_SITARANI, 19_900, ts)
        d = p.check(NPUB_SITARANI, amount=200, now=ts, created_at=ts, event_id="e2")
        assert d.kind == DecisionKind.REJECTED
        assert d.code == "GLOBAL_CAP_EXCEEDED"


class TestStaleRequest:
    def test_old_request_rejected(self, policy):
        old_created = now() - timedelta(seconds=601)
        d = policy.check(NPUB_FELIX, amount=100, now=now(), created_at=old_created, event_id="e1")
        assert d.kind == DecisionKind.REJECTED
        assert d.code == "STALE_REQUEST"

    def test_within_threshold_allowed(self, policy):
        old_created = now() - timedelta(seconds=600)
        d = policy.check(NPUB_FELIX, amount=100, now=now(), created_at=old_created, event_id="e1")
        assert d.kind == DecisionKind.ALLOW
