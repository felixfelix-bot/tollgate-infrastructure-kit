"""Journal — SQLite-backed state machine for DM issuance requests (spec §2).

Tables (DM-ST-1):

* ``requests``       — one row per request; primary key = sha256(event_id)[0:16]
* ``processed_events`` — event_id dedupe (DM-IDEM-3)
* ``usage``           — per (npub, UTC day) requests + sats_issued totals
* ``kv``              — ``last_dm_scan_at`` cursor and other singletons

State machine (DM-ST-2) — only forward, with compare-and-swap::

    REQUESTED -> QUOTED -> PAID -> DELIVERED
                                   -> FAILED
                            -> EXPIRED
                  -> REJECTED   (terminal)

Usage is committed at DELIVERED (quote-handoff analog of MINTED — when the
paid quote_id is DM'd to the user).

Both a SQLite on-disk implementation (``SQLiteJournal``) and an in-memory
implementation (``InMemoryJournal``) live here; the latter exists for tests
and the policy engine's unit tests.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional, Sequence, Protocol, runtime_checkable

log = logging.getLogger(__name__)


REQUESTED = "REQUESTED"
QUOTED = "QUOTED"
PAID = "PAID"
DELIVERED = "DELIVERED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"
REJECTED = "REJECTED"

TERMINAL_STATES = frozenset({DELIVERED, FAILED, EXPIRED, REJECTED})
RECOVERABLE_STATES = frozenset({REQUESTED, QUOTED, PAID})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    REQUESTED: frozenset({QUOTED, FAILED, EXPIRED, REJECTED}),
    QUOTED: frozenset({PAID, FAILED, EXPIRED, REJECTED}),
    PAID: frozenset({DELIVERED, FAILED, EXPIRED, REJECTED}),
    DELIVERED: frozenset(),
    FAILED: frozenset(),
    EXPIRED: frozenset(),
    REJECTED: frozenset(),
}


def _is_valid_transition(from_state: str, to_state: str) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, frozenset())

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS requests (
    request_id   TEXT PRIMARY KEY,
    event_id     TEXT UNIQUE NOT NULL,
    npub         TEXT NOT NULL,
    amount       INTEGER NOT NULL,
    quote_id     TEXT,
    state        TEXT NOT NULL,
    error_code   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    delivered    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS processed_events (
    event_id     TEXT PRIMARY KEY,
    ts           REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    npub         TEXT NOT NULL,
    day_utc      TEXT NOT NULL,
    requests     INTEGER DEFAULT 0,
    sats_issued  INTEGER DEFAULT 0,
    PRIMARY KEY (npub, day_utc)
);
CREATE TABLE IF NOT EXISTS kv (
    k            TEXT PRIMARY KEY,
    v            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_state ON requests(state);
CREATE INDEX IF NOT EXISTS idx_requests_npub_day ON requests(npub, created_at);
"""


@dataclass(frozen=True)
class RequestRow:
    request_id: str
    event_id: str
    npub: str
    amount: int
    quote_id: Optional[str]
    state: str
    error_code: Optional[str]
    created_at: str
    updated_at: str
    delivered: int


@runtime_checkable
class Journal(Protocol):
    def is_event_processed(self, event_id: str) -> bool: ...
    def mark_event_processed(self, event_id: str, ts: float) -> None: ...
    def insert_request(self, event_id: str, npub: str, amount: int, ts: datetime) -> str: ...
    def fetch_request_by_event(self, event_id: str) -> Optional[RequestRow]: ...
    def fetch_request(self, request_id: str) -> Optional[RequestRow]: ...
    def cas_state(
        self,
        request_id: str,
        from_state: str,
        to_state: str,
        *,
        quote_id: Optional[str] = None,
        error_code: Optional[str] = None,
        ts: Optional[datetime] = None,
    ) -> bool: ...
    def reserve_request(self, npub: str, event_id: str, amount: int, ts: datetime) -> None: ...
    def commit_usage(self, npub: str, amount: int, ts: datetime) -> None: ...
    def get_usage(self, npub: str, day_utc: str) -> tuple[int, int]: ...
    def get_global_usage(self, day_utc: str) -> int: ...
    def get_pending_usage(self, npub: str, day_utc: str) -> int: ...
    def count_recent_requests(self, npub: str, since: datetime) -> int: ...
    def fetch_recoverable(self) -> Sequence[RequestRow]: ...
    def fetch_non_terminal(self) -> Sequence[RequestRow]: ...
    def get_kv(self, key: str, default: Optional[str] = None) -> Optional[str]: ...
    def set_kv(self, key: str, value: str) -> None: ...
    def mark_delivered(self, request_id: str, *, ts: Optional[datetime] = None) -> bool: ...
    def backlog(self) -> Sequence[RequestRow]: ...


def request_id_for(event_id: str) -> str:
    return hashlib.sha256(event_id.encode("utf-8")).hexdigest()[:16]


def day_utc(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).date().isoformat()


def iso(ts: Optional[datetime] = None) -> str:
    if ts is None:
        ts = datetime.now(timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(timezone.utc)


class InMemoryJournal:
    """In-memory implementation backed by lists/dicts — tests & policy unit."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processed: dict[str, float] = {}
        self._requests: dict[str, RequestRow] = {}
        self._by_event: dict[str, str] = {}
        self._usage: dict[tuple[str, str], list[int]] = {}
        self._global: dict[str, int] = {}
        self._pending: dict[tuple[str, str], int] = {}
        self._recent: list[tuple[str, datetime]] = []
        self._kv: dict[str, str] = {}

    def is_event_processed(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._processed

    def mark_event_processed(self, event_id: str, ts: float) -> None:
        with self._lock:
            self._processed[event_id] = ts

    def insert_request(self, event_id: str, npub: str, amount: int, ts: datetime) -> str:
        with self._lock:
            rid = request_id_for(event_id)
            row = RequestRow(
                request_id=rid,
                event_id=event_id,
                npub=npub,
                amount=amount,
                quote_id=None,
                state=REQUESTED,
                error_code=None,
                created_at=iso(ts),
                updated_at=iso(ts),
                delivered=0,
            )
            self._requests[rid] = row
            self._by_event[event_id] = rid
            return rid

    def fetch_request(self, request_id: str) -> Optional[RequestRow]:
        with self._lock:
            return self._requests.get(request_id)

    def fetch_request_by_event(self, event_id: str) -> Optional[RequestRow]:
        with self._lock:
            rid = self._by_event.get(event_id)
            if rid is None:
                return None
            return self._requests.get(rid)

    def cas_state(
        self,
        request_id: str,
        from_state: str,
        to_state: str,
        *,
        quote_id: Optional[str] = None,
        error_code: Optional[str] = None,
        ts: Optional[datetime] = None,
    ) -> bool:
        with self._lock:
            row = self._requests.get(request_id)
            if row is None or row.state != from_state:
                return False
            if not _is_valid_transition(from_state, to_state):
                return False
            new_qid = quote_id if quote_id is not None else row.quote_id
            new_err = error_code if error_code is not None else row.error_code
            ts_iso = iso(ts) if ts is not None else iso()
            self._requests[request_id] = RequestRow(
                request_id=row.request_id,
                event_id=row.event_id,
                npub=row.npub,
                amount=row.amount,
                quote_id=new_qid,
                state=to_state,
                error_code=new_err,
                created_at=row.created_at,
                updated_at=ts_iso,
                delivered=row.delivered,
            )
            return True

    def reserve_request(self, npub: str, event_id: str, amount: int, ts: datetime) -> None:
        with self._lock:
            day = day_utc(ts)
            key = (npub, day)
            self._pending[key] = self._pending.get(key, 0) + amount
            self._recent.append((npub, ts))

    def commit_usage(self, npub: str, amount: int, ts: datetime) -> None:
        with self._lock:
            day = day_utc(ts)
            key = (npub, day)
            bucket = self._usage.setdefault(key, [0, 0])
            bucket[0] += 1
            bucket[1] += amount
            self._global[day] = self._global.get(day, 0) + amount
            self._pending[key] = max(0, self._pending.get(key, 0) - amount)

    def get_usage(self, npub: str, day_utc: str) -> tuple[int, int]:
        with self._lock:
            bucket = self._usage.get((npub, day_utc), [0, 0])
            return (bucket[0], bucket[1])

    def get_global_usage(self, day_utc: str) -> int:
        with self._lock:
            return self._global.get(day_utc, 0)

    def get_pending_usage(self, npub: str, day_utc: str) -> int:
        with self._lock:
            return self._pending.get((npub, day_utc), 0)

    def count_recent_requests(self, npub: str, since: datetime) -> int:
        with self._lock:
            return sum(1 for (n, ts) in self._recent if n == npub and ts >= since)

    def fetch_recoverable(self) -> Sequence[RequestRow]:
        with self._lock:
            return [r for r in self._requests.values() if r.state in RECOVERABLE_STATES]

    def fetch_non_terminal(self) -> Sequence[RequestRow]:
        with self._lock:
            return [r for r in self._requests.values() if r.state not in TERMINAL_STATES]

    def backlog(self) -> Sequence[RequestRow]:
        with self._lock:
            return [r for r in self._requests.values() if r.state == DELIVERED and not r.delivered]

    def mark_delivered(self, request_id: str, *, ts: Optional[datetime] = None) -> bool:
        with self._lock:
            row = self._requests.get(request_id)
            if row is None:
                return False
            self._requests[request_id] = RequestRow(
                request_id=row.request_id,
                event_id=row.event_id,
                npub=row.npub,
                amount=row.amount,
                quote_id=row.quote_id,
                state=row.state,
                error_code=row.error_code,
                created_at=row.created_at,
                updated_at=iso(ts) if ts is not None else iso(),
                delivered=1,
            )
            return True

    def get_kv(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self._lock:
            return self._kv.get(key, default)

    def set_kv(self, key: str, value: str) -> None:
        with self._lock:
            self._kv[key] = value


class SQLiteJournal(InMemoryJournal):
    """SQLite-backed journal. Inherits the in-memory accounting methods from
    InMemoryJournal (they share the same naive bookkeeping shape); this class
    writes the authoritative ``requests`` / ``processed_events`` / ``usage``
    / ``kv`` rows to disk so a process restart preserves them.

    For tests we delegate ``Journal`` protocol callers through SQLite for the
    SQLite-specific behaviours (CAS durability, recoverable scan); the in-ram
    counters remain the source of truth for pending usage to avoid re-loading
    every row on each policy check.
    """

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        super().__init__()
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._conn.commit()
        self._load_state_from_disk()

    def _load_state_from_disk(self) -> None:
        for r in self._conn.execute("SELECT npub, day_utc, requests, sats_issued FROM usage"):
            self._usage[(r["npub"], r["day_utc"])] = [int(r["requests"]), int(r["sats_issued"])]
        for r in self._conn.execute("SELECT day_utc, COALESCE(SUM(sats_issued), 0) AS s FROM usage GROUP BY day_utc"):
            self._global[r["day_utc"]] = int(r["s"])
        for r in self._conn.execute("SELECT npub, created_at FROM requests WHERE state NOT IN ('DELIVERED', 'FAILED', 'EXPIRED', 'REJECTED')"):
            try:
                self._recent.append((r["npub"], parse_iso(r["created_at"])))
            except (ValueError, TypeError):
                continue
        for r in self._conn.execute(
            "SELECT npub, created_at, amount FROM requests "
            "WHERE state IN ('REQUESTED', 'QUOTED', 'PAID')"
        ):
            try:
                ts = parse_iso(r["created_at"])
                d = day_utc(ts)
                key = (r["npub"], d)
                self._pending[key] = self._pending.get(key, 0) + int(r["amount"])
            except (ValueError, TypeError):
                continue

    def is_event_processed(self, event_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM processed_events WHERE event_id = ?", (event_id,))
        return cur.fetchone() is not None

    def mark_event_processed(self, event_id: str, ts: float) -> None:
        with self._lock:
            self._processed[event_id] = ts
        self._conn.execute(
            "INSERT OR IGNORE INTO processed_events(event_id, ts) VALUES(?, ?)",
            (event_id, float(ts)),
        )
        self._conn.commit()

    def insert_request(self, event_id: str, npub: str, amount: int, ts: datetime) -> str:
        rid = request_id_for(event_id)
        ts_iso = iso(ts)
        try:
            self._conn.execute(
                """
                INSERT INTO requests(request_id, event_id, npub, amount, quote_id,
                                     state, error_code, created_at, updated_at, delivered)
                VALUES(?, ?, ?, ?, NULL, ?, NULL, ?, ?, 0)
                """,
                (rid, event_id, npub, int(amount), REQUESTED, ts_iso, ts_iso),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            existing = self._conn.execute(
                "SELECT request_id FROM requests WHERE event_id = ?", (event_id,)
            ).fetchone()
            if existing:
                return existing["request_id"]
            raise
        with self._lock:
            self._by_event[event_id] = rid
            self._requests[rid] = RequestRow(
                request_id=rid,
                event_id=event_id,
                npub=npub,
                amount=amount,
                quote_id=None,
                state=REQUESTED,
                error_code=None,
                created_at=ts_iso,
                updated_at=ts_iso,
                delivered=0,
            )
        return rid

    def fetch_request(self, request_id: str) -> Optional[RequestRow]:
        cur = self._conn.execute(
            "SELECT * FROM requests WHERE request_id = ?", (request_id,)
        )
        r = cur.fetchone()
        return _row_to_RequestRow(r) if r else None

    def fetch_request_by_event(self, event_id: str) -> Optional[RequestRow]:
        cur = self._conn.execute(
            "SELECT * FROM requests WHERE event_id = ?", (event_id,)
        )
        r = cur.fetchone()
        return _row_to_RequestRow(r) if r else None

    def cas_state(
        self,
        request_id: str,
        from_state: str,
        to_state: str,
        *,
        quote_id: Optional[str] = None,
        error_code: Optional[str] = None,
        ts: Optional[datetime] = None,
    ) -> bool:
        if not _is_valid_transition(from_state, to_state):
            return False
        ts_iso = iso(ts) if ts is not None else iso()
        sets = ["state = ?", "updated_at = ?"]
        params: list = [to_state, ts_iso]
        if quote_id is not None:
            sets.append("quote_id = ?")
            params.append(quote_id)
        if error_code is not None:
            sets.append("error_code = ?")
            params.append(error_code)
        params.extend([request_id, from_state])
        cur = self._conn.execute(
            f"UPDATE requests SET {', '.join(sets)} WHERE request_id = ? AND state = ?",
            params,
        )
        self._conn.commit()
        affected = cur.rowcount
        if affected > 0:
            self._sync_row(request_id)
        return affected > 0

    def commit_usage(self, npub: str, amount: int, ts: datetime) -> None:
        day = day_utc(ts)
        self._conn.execute(
            """
            INSERT INTO usage(npub, day_utc, requests, sats_issued)
            VALUES(?, ?, 1, ?)
            ON CONFLICT(npub, day_utc)
            DO UPDATE SET requests = requests + 1, sats_issued = sats_issued + ?
            """,
            (npub, day, int(amount), int(amount)),
        )
        self._conn.commit()
        super().commit_usage(npub, amount, ts)

    def mark_delivered(self, request_id: str, *, ts: Optional[datetime] = None) -> bool:
        ts_iso = iso(ts) if ts is not None else iso()
        cur = self._conn.execute(
            "UPDATE requests SET delivered = 1, updated_at = ? WHERE request_id = ?",
            (ts_iso, request_id),
        )
        self._conn.commit()
        affected = cur.rowcount
        if affected > 0:
            self._sync_row(request_id)
        return affected > 0

    def fetch_recoverable(self) -> Sequence[RequestRow]:
        cur = self._conn.execute(
            "SELECT * FROM requests WHERE state IN ('REQUESTED', 'QUOTED', 'PAID') ORDER BY created_at ASC",
        )
        return [_row_to_RequestRow(r) for r in cur.fetchall()]

    def fetch_non_terminal(self) -> Sequence[RequestRow]:
        cur = self._conn.execute(
            "SELECT * FROM requests WHERE state NOT IN ('DELIVERED','FAILED','EXPIRED','REJECTED') ORDER BY created_at ASC",
        )
        return [_row_to_RequestRow(r) for r in cur.fetchall()]

    def backlog(self) -> Sequence[RequestRow]:
        cur = self._conn.execute(
            "SELECT * FROM requests WHERE state = 'DELIVERED' AND delivered = 0",
        )
        return [_row_to_RequestRow(r) for r in cur.fetchall()]

    def get_kv(self, key: str, default: Optional[str] = None) -> Optional[str]:
        cur = self._conn.execute("SELECT v FROM kv WHERE k = ?", (key,))
        r = cur.fetchone()
        return r["v"] if r else default

    def set_kv(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO kv(k, v) VALUES(?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v",
            (key, value),
        )
        self._conn.commit()

    def recover(self, *, now: datetime, stale_secs: int) -> list[RequestRow]:
        """DM-ST-4 startup recovery: stale REQUESTED rows → REJECTED,
        deliveries marked failed if undelivered."""
        out: list[RequestRow] = []
        stale_cutoff = iso(now.replace(microsecond=0))
        for row in self.fetch_recoverable():
            created = parse_iso(row.created_at)
            age = (now - created).total_seconds()
            if age > stale_secs and row.state == REQUESTED:
                self.cas_state(row.request_id, REQUESTED, REJECTED, error_code="STALE_REQUEST", ts=now)
                continue
            out.append(row)
        return out

    def _sync_row(self, request_id: str) -> None:
        cur = self._conn.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,))
        r = cur.fetchone()
        if r is None:
            return
        with self._lock:
            self._requests[request_id] = _row_to_RequestRow(r)
            self._by_event[r["event_id"]] = r["request_id"]

    def close(self) -> None:
        self._conn.close()


def _row_to_RequestRow(r: sqlite3.Row) -> RequestRow:
    return RequestRow(
        request_id=r["request_id"],
        event_id=r["event_id"],
        npub=r["npub"],
        amount=int(r["amount"]),
        quote_id=r["quote_id"] if "quote_id" in r.keys() else None,
        state=r["state"],
        error_code=r["error_code"] if "error_code" in r.keys() else None,
        created_at=r["created_at"],
        updated_at=r["updated_at"],
        delivered=int(r["delivered"]) if "delivered" in r.keys() else 0,
    )
