#!/usr/bin/env python3
"""
VPS Diagnostic Collector — SSHes to a VPS, collects health data,
identifies cleanup opportunities, produces actionable recommendations.

Usage:
  python3 vps_diag.py --host 23.182.128.51 --user debian --password PASS
  python3 vps_diag.py --host 23.182.128.51 --user debian --password PASS --json

Output:
  Human-readable report to stdout (or JSON with --json)
  Saves state to ~/.hermes/state/vps_diag_<host>.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime

STATE_DIR = os.path.expanduser("~/.hermes/state")


def ssh_cmd(host, user, password, command, timeout=30):
    """Execute a command via SSH using sshpass."""
    full_cmd = [
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout=10",
        f"{user}@{host}",
        command
    ]
    try:
        result = subprocess.run(
            full_cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1
    except FileNotFoundError:
        return "", "sshpass not found", -2


def collect_diagnostics(host, user, password):
    """Collect all diagnostic data from the VPS."""
    data = {"host": host, "timestamp": datetime.utcnow().isoformat() + "Z"}

    # 1. Disk usage
    out, _, _ = ssh_cmd(host, user, password, "df -h --output=target,size,used,avail,pcent 2>/dev/null")
    data["disk"] = out

    # 2. Top directories by size
    out, _, _ = ssh_cmd(host, user, password,
        "sudo du -sh /opt/* /var/lib/docker /var/log /tmp /home 2>/dev/null | sort -rh | head -20", timeout=45)
    data["top_dirs"] = out

    # 3. Docker system df
    out, _, rc = ssh_cmd(host, user, password, "docker system df 2>/dev/null")
    data["docker_df"] = out

    # 4. Docker images
    out, _, _ = ssh_cmd(host, user, password,
        "docker images --format '{{.Repository}}:{{.Tag}} {{.Size}} {{.ID}}' 2>/dev/null", timeout=20)
    data["docker_images"] = out

    # 5. Container status
    out, _, _ = ssh_cmd(host, user, password,
        "docker ps -a --format '{{.Names}}|{{.Status}}|{{.Size}}' 2>/dev/null", timeout=20)
    data["containers"] = out

    # 6. Journal size
    out, _, _ = ssh_cmd(host, user, password, "journalctl --disk-usage 2>/dev/null")
    data["journal_size"] = out

    # 7. Log directory sizes
    out, _, _ = ssh_cmd(host, user, password,
        "sudo du -sh /var/log/* 2>/dev/null | sort -rh | head -15", timeout=30)
    data["log_sizes"] = out

    # 8. Backups
    out, _, _ = ssh_cmd(host, user, password,
        "sudo find /opt -name '*.tar.gz' -o -name '*.tar' -o -name '*.bak' -o -name '*.sql.gz' 2>/dev/null | head -20 | xargs -I{} sudo ls -lh {} 2>/dev/null", timeout=30)
    data["backups"] = out

    # 9. apt cache
    out, _, _ = ssh_cmd(host, user, password, "sudo du -sh /var/cache/apt 2>/dev/null")
    data["apt_cache"] = out

    # 10. Memory
    out, _, _ = ssh_cmd(host, user, password, "free -m 2>/dev/null")
    data["memory"] = out

    # 11. Load
    out, _, _ = ssh_cmd(host, user, password, "cat /proc/loadavg 2>/dev/null")
    data["load"] = out

    # 12. Dangling images
    out, _, _ = ssh_cmd(host, user, password,
        "docker images -f dangling=true --format '{{.ID}} {{.Size}}' 2>/dev/null")
    data["dangling_images"] = out

    # 13. Stopped containers
    out, _, _ = ssh_cmd(host, user, password,
        "docker ps -a --filter status=exited --filter status=dead --format '{{.Names}} {{.Status}}' 2>/dev/null")
    data["stopped_containers"] = out

    # 14. Unused volumes
    out, _, _ = ssh_cmd(host, user, password,
        "docker volume ls -f dangling=true 2>/dev/null")
    data["dangling_volumes"] = out

    # 15. Old tmp files
    out, _, _ = ssh_cmd(host, user, password,
        "sudo find /tmp -type f -mtime +1 -exec du -sh {} + 2>/dev/null | sort -rh | head -10", timeout=20)
    data["old_tmp"] = out

    return data


def analyze(data):
    """Analyze collected data and produce recommendations."""
    recs = []
    safe_total = 0

    # Parse disk percentage
    for line in data.get("disk", "").split("\n"):
        if "/" in line and "%" in line:
            parts = line.split()
            for p in parts:
                if "%" in p:
                    pct = int(p.replace("%", "").replace("use%", ""))
                    if pct > 85:
                        recs.append({
                            "severity": "WARNING",
                            "category": "disk",
                            "message": f"Mount at {parts[-1]} is {pct}% full",
                            "action": "review_cleanup_options"
                        })

    # Docker dangling images
    dangling = data.get("dangling_images", "").strip()
    if dangling and "<none>" not in dangling:
        count = len([l for l in dangling.split("\n") if l.strip()])
        recs.append({
            "severity": "SAFE",
            "category": "docker-images",
            "message": f"{count} dangling image(s) can be pruned",
            "command": "docker image prune -f",
            "est_recover_mb": count * 200
        })
        safe_total += count * 200

    # Stopped containers
    stopped = data.get("stopped_containers", "").strip()
    if stopped:
        count = len([l for l in stopped.split("\n") if l.strip()])
        recs.append({
            "severity": "SAFE",
            "category": "docker-containers",
            "message": f"{count} stopped container(s) can be removed",
            "command": "docker container prune -f",
            "est_recover_mb": count * 10
        })
        safe_total += count * 10

    # Dangling volumes
    vol_dangling = data.get("dangling_volumes", "").strip()
    if vol_dangling:
        recs.append({
            "severity": "SAFE",
            "category": "docker-volumes",
            "message": "Dangling volumes can be pruned",
            "command": "docker volume prune -f",
            "est_recover_mb": 500
        })
        safe_total += 500

    # Docker build cache
    dd = data.get("docker_df", "")
    if "BUILD CACHE" in dd:
        for line in dd.split("\n"):
            if "BUILD CACHE" in line:
                recs.append({
                    "severity": "SAFE",
                    "category": "docker-build-cache",
                    "message": "Build cache can be pruned",
                    "command": "docker builder prune -f",
                    "est_recover_mb": 100
                })
                safe_total += 100
                break

    # Journal
    journal = data.get("journal_size", "")
    if journal:
        for token in journal.split():
            if "G" in token:
                size = float(token.replace("G", "").replace("s", "").replace("(", ""))
                if size > 0.5:
                    recs.append({
                        "severity": "SAFE",
                        "category": "journal",
                        "message": f"Journal is {size:.1f}GB, vacuum to 200M",
                        "command": "journalctl --vacuum-size=200M",
                        "est_recover_mb": int((size - 0.2) * 1024)
                    })
                    safe_total += int((size - 0.2) * 1024)
                break
            elif "M" in token:
                try:
                    size = float(token.replace("M", "").replace("s", "").replace("(", ""))
                    if size > 500:
                        recs.append({
                            "severity": "SAFE",
                            "category": "journal",
                            "message": f"Journal is {size:.0f}MB, vacuum to 200M",
                            "command": "journalctl --vacuum-size=200M",
                            "est_recover_mb": int(size - 200)
                        })
                        safe_total += int(size - 200)
                except ValueError:
                    pass
                break

    # apt cache
    apt = data.get("apt_cache", "")
    if apt and "/var/cache/apt" in apt:
        for line in apt.split("\n"):
            if "/var/cache/apt" in line:
                parts = line.split()
                for p in parts:
                    if "M" in p:
                        size = int(p.replace("M", ""))
                        if size > 10:
                            recs.append({
                                "severity": "SAFE",
                                "category": "apt-cache",
                                "message": f"apt cache is {size}MB",
                                "command": "sudo apt-get clean",
                                "est_recover_mb": size
                            })
                            safe_total += size

    # Backups
    backups = data.get("backups", "")
    if backups:
        count = len([l for l in backups.split("\n") if l.strip()])
        recs.append({
            "severity": "REVIEW",
            "category": "backups",
            "message": f"{count} backup file(s) found in /opt — review age before deleting",
            "command": "sudo find /opt -name '*.tar.gz' -o -name '*.bak' -mtime +7 -delete",
            "est_recover_mb": count * 500
        })

    # Old tmp files
    tmp = data.get("old_tmp", "")
    if tmp.strip():
        count = len([l for l in tmp.split("\n") if l.strip()])
        recs.append({
            "severity": "SAFE",
            "category": "tmp",
            "message": f"{count} file(s) in /tmp older than 24h",
            "command": "sudo find /tmp -type f -mtime +1 -delete",
            "est_recover_mb": count * 50
        })
        safe_total += count * 50

    return recs, safe_total


def format_report(data, recs, safe_total):
    """Format human-readable report."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"VPS DIAGNOSTIC REPORT — {data['host']}")
    lines.append(f"Time: {data['timestamp']}")
    lines.append("=" * 60)
    lines.append("")

    # Disk
    lines.append("--- DISK USAGE ---")
    lines.append(data.get("disk", "N/A"))
    lines.append("")

    # Memory
    lines.append("--- MEMORY ---")
    lines.append(data.get("memory", "N/A"))
    lines.append("")

    # Load
    lines.append("--- LOAD ---")
    lines.append(data.get("load", "N/A"))
    lines.append("")

    # Docker
    lines.append("--- DOCKER SYSTEM ---")
    lines.append(data.get("docker_df", "N/A"))
    lines.append("")

    # Top dirs
    lines.append("--- TOP DIRECTORIES BY SIZE ---")
    lines.append(data.get("top_dirs", "N/A"))
    lines.append("")

    # Containers
    lines.append("--- CONTAINER STATUS ---")
    for line in data.get("containers", "").split("\n"):
        if line.strip():
            parts = line.split("|")
            if len(parts) >= 2:
                name, status = parts[0], parts[1]
                icon = "UP" if "Up" in status or "running" in status else "DOWN"
                lines.append(f"  [{icon}] {name:40s} {status}")
    lines.append("")

    # Stopped containers
    stopped = data.get("stopped_containers", "").strip()
    if stopped:
        lines.append(f"--- STOPPED CONTAINERS ({len([l for l in stopped.split(chr(10)) if l.strip()])}) ---")
        lines.append(stopped)
        lines.append("")

    # Recommendations
    lines.append("=" * 60)
    lines.append("RECOMMENDATIONS")
    lines.append("=" * 60)
    lines.append("")

    safe_recs = [r for r in recs if r["severity"] == "SAFE"]
    review_recs = [r for r in recs if r["severity"] == "REVIEW"]
    warn_recs = [r for r in recs if r["severity"] == "WARNING"]

    if warn_recs:
        lines.append("WARNINGS:")
        for r in warn_recs:
            lines.append(f"  - {r['message']}")
        lines.append("")

    if safe_recs:
        lines.append(f"SAFE TO DELETE (estimated {safe_total} MB recoverable):")
        for r in safe_recs:
            est = f" ~{r.get('est_recover_mb', '?')}MB" if r.get("est_recover_mb") else ""
            lines.append(f"  [{r['category']}] {r['message']}{est}")
            lines.append(f"         cmd: {r['command']}")
        lines.append("")

    if review_recs:
        lines.append("REVIEW BEFORE DELETING:")
        for r in review_recs:
            lines.append(f"  [{r['category']}] {r['message']}")
            lines.append(f"         cmd: {r['command']}")
        lines.append("")

    lines.append(f"TOTAL SAFE RECOVERABLE: ~{safe_total} MB ({safe_total/1024:.1f} GB)")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="VPS Diagnostic Collector")
    parser.add_argument("--host", required=True, help="VPS hostname/IP")
    parser.add_argument("--user", required=True, help="SSH user")
    parser.add_argument("--password", help="SSH password")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    password = args.password
    if not password:
        env_path = os.path.expanduser("~/tollgate-infrastructure-kit/.env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    if "VPS2_PASSWORD" in line and "=" in line:
                        password = line.split("=", 1)[1].strip().strip('"')
                        break

    if not password:
        print("ERROR: No password provided and not found in .env", file=sys.stderr)
        sys.exit(1)

    print(f"Collecting diagnostics from {args.host}...", file=sys.stderr)
    data = collect_diagnostics(args.host, args.user, password)

    recs, safe_total = analyze(data)

    # Save state
    os.makedirs(STATE_DIR, exist_ok=True)
    state_file = os.path.join(STATE_DIR, f"vps_diag_{args.host.replace('.', '_')}.json")
    state = {"data": data, "recommendations": recs, "safe_total_mb": safe_total,
             "timestamp": data["timestamp"]}
    with open(state_file, "w") as f:
        json.dump(state, f, indent=2)

    if args.json:
        print(json.dumps(state, indent=2))
    else:
        print(format_report(data, recs, safe_total))

    # Exit 1 if there are warnings
    if any(r["severity"] == "WARNING" for r in recs):
        sys.exit(1)


if __name__ == "__main__":
    main()
