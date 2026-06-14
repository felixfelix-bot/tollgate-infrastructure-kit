#!/usr/bin/env python3
import sqlite3
import sys
import os

DB_PATH = os.environ.get("RELATR_DB_PATH", "/opt/tollgate/relatr/data/relatr.db")
THRESHOLD = float(os.environ.get("RELATR_TRUST_THRESHOLD", "0.1"))

def is_trusted(pubkey_hex):
    if not os.path.isfile(DB_PATH):
        return True
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        cur = conn.cursor()
        cur.execute("SELECT latest_rank FROM ta WHERE pubkey = ?", (pubkey_hex,))
        row = cur.fetchone()
        if row and row[0] is not None:
            trust = row[0] / 100.0
            conn.close()
            return trust >= THRESHOLD
        conn.execute("PRAGMA table_info(pubkey_distances)")
        if cur.fetchone():
            cur.execute("SELECT distance FROM pubkey_distances WHERE pubkey = ? LIMIT 1", (pubkey_hex,))
            drow = cur.fetchone()
            if drow and drow[0] is not None:
                trust = 1.0 / (1.0 + drow[0])
                conn.close()
                return trust >= THRESHOLD
        conn.close()
    except Exception:
        pass
    return False

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: grasp-trust-filter.py <npub_hex>")
        sys.exit(1)
    pubkey = sys.argv[1]
    if is_trusted(pubkey):
        print("trusted")
        sys.exit(0)
    else:
        print("untrusted")
        sys.exit(1)
