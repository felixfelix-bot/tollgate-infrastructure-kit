#!/usr/bin/env python3
"""Generate machine status JSON with system resources + local service health.

Runs via systemd timer (every 10 seconds) and writes to the services dir.
Each VPS probes only its own local services (localhost, no CORS, instant).
Also publishes status as a Nostr kind 31998 parameterized replaceable event.
"""
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone

MACHINE_ID_FILE = "/etc/tollgate-machine-id"
STATS_DIR = "/srv/tollgate/services"
ENV_FILE = "/opt/tollgate/.env"
NOSTR_STATUS_KIND = 31998
NOSTR_STATUS_DTAG = "tollgate-vps-status"
NOSTR_PUB_RELAYS = [
    "wss://relay1.orangesync.tech",
    "wss://relay2.orangesync.tech",
]


def load_env():
    env = {}
    if not os.path.exists(ENV_FILE):
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10, check=False)
        return r.stdout.strip()
    except Exception:
        return ""


def get_machine_id():
    if os.path.exists(MACHINE_ID_FILE):
        with open(MACHINE_ID_FILE) as f:
            return f.read().strip()
    return os.uname().nodename


def probe_http(url, timeout=3):
    try:
        req = urllib.request.Request(url, method="GET")
        req.add_header("User-Agent", "tollgate-stats/1.0")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return {"healthy": True, "status": resp.status, "ms": 0}
    except urllib.error.HTTPError as e:
        return {"healthy": e.code < 500, "status": e.code, "ms": 0}
    except Exception:
        return {"healthy": False, "status": 0, "ms": 0}


def probe_tcp(host, port, timeout=2):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        start = time.monotonic()
        s.connect((host, port))
        s.close()
        ms = int((time.monotonic() - start) * 1000)
        return {"healthy": True, "ms": ms}
    except Exception:
        return {"healthy": False, "ms": 0}


def probe_docker_container(name):
    out = run(f"docker inspect --format '{{{{.State.Status}}}}' {name} 2>/dev/null")
    return {"healthy": out == "running", "status": out or "unknown"}


def probe_systemd(unit):
    out = run(f"systemctl is-active {unit} 2>/dev/null")
    return {"healthy": out == "active", "status": out or "unknown"}


def get_cpu():
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        fields = line.split()
        user, nice, system, idle = int(fields[1]), int(fields[2]), int(fields[3]), int(fields[4])
        iowait = int(fields[5]) if len(fields) > 5 else 0
        total = user + nice + system + idle + iowait
        used = user + nice + system
        return round(used / total * 100, 1) if total > 0 else 0.0
    except Exception:
        return 0.0


def get_load():
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
        return [float(parts[0]), float(parts[1]), float(parts[2])]
    except Exception:
        return [0.0, 0.0, 0.0]


def get_memory():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(":")
                val = int(parts[1])
                info[key] = val
        total = info.get("MemTotal", 0) * 1024
        available = info.get("MemAvailable", 0) * 1024
        used = total - available
        swap_total = info.get("SwapTotal", 0) * 1024
        swap_free = info.get("SwapFree", 0) * 1024
        swap_used = swap_total - swap_free
        return {
            "total_bytes": total,
            "used_bytes": used,
            "available_bytes": available,
            "percent": round(used / total * 100, 1) if total > 0 else 0.0,
            "swap_total_bytes": swap_total,
            "swap_used_bytes": swap_used,
            "swap_percent": round(swap_used / swap_total * 100, 1) if swap_total > 0 else 0.0,
        }
    except Exception:
        return {}


def get_disk():
    out = run("df -B1 / | tail -1")
    if not out:
        return {}
    parts = out.split()
    if len(parts) < 6:
        return {}
    total = int(parts[1])
    used = int(parts[2])
    avail = int(parts[3])
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": avail,
        "percent": round(used / total * 100, 1) if total > 0 else 0.0,
    }


def get_uptime():
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        mins = int((seconds % 3600) // 60)
        return {"seconds": seconds, "human": f"{days}d {hours}h {mins}m"}
    except Exception:
        return {}


def get_top_processes(n=10):
    out = run(f"ps aux --sort=-%mem | head -{n + 1}")
    if not out:
        return []
    lines = out.strip().split("\n")
    procs = []
    for line in lines[1:]:
        parts = line.split(None, 10)
        if len(parts) < 11:
            continue
        procs.append({
            "user": parts[0],
            "pid": parts[1],
            "cpu_pct": float(parts[2]),
            "mem_pct": float(parts[3]),
            "vsz_mb": round(int(parts[4]) / 1024, 1),
            "rss_mb": round(int(parts[5]) / 1024, 1),
            "command": parts[10][:80],
        })
    return procs


def get_docker():
    out = run("docker stats --no-stream --format '{{.Name}}\\t{{.CPUPerc}}\\t{{.MemUsage}}\\t{{.MemPerc}}' 2>/dev/null")
    if not out:
        return []
    containers = []
    for line in out.strip().split("\n"):
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        containers.append({
            "name": parts[0],
            "cpu_pct": parts[1],
            "mem_usage": parts[2],
            "mem_pct": parts[3],
        })
    return containers


def get_cpu_cores():
    try:
        return os.cpu_count() or 1
    except Exception:
        return 1


SERVICES_VPS1 = [
    {"name": "caddy",            "type": "http",  "url": "http://localhost:80"},
    {"name": "strfry",           "type": "tcp",   "host": "localhost", "port": 7777},
    {"name": "obelisk",          "type": "tcp",   "host": "localhost", "port": 8080},
    {"name": "blossom",          "type": "tcp",   "host": "localhost", "port": 3001},
    {"name": "nsite-gateway",    "type": "tcp",   "host": "localhost", "port": 3002},
    {"name": "releases",         "type": "http",  "url": "http://localhost/releases/"},
    {"name": "hive-ci",          "type": "http",  "url": "http://localhost/ci/"},
    {"name": "routstr",          "type": "http",  "url": "http://localhost:8000/v1/models"},
    {"name": "routstr-mint",     "type": "http",  "url": "http://localhost:8089/v1/info"},
    {"name": "ngit-relay",       "type": "tcp",   "host": "localhost", "port": 7778},
    {"name": "relatr",           "type": "http",  "url": "http://localhost:3000"},
    {"name": "fips",             "type": "tcp",   "host": "localhost", "port": 8443},
    {"name": "act-runner",       "type": "systemd", "unit": "tollgate-act-runner.service"},
    {"name": "cashu-brrr",       "type": "http",  "url": "http://localhost:3000"},
    {"name": "jitsi-meet",       "type": "http",  "url": "http://localhost:8090"},
    {"name": "bitcoin-core",     "type": "systemd", "unit": "bitcoind.service"},
    {"name": "syncthing",        "type": "systemd", "unit": "syncthing@syncthing.service"},
    {"name": "mint-testnut",     "type": "docker", "container": "mint-testnut"},
    {"name": "mint-routstr",     "type": "docker", "container": "mint-routstr-mint"},
    {"name": "mint-test-gb",     "type": "docker", "container": "mint-test-gb"},
    {"name": "mint-test-kb",     "type": "docker", "container": "mint-test-kb"},
    {"name": "mint-test-mb",     "type": "docker", "container": "mint-test-mb"},
    {"name": "mint-test-min",    "type": "docker", "container": "mint-test-min"},
    {"name": "routstr-tor",      "type": "docker", "container": "tollgate-routstr-tor"},
]

SERVICES_VPS2 = [
    {"name": "caddy",            "type": "http",  "url": "http://localhost:80"},
    {"name": "strfry",           "type": "tcp",   "host": "localhost", "port": 7777},
    {"name": "obelisk",          "type": "tcp",   "host": "localhost", "port": 8080},
    {"name": "blossom",          "type": "tcp",   "host": "localhost", "port": 3001},
    {"name": "nsite-gateway",    "type": "tcp",   "host": "localhost", "port": 3002},
    {"name": "ngit-relay",       "type": "tcp",   "host": "localhost", "port": 7778},
    {"name": "relatr",           "type": "http",  "url": "http://localhost:3000"},
    {"name": "fips",             "type": "tcp",   "host": "localhost", "port": 8443},
    {"name": "act-runner",       "type": "systemd", "unit": "tollgate-act-runner.service"},
    {"name": "cashu-brrr",       "type": "http",  "url": "http://localhost:3000"},
    {"name": "routstr",          "type": "http",  "url": "http://localhost:8000/v1/models"},
    {"name": "routstr-mint",     "type": "http",  "url": "http://localhost:8089/v1/info"},
    {"name": "jitsi-meet",       "type": "http",  "url": "http://localhost:8090"},
    {"name": "bitcoin-knots",    "type": "systemd", "unit": "bitcoind-knots.service"},
    {"name": "syncthing",        "type": "systemd", "unit": "syncthing@syncthing.service"},
    {"name": "grasp",            "type": "systemd", "unit": "ngit-grasp.service"},
    {"name": "grasp-mirror",     "type": "systemd", "unit": "grasp-mirror.service"},
    {"name": "voting-worker",    "type": "systemd", "unit": "tollgate-voting-worker.service"},
    {"name": "mint-testnut",     "type": "docker", "container": "mint-testnut"},
    {"name": "mint-routstr",     "type": "docker", "container": "mint-routstr-mint"},
    {"name": "mint-test-gb",     "type": "docker", "container": "mint-test-gb"},
    {"name": "mint-test-kb",     "type": "docker", "container": "mint-test-kb"},
    {"name": "mint-test-mb",     "type": "docker", "container": "mint-test-mb"},
    {"name": "mint-test-min",    "type": "docker", "container": "mint-test-min"},
    {"name": "nutshell-compat",  "type": "docker", "container": "nutshell-compat"},
    {"name": "nutshell-mint",    "type": "docker", "container": "nutshell-mint"},
    {"name": "routstr-tor",      "type": "docker", "container": "tollgate-routstr-tor"},
]

SERVICES_MAP = {
    "vps1": SERVICES_VPS1,
    "vps2": SERVICES_VPS2,
}


def probe_services(services):
    results = {}
    for svc in services:
        name = svc["name"]
        if svc["type"] == "http":
            results[name] = probe_http(svc["url"])
        elif svc["type"] == "tcp":
            results[name] = probe_tcp(svc["host"], svc["port"])
        elif svc["type"] == "docker":
            results[name] = probe_docker_container(svc["container"])
        elif svc["type"] == "systemd":
            results[name] = probe_systemd(svc["unit"])
    return results


PEER_FETCH = {
    "vps1": {"peer_id": "vps2", "peer_ip_env": "VPS2_IP"},
    "vps2": {"peer_id": "vps1", "peer_ip_env": "VPS_IP"},
}


def fetch_peer_status(machine_id):
    peer = PEER_FETCH.get(machine_id)
    if not peer:
        return
    env = load_env()
    peer_ip = env.get(peer["peer_ip_env"], os.environ.get(peer["peer_ip_env"], ""))
    if not peer_ip:
        return
    path = f"{peer['peer_id']}-status.json"
    url = f"https://services.orangesync.tech/{path}"
    try:
        cmd = f"curl -sk --resolve services.orangesync.tech:443:{peer_ip} --connect-timeout 5 --max-time 10 '{url}'"
        data = run(cmd)
        if not data:
            return
        d = json.loads(data)
        if d.get("machine_id") == peer["peer_id"]:
            peer_file = os.path.join(STATS_DIR, f"{peer['peer_id']}-status.json")
            tmp = peer_file + ".tmp"
            with open(tmp, "w") as f:
                f.write(data)
            os.replace(tmp, peer_file)
    except (json.JSONDecodeError, ValueError):
        pass
    except Exception:
        pass


def serialize_event(evt):
    return json.dumps(
        [0, evt['pubkey'], evt['created_at'], evt['kind'], evt['tags'], evt['content']],
        separators=(',', ':'),
    )


def sign_event(evt, nsec_hex):
    try:
        from coincurve import PrivateKey
    except ImportError:
        return None
    sk = PrivateKey(bytes.fromhex(nsec_hex))
    pubkey = sk.public_key.format(compressed=True)[1:].hex()
    evt['pubkey'] = pubkey
    serialized = serialize_event(evt)
    evt['id'] = hashlib.sha256(serialized.encode()).hexdigest()
    sig = sk.sign_schnorr(bytes.fromhex(evt['id']))
    evt['sig'] = sig.hex()
    return evt


def create_status_event(content_json_str, nsec_hex, machine_id):
    evt = {
        'kind': NOSTR_STATUS_KIND,
        'content': content_json_str,
        'tags': [
            ['d', NOSTR_STATUS_DTAG],
            ['t', 'tollgate-infrastructure'],
            ['t', machine_id],
            ['machine', machine_id],
        ],
        'created_at': int(time.time()),
    }
    return sign_event(evt, nsec_hex)


def publish_nostr_status(stats_json_str, nsec_hex):
    machine_id = stats_json_str and json.loads(stats_json_str).get("machine_id", "unknown")
    evt = create_status_event(stats_json_str, nsec_hex, machine_id)
    if evt is None:
        return
    try:
        import asyncio
        import websockets
    except ImportError:
        return

    async def _publish():
        payload = json.dumps(["EVENT", evt])
        for relay_url in NOSTR_PUB_RELAYS:
            try:
                async with websockets.connect(relay_url, max_size=2**20, close_timeout=3) as ws:
                    await ws.send(payload)
                    await asyncio.wait_for(ws.recv(), timeout=5)
            except Exception:
                pass

    try:
        asyncio.run(_publish())
    except Exception:
        pass


def main():
    machine_id = get_machine_id()
    services = SERVICES_MAP.get(machine_id, SERVICES_VPS1)

    stats = {
        "machine_id": machine_id,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hostname": os.uname().nodename,
        "cpu_cores": get_cpu_cores(),
        "cpu_percent": get_cpu(),
        "load": get_load(),
        "memory": get_memory(),
        "disk": get_disk(),
        "uptime": get_uptime(),
        "top_processes": get_top_processes(12),
        "docker_containers": get_docker(),
        "services": probe_services(services),
    }

    os.makedirs(STATS_DIR, exist_ok=True)
    output_file = os.path.join(STATS_DIR, f"{machine_id}-status.json")
    tmp = output_file + ".tmp"
    with open(tmp, "w") as f:
        json.dump(stats, f, indent=2)
    os.replace(tmp, output_file)

    fetch_peer_status(machine_id)

    env = load_env()
    nsec_hex = env.get("TOLLGATE_STATUS_NSEC_HEX", "")
    if nsec_hex:
        stats_json_str = json.dumps(stats, separators=(',', ':'))
        publish_nostr_status(stats_json_str, nsec_hex)

    for old_name in ["vps-stats.json"]:
        old_file = os.path.join(STATS_DIR, old_name)
        if os.path.exists(old_file):
            try:
                os.remove(old_file)
            except Exception:
                pass


if __name__ == "__main__":
    main()
