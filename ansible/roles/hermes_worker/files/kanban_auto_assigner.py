#!/usr/bin/env python3
"""API gate: skip if z.ai is throttled — allows either our key OR friend's key"""
import json, os, sys
_gate_file = os.path.expanduser("~/.hermes/bot/zai_state.json")
if os.path.isfile(_gate_file):
    try:
        _d = json.load(open(_gate_file))
        _our_ok = (not _d.get("quota_pause") and not _d.get("critical") and
                   not _d.get("throttle") and int(_d.get("token_pct", 0)) < 80 and
                   int(_d.get("session_pct", 0)) < 85)
        _friend_ok = int(_d.get("friend_token_pct", 0)) < 80
        if not _our_ok and not _friend_ok:
            sys.exit(0)  # both keys exhausted — silent skip
    except Exception:
        pass

"""
Kanban Auto-Assigner — scans all boards for ready+unassigned tasks and
intelligently assigns them to available worker profiles.

Runs as a cron job (LLM-driven, with --auto flag) or standalone (report only).

Assignment logic (deterministic, no LLM needed for this part):
  - Tasks on 'plebeian' board → worker-plebeian
  - Tasks on 'tollgate' board → worker-tollgate
  - Tasks on 'admin' board → worker-admin
  - If a board's dedicated worker is busy → fall back to worker-base
  - If all workers busy → report and defer

Usage:
  # Report mode (zero tokens) — scan and print what needs assigning
  python3 ~/.hermes/profiles/manager/scripts/kanban_auto_assigner.py

  # Auto-assign mode — actually assign profiles to unassigned tasks
  python3 ~/.hermes/profiles/manager/scripts/kanban_auto_assigner.py --auto

  # Dry-run mode — show what would be assigned without doing it
  python3 ~/.hermes/profiles/manager/scripts/kanban_auto_assigner.py --auto --dry-run

  # Custom idle threshold (default: 1h)
  python3 ~/.hermes/profiles/manager/scripts/kanban_auto_assigner.py --min-idle-hours 2
"""

import subprocess
import json
import re
import sys
import time
import os
import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def run_hermes(cmd, timeout=15):
    """Run a hermes CLI command and return stdout."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=True
        )
        return r.stdout, r.returncode
    except subprocess.TimeoutExpired:
        return "", -1


def get_all_boards():
    """Discover all boards from filesystem — always accurate, no CLI parsing needed.
    
    Scans ~/.hermes/kanban/boards/ for SQLite databases. Skips 'default' and
    'archive' boards. This adapts automatically when new boards are created
    without needing to update any hardcoded lists.
    """
    boards_dir = Path.home() / ".hermes" / "kanban" / "boards"
    skip = {"default", "archive", "archived"}
    try:
        boards = sorted([
            d.name for d in boards_dir.iterdir()
            if d.is_dir() and d.name not in skip and (d / "kanban.db").exists()
        ])
    except Exception:
        boards = ["admin", "plebeian", "tollgate", "market"]
    return boards if boards else ["admin", "plebeian", "tollgate", "market"]


def parse_task_line(line):
    """Parse a kanban ls output line into structured data."""
    # Format: ✓ t_abc123  done      profile-name      Task title
    #         ▶ t_def456  ready     (unassigned)      Task title
    #         ⊘ t_ghi789  blocked   profile-name      Task title
    #         ◻ t_jkl012  todo      profile-name      Task title
    m = re.match(
        r"[▶✓⊘◻●]\s+(t_\w+)\s+(\w+)\s+(\(?[\w-]+\)?)\s+(.*)",
        line,
    )
    if m:
        tid = m.group(1)
        status = m.group(2)
        assignee = m.group(3)
        if assignee == "(unassigned)":
            assignee = ""
        title = m.group(4).strip()
        return {"id": tid, "status": status, "assignee": assignee, "title": title}
    return None


def scan_board(board):
    """Scan a single board for tasks."""
    out, rc = run_hermes(f"hermes kanban --board {board} ls 2>/dev/null")
    if rc != 0 or not out:
        return []
    tasks = []
    for line in out.split("\n"):
        parsed = parse_task_line(line)
        if parsed:
            parsed["board"] = board
            tasks.append(parsed)
    return tasks


def scan_all_boards_fast():
    """Scan ALL boards for tasks via direct SQLite queries.

    Replaces the per-board `hermes kanban ls` subprocess calls (which spawn the
    CLI 86+ times and exceed the 120s cron timeout under load) with a single
    pass over the board databases. ~100x faster: <2s vs >120s.

    Returns the same task dict structure as scan_board():
        {"id", "status", "assignee", "title", "board"}
    """
    boards_dir = Path.home() / ".hermes" / "kanban" / "boards"
    skip = {"default", "archive", "archived"}
    all_tasks = []
    if not boards_dir.exists():
        return all_tasks
    for db_path in sorted(boards_dir.glob("*/kanban.db")):
        board = db_path.parent.name
        if board in skip:
            continue
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                "SELECT id, title, status, assignee FROM tasks "
                "WHERE status NOT IN ('archived', 'done')"
            ).fetchall():
                assignee = r["assignee"] or ""
                if assignee == "(unassigned)":
                    assignee = ""
                all_tasks.append({
                    "id": r["id"],
                    "status": r["status"],
                    "assignee": assignee,
                    "title": r["title"] or "",
                    "board": board,
                })
            conn.close()
        except Exception:
            continue
    return all_tasks


def get_profile_status():
    """Get profile status from assignees output."""
    out, rc = run_hermes("hermes kanban --board admin assignees 2>/dev/null")
    if rc != 0:
        return {}
    profiles = {}
    for line in out.split("\n"):
        line = line.strip()
        if not line or line.startswith("NAME"):
            continue
        # Try with parens: "worker-admin  yes  (idle)" or "worker-admin  yes  (blocked=1)"
        m = re.match(r"(\S+)\s+(\w+)\s+\((.+)\)", line)
        if m:
            name, disk_state, counts_str = m.group(1), m.group(2), m.group(3)
        else:
            # Fallback: no parens: "worker-admin  yes  blocked=3, done=3"
            m = re.match(r"(\S+)\s+(\w+)\s+(.+)", line)
            if not m:
                # Minimal: "worker-admin  yes"
                m = re.match(r"(\S+)\s+(\w+)\s*$", line)
                if not m:
                    continue
                name, disk_state, counts_str = m.group(1), m.group(2), ""
            else:
                name, disk_state, counts_str = m.group(1), m.group(2), m.group(3)
        if name == "NAME":
            continue
        is_running = "running" in counts_str if counts_str else False
        is_idle = not is_running  # idle = not currently running anything
        profiles[name] = {
            "on_disk": disk_state == "yes",
            "running": is_running,
            "idle": is_idle,
        }
    return profiles


# Board → preferred worker profile mapping
BOARD_PROFILE_MAP = {
    "plebeian": "worker-plebeian",
    "tollgate": "worker-tollgate",
    "admin": "worker-admin",
    "market": "worker-plebeian",
    "fips": "worker-admin",
    "vps-infra": "worker-admin",
}

# Worker profile → description (for reporting)
WORKER_DESCRIPTIONS = {
    "worker-plebeian": "Plebeian Market tasks (React, NDK, e2e, CI)",
    "worker-tollgate": "TollGate/IoT tasks (ESP32, RP2040, LoRa, firmware)",
    "worker-admin": "Admin/ops tasks (Hermes, proxy, kanban, monitoring)",
    "worker-base": "General fallback worker (any task type)",
}




def get_busy_profiles():
    """Scan ALL board databases for tasks in 'running' status.
    
    Returns a set of assignee names that currently have at least one running
    task on ANY board. This is the definitive source of truth for profile
    availability — unlike per-board assignees output which only shows status
    relative to a single board.
    """
    busy = set()
    boards_dir = Path.home() / ".hermes" / "kanban" / "boards"
    if not boards_dir.exists():
        return busy
    for db_path in boards_dir.glob("*/kanban.db"):
        try:
            conn = sqlite3.connect(str(db_path))
            for row in conn.execute(
                "SELECT DISTINCT assignee FROM tasks WHERE status='running'"
            ).fetchall():
                if row[0]:
                    busy.add(row[0])
            conn.close()
        except Exception:
            continue
    return busy


# Heavy task patterns that should route to DQ05 (10GB RAM, no OOM risk)
HEAVY_PATTERNS = [
    "tdd", "full suite", "nip60", "playwright", "tsc", "bun test",
    "e2e", "settlement", "cashu", "auction", "nip-60", "wallet",
    "install", "build", "compile", "migration",
]

# Task classification patterns for resource-aware routing
TASK_MEMORY_HEAVY = [
    "tdd", "full suite", "e2e", "playwright", "tsc", "bun test",
    "migration", "nip60", "nip-60", "wallet", "settlement", "cashu",
    "auction", "compile", "build", "install",
]
TASK_CPU_HEAVY = [
    "build", "compile", "tsc", "bun test", "full suite", "tdd",
    "e2e", "playwright", "install",
]
TASK_LIGHT = [
    "search", "lookup", "find", "grep", "list", "status", "check",
    "read", "view", "show", "ls", "cat", "report", "summary",
]

# Kalman routing thresholds (separate from predictor's internal thresholds)
KALMAN_T470_OFFLOAD_MEMORY_PCT = 80.0
KALMAN_T470_OFFLOAD_CPU_LOAD = 6.0
KALMAN_DQ05_MAX_MEMORY_PCT = 70.0
KALMAN_DQ05_MAX_CPU_LOAD = 3.0
KALMAN_PREDICTION_MINUTES = 30

DQ05_SSH_TARGET = "c03rad0r@100.90.22.201"
DQ05_CONTEXTVM_URL = "http://100.90.22.201:9100"


def is_dq05_reachable():
    """Quick check if DQ05 is reachable via SSH."""
    import subprocess
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=2", DQ05_SSH_TARGET, "echo ok"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0 and "ok" in result.stdout
    except Exception:
        return False


def classify_task(title, task_id="", body=""):
    """Classify a task by resource intensity.

    Returns one of: 'memory_heavy', 'cpu_heavy', 'light', 'medium'
    """
    combined = (title + " " + task_id + " " + (body or "")).lower()

    is_mem_heavy = any(p in combined for p in TASK_MEMORY_HEAVY)
    is_cpu_heavy = any(p in combined for p in TASK_CPU_HEAVY)
    is_light = any(p in combined for p in TASK_LIGHT)

    if is_mem_heavy:
        return "memory_heavy"
    if is_cpu_heavy:
        return "cpu_heavy"
    if is_light:
        return "light"
    return "medium"


def get_t470_resource_state():
    """Read T470's current and predicted resource state.

    Uses MultiResourceKalmanPredictor if available (with history data),
    otherwise falls back to a live system snapshot.

    Returns:
        Dict with current and predicted resource values, or None on error.
    """
    import os, sys as _sys

    bot_dir = os.path.expanduser("~/.hermes/bot")
    if bot_dir not in _sys.path:
        _sys.path.insert(0, bot_dir)

    try:
        from multi_resource_kalman import (
            MultiResourceKalmanPredictor,
            get_resource_history,
        )

        history = get_resource_history(hours=2)
        if not history:
            return _get_live_system_snapshot("t470")

        predictor = MultiResourceKalmanPredictor(
            process_noise=0.5,
            measurement_noise={
                "tokens": 50000,
                "cpu_load": 0.3,
                "memory_pct": 3.0,
                "worker_count": 1.0,
            },
        )
        for point in history:
            predictor.update({
                "tokens": point.get("tokens", 0),
                "cpu_load": point.get("cpu_load", 0),
                "memory_pct": point.get("memory_pct", 0),
                "worker_count": point.get("worker_count", 0),
            })

        if not predictor.is_initialized:
            return _get_live_system_snapshot("t470")

        steps = max(1, KALMAN_PREDICTION_MINUTES // 5)
        predictions = predictor.predict_steps_ahead(steps)
        current = predictor.state_vector

        final_pred = predictions[-1] if predictions else {}

        return {
            "host": "t470",
            "current": {
                "cpu_load": float(current[1]),
                "memory_pct": float(current[2]),
                "worker_count": float(current[3]),
            },
            "predicted": {
                "cpu_load": final_pred.get("cpu_load", {}).get("value", float(current[1])),
                "memory_pct": final_pred.get("memory_pct", {}).get("value", float(current[2])),
                "worker_count": final_pred.get("worker_count", {}).get("value", float(current[3])),
            },
            "source": "kalman",
            "update_count": predictor._update_count,
        }
    except Exception:
        return _get_live_system_snapshot("t470")


def get_dq05_resource_state():
    """Read DQ05's current resource state via ContextVM HTTP endpoint.

    Falls back to SSH if HTTP is unreachable.

    Returns:
        Dict with current resource values, or None if unreachable.
    """
    import json as _json
    import urllib.request
    import urllib.error

    # Try HTTP first (faster, no SSH overhead)
    try:
        req = urllib.request.Request(
            DQ05_CONTEXTVM_URL,
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))

        # ContextVM returns: cpu_percent, memory, load_avg, etc.
        mem_info = data.get("memory", {})
        mem_total = mem_info.get("total", 0)
        mem_available = mem_info.get("available", 0)
        memory_pct = 0.0
        if mem_total > 0:
            memory_pct = ((mem_total - mem_available) / mem_total) * 100.0

        load_avg = data.get("load_avg", {})
        cpu_load = load_avg.get("load_1m", 0.0)

        return {
            "host": "dq05",
            "current": {
                "cpu_load": float(cpu_load),
                "memory_pct": round(memory_pct, 1),
                "worker_count": 0,
            },
            "predicted": {
                "cpu_load": float(cpu_load),
                "memory_pct": round(memory_pct, 1),
                "worker_count": 0,
            },
            "source": "contextvm_http",
        }
    except Exception:
        pass

    # Fallback: SSH query
    try:
        import subprocess
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=3", DQ05_SSH_TARGET,
             "cat /proc/loadavg; free | awk '/Mem:/ {print $3, $2}'"],
            capture_output=True, text=True, timeout=8,
        )
        if result.returncode != 0:
            return None

        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return None

        load_1m = float(lines[0].split()[0])
        mem_parts = lines[1].split()
        mem_used = int(mem_parts[0])
        mem_total = int(mem_parts[1])
        memory_pct = (mem_used / mem_total * 100.0) if mem_total > 0 else 0.0

        return {
            "host": "dq05",
            "current": {
                "cpu_load": load_1m,
                "memory_pct": round(memory_pct, 1),
                "worker_count": 0,
            },
            "predicted": {
                "cpu_load": load_1m,
                "memory_pct": round(memory_pct, 1),
                "worker_count": 0,
            },
            "source": "ssh",
        }
    except Exception:
        return None


def _get_live_system_snapshot(host="t470"):
    """Fallback: read live system stats without Kalman prediction.

    Returns current values only (predicted == current) when Kalman
    is unavailable.
    """
    try:
        import os

        load_1m = 0.0
        with open("/proc/loadavg") as f:
            load_1m = float(f.read().split()[0])

        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = int(parts[1].strip().split()[0]) * 1024
                    meminfo[key] = val

        mem_total = meminfo.get("MemTotal", 1)
        mem_available = meminfo.get("MemAvailable", meminfo.get("MemFree", 0))
        memory_pct = ((mem_total - mem_available) / mem_total) * 100.0 if mem_total > 0 else 0.0

        worker_count = 0
        boards_dir = Path.home() / ".hermes" / "kanban" / "boards"
        if boards_dir.exists():
            for db_path in boards_dir.glob("*/kanban.db"):
                try:
                    conn = sqlite3.connect(str(db_path))
                    for row in conn.execute(
                        "SELECT COUNT(*) FROM tasks WHERE status='running'"
                    ).fetchall():
                        worker_count += row[0]
                    conn.close()
                except Exception:
                    continue

        return {
            "host": host,
            "current": {
                "cpu_load": load_1m,
                "memory_pct": round(memory_pct, 1),
                "worker_count": worker_count,
            },
            "predicted": {
                "cpu_load": load_1m,
                "memory_pct": round(memory_pct, 1),
                "worker_count": worker_count,
            },
            "source": "live_snapshot",
            "update_count": 0,
        }
    except Exception:
        return None


def kalman_aware_route(board, title, task_id, body=""):
    """Decide where to dispatch a task using Kalman resource predictions.

    Routing rules:
      - If T470 memory_pct predicted > 80% in 30 min → offload to DQ05
      - If T470 cpu_load predicted > 6.0 in 30 min → offload to DQ05
      - If DQ05 memory_pct predicted > 70% → don't offload (leave headroom)
      - If DQ05 cpu_load predicted > 3.0 → don't offload (N95 is slower)
      - If DQ05 unreachable → stay on T470
      - If both machines stressed → don't dispatch (return None, let kanban queue)
      - Falls back to static HEAVY_PATTERNS if Kalman unavailable

    Returns:
        (profile, reason) tuple. profile is a string like "worker-dq05",
        "worker-base", "worker-admin", etc., or None if no dispatch.
    """
    task_type = classify_task(title, task_id, body)

    # Get resource states
    t470_state = get_t470_resource_state()
    dq05_state = get_dq05_resource_state()
    dq05_reachable = dq05_state is not None

    # If Kalman is unavailable, fall back to static patterns
    if t470_state is None or t470_state.get("source") == "live_snapshot":
        if dq05_reachable and should_route_to_dq05(board, title, task_id, body):
            return ("worker-dq05", f"static_pattern_match (kalman_unavailable, task={task_type})")
        return _keyword_route(board, title, task_id, body, task_type)

    if t470_state is None:
        return _keyword_route(board, title, task_id, body, task_type)

    t470_pred = t470_state.get("predicted", t470_state.get("current", {}))
    t470_mem = t470_pred.get("memory_pct", 0)
    t470_cpu = t470_pred.get("cpu_load", 0)

    # Determine if T470 is stressed
    t470_mem_stressed = t470_mem > KALMAN_T470_OFFLOAD_MEMORY_PCT
    t470_cpu_stressed = t470_cpu > KALMAN_T470_OFFLOAD_CPU_LOAD
    t470_stressed = t470_mem_stressed or t470_cpu_stressed

    # Light tasks never need offloading — they're cheap
    if task_type == "light" and not t470_stressed:
        return _keyword_route(board, title, task_id, body, task_type)

    # T470 is fine and task is not heavy → keep it local
    if not t470_stressed and task_type in ("medium", "light"):
        return _keyword_route(board, title, task_id, body, task_type)

    # T470 is stressed or task is heavy → consider DQ05
    if t470_stressed or should_route_to_dq05(board, title, task_id, body):
        if not dq05_reachable:
            if t470_stressed:
                stress_reason = f"mem={t470_mem:.0f}%>" \
                    f"{KALMAN_T470_OFFLOAD_MEMORY_PCT:.0f}%" if t470_mem_stressed else ""
                if t470_cpu_stressed:
                    stress_reason += f" cpu={t470_cpu:.1f}>{KALMAN_T470_OFFLOAD_CPU_LOAD}" if stress_reason \
                        else f"cpu={t470_cpu:.1f}>{KALMAN_T470_OFFLOAD_CPU_LOAD}"
                return (None, f"t470_stressed ({stress_reason}) but dq05_unreachable — defer")
            return _keyword_route(board, title, task_id, body, task_type)

        # Check DQ05 capacity
        dq05_pred = dq05_state.get("predicted", dq05_state.get("current", {}))
        dq05_mem = dq05_pred.get("memory_pct", 0)
        dq05_cpu = dq05_pred.get("cpu_load", 0)

        dq05_mem_ok = dq05_mem < KALMAN_DQ05_MAX_MEMORY_PCT
        dq05_cpu_ok = dq05_cpu < KALMAN_DQ05_MAX_CPU_LOAD

        if not dq05_mem_ok or not dq05_cpu_ok:
            # Both machines stressed — don't dispatch
            t470_reason = ""
            if t470_mem_stressed:
                t470_reason += f"t470_mem={t470_mem:.0f}% "
            if t470_cpu_stressed:
                t470_reason += f"t470_cpu={t470_cpu:.1f} "
            dq05_reason = ""
            if not dq05_mem_ok:
                dq05_reason += f"dq05_mem={dq05_mem:.0f}% "
            if not dq05_cpu_ok:
                dq05_reason += f"dq05_cpu={dq05_cpu:.1f} "
            return (None, f"both_stressed — {t470_reason}{dq05_reason}defer to queue")

        # DQ05 has capacity — offload
        reason_parts = []
        if t470_mem_stressed:
            reason_parts.append(f"t470_mem={t470_mem:.0f}%>{KALMAN_T470_OFFLOAD_MEMORY_PCT:.0f}%")
        if t470_cpu_stressed:
            reason_parts.append(f"t470_cpu={t470_cpu:.1f}>{KALMAN_T470_OFFLOAD_CPU_LOAD}")
        if not t470_stressed:
            reason_parts.append(f"heavy_pattern_match (task={task_type})")
        reason_parts.append(f"dq05_ok(mem={dq05_mem:.0f}%,cpu={dq05_cpu:.1f})")
        return ("worker-dq05", ", ".join(reason_parts))

    # Default: keyword-based routing
    return _keyword_route(board, title, task_id, body, task_type)


def _keyword_route(board, title, task_id, body, task_type="medium"):
    """Fallback keyword-based profile recommendation (original logic).

    Returns (profile, reason) tuple.
    """
    fw_keywords = [
        "esp32", "rp2040", "lora", "firmware", "balloon", "tollgate",
        "spi", "dma", "pio", "flrc", "meshcore", "sx1280", "radio",
        "uart", "serial", "i2c", "gps", "nmea",
    ]
    market_keywords = [
        "market", "plebeian", "nostr", "nip", "applesauce", "ndk",
        "e2e", "test", "ci", "pr", "ui", "react", "typescript",
    ]
    admin_keywords = [
        "hermes", "proxy", "kanban", "gateway", "cron", "ngit",
        "deploy", "monitor", "ctx", "backup", "ansible",
    ]

    title_lower = title.lower() + " " + task_id.lower()

    fw_score = sum(1 for kw in fw_keywords if kw in title_lower)
    market_score = sum(1 for kw in market_keywords if kw in title_lower)
    admin_score = sum(1 for kw in admin_keywords if kw in title_lower)

    scores = {
        "worker-tollgate": fw_score * 3 + (1 if board == "tollgate" else 0),
        "worker-plebeian": market_score * 3 + (1 if board == "plebeian" else 0),
        "worker-admin": admin_score * 3 + (1 if board == "admin" else 0),
        "worker-base": 0,
    }

    best = max(scores, key=scores.get)
    profile = best if scores[best] > 0 else "worker-base"
    return (profile, f"keyword_route (task={task_type}, score={scores[best]})")


def should_route_to_dq05(board, title, task_id, body=""):
    """Check if a task is heavy enough to warrant DQ05 routing."""
    combined = (title + " " + task_id + " " + (body or "")).lower()

    # Pattern match
    if any(p in combined for p in HEAVY_PATTERNS):
        return True

    return False


def recommend_profile(board, title, task_id, body=""):
    """Recommend the best worker profile for a task.

    Uses kalman_aware_route() for resource-aware routing, falling back
    to static keyword matching if Kalman is unavailable.
    """
    profile, reason = kalman_aware_route(board, title, task_id, body)
    if profile is not None:
        return profile

    # kalman_aware_route returned None (both stressed or DQ05 unreachable + stressed)
    # Fall back to keyword routing so the task still gets assigned locally
    profile, _ = _keyword_route(board, title, task_id, body, classify_task(title, task_id, body))
    return profile


def assign_task(board, task_id, profile, dry_run=False):
    """Assign a task to a profile."""
    if dry_run:
        return True, f"WOULD assign {task_id} on {board} → {profile}"
    out, rc = run_hermes(
        f"hermes kanban --board {board} reassign {task_id} {profile} 2>&1",
        timeout=10,
    )
    success = rc == 0 and "error" not in out.lower()
    return success, out.strip() if not success else f"Assigned {task_id} → {profile}"


def main():
    parser = argparse.ArgumentParser(description="Kanban auto-assigner")
    parser.add_argument("--auto", action="store_true", help="Actually assign tasks")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be assigned"
    )
    parser.add_argument(
        "--min-idle-hours", type=float, default=1.0, help="Minimum idle age threshold"
    )
    parser.add_argument(
        "--board", type=str, default="", help="Only process this board"
    )
    args = parser.parse_args()

    # Scan all boards
    if args.board:
        # Single-board mode: use the CLI-based scan (accurate, one CLI call)
        all_tasks = scan_board(args.board)
    else:
        # Multi-board mode: fast direct-SQLite scan — avoids 86+ CLI spawns
        # that exceed the 120s cron timeout under load. ~100x faster.
        all_tasks = scan_all_boards_fast()

    # Filter to ready+unassigned
    ready_unassigned = [
        t
        for t in all_tasks
        if t["status"] == "ready" and not t["assignee"]
    ]

    # Get profile status
    profiles = get_profile_status()
    # Query all board DBs for the definitive set of busy profiles
    busy_profiles_global = get_busy_profiles()
    running_profiles = {
        name: info
        for name, info in profiles.items()
        if name in busy_profiles_global and name.startswith("worker-")
    }

    # Read Kalman-smoothed pool size from the daemon's state
    pool_smoothed = None
    pool_cap = len(profiles)  # default: all profiles
    pool_state_path = os.path.expanduser("~/.hermes/state/pool_kalman.json")
    try:
        if os.path.exists(pool_state_path):
            with open(pool_state_path) as f:
                ps = json.load(f)
            pool_smoothed = int(round(ps["x"][0]))
            pool_velocity = ps["x"][1]
            # Pool cap = smoothed workers, but at least 1 and at most all profiles
            pool_cap = max(1, min(pool_smoothed, len(profiles)))
    except (KeyError, ValueError, json.JSONDecodeError):
        pass

    # How many additional workers can we assign?
    running_total = len(running_profiles)
    remaining_slots = max(0, pool_cap - running_total)

    idle_profiles = {
        name: info
        for name, info in profiles.items()
        if name not in busy_profiles_global
        and name.startswith("worker-")
        and info.get("on_disk", False)
    }

    if not ready_unassigned:
        print("NO_ACTION: no ready+unassigned tasks found")
        return

    # Print structured output
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"=== Auto-Assigner Scan: {now} ===")
    print(f"Ready+unassigned: {len(ready_unassigned)}")
    print(f"Available workers (idle): {len(idle_profiles)} ({', '.join(idle_profiles.keys())})")
    if running_profiles:
        print(f"Busy workers: {len(running_profiles)} ({', '.join(running_profiles.keys())})")
    if pool_smoothed:
        print(f"Pool Kalman: smoothed={pool_smoothed}, running={running_total}, "
              f"remaining_slots={remaining_slots}")
    print()

    # Assignments
    assigned = 0
    skipped_no_worker = 0

    for task in ready_unassigned:
        board = task["board"]
        preferred = BOARD_PROFILE_MAP.get(board, "worker-base")
        recommended = recommend_profile(board, task["title"], task["id"])

        # Check if preferred profile is idle
        if preferred in idle_profiles:
            target = preferred
        elif recommended in idle_profiles:
            target = recommended
        elif "worker-base" in idle_profiles:
            target = "worker-base"
        elif idle_profiles:
            # Last resort: any idle worker profile
            target = sorted(idle_profiles.keys())[0]
        else:
            target = None

        idle_str = ""
        if task.get("board"):
            pass  # already available

        if target and args.auto:
            success, msg = assign_task(board, task["id"], target, args.dry_run)
            prefix = "[DRY-RUN]" if args.dry_run else "[ASSIGNED]"
            print(f"{prefix} {board}/{task['id']}: {task['title']}")
            print(f"       recommended={recommended} → assigned={target}")
            if not args.dry_run:
                idle_profiles.pop(target, None)  # consume it
                remaining_slots -= 1
            assigned += 1
            # Stop assigning if we've filled the pool
            if remaining_slots <= 0:
                print(f"       (pool at capacity — {pool_cap} workers)")
                break
        elif target:
            print(f"[SUGGEST] {board}/{task['id']}: {task['title']}")
            print(f"          recommended={recommended}, available={target}")
            print(f"          → hermes kanban --board {board} reassign {task['id']} {target}")
            assigned += 1
        else:
            print(f"[STALLED] {board}/{task['id']}: {task['title']}")
            print(f"          recommended={recommended}, but ALL workers busy")
            skipped_no_worker += 1

    print()
    summary_parts = []
    if args.auto:
        action = "dry-run" if args.dry_run else "assigned"
        summary_parts.append(f"{assigned} {action}")
    else:
        summary_parts.append(f"{assigned} suggestions")
    if skipped_no_worker:
        summary_parts.append(f"{skipped_no_worker} skipped (no free workers)")
    print(f"Summary: {', '.join(summary_parts)}")


if __name__ == "__main__":
    main()
