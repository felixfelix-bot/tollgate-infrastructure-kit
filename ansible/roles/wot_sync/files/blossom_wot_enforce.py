#!/usr/bin/env python3
"""
blossom-wot-enforce — Delete Blossom blobs owned by npubs outside the
Web-of-Trust allowlist. Runs locally on the VPS as a systemd timer.

Single source of truth: /opt/tollgate/strfry-agg/state/allowed.npubs
(the hex pubkeys the root npub follows, reconciled every 15 min by
strfry-agg-reconcile). This script reads that file directly — it does
NOT re-fetch kind-3.

Correctness notes:
  * Blossom's `owners` table is many-to-many (a blob can have several
    uploading npubs). A blob is deleted only when ALL of its owners are
    non-allowed — a blob shared with even one allowed npub is kept.
  * Orphaned rows in `accessed`, `media_derivatives`, and `reports`
    referencing a deleted blob are cleaned up too (only when the column
    exists — schema is introspected at runtime so this is forward-safe).
  * Physical blob files are unlinked only after their DB rows are gone.
  * Exit code is 0 even on partial failure so the systemd timer does not
    flap; problems go to stderr for the journal.

Usage:
  blossom-wot-enforce                 # live cleanup
  blossom-wot-enforce --dry-run       # report only, no writes
  blossom-wot-enforce --verbose       # always print, even on no-op

Environment overrides:
  WOT_ALLOWED_PATH   (default /opt/tollgate/strfry-agg/state/allowed.npubs)
  WOT_BLOSSOM_DB     (default /var/lib/docker/volumes/blossom_blossom-data/_data/blossom.db)
  WOT_BLOSSOM_BLOBS  (default /var/lib/docker/volumes/blossom_blossom-data/_data/blobs)
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

ALLOWED_PATH = Path(
    os.environ.get("WOT_ALLOWED_PATH", "/opt/tollgate/strfry-agg/state/allowed.npubs")
)
BLOSSOM_DB = Path(
    os.environ.get(
        "WOT_BLOSSOM_DB",
        "/var/lib/docker/volumes/blossom_blossom-data/_data/blossom.db",
    )
)
BLOSSOM_BLOBS = Path(
    os.environ.get(
        "WOT_BLOSSOM_BLOBS",
        "/var/lib/docker/volumes/blossom_blossom-data/_data/blobs",
    )
)

log = logging.getLogger("blossom-wot-enforce")


def load_allowed(path: Path) -> set[str]:
    """Read the allowlist into a set of lowercase 64-char hex pubkeys."""
    allowed: set[str] = set()
    if not path.is_file():
        return allowed
    for line in path.read_text(errors="replace").splitlines():
        pk = line.strip().lower()
        if pk and not pk.startswith("#") and len(pk) == 64:
            try:
                int(pk, 16)
                allowed.add(pk)
            except ValueError:
                continue
    return allowed


def _blob_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    """Return the set of column names in `table` (empty if table absent)."""
    try:
        cur.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}
    except sqlite3.DatabaseError:
        return set()


def _doomed_blob_sql(allowed: set[str], owner_col: str) -> tuple[str, tuple]:
    """Subquery + params selecting (blob hash, size) of blobs that have NO
    allowed owner. With an empty allowlist this selects every blob."""
    if allowed:
        ph = ",".join("?" for _ in allowed)
        sql = (
            f"SELECT o.blob, (SELECT COALESCE(b.size,0) FROM blobs b "
            f" WHERE b.{owner_col} = o.blob) FROM owners o "
            f"WHERE NOT EXISTS ("
            f"  SELECT 1 FROM owners o2 WHERE o2.blob = o.blob "
            f"  AND o2.pubkey IN ({ph}))"
            f" GROUP BY o.blob"
        )
        return sql, tuple(allowed)
    return f"SELECT {owner_col}, COALESCE(size,0) FROM blobs", ()


def enforce(db_path: Path, blobs_dir: Path, allowed: set[str], dry_run: bool) -> dict:
    """Remove blobs whose owners are all non-allowed. Returns a stats dict."""
    stats = {
        "non_allowed_owners": 0,
        "blobs_deleted": 0,
        "bytes_freed": 0,
        "files_unlinked": 0,
        "unlink_errors": 0,
    }
    if not db_path.is_file():
        log.warning("blossom db not found: %s — nothing to enforce", db_path)
        return stats

    con = sqlite3.connect(str(db_path))
    con.isolation_level = None  # explicit transaction control
    cur = con.cursor()
    try:
        cols_owners = _blob_columns(cur, "owners")
        cols_blobs = _blob_columns(cur, "blobs")
        if "pubkey" not in cols_owners or "blob" not in cols_owners:
            log.warning("owners table missing pubkey/blob columns — nothing to do")
            return stats
        # blobs table uses `sha256` as the PK; owners.blob references it.
        owner_col = "sha256" if "sha256" in cols_blobs else "blob"

        # Non-allowed owners = owner rows whose pubkey is not in the allowlist.
        ph = ",".join("?" for _ in allowed) if allowed else ""
        if allowed:
            cur.execute(
                f"SELECT COUNT(DISTINCT pubkey) FROM owners "
                f"WHERE pubkey NOT IN ({ph})",
                tuple(allowed),
            )
        else:
            cur.execute("SELECT COUNT(DISTINCT pubkey) FROM owners")
        stats["non_allowed_owners"] = cur.fetchone()[0]

        if stats["non_allowed_owners"] == 0:
            return stats

        sel_sql, sel_args = _doomed_blob_sql(allowed, owner_col)
        cur.execute(sel_sql, sel_args)
        doomed = cur.fetchall()
        stats["blobs_deleted"] = len(doomed)
        stats["bytes_freed"] = sum(int(r[1] or 0) for r in doomed)
        doomed_hashes = [str(r[0]) for r in doomed]

        if dry_run:
            return stats
        if not doomed_hashes:
            return stats

        cur.execute("BEGIN")
        # Clean referencing tables first (order matters for any FK constraints).
        for ref_table in ("accessed", "media_derivatives", "reports"):
            rcols = _blob_columns(cur, ref_table)
            if not rcols:
                continue
            blobref = next(
                (c for c in ("blob", "sha256", "blob_hash") if c in rcols), None
            )
            if blobref is None:
                continue
            rph = ",".join("?" for _ in doomed_hashes)
            cur.execute(
                f"DELETE FROM {ref_table} WHERE {blobref} IN ({rph})",
                tuple(doomed_hashes),
            )

        # Remove owner rows for non-allowed npubs, then the orphaned blobs.
        if allowed:
            cur.execute(
                f"DELETE FROM owners WHERE pubkey NOT IN ({ph})",
                tuple(allowed),
            )
        else:
            cur.execute("DELETE FROM owners")
        dph = ",".join("?" for _ in doomed_hashes)
        cur.execute(
            f"DELETE FROM blobs WHERE {owner_col} IN ({dph})",
            tuple(doomed_hashes),
        )
        con.commit()

        # Unlink physical files AFTER the DB commit succeeded.
        for h in doomed_hashes:
            try:
                (blobs_dir / h).unlink(missing_ok=True)
                stats["files_unlinked"] += 1
            except OSError as exc:
                stats["unlink_errors"] += 1
                log.warning("unlink failed for %s: %s", h, exc)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Enforce WoT allowlist on Blossom blobs")
    p.add_argument("--dry-run", action="store_true", help="report only, no writes")
    p.add_argument("--verbose", "-v", action="store_true", help="log even on no-op")
    p.add_argument(
        "--allowed", default=str(ALLOWED_PATH), help="path to allowed.npubs"
    )
    p.add_argument("--db", default=str(BLOSSOM_DB), help="path to blossom.db")
    p.add_argument("--blobs-dir", default=str(BLOSSOM_BLOBS), help="blobs directory")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )

    allowed = load_allowed(Path(args.allowed))
    if not allowed:
        log.error(
            "allowlist empty or missing at %s — refusing to run "
            "(would delete everything). Aborting.",
            args.allowed,
        )
        return 0  # exit 0 so timer stays healthy; surfaces via stderr

    stats = enforce(
        Path(args.db), Path(args.blobs_dir), allowed, dry_run=args.dry_run
    )

    if stats["non_allowed_owners"] == 0:
        if args.verbose:
            log.info("no non-WoT blobs to clean")
        return 0

    mb = stats["bytes_freed"] / 1024 / 1024
    prefix = "DRY-RUN: would clean" if args.dry_run else "BLOSSOM-WOT: cleaned"
    print(
        f"{prefix} {stats['blobs_deleted']} blobs ({mb:.0f} MB) "
        f"from {stats['non_allowed_owners']} non-WoT npubs; "
        f"unlinked {stats['files_unlinked']} files",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
