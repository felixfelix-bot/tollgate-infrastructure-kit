#!/usr/bin/env python3
"""
vps-health-mcp.py — MCP server exposing VPS health metrics to Hermes.

Deployed on the VPS (23.182.128.51), runs as a systemd service.
Hermes connects to it remotely to get real-time health data.

Tools exposed:
  - vps_health: CPU, memory, disk, load, uptime
  - vps_services: List all Docker containers + systemd services with status
  - vps_disk_trend: Disk usage trend + prediction (when will it fill?)
  - vps_predict: Kalman-filtered predictions for resource exhaustion

No pip packages — stdlib only.
"""

import json
import os
import subprocess
import sys
import time
import sqlite3
from pathlib import Path

DB_PATH = "/var/lib/vps-health/metrics.db"
DISK_DEV = "/dev/sda1"


def ensure_db():
    """Create metrics DB if it doesn't exist."""
    Path(os.path.dirname(DB_PATH)).mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("""CREATE TABLE IF NOT EXISTS metrics (
        ts REAL,
        cpu_load1 REAL,
        cpu_load5 REAL,
        mem_used_mb INTEGER,
        mem_total_mb INTEGER,
        mem_pct REAL,
        disk_used_gb REAL,
        disk_total_gb REAL,
        disk_pct REAL,
        swap_used_kb INTEGER,
        container_count INTEGER,
        healthy_containers INTEGER
    )""")
    db.commit()
    db.close()


def collect_metrics():
    """Collect current system metrics."""
    # Load average
    with open("/proc/loadavg") as f:
        parts = f.read().split()
        load1, load5 = float(parts[0]), float(parts[1])

    # Memory
    mem_total, mem_avail = 0, 0
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) // 1024
            elif line.startswith("MemAvailable:"):
                mem_avail = int(line.split()[1]) // 1024
    mem_used = mem_total - mem_avail
    mem_pct = (mem_used / mem_total * 100) if mem_total > 0 else 0

    # Disk
    disk_total, disk_used, disk_pct = 0, 0, 0
    try:
        result = subprocess.run(["df", "-B1", DISK_DEV], capture_output=True, text=True, timeout=5)
        lines = result.stdout.strip().split("\n")
        if len(lines) > 1:
            parts = lines[1].split()
            disk_total = int(parts[1]) / (1024**3)  # GB
            disk_used = int(parts[2]) / (1024**3)
            disk_pct = float(parts[4].rstrip("%"))
    except Exception:
        pass

    # Swap
    swap_used = 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("SwapTotal:"):
                    swap_total_kb = int(line.split()[1])
                elif line.startswith("SwapFree:"):
                    swap_free_kb = int(line.split()[1])
        swap_used = swap_total_kb - swap_free_kb
    except Exception:
        pass

    # Docker containers
    container_count, healthy = 0, 0
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}\t{{.Status}}"],
            capture_output=True, text=True, timeout=10
        )
        for line in result.stdout.strip().split("\n"):
            if line:
                container_count += 1
                if "Up" in line and "unhealthy" not in line.lower():
                    healthy += 1
    except Exception:
        pass

    return {
        "ts": time.time(),
        "cpu_load1": load1,
        "cpu_load5": load5,
        "mem_used_mb": mem_used,
        "mem_total_mb": mem_total,
        "mem_pct": round(mem_pct, 1),
        "disk_used_gb": round(disk_used, 1),
        "disk_total_gb": round(disk_total, 1),
        "disk_pct": round(disk_pct, 1),
        "swap_used_kb": swap_used,
        "container_count": container_count,
        "healthy_containers": healthy,
    }


def save_metrics(metrics):
    """Save metrics to DB for trend analysis."""
    db = sqlite3.connect(DB_PATH)
    db.execute("""INSERT INTO metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
        metrics["ts"], metrics["cpu_load1"], metrics["cpu_load5"],
        metrics["mem_used_mb"], metrics["mem_total_mb"], metrics["mem_pct"],
        metrics["disk_used_gb"], metrics["disk_total_gb"], metrics["disk_pct"],
        metrics["swap_used_kb"], metrics["container_count"],
        metrics["healthy_containers"]
    ))
    db.commit()
    db.close()


def predict_disk_full():
    """Simple linear regression to predict disk full date."""
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        "SELECT ts, disk_pct FROM metrics ORDER BY ts DESC LIMIT 100"
    ).fetchall()
    db.close()

    if len(rows) < 10:
        return {"predictable": False, "reason": "insufficient data"}

    # Simple linear regression: y = a + b*x
    n = len(rows)
    xs = [(rows[0][0] - r[0]) / 86400 for r in rows]  # days ago
    ys = [r[1] for r in rows]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    b_num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    b_den = sum((x - x_mean) ** 2 for x in xs)
    if b_den == 0 or b_num <= 0:
        return {"predictable": False, "rate_pct_per_day": 0}
    slope = b_num / b_den  # %/day
    intercept = y_mean - slope * x_mean
    if slope <= 0:
        return {"predictable": False, "rate_pct_per_day": slope, "trend": "decreasing"}
    days_to_full = (100 - intercept) / slope
    return {
        "predictable": True,
        "rate_pct_per_day": round(slope, 3),
        "current_pct": round(ys[0], 1),
        "days_to_full": round(days_to_full, 1),
        "eta_full_date": time.strftime("%Y-%m-%d", time.gmtime(rows[0][0] + days_to_full * 86400)),
    }


def predict_oom():
    """Predict memory exhaustion."""
    db = sqlite3.connect(DB_PATH)
    rows = db.execute(
        "SELECT ts, mem_pct FROM metrics ORDER BY ts DESC LIMIT 100"
    ).fetchall()
    db.close()

    if len(rows) < 10:
        return {"predictable": False, "reason": "insufficient data"}

    n = len(rows)
    xs = [(rows[0][0] - r[0]) / 86400 for r in rows]
    ys = [r[1] for r in rows]
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    b_num = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    b_den = sum((x - x_mean) ** 2 for x in xs)
    if b_den == 0:
        return {"predictable": False}
    slope = b_num / b_den
    if slope <= 0:
        return {"predictable": False, "trend": "stable or decreasing"}
    intercept = y_mean - slope * x_mean
    days_to_full = (100 - intercept) / slope
    return {
        "predictable": True,
        "rate_pct_per_day": round(slope, 2),
        "current_pct": round(ys[0], 1),
        "days_to_full": round(days_to_full, 1),
    }


# MCP server protocol
TOOLS = [
    {
        "name": "vps_health",
        "description": "Get current VPS health: CPU, memory, disk, load, containers",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "vps_services",
        "description": "List all Docker containers and their status",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "vps_disk_trend",
        "description": "Disk usage trend and prediction for when disk will fill",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "vps_predict",
        "description": "Kalman-filtered predictions for disk and memory exhaustion",
        "inputSchema": {"type": "object", "properties": {}}
    },
]


def handle_request(request):
    req_id = request.get("id")
    method = request.get("method", "")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "vps-health", "version": "1.0.0"}
        }}
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        tool = request.get("params", {}).get("name", "")
        ensure_db()

        if tool == "vps_health":
            m = collect_metrics()
            save_metrics(m)
            result = {
                "load_1m": m["cpu_load1"],
                "load_5m": m["cpu_load5"],
                "memory": f"{m['mem_used_mb']}MB / {m['mem_total_mb']}MB ({m['mem_pct']}%)",
                "disk": f"{m['disk_used_gb']}GB / {m['disk_total_gb']}GB ({m['disk_pct']}%)",
                "swap_kb": m["swap_used_kb"],
                "containers": f"{m['healthy_containers']}/{m['container_count']} healthy",
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(m["ts"]))
            }
        elif tool == "vps_services":
            try:
                svc = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
                    capture_output=True, text=True, timeout=10
                )
                result = {"services": svc.stdout.strip().split("\n")}
            except Exception as e:
                result = {"error": str(e)}
        elif tool == "vps_disk_trend":
            result = predict_disk_full()
        elif tool == "vps_predict":
            result = {
                "disk": predict_disk_full(),
                "memory": predict_oom()
            }
        else:
            result = {"error": f"Unknown tool: {tool}"}

        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}
        }
    elif method == "notifications/initialized":
        return None
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {
            "code": -32601, "message": f"Method not found: {method}"}}


def main():
    ensure_db()
    # Collect metrics on startup
    m = collect_metrics()
    save_metrics(m)

    sys.stderr.write(f"vps-health MCP server started "
                     f"(load={m['cpu_load1']}, disk={m['disk_pct']}%, "
                     f"containers={m['healthy_containers']}/{m['container_count']})\n")
    sys.stderr.flush()

    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue


if __name__ == "__main__":
    main()
