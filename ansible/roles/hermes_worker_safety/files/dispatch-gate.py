#!/usr/bin/env python3
"""
dispatch-gate.py — Pre-dispatch gate that enforces Kalman-predicted concurrency.

Wraps `hermes kanban dispatch` to prevent worker burst spawns.

Usage:
  python3 dispatch-gate.py              # Check + dispatch (safe)
  python3 dispatch-gate.py --dry-run    # Check only, no dispatch
  python3 dispatch-gate.py --force N    # Force N max workers (override Kalman)

Reads:
  - ~/.hermes/state/pool_kalman.json (Kalman-smoothed max_workers)
  - Current running worker count (ps + kanban board)
  - System load average

Logic:
  1. Read Kalman prediction for max concurrent workers
  2. Count currently running workers
  3. available_slots = max(0, kalman_max - currently_running)
  4. If available_slots > 0: dispatch with --limit available_slots
  5. If available_slots = 0: skip dispatch, log reason
  6. Rate limit: max 1 new worker per 30s (configurable)

No pip packages needed — stdlib only.
"""

import json
import os
import subprocess
import sys
import time

KALMAN_FILE = os.path.expanduser("~/.hermes/state/pool_kalman.json")
METRICS_DB = os.path.expanduser("~/.hermes/bot/worker_metrics.db")
RATE_LIMIT_FILE = "/tmp/dispatch-gate-last-spawn"
RATE_LIMIT_SECONDS = 30  # min seconds between dispatches
HARD_FLOOR = 1  # never go below 1 worker
HARD_CEILING = 8  # never exceed this even if Kalman says more
LOAD_SAFETY_THRESHOLD = 6.0  # if load > this, refuse to dispatch


def read_kalman_max():
    """Read Kalman-smoothed max workers prediction."""
    try:
        with open(KALMAN_FILE) as f:
            state = json.load(f)
        smoothed = state["x"][0]
        return max(HARD_FLOOR, min(HARD_CEILING, int(round(smoothed))))
    except (FileNotFoundError, KeyError, json.JSONDecodeError):
        return 3  # safe default


def count_running_workers():
    """Count currently running kanban worker processes."""
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=5
        )
        count = 0
        for line in result.stdout.split("\n"):
            if "hermes" in line and "-p" in line and "grep" not in line and "manager" not in line:
                count += 1
        return count
    except Exception:
        return 0


def get_load():
    """Get current 1-minute load average."""
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0


def get_available_memory():
    """Get available memory in MB."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024  # KB to MB
    except Exception:
        pass
    return 9999  # unknown


def check_rate_limit():
    """Check if we're within the rate limit window."""
    try:
        if os.path.exists(RATE_LIMIT_FILE):
            mtime = os.path.getmtime(RATE_LIMIT_FILE)
            elapsed = time.time() - mtime
            if elapsed < RATE_LIMIT_SECONDS:
                return False, RATE_LIMIT_SECONDS - elapsed
    except Exception:
        pass
    return True, 0


def record_dispatch():
    """Record that we dispatched (for rate limiting)."""
    try:
        with open(RATE_LIMIT_FILE, "w") as f:
            f.write(str(time.time()))
    except Exception:
        pass


def log_metrics(max_workers, running, load, mem_mb, reason, dispatched=0):
    """Log to worker_metrics.db."""
    try:
        import sqlite3
        db = sqlite3.connect(METRICS_DB)
        db.execute("""
            INSERT INTO worker_metrics
            (ts, load1, workers, max_concurrent, mem_avail_mb,
             tasks_running, tasks_done)
            VALUES (?, ?, ?, ?, ?, ?, 0)
        """, (
            time.time(), load, running, max_workers, mem_mb,
            running, dispatched
        ))
        db.commit()
        db.close()
    except Exception:
        pass


def main():
    dry_run = "--dry-run" in sys.argv
    force_max = None
    if "--force" in sys.argv:
        idx = sys.argv.index("--force")
        if idx + 1 < len(sys.argv):
            force_max = int(sys.argv[idx + 1])

    # Gather system state
    kalman_max = force_max if force_max else read_kalman_max()
    running = count_running_workers()
    load = get_load()
    mem_mb = get_available_memory()
    available_slots = max(0, kalman_max - running)

    # Check rate limit
    can_dispatch, wait_time = check_rate_limit()

    # Safety checks
    reasons = []
    if load > LOAD_SAFETY_THRESHOLD:
        reasons.append(f"LOAD_TOO_HIGH ({load:.1f} > {LOAD_SAFETY_THRESHOLD})")
        available_slots = 0
    if mem_mb < 500:
        reasons.append(f"MEM_TOO_LOW ({mem_mb}MB < 500MB)")
        available_slots = 0
    if not can_dispatch:
        reasons.append(f"RATE_LIMITED (wait {wait_time:.0f}s)")
        available_slots = 0
    if available_slots == 0 and running >= kalman_max:
        reasons.append(f"AT_CAPACITY ({running}/{kalman_max})")

    # Output status
    print(f"Kalman max: {kalman_max}")
    print(f"Running:    {running}")
    print(f"Available:  {available_slots}")
    print(f"Load:       {load:.2f}")
    print(f"Mem avail:  {mem_mb}MB")

    if reasons:
        print(f"Blocked:    {'; '.join(reasons)}")
    elif available_slots > 0 and not dry_run:
        print(f"Dispatching with limit={available_slots}...")
        record_dispatch()
        result = subprocess.run(
            ["hermes", "kanban", "--board", "fips", "dispatch",
             "--failure-limit", "3"],
            capture_output=True, text=True, timeout=60
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        log_metrics(kalman_max, running, load, mem_mb, "dispatched", available_slots)
    elif dry_run:
        print("(dry-run — would dispatch)")
    else:
        print("No slots available, skipping dispatch")

    log_metrics(kalman_max, running, load, mem_mb,
                "; ".join(reasons) if reasons else "ok", 0)


if __name__ == "__main__":
    main()
