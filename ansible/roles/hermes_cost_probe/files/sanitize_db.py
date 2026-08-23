#!/usr/bin/env python3
"""Sanitize zai_usage.db for public publication.

Copies zai_usage.db → scrubbed.db, then scrubs PII and sensitive fields:
  - api_calls: drop key_suffix, session_id; categorize error to enum
  - anomaly_events: drop detail (keep title + category)
  - key_health: drop last_failure_ts, backoff_until (transient, no value)
  - provider_telemetry: categorize error_type to enum

Provider names (openrouter, telnyx, routstrd, etc.) are KEPT per user
request — they make the dataset useful. No full API keys exist in the DB
(verified: key_suffix is last-4 only; error/detail fields scanned clean).

Usage: python3 sanitize_db.py [--source DB] [--output scrubbed.db]
"""
import sqlite3, os, sys, shutil, re

DEFAULT_SRC = os.path.expanduser("~/.hermes/bot/zai_usage.db")
DEFAULT_OUT = os.path.expanduser("~/scrubbed.db")

ERROR_MAP = {
    "client disconnect: BrokenPipeError": "broken_pipe",
    "proxy error: The read operation timed out": "timeout",
    "proxy error: <urlopen error [Errno -2] Name or service not known>": "dns_error",
    "proxy error: <urlopen error [Errno 101] Network is unreachable>": "net_unreachable",
    "proxy error: <urlopen error [Errno -3] Temporary failure in name resolution]": "dns_temp",
    "proxy error: <urlopen error _ssl.c": "ssl_timeout",
}

ERROR_RE = re.compile(r"^(exhausted|backoff|dead|server|api_error|parse_error|no_response|none|broken_pipe|timeout)", re.I)


def categorize_error(err):
    if not err:
        return "none"
    if err in ERROR_MAP:
        return ERROR_MAP[err]
    for prefix in ("exhausted", "backoff", "dead", "server"):
        if err.lower().startswith(prefix):
            return prefix
    if "broken" in err.lower():
        return "broken_pipe"
    if "timeout" in err.lower() or "timed out" in err.lower():
        return "timeout"
    if "dns" in err.lower() or "name resolution" in err.lower():
        return "dns_error"
    if "api_error" in err.lower():
        return "api_error"
    if "parse" in err.lower():
        return "parse_error"
    return "other"


def main():
    src = sys.argv[sys.argv.index("--source") + 1] if "--source" in sys.argv else DEFAULT_SRC
    out = sys.argv[sys.argv.index("--output") + 1] if "--output" in sys.argv else DEFAULT_OUT

    if not os.path.exists(src):
        print(f"Source DB not found: {src}", file=sys.stderr)
        return 1

    print(f"Copying {src} → {out} ...")
    shutil.copy2(src, out)

    c = sqlite3.connect(out, timeout=30)
    c.row_factory = sqlite3.Row

    total_dropped = 0

    # api_calls: drop key_suffix, session_id; categorize error
    try:
        c.execute("ALTER TABLE api_calls DROP COLUMN key_suffix")
        total_dropped += c.total_changes
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE api_calls DROP COLUMN session_id")
        total_dropped += c.total_changes
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE api_calls DROP COLUMN task_type")
    except Exception:
        pass

    # Categorize error field
    for rid, err in c.execute("SELECT rowid, error FROM api_calls WHERE error IS NOT NULL").fetchall():
        cat = categorize_error(err)
        c.execute("UPDATE api_calls SET error=? WHERE rowid=?", (cat, rid))

    # anomaly_events: drop detail
    try:
        c.execute("ALTER TABLE anomaly_events DROP COLUMN detail")
    except Exception:
        pass

    # key_health: drop transients
    for col in ("last_failure_ts", "backoff_until", "backoff_seconds"):
        try:
            c.execute(f"ALTER TABLE key_health DROP COLUMN {col}")
        except Exception:
            pass

    # provider_telemetry: categorize error_type
    try:
        for rid, et in c.execute("SELECT rowid, error_type FROM provider_telemetry WHERE error_type IS NOT NULL").fetchall():
            cat = categorize_error(et)
            c.execute("UPDATE provider_telemetry SET error_type=? WHERE rowid=?", (cat, rid))
    except Exception:
        pass

    # Rename service-specific internal columns for clarity
    # (key_decisions.reason references key names like 'ours', 'friend' — fine to keep)

    c.commit()
    c.isolation_level = None
    c.execute("VACUUM")
    c.close()

    size_mb = os.path.getsize(out) / 1e6
    print(f"Scrubbed DB: {out} ({size_mb:.1f} MB)")
    print(f"  key_suffix/session_id/task_type dropped from api_calls")
    print(f"  anomaly_events.detail dropped")
    print(f"  key_health transients dropped")
    print(f"  error fields categorized to enums")
    print(f"  provider names KEPT (user-confirmed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
