"""Tests for the CLI (cli.py) — uses InMemoryJournal as mock journal.

Command-level tests verify output via captured stdout. Integration tests
exercise main() with a temporary SQLiteJournal via the --db flag.
"""
from __future__ import annotations

import contextlib
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from tollgate_dm_issuer.cli import (
    CURSOR_KEY,
    build_parser,
    cmd_reset_cursor,
    cmd_revoke_request,
    cmd_show_ledger,
    cmd_show_usage,
    main,
)
from tollgate_dm_issuer.journal import (
    DELIVERED,
    InMemoryJournal,
    PAID,
    QUOTED,
    REJECTED,
    REQUESTED,
    SQLiteJournal,
    iso,
)


NPUB_ALICE = "npub1alice0000000000000000000000000000000000000000000000000000ab"
NPUB_BOB = "npub1bob00000000000000000000000000000000000000000000000000000000c"


def now() -> datetime:
    return datetime(2026, 8, 23, 12, 0, 0, tzinfo=timezone.utc)


def capture(func, *args, **kwargs) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = func(*args, **kwargs)
    return rc, buf.getvalue()


class TestShowLedger:
    def test_empty(self):
        j = InMemoryJournal()
        rc, out = capture(cmd_show_ledger, j)
        assert rc == 0
        assert "(no requests)" in out

    def test_with_requests(self):
        j = InMemoryJournal()
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        rc, out = capture(cmd_show_ledger, j)
        assert rc == 0
        assert rid in out
        assert NPUB_ALICE in out
        assert "1000" in out
        assert REQUESTED in out

    def test_limit(self):
        j = InMemoryJournal()
        ts = now()
        for i in range(10):
            j.insert_request(f"e{i}", NPUB_ALICE, 100, ts)
        rc, out = capture(cmd_show_ledger, j, limit=3)
        assert rc == 0
        assert "(3 rows)" in out


class TestShowUsage:
    def test_usage_displayed(self):
        j = InMemoryJournal()
        ts = now()
        j.commit_usage(NPUB_ALICE, 500, ts)
        j.reserve_request(NPUB_ALICE, "e1", 1000, ts)
        rc, out = capture(cmd_show_usage, j, NPUB_ALICE)
        assert rc == 0
        assert NPUB_ALICE in out
        assert "500" in out
        assert "1000" in out

    def test_usage_empty_user(self):
        j = InMemoryJournal()
        rc, out = capture(cmd_show_usage, j, NPUB_BOB)
        assert rc == 0
        assert NPUB_BOB in out
        assert "0" in out


class TestResetCursor:
    def test_resets_kv(self):
        j = InMemoryJournal()
        j.set_kv(CURSOR_KEY, "2026-08-23T12:00:00+00:00")
        assert j.get_kv(CURSOR_KEY) is not None
        rc, out = capture(cmd_reset_cursor, j)
        assert rc == 0
        assert j.get_kv(CURSOR_KEY) == ""

    def test_output_confirms(self):
        j = InMemoryJournal()
        rc, out = capture(cmd_reset_cursor, j)
        assert "reset" in out.lower()


class TestRevokeRequest:
    def test_not_found(self):
        j = InMemoryJournal()
        rc, out = capture(cmd_revoke_request, j, "nonexistent1234567")
        assert rc == 1
        assert "not found" in out.lower()

    def test_already_terminal(self):
        j = InMemoryJournal()
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        j.cas_state(rid, REQUESTED, QUOTED, quote_id="q1", ts=ts)
        j.cas_state(rid, QUOTED, PAID, ts=ts)
        j.cas_state(rid, PAID, DELIVERED, ts=ts)
        rc, out = capture(cmd_revoke_request, j, rid)
        assert rc == 1
        assert "terminal" in out.lower()

    def test_from_requested(self):
        j = InMemoryJournal()
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        rc, out = capture(cmd_revoke_request, j, rid)
        assert rc == 0
        row = j.fetch_request(rid)
        assert row is not None
        assert row.state == REJECTED
        assert row.error_code == "ADMIN_REVOKED"
        assert REQUESTED in out

    def test_from_quoted(self):
        j = InMemoryJournal()
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        j.cas_state(rid, REQUESTED, QUOTED, quote_id="q1", ts=ts)
        rc, out = capture(cmd_revoke_request, j, rid)
        assert rc == 0
        row = j.fetch_request(rid)
        assert row is not None
        assert row.state == REJECTED

    def test_from_paid(self):
        j = InMemoryJournal()
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        j.cas_state(rid, REQUESTED, QUOTED, quote_id="q1", ts=ts)
        j.cas_state(rid, QUOTED, PAID, ts=ts)
        rc, out = capture(cmd_revoke_request, j, rid)
        assert rc == 0
        row = j.fetch_request(rid)
        assert row is not None
        assert row.state == REJECTED


class TestParser:
    def test_show_ledger(self):
        parser = build_parser()
        args = parser.parse_args(["show-ledger", "--limit", "5"])
        assert args.command == "show-ledger"
        assert args.limit == 5

    def test_show_usage(self):
        parser = build_parser()
        args = parser.parse_args(["show-usage", NPUB_ALICE])
        assert args.command == "show-usage"
        assert args.npub == NPUB_ALICE

    def test_reset_cursor(self):
        parser = build_parser()
        args = parser.parse_args(["reset-cursor"])
        assert args.command == "reset-cursor"

    def test_revoke_request(self):
        parser = build_parser()
        args = parser.parse_args(["revoke-request", "abc123def456"])
        assert args.command == "revoke-request"
        assert args.request_id == "abc123def456"


class TestMainIntegration:
    @pytest.fixture
    def db_path(self, tmp_path: Path) -> str:
        return str(tmp_path / "cli_test.sqlite")

    def test_show_ledger_empty(self, db_path: str):
        j = SQLiteJournal(db_path)
        j.close()
        rc = main(["show-ledger", "--db", db_path])
        assert rc == 0

    def test_show_ledger_with_data(self, db_path: str):
        j = SQLiteJournal(db_path)
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        j.close()
        rc = main(["show-ledger", "--db", db_path])
        assert rc == 0

    def test_reset_cursor(self, db_path: str):
        j = SQLiteJournal(db_path)
        j.set_kv(CURSOR_KEY, "2026-08-23T12:00:00+00:00")
        j.close()
        rc = main(["reset-cursor", "--db", db_path])
        assert rc == 0
        j2 = SQLiteJournal(db_path)
        assert j2.get_kv(CURSOR_KEY) == ""
        j2.close()

    def test_revoke_request(self, db_path: str):
        j = SQLiteJournal(db_path)
        ts = now()
        rid = j.insert_request("e1", NPUB_ALICE, 1000, ts)
        j.close()
        rc = main(["revoke-request", rid, "--db", db_path])
        assert rc == 0
        j2 = SQLiteJournal(db_path)
        row = j2.fetch_request(rid)
        assert row is not None
        assert row.state == REJECTED
        j2.close()

    def test_revoke_not_found(self, db_path: str):
        j = SQLiteJournal(db_path)
        j.close()
        rc = main(["revoke-request", "nonexistent1234567", "--db", db_path])
        assert rc == 1

    def test_show_usage(self, db_path: str):
        j = SQLiteJournal(db_path)
        ts = now()
        j.commit_usage(NPUB_ALICE, 500, ts)
        j.close()
        rc = main(["show-usage", NPUB_ALICE, "--db", db_path])
        assert rc == 0
