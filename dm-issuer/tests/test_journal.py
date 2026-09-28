"""Journal tests — covers both InMemoryJournal and SQLiteJournal.

The SQLiteJournal is the production backing store; InMemoryJournal is the same
shape and used by policy unit tests. We exercise the SQLite implementation
end-to-end with a temp file.
"""
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tollgate_dm_issuer.journal import (
    InMemoryJournal,
    SQLiteJournal,
    REQUESTED,
    QUOTED,
    PAID,
    DELIVERED,
    FAILED,
    request_id_for,
    iso,
    parse_iso,
    day_utc,
)


NPUB_ALICE = "npub1alice0000000000000000000000000000000000000000000000000000ab"
NPUB_BOB = "npub1bob00000000000000000000000000000000000000000000000000000000c"


def now():
    return datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(params=["memory", "sqlite"])
def journal(request, tmp_path: Path):
    if request.param == "memory":
        return InMemoryJournal()
    db_path = tmp_path / "ledger.sqlite"
    return SQLiteJournal(db_path)


class TestEventDedup:
    def test_first_seen(self, journal):
        assert journal.is_event_processed("e1") is False
        journal.mark_event_processed("e1", 1234567890.0)
        assert journal.is_event_processed("e1") is True

    def test_idempotent(self, journal):
        journal.mark_event_processed("e1", 1.0)
        journal.mark_event_processed("e1", 2.0)
        assert journal.is_event_processed("e1") is True


class TestRequestLifecycle:
    def test_insert_then_fetch(self, journal):
        ts = now()
        rid = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        assert rid == request_id_for("e1")
        row = journal.fetch_request(rid)
        assert row is not None
        assert row.event_id == "e1"
        assert row.npub == NPUB_ALICE
        assert row.amount == 1000
        assert row.state == REQUESTED
        assert row.quote_id is None

    def test_fetch_by_event(self, journal):
        ts = now()
        rid = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        row = journal.fetch_request_by_event("e1")
        assert row is not None
        assert row.request_id == rid

    def test_cas_state_forward_only(self, journal):
        ts = now()
        rid = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        assert journal.cas_state(rid, REQUESTED, QUOTED, quote_id="q123", ts=ts) is True
        row = journal.fetch_request(rid)
        assert row.state == QUOTED
        assert row.quote_id == "q123"
        assert journal.cas_state(rid, REQUESTED, QUOTED) is False

    def test_cas_state_rejects_backward(self, journal):
        ts = now()
        rid = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        assert journal.cas_state(rid, REQUESTED, QUOTED, quote_id="q", ts=ts) is True
        assert journal.cas_state(rid, QUOTED, REQUESTED) is False
        assert journal.cas_state(rid, QUOTED, REQUESTED) is False

    def test_full_lifecycle(self, journal):
        ts = now()
        rid = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        assert journal.cas_state(rid, REQUESTED, QUOTED, quote_id="q1", ts=ts)
        assert journal.cas_state(rid, QUOTED, PAID, ts=ts)
        assert journal.cas_state(rid, PAID, DELIVERED, ts=ts)
        row = journal.fetch_request(rid)
        assert row.state == DELIVERED
        assert journal.cas_state(rid, DELIVERED, REQUESTED) is False


class TestUsage:
    def test_commit_usage_increments(self, journal):
        ts = now()
        journal.commit_usage(NPUB_ALICE, 1000, ts)
        requests, sats = journal.get_usage(NPUB_ALICE, day_utc(ts))
        assert requests == 1
        assert sats == 1000
        journal.commit_usage(NPUB_ALICE, 500, ts)
        requests, sats = journal.get_usage(NPUB_ALICE, day_utc(ts))
        assert requests == 2
        assert sats == 1500

    def test_global_usage_across_npubs(self, journal):
        ts = now()
        journal.commit_usage(NPUB_ALICE, 100, ts)
        journal.commit_usage(NPUB_BOB, 200, ts)
        assert journal.get_global_usage(day_utc(ts)) == 300

    def test_daily_rollover_isolates_usage(self, journal):
        ts_t1 = now()
        ts_t2 = ts_t1 + timedelta(days=1)
        journal.commit_usage(NPUB_ALICE, 1000, ts_t1)
        requests, sats = journal.get_usage(NPUB_ALICE, day_utc(ts_t2))
        assert requests == 0
        assert sats == 0


class TestPendingReservation:
    def test_reserve_then_commit_clears_pending(self, journal):
        ts = now()
        journal.reserve_request(NPUB_ALICE, "e1", 1000, ts)
        assert journal.get_pending_usage(NPUB_ALICE, day_utc(ts)) == 1000
        journal.commit_usage(NPUB_ALICE, 1000, ts)
        assert journal.get_pending_usage(NPUB_ALICE, day_utc(ts)) == 0

    def test_count_recent_requests(self, journal):
        ts = now()
        journal.reserve_request(NPUB_ALICE, "e1", 100, ts)
        journal.reserve_request(NPUB_ALICE, "e2", 100, ts + timedelta(seconds=10))
        assert journal.count_recent_requests(NPUB_ALICE, ts - timedelta(minutes=1)) == 2
        assert journal.count_recent_requests(NPUB_ALICE, ts + timedelta(seconds=20)) == 0


class TestRecovery:
    def test_fetch_recoverable_after_restart(self, tmp_path: Path):
        db_path = tmp_path / "ledger.sqlite"
        j1 = SQLiteJournal(db_path)
        ts = now()
        rid = j1.insert_request("e1", NPUB_ALICE, 1000, ts)
        j1.cas_state(rid, REQUESTED, QUOTED, quote_id="q", ts=ts)
        j1.close()
        j2 = SQLiteJournal(db_path)
        rec = j2.fetch_recoverable()
        assert len(rec) == 1
        assert rec[0].request_id == rid
        assert rec[0].state == QUOTED
        j2.close()


class TestKV:
    def test_kv_set_get(self, journal):
        assert journal.get_kv("foo") is None
        assert journal.get_kv("foo", "default") == "default"
        journal.set_kv("foo", "bar")
        assert journal.get_kv("foo") == "bar"
        journal.set_kv("foo", "baz")
        assert journal.get_kv("foo") == "baz"


class TestDedupeIdempotency:
    def test_double_insert_same_event_id_second_returns_existing(self, journal):
        ts = now()
        rid1 = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        rid2 = journal.insert_request("e1", NPUB_ALICE, 500, ts)
        assert rid1 == rid2


class TestMarkDelivered:
    def test_mark_delivered_flag(self, journal):
        ts = now()
        rid = journal.insert_request("e1", NPUB_ALICE, 1000, ts)
        journal.cas_state(rid, REQUESTED, QUOTED, quote_id="q", ts=ts)
        journal.cas_state(rid, QUOTED, PAID, ts=ts)
        journal.cas_state(rid, PAID, DELIVERED, ts=ts)
        row = journal.fetch_request(rid)
        assert row.state == DELIVERED
        assert row.delivered == 0
        journal.mark_delivered(rid, ts=ts)
        row = journal.fetch_request(rid)
        assert row.delivered == 1


class TestRecoveryMethod:
    def test_recover_rejects_stale_requested(self, tmp_path: Path):
        db_path = tmp_path / "ledger.sqlite"
        j = SQLiteJournal(db_path)
        ts = now()
        rid = j.insert_request("e_old", NPUB_ALICE, 1000, ts - timedelta(seconds=601))
        out = j.recover(now=ts, stale_secs=600)
        row = j.fetch_request(rid)
        assert row.state == "REJECTED"
        assert row.error_code == "STALE_REQUEST"
        j.close()
