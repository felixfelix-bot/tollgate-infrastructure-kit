"""CLI tool for inspecting and managing the DM issuer journal.

Subcommands:
* show-ledger          — list recent requests (default 20)
* show-usage <npub>    — show daily usage for a whitelist user
* reset-cursor         — reset the last_dm_scan_at cursor
* revoke-request <id>  — force-set a request state to REJECTED

Uses argparse (stdlib only). The journal is injected for testability;
in production a SQLiteJournal is opened from DM_ISSUER_DB_PATH.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence

from .journal import (
    REJECTED,
    REQUESTED,
    QUOTED,
    PAID,
    TERMINAL_STATES,
    Journal,
    SQLiteJournal,
    day_utc,
)

CURSOR_KEY = "last_dm_scan_at"


def _open_journal(db_path: Optional[str] = None) -> SQLiteJournal:
    path = db_path or os.environ.get(
        "DM_ISSUER_DB_PATH", "/var/lib/dm-issuer/dm-issuer.db",
    )
    return SQLiteJournal(path)


def cmd_show_ledger(journal: Journal, limit: int = 20) -> int:
    rows = journal.list_recent(limit=limit)
    if not rows:
        print("(no requests)")
        return 0
    print(f"{'request_id':<18} {'state':<12} {'npub':<62} {'amount':>8} {'quote_id':<12} {'created_at'}")
    print("-" * 140)
    for r in rows:
        qid = r.quote_id or "-"
        print(f"{r.request_id:<18} {r.state:<12} {r.npub:<62} {r.amount:>8} {qid:<12} {r.created_at}")
    print(f"\n({len(rows)} rows)")
    return 0


def cmd_show_usage(journal: Journal, npub: str) -> int:
    today = day_utc(datetime.now(timezone.utc))
    requests, sats = journal.get_usage(npub, today)
    pending = journal.get_pending_usage(npub, today)
    recent = journal.count_recent_requests(npub, datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0))
    print(f"Usage for {npub} (UTC day {today}):")
    print(f"  requests (committed): {requests}")
    print(f"  sats issued (committed): {sats}")
    print(f"  sats pending (in-flight): {pending}")
    print(f"  recent requests (today): {recent}")
    cursor = journal.get_kv(CURSOR_KEY)
    print(f"  last scan cursor: {cursor or '(not set)'}")
    return 0


def cmd_reset_cursor(journal: Journal) -> int:
    journal.set_kv(CURSOR_KEY, "")
    print(f"Cursor '{CURSOR_KEY}' reset to empty (next poll will use lookback default)")
    return 0


def cmd_revoke_request(journal: Journal, request_id: str) -> int:
    row = journal.fetch_request(request_id)
    if row is None:
        print(f"Request {request_id} not found")
        return 1
    if row.state in TERMINAL_STATES:
        print(f"Request {request_id} is already in terminal state: {row.state}")
        return 1
    now = datetime.now(timezone.utc)
    for old_state in (REQUESTED, QUOTED, PAID):
        if journal.cas_state(
            request_id, old_state, REJECTED,
            error_code="ADMIN_REVOKED", ts=now,
        ):
            print(f"Request {request_id} rejected (was {old_state} -> REJECTED)")
            return 0
    print(f"Could not reject request {request_id} (unexpected state: {row.state})")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dm-issuer",
        description="DM issuer journal CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ledger = sub.add_parser("show-ledger", help="List recent requests")
    p_ledger.add_argument("--limit", type=int, default=20, help="Max rows to show")
    p_ledger.add_argument("--db", default=None, help="SQLite DB path override")

    p_usage = sub.add_parser("show-usage", help="Show daily usage for an npub")
    p_usage.add_argument("npub", help="User npub (bech32)")
    p_usage.add_argument("--db", default=None, help="SQLite DB path override")

    p_cursor = sub.add_parser("reset-cursor", help="Reset last_dm_scan_at cursor")
    p_cursor.add_argument("--db", default=None, help="SQLite DB path override")

    p_revoke = sub.add_parser("revoke-request", help="Force-set a request to REJECTED")
    p_revoke.add_argument("request_id", help="Request ID (16-char hex)")
    p_revoke.add_argument("--db", default=None, help="SQLite DB path override")

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db_path = getattr(args, "db", None)

    if args.command == "show-ledger":
        j = _open_journal(db_path)
        return cmd_show_ledger(j, limit=args.limit)
    elif args.command == "show-usage":
        j = _open_journal(db_path)
        return cmd_show_usage(j, args.npub)
    elif args.command == "reset-cursor":
        j = _open_journal(db_path)
        return cmd_reset_cursor(j)
    elif args.command == "revoke-request":
        j = _open_journal(db_path)
        return cmd_revoke_request(j, args.request_id)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
