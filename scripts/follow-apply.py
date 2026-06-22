#!/usr/bin/env python3
"""Apply a triage result: publish a curated kind-3 of only the keep-set.

Reads triage.json (from follow-triage.py) plus optionally enriched relay hints,
builds a new kind-3 with the keep dispositions only (each p-tag carrying a relay
hint + petname), and publishes it via nak + Amber (NIP-46 bunker).

A backup of the current kind-3 is written first.

Usage:
    follow-apply.py triage.json --user-npub <npub> [--bunker bunker://...] [--dry-run]

Env:
    AMBER_BUNKER   bunker://...   (or pass --bunker)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

RELAYS = ["wss://relay.damus.io", "wss://nos.lol", "wss://relay.orangesync.tech"]


def nak(cmd: list[str], stdin: str | None = None, timeout: int = 60) -> str:
    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("triage", help="triage.json from follow-triage.py")
    ap.add_argument("--user-npub", required=True)
    ap.add_argument("--bunker", default=os.environ.get("AMBER_BUNKER", ""))
    ap.add_argument("--backup", default="follows-backup.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--also-fetch-relays", action="store_true",
                    help="fetch each keeper's kind-10002 for accurate relay hints")
    args = ap.parse_args()

    triage = json.load(open(args.triage))
    keepers: list[dict] = []
    for entries in triage.get("sets", {}).values():
        for e in entries:
            if e.get("disposition") == "keep":
                keepers.append(e)
    keepers = [{k: e[k] for k in ("pubkey", "petname") if k in e} for e in keepers]
    print(f"[apply] {len(keepers)} keepers", file=sys.stderr)

    cur_k3 = nak(
        ["nak", "req", "-k", "3", "-a", args.user_npub, "-l", "1"] + RELAYS,
        timeout=30,
    ).strip()
    Path(args.backup).write_text(cur_k3 or "{}")
    print(f"[apply] backed up current kind-3 -> {args.backup}", file=sys.stderr)

    relay_hints: dict[str, str] = {}
    if args.also_fetch_relays:
        print("[apply] fetching relay hints for keepers...", file=sys.stderr)
        for k in keepers:
            pk = k["pubkey"]
            ev = nak(["nak", "req", "-k", "10002", "-a", pk, "-l", "1"] + RELAYS, timeout=20)
            hint = RELAYS[0]
            for line in ev.splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for t in e.get("tags", []):
                    if t and t[0] == "r" and len(t) >= 2 and t[1].startswith("wss://"):
                        hint = t[1]
                        break
                if hint != RELAYS[0]:
                    break
            relay_hints[pk] = hint

    tags = []
    for k in keepers:
        pk = k["pubkey"]
        petname = k.get("petname", "")
        relay = relay_hints.get(pk, RELAYS[0])
        tags.append(["p", pk, relay, petname])

    new_event = json.dumps({"tags": tags})
    print(f"[apply] new kind-3 has {len(tags)} follows", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(json.loads(new_event), indent=2))
        print(f"[apply] dry-run only; {len(tags)} follows would be published", file=sys.stderr)
        return 0

    if not args.bunker:
        print("ERROR: set AMBER_BUNKER or pass --bunker (bunker://...)", file=sys.stderr)
        return 2

    print("[apply] publishing via Amber (approve on your phone)...", file=sys.stderr)
    result = nak(
        ["nak", "event", "-k", "3", "-c", "{}", "--sec", args.bunker] + RELAYS,
        stdin=new_event,
        timeout=120,
    )
    print(result.strip(), file=sys.stderr)
    print(f"[apply] done — agg relay will reconcile to {len(tags)} follows within 15 min", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
