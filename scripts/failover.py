#!/usr/bin/env python3
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_DIR / ".env"
STATE_DIR = Path.home() / ".local" / "state" / "tollgate-failover"
STATE_FILE = STATE_DIR / "state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("tollgate-failover")


def load_env():
    env = {}
    if not ENV_FILE.exists():
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def load_state():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, ValueError):
            pass
    return {
        "failover_active": False,
        "active_vps": "vps-1",
        "failover_since": None,
        "last_action": None,
    }


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def ssh_cmd(host, user, password, command, key_file=None, timeout=30):
    cmd = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", f"ConnectTimeout={timeout}"]
    if key_file:
        cmd.extend(["-i", os.path.expanduser(key_file)])
    cmd.append(f"{user}@{host}")
    cmd.append(command)

    env = os.environ.copy()
    if password:
        cmd = ["sshpass", "-p", password] + cmd

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 30, env=env)
        if result.returncode != 0:
            log.error("SSH failed (%s@%s): %s", user, host, result.stderr[-300:])
            return False, result.stderr
        return True, result.stdout
    except subprocess.TimeoutExpired:
        log.error("SSH timed out (%s@%s)", user, host)
        return False, "timeout"


def cf_api(token, zone_id, method, path, data=None):
    import urllib.request
    import urllib.error

    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}{path}"
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        log.error("Cloudflare API error: %s %s", e.code, e.read().decode()[:200])
        return None
    except Exception as e:
        log.error("Cloudflare API error: %s", e)
        return None


def update_mints_dns(env, target_ip):
    token = env.get("CLOUDFLARE_API_TOKEN", "")
    zone_id = env.get("CLOUDFLARE_ZONE_ID", "")
    base_domain = env.get("BASE_DOMAIN", "orangesync.tech")
    mint_name = f"*.mints.{base_domain}"

    if not token or not zone_id:
        log.error("Missing Cloudflare credentials")
        return False

    result = cf_api(token, zone_id, "GET", f"/dns_records?name={mint_name}&type=A")
    if not result or not result.get("success"):
        log.error("Failed to find mint DNS record")
        return False

    records = result.get("result", [])
    if not records:
        log.error("No mint DNS record found")
        return False

    record = records[0]
    old_ip = record.get("content", "")
    if old_ip == target_ip:
        log.info("Mint DNS already points to %s", target_ip)
        return True

    record["content"] = target_ip
    update_result = cf_api(token, zone_id, "PUT", f"/dns_records/{record['id']}", record)
    if update_result and update_result.get("success"):
        log.info("Updated *.mints.%s: %s → %s", base_domain, old_ip, target_ip)
        return True
    return False


STANDBY_SERVICES = [
    ("systemd", "ngit-grasp", "sudo systemctl start ngit-grasp"),
    ("docker", "routstr", "cd /opt/tollgate/routstr && sudo docker compose up -d"),
    ("docker", "test-mb", "cd /opt/tollgate/mints/test-mb && sudo docker compose up -d"),
    ("docker", "test-kb", "cd /opt/tollgate/mints/test-kb && sudo docker compose up -d"),
    ("docker", "test-gb", "cd /opt/tollgate/mints/test-gb && sudo docker compose up -d"),
    ("docker", "test-min", "cd /opt/tollgate/mints/test-min && sudo docker compose up -d"),
    ("docker", "testnut", "cd /opt/tollgate/mints/testnut && sudo docker compose up -d"),
    ("docker", "routstr-mint", "cd /opt/tollgate/mints/routstr-mint && sudo docker compose up -d"),
    ("systemd", "act-runner", "sudo systemctl start tollgate-act-runner"),
]

STOP_COMMANDS = [
    ("systemd", "ngit-grasp", "sudo systemctl stop ngit-grasp"),
    ("docker", "routstr", "cd /opt/tollgate/routstr && sudo docker compose down"),
    ("docker", "test-mb", "cd /opt/tollgate/mints/test-mb && sudo docker compose down"),
    ("docker", "test-kb", "cd /opt/tollgate/mints/test-kb && sudo docker compose down"),
    ("docker", "test-gb", "cd /opt/tollgate/mints/test-gb && sudo docker compose down"),
    ("docker", "test-min", "cd /opt/tollgate/mints/test-min && sudo docker compose down"),
    ("docker", "testnut", "cd /opt/tollgate/mints/testnut && sudo docker compose down"),
    ("docker", "routstr-mint", "cd /opt/tollgate/mints/routstr-mint && sudo docker compose down"),
    ("systemd", "act-runner", "sudo systemctl stop tollgate-act-runner"),
]


def do_failover(env, dry_run=False):
    vps2_ip = env.get("VPS2_IP", "")
    vps2_user = env.get("VPS2_USER", "debian")
    vps2_pass = env.get("VPS2_PASSWORD", "")
    key_file = env.get("SSH_PRIVATE_KEY_FILE", "")

    if not vps2_ip:
        log.error("VPS2_IP not configured")
        return False

    log.info("=== FAILOVER: Activating standby on vps-2 (%s) ===", vps2_ip)

    for svc_type, name, cmd in STANDBY_SERVICES:
        log.info("Starting %s on vps-2: %s", name, cmd)
        if not dry_run:
            ok, _ = ssh_cmd(vps2_ip, vps2_user, vps2_pass, cmd, key_file)
            if not ok:
                log.warning("Failed to start %s (may not be deployed)", name)

    log.info("Updating DNS: *.mints → %s", vps2_ip)
    if not dry_run:
        update_mints_dns(env, vps2_ip)

    if not dry_run:
        state = load_state()
        state["failover_active"] = True
        state["active_vps"] = "vps-2"
        state["failover_since"] = datetime.now(timezone.utc).isoformat()
        state["last_action"] = "failover"
        save_state(state)

    log.info("Failover %s", "simulated" if dry_run else "complete")
    return True


def do_failback(env, dry_run=False):
    vps1_ip = env.get("VPS_IP", "")
    vps1_user = env.get("VPS_USER", "root")
    vps1_pass = env.get("VPS_PASSWORD", "")
    vps2_ip = env.get("VPS2_IP", "")
    vps2_user = env.get("VPS2_USER", "debian")
    vps2_pass = env.get("VPS2_PASSWORD", "")
    key_file = env.get("SSH_PRIVATE_KEY_FILE", "")

    log.info("=== FAILBACK: Restoring services to vps-1 (%s) ===", vps1_ip)

    if vps1_ip:
        for svc_type, name, cmd in STANDBY_SERVICES:
            log.info("Starting %s on vps-1: %s", name, cmd)
            if not dry_run:
                ok, _ = ssh_cmd(vps1_ip, vps1_user, vps1_pass, cmd, key_file)
                if not ok:
                    log.warning("Failed to start %s on vps-1", name)

    if vps2_ip:
        for svc_type, name, cmd in STOP_COMMANDS:
            log.info("Stopping %s on vps-2: %s", name, cmd)
            if not dry_run:
                ok, _ = ssh_cmd(vps2_ip, vps2_user, vps2_pass, cmd, key_file)
                if not ok:
                    log.warning("Failed to stop %s on vps-2", name)

    log.info("Restoring DNS: *.mints → %s", vps1_ip)
    if not dry_run:
        update_mints_dns(env, vps1_ip)

    if not dry_run:
        state = load_state()
        state["failover_active"] = False
        state["active_vps"] = "vps-1"
        state["failover_since"] = None
        state["last_action"] = "failback"
        save_state(state)

    log.info("Failback %s", "simulated" if dry_run else "complete")
    return True


def show_status(env):
    state = load_state()
    print(f"Failover active: {state.get('failover_active', False)}")
    print(f"Active VPS:      {state.get('active_vps', 'unknown')}")
    print(f"Since:           {state.get('failover_since', 'never')}")
    print(f"Last action:     {state.get('last_action', 'none')}")

    vps1_ip = env.get("VPS_IP", "")
    vps2_ip = env.get("VPS2_IP", "")
    if vps1_ip:
        ok, _ = ssh_cmd(vps1_ip, env.get("VPS_USER", "root"), env.get("VPS_PASSWORD", ""), "uptime", timeout=10)
        print(f"vps-1 ({vps1_ip}): {'REACHABLE' if ok else 'UNREACHABLE'}")
    if vps2_ip:
        ok, _ = ssh_cmd(vps2_ip, env.get("VPS2_USER", "debian"), env.get("VPS2_PASSWORD", ""), "uptime", timeout=10)
        print(f"vps-2 ({vps2_ip}): {'REACHABLE' if ok else 'UNREACHABLE'}")


def main():
    parser = argparse.ArgumentParser(description="TollGate VPS failover management")
    parser.add_argument("--failover", action="store_true", help="Activate standby on vps-2")
    parser.add_argument("--failback", action="store_true", help="Restore services to vps-1")
    parser.add_argument("--status", action="store_true", help="Show current failover state")
    parser.add_argument("--dry-run", action="store_true", help="Show what would happen")
    args = parser.parse_args()

    env = load_env()
    for k, v in env.items():
        os.environ.setdefault(k, v)

    if args.status:
        show_status(env)
    elif args.failover:
        do_failover(env, dry_run=args.dry_run)
    elif args.failback:
        do_failback(env, dry_run=args.dry_run)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
