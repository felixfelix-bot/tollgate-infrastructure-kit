#!/usr/bin/env python3
import json
import logging
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import urllib.request
import urllib.error

WATCHDOG_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = WATCHDOG_DIR / "scripts" / "watchdog.json"
ANSIBLE_DIR = WATCHDOG_DIR / "ansible"
ENV_FILE = WATCHDOG_DIR / ".env"
STATE_DIR = Path.home() / ".local" / "state" / "tollgate-watchdog"
LOG_DIR = Path.home() / ".local" / "log"
STATE_FILE = STATE_DIR / "state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "watchdog.log", mode="a"),
    ],
)
log = logging.getLogger("tollgate-watchdog")


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
            log.warning("Corrupted state file — resetting")
    return {"last_redeploy": {}}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def check_ssh(host, port, timeout):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError):
        return False


def check_http(url, timeout):
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "tollgate-watchdog/1.0")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def run_ansible(playbook, env_vars, limit_host=None):
    playbook_path = ANSIBLE_DIR / "playbooks" / playbook
    if not playbook_path.exists():
        log.error("Playbook not found: %s", playbook)
        return False

    cmd = [
        "ansible-playbook",
        str(playbook_path),
        "-i", str(ANSIBLE_DIR / "inventory" / "hosts.yml"),
    ]
    if limit_host:
        cmd.extend(["--limit", limit_host])

    env = os.environ.copy()
    env.update(env_vars)

    log.info("Running ansible-playbook %s (limit=%s)", playbook, limit_host or "none")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ANSIBLE_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
        if result.returncode == 0:
            log.info("Playbook %s succeeded", playbook)
            return True
        else:
            log.error("Playbook %s failed (rc=%d): %s", playbook, result.returncode, result.stderr[-500:])
            return False
    except subprocess.TimeoutExpired:
        log.error("Playbook %s timed out", playbook)
        return False


def render_url(template, env):
    url = template
    for key, val in env.items():
        url = url.replace("{{ " + key + " }}", val)
    return url


def get_machine_ssh_host(machine_cfg, env):
    return env.get(machine_cfg.get("ssh_host_env", ""), "")


def _check_failover(state, machines, machine_ssh_status, env, threshold, failover_cfg):
    failover_active = state.get("failover_active", False)
    auto_failback = failover_cfg.get("auto_failback", False)

    vps1_down = state.get("vps_down_count", {}).get("vps-1", 0)
    vps1_reachable = machine_ssh_status.get("vps-1", False)

    if not failover_active and vps1_down >= threshold and machine_ssh_status.get("vps-2", False):
        log.warning("VPS-1 down %d consecutive checks — triggering failover to VPS-2", vps1_down)
        try:
            result = subprocess.run(
                [sys.executable, str(WATCHDOG_DIR / "scripts" / "failover.py"), "--failover"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, **env},
            )
            if result.returncode == 0:
                state["failover_active"] = True
                state["active_vps"] = "vps-2"
                state["failover_since"] = datetime.now(timezone.utc).isoformat()
                state["last_action"] = "failover"
                save_state(state)
                log.info("Failover to VPS-2 completed successfully")
            else:
                log.error("Failover script failed: %s", result.stderr[-300:])
        except Exception as e:
            log.error("Failover script error: %s", e)

    if failover_active and auto_failback and vps1_reachable:
        log.info("VPS-1 recovered — auto-failback enabled, triggering failback")
        try:
            result = subprocess.run(
                [sys.executable, str(WATCHDOG_DIR / "scripts" / "failover.py"), "--failback"],
                capture_output=True, text=True, timeout=300,
                env={**os.environ, **env},
            )
            if result.returncode == 0:
                state["failover_active"] = False
                state["active_vps"] = "vps-1"
                state["failover_since"] = None
                state["last_action"] = "failback"
                save_state(state)
                log.info("Failback to VPS-1 completed")
            else:
                log.error("Failback script failed: %s", result.stderr[-300:])
        except Exception as e:
            log.error("Failback script error: %s", e)


def check_cycle(config, env, context, state, ssh_timeout, http_timeout, cooldown, run_redeploy=True):
    now = time.time()
    machines = config.get("machines", {})
    services = config.get("services", [])
    failover_cfg = config.get("failover", {})
    detection_threshold = failover_cfg.get("detection_threshold", 3)

    machine_ssh_status = {}
    for mid, mcfg in machines.items():
        host = get_machine_ssh_host(mcfg, env)
        if not host:
            machine_ssh_status[mid] = False
            log.warning("Machine %s: no SSH host configured", mid)
            continue
        ok = check_ssh(host, 22, ssh_timeout)
        machine_ssh_status[mid] = ok
        if ok:
            log.info("Machine %s (%s): SSH OK", mid, host)
            state.setdefault("vps_down_count", {})[mid] = 0
        else:
            state.setdefault("vps_down_count", {})[mid] = state.get("vps_down_count", {}).get(mid, 0) + 1
            log.warning("Machine %s (%s): SSH UNREACHABLE (count: %d)", mid, host, state["vps_down_count"][mid])

    save_state(state)

    if run_redeploy:
        _check_failover(state, machines, machine_ssh_status, env, detection_threshold, failover_cfg)

    results = {}
    down_services = []

    for svc in services:
        name = svc["name"]
        mid = svc.get("machine", "vps-1")
        url = render_url(svc["url"], context)
        healthy = check_http(url, http_timeout)
        results[name] = {"healthy": healthy, "url": url, "machine": mid}

        if not healthy:
            if not machine_ssh_status.get(mid, False):
                log.warning("Service %s DOWN (%s) — machine %s SSH unreachable, cannot redeploy", name, url, mid)
                continue

            last_ts = state["last_redeploy"].get(name, 0)
            elapsed = now - last_ts
            if elapsed < cooldown:
                log.warning("Service %s DOWN (%s) — cooling down (%ds/%ds)", name, url, int(elapsed), cooldown)
                continue
            down_services.append(svc)
            log.warning("Service %s DOWN — %s (machine: %s)", name, url, mid)
        else:
            log.info("Service %s OK — %s", name, url)

    redeployed = []
    if down_services and run_redeploy:
        redeploy_keys = []
        for svc in down_services:
            mid = svc.get("machine", "vps-1")
            pb = svc["playbook"]
            key = (mid, pb)
            if key not in redeploy_keys:
                redeploy_keys.append(key)

        for mid, pb in redeploy_keys:
            mcfg = machines.get(mid, {})
            ssh_host = get_machine_ssh_host(mcfg, env)
            ssh_user = env.get(mcfg.get("ssh_user_env", "VPS_USER"), "debian")
            ssh_key = os.path.expanduser(env.get(mcfg.get("ssh_key_env", "SSH_PRIVATE_KEY_FILE"), "~/.ssh/id_ed25519"))
            ansible_host = mcfg.get("ansible_host", "")

            affected = [s["name"] for s in down_services if s.get("machine", "m1") == mid and s["playbook"] == pb]
            log.info("Redeploying %s on %s for: %s", pb, mid, ", ".join(affected))

            ansible_env = {
                "VPS_IP": env.get("VPS_IP", ""),
                "VPS_USER": env.get("VPS_USER", "root"),
                "SSH_PRIVATE_KEY_FILE": ssh_key,
                "VPS2_IP": env.get("VPS2_IP", ""),
                "VPS2_USER": env.get("VPS2_USER", "debian"),
                "VPS2_PASSWORD": env.get("VPS2_PASSWORD", ""),
                "BASE_DOMAIN": context.get("base_domain", ""),
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            }
            for k, v in env.items():
                if k not in ansible_env:
                    ansible_env[k] = v

            limit = ansible_host if ansible_host else None
            success = run_ansible(pb, ansible_env, limit_host=limit)

            for svc in down_services:
                if svc.get("machine", "m1") == mid and svc["playbook"] == pb:
                    state["last_redeploy"][svc["name"]] = now
                    if success:
                        redeployed.append(svc["name"])
            save_state(state)

        for svc in down_services:
            url = render_url(svc["url"], context)
            healthy = check_http(url, http_timeout)
            status = "RECOVERED" if healthy else "STILL DOWN"
            log.info("Service %s: %s after redeploy", svc["name"], status)

    return {"machines": {mid: {"ssh": ok} for mid, ok in machine_ssh_status.items()}, "services": results, "redeployed": redeployed}


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    run_once = "--once" in sys.argv or "check" in sys.argv
    dry_run = "--dry-run" in sys.argv

    env = load_env()
    for k, v in env.items():
        os.environ.setdefault(k, v)

    base_domain = env.get("BASE_DOMAIN", "orangesync.tech")

    with open(CONFIG_PATH) as f:
        config = json.load(f)

    check_interval = config.get("check_interval", 120)
    ssh_timeout = config.get("ssh_timeout", 10)
    http_timeout = config.get("http_timeout", 10)
    cooldown = config.get("cooldown", 600)

    context = {"base_domain": base_domain}
    state = load_state()

    machines = config.get("machines", {})
    svc_count = len(config.get("services", []))
    log.info("Watchdog started — interval=%ds, cooldown=%ds, %d services, %d machines", check_interval, cooldown, svc_count, len(machines))

    if run_once or dry_run:
        result = check_cycle(config, env, context, state, ssh_timeout, http_timeout, cooldown, run_redeploy=not dry_run)
        print(json.dumps(result, indent=2))
        all_ssh_ok = all(m.get("ssh", False) for m in result.get("machines", {}).values())
        sys.exit(0 if all_ssh_ok else 1)

    while True:
        try:
            check_cycle(config, env, context, state, ssh_timeout, http_timeout, cooldown, run_redeploy=True)
        except Exception as e:
            log.error("Check cycle error: %s", e)
        time.sleep(check_interval)


if __name__ == "__main__":
    main()
