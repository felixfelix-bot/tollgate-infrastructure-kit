#!/usr/bin/env python3
"""
compute_max_workers.py — Adaptive worker concurrency calculator for v5.

Reads real-time system signals and outputs the optimal number of workers
for the current resource state. Called by worker-watchdog.sh v5.

Signals used:
  - Available RAM (accounts for system baseline + headroom)
  - Load average per core (normalized)
  - Swap usage (only penalizes when combined with RAM pressure)
  - z.ai API quota (reduces workers when quota is scarce)

Output: a single integer (the max number of workers to allow).
Exit 0 always — never crashes the watchdog. On any error, outputs the
safe fallback (2).

Usage:
  MAX=$(python3 compute_max_workers.py)
  MAX=$(python3 compute_max_workers.py --verbose)  # prints reasoning to stderr

Design principles:
  - RAM is the hard limiter. CPU load throttles but doesn't kill.
  - Scale UP aggressively when resources are plentiful.
  - Scale DOWN gradually (one factor at a time).
  - Never output 0 (always allow at least 1 worker when system is healthy).
  - Hard cap at MAX_CAP to prevent over-dispatch on this hardware.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

# ─── Hardware profile ──────────────────────────────────────

# Detected at runtime, but cached with sensible fallback
def _read_meminfo():
    """Read /proc/meminfo, return dict in KB."""
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2:
                    info[parts[0].rstrip(":")] = int(parts[1])
    except Exception:
        pass
    return info

def _read_loadavg():
    """Read 1-minute load average."""
    try:
        with open("/proc/loadavg") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0.0

def _read_nproc():
    """Get number of logical CPUs."""
    try:
        return int(subprocess.check_output(["nproc"]).strip())
    except Exception:
        return 4  # safe fallback

def _read_zai_quota():
    """Read z.ai session quota percentage from state file."""
    state_file = Path.home() / ".hermes" / "bot" / "zai_state.json"
    if not state_file.exists():
        return 0  # no state = assume plenty of quota
    try:
        with open(state_file) as f:
            data = json.load(f)
        return int(data.get("session_pct", 0))
    except Exception:
        return 0

# ─── Configuration (env var overrides) ─────────────────────

# Minimum workers (never go below this when system is healthy)
MIN_WORKERS = int(os.environ.get("V5_MIN_WORKERS", "1"))

# Hard cap for this hardware
MAX_CAP = int(os.environ.get("V5_MAX_CAP", "4"))

# RAM budget per worker (MB). Workers spike to 300-500MB under load.
MB_PER_WORKER = int(os.environ.get("V5_MB_PER_WORKER", "350"))

# System RAM headroom (MB). Reserved for OS + gateway + ollama + etc.
SYSTEM_HEADROOM_MB = int(os.environ.get("V5_SYSTEM_HEADROOM_MB", "3500"))

# Additional safety headroom (MB) kept free
SAFETY_HEADROOM_MB = int(os.environ.get("V5_SAFETY_HEADROOM_MB", "500"))

# Load-per-core thresholds for scaling factors
LOAD_FULL_SPEED = float(os.environ.get("V5_LOAD_FULL_SPEED", "1.5"))  # below: 1.0x
LOAD_THROTTLE   = float(os.environ.get("V5_LOAD_THROTTLE", "2.0"))   # 0.75x
LOAD_HEAVY      = float(os.environ.get("V5_LOAD_HEAVY", "2.5"))      # 0.5x
# above LOAD_HEAVY: 0.25x (barely dispatch)

# API quota thresholds
API_OK    = float(os.environ.get("V5_API_OK", "60"))    # below: 1.0x
API_WARN  = float(os.environ.get("V5_API_WARN", "80"))  # 0.75x
# above API_WARN: 0.5x

# Swap threshold (% of total swap) — only matters if RAM also pressured
SWAP_PENALTY_PCT = float(os.environ.get("V5_SWAP_PENALTY_PCT", "50"))

# Safe fallback if anything goes wrong
SAFE_FALLBACK = int(os.environ.get("V5_SAFE_FALLBACK", "2"))


def compute(verbose=False):
    """Compute optimal max workers. Returns int."""
    log = []
    try:
        meminfo = _read_meminfo()
        total_ram_mb = meminfo.get("MemTotal", 7 * 1024 * 1024) // 1024
        available_ram_mb = meminfo.get("MemAvailable", 0) // 1024

        load = _read_loadavg()
        nproc = _read_nproc()
        load_per_core = load / nproc if nproc > 0 else load

        # Total swap for percentage calculation
        total_swap_kb = meminfo.get("SwapTotal", 0)
        free_swap_kb = meminfo.get("SwapFree", 0)
        used_swap_kb = total_swap_kb - free_swap_kb
        swap_pct = (used_swap_kb / total_swap_kb * 100) if total_swap_kb > 0 else 0

        api_quota_pct = _read_zai_quota()

        log.append(f"Signals: RAM avail={available_ram_mb}MB | load={load:.1f} "
                    f"({load_per_core:.2f}/core) | swap={swap_pct:.0f}% | api={api_quota_pct}%")

        # ─── Step 1: RAM-limited ceiling ───────────────────
        # How much RAM can we give to workers?
        # available_ram already accounts for cached buffers (MemAvailable).
        # But we need to keep the safety headroom for spikes.
        worker_ram_budget = available_ram_mb - SAFETY_HEADROOM_MB
        if worker_ram_budget < 0:
            worker_ram_budget = 0

        ram_ceiling = worker_ram_budget // MB_PER_WORKER
        log.append(f"RAM ceiling: ({available_ram_mb} - {SAFETY_HEADROOM_MB}) / {MB_PER_WORKER} = {ram_ceiling}")

        # ─── Step 2: Load scaling factor ───────────────────
        if load_per_core < LOAD_FULL_SPEED:
            load_factor = 1.0
        elif load_per_core < LOAD_THROTTLE:
            load_factor = 0.75
        elif load_per_core < LOAD_HEAVY:
            load_factor = 0.5
        else:
            load_factor = 0.25
        log.append(f"Load factor: {load_factor}x (lpc={load_per_core:.2f})")

        # ─── Step 3: API quota scaling factor ──────────────
        if api_quota_pct < API_OK:
            api_factor = 1.0
        elif api_quota_pct < API_WARN:
            api_factor = 0.75
        else:
            api_factor = 0.5
        log.append(f"API factor: {api_factor}x (quota={api_quota_pct}%)")

        # ─── Step 4: Swap penalty (only if RAM pressured) ──
        # Swap alone isn't a signal — stale pages from killed workers.
        # Only penalize if both swap is high AND available RAM is low.
        ram_pressure = available_ram_mb < (total_ram_mb - SYSTEM_HEADROOM_MB) * 0.3
        if swap_pct > SWAP_PENALTY_PCT and ram_pressure:
            swap_factor = 0.5
            log.append(f"Swap factor: {swap_factor}x (swap={swap_pct:.0f}% + RAM pressured)")
        else:
            swap_factor = 1.0
            log.append(f"Swap factor: {swap_factor}x (no penalty)")

        # ─── Step 5: Compute target ────────────────────────
        raw_target = ram_ceiling * load_factor * api_factor * swap_factor
        target = max(MIN_WORKERS, min(int(raw_target), MAX_CAP))

        log.append(f"Target: max({MIN_WORKERS}, min(int({raw_target:.1f}), {MAX_CAP})) = {target}")

        if verbose:
            for line in log:
                print(line, file=sys.stderr)

        return target

    except Exception as e:
        if verbose:
            print(f"ERROR: {e} — using safe fallback {SAFE_FALLBACK}", file=sys.stderr)
        return SAFE_FALLBACK


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    result = compute(verbose=verbose)
    print(result)
