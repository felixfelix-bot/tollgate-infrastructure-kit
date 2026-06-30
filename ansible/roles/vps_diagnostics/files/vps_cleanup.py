#!/usr/bin/env python3
"""
VPS Cleanup Executor — applies safe cleanup actions from a diagnostic report.
Only runs actions marked SAFE unless --include-review is passed.

Usage:
  python3 vps_cleanup.py --host 23.182.128.51 --user debian --password PASS --apply-safe-only
  python3 vps_cleanup.py --host 23.182.128.51 --user debian --password PASS --include-review
"""

import argparse
import json
import os
import subprocess
import sys

STATE_DIR = os.path.expanduser("~/.hermes/state")

SAFE_COMMANDS = [
    ("Dangling images", "docker image prune -f"),
    ("Stopped containers", "docker container prune -f"),
    ("Build cache", "docker builder prune -f"),
    ("apt cache", "sudo apt-get clean"),
    ("Journal vacuum", "sudo journalctl --vacuum-size=200M"),
    ("Old tmp files", "sudo find /tmp -type f -mtime +1 -delete"),
]

REVIEW_COMMANDS = [
    ("Old backups (>7d)", "sudo find /opt -name '*.tar.gz' -o -name '*.tar' -o -name '*.bak' -mtime +7 -delete"),
    ("Dangling volumes", "docker volume prune -f"),
]


def ssh_cmd(host, user, password, command, timeout=60):
    full_cmd = [
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        f"{user}@{host}",
        command
    ]
    try:
        result = subprocess.run(full_cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "TIMEOUT", -1


def main():
    parser = argparse.ArgumentParser(description="VPS Cleanup Executor")
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password")
    parser.add_argument("--apply-safe-only", action="store_true", dest="safe_only")
    parser.add_argument("--include-review", action="store_true")
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
        print("ERROR: No password", file=sys.stderr)
        sys.exit(1)

    # Get disk before
    before, _, _ = ssh_cmd(args.host, args.user, password, "df -h / | tail -1")
    print(f"BEFORE: {before}\n")

    commands = list(SAFE_COMMANDS)
    if args.include_review:
        commands.extend(REVIEW_COMMANDS)

    for name, cmd in commands:
        print(f"[{name}] Running: {cmd}")
        out, err, rc = ssh_cmd(args.host, args.user, password, cmd, timeout=120)
        if out:
            print(f"  {out}")
        if err and rc != 0:
            print(f"  WARNING: {err}")
        else:
            print(f"  OK")
        print()

    # Get disk after
    after, _, _ = ssh_cmd(args.host, args.user, password, "df -h / | tail -1")
    print(f"AFTER:  {after}")


if __name__ == "__main__":
    main()
