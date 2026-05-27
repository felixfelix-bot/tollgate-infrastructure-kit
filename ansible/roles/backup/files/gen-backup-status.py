#!/usr/bin/env python3
"""Generate backup-status.json from syncthing API.

Reports per-folder completion for each remote device, plus local file counts/sizes.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

API = "http://127.0.0.1:8384"
CONFIG_XML = "/var/lib/syncthing/.config/syncthing/config.xml"
STATUS_FILE = "/srv/tollgate/services/backup-status.json"


def api_call(path, api_key):
    try:
        r = subprocess.run(
            ["curl", "-sf", f"{API}{path}", "-H", f"X-API-Key: {api_key}"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception:
        return {}


def get_api_key():
    try:
        r = subprocess.run(
            ["grep", "-oP", "(?<=<apikey>)[^<]+", CONFIG_XML],
            capture_output=True, text=True, check=False,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def human_size(n):
    if n < 1024:
        return f"{n}B"
    if n < 1024 * 1024:
        return f"{n/1024:.0f}KB"
    if n < 1024 * 1024 * 1024:
        return f"{n/(1024*1024):.1f}MB"
    return f"{n/(1024*1024*1024):.1f}GB"


def main():
    key = get_api_key()
    if not key:
        print("ERROR: no API key", file=sys.stderr)
        sys.exit(1)

    folders_raw = api_call("/rest/config/folders", key)
    devices_raw = api_call("/rest/config/devices", key)

    devices = {}
    for d in devices_raw:
        did = d.get("deviceID", "")
        name = d.get("name", did[:8])
        if did == devices_raw[0].get("deviceID", ""):
            continue
        devices[did] = {"name": name, "connected": d.get("connected", False)}

    overall = "synced"
    folders = {}

    for f in folders_raw:
        fid = f.get("id", "")
        if not fid.startswith("orangesync-"):
            continue
        label = f.get("label", fid)

        status = api_call(f"/rest/db/status?folder={fid}", key)
        local_files = status.get("localFiles", 0)
        local_bytes = status.get("localBytes", 0)

        folder_entry = {
            "label": label,
            "completion": 100,
            "state": "synced",
            "local_files": local_files,
            "local_size": local_bytes,
            "local_size_human": human_size(local_bytes),
            "machines": {},
        }

        for did, dinfo in devices.items():
            comp = api_call(f"/rest/db/completion?folder={fid}&device={did}", key)
            pct = int(comp.get("completion", 0))
            need_bytes = comp.get("needBytes", 0)
            global_items = comp.get("globalItems", 0)
            global_bytes = comp.get("globalBytes", 0)

            if pct >= 100:
                state = "synced"
            elif pct > 0:
                state = "syncing"
                overall = "syncing"
            else:
                state = "problem"
                overall = "problem"

            if state != "synced":
                folder_entry["completion"] = min(folder_entry["completion"], pct)
                folder_entry["state"] = state

            folder_entry["machines"][dinfo["name"]] = {
                "completion": pct,
                "state": state,
                "connected": dinfo["connected"],
                "global_items": global_items,
                "global_size_human": human_size(global_bytes),
                "need_size_human": human_size(need_bytes),
            }

        folders[fid] = folder_entry

    hostname = os.uname().nodename
    status = {
        "last_backup": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "overall_status": overall,
        "source_host": hostname,
        "machines": {dinfo["name"]: {"connected": dinfo["connected"]} for dinfo in devices.values()},
        "folders": folders,
    }

    tmp = STATUS_FILE + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(status, fh, indent=2)
    os.replace(tmp, STATUS_FILE)
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
