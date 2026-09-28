#!/usr/bin/env python3
"""Fetch follower list of anchor npub and output as hex pubkeys for blossom whitelist."""
import json, subprocess, sys, os

ANCHOR_NPUB = os.environ.get("BLOSSOM_ANCHOR_NPUB", "npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw")
RELAYS = os.environ.get("BLOSSOM_RELAYS", "wss://relay1.orangesync.tech wss://relay.damus.io wss://nos.lol").split()

def npub_to_hex(npub):
    r = subprocess.run(["nak", "decode", npub], capture_output=True, text=True)
    return r.stdout.strip()

def fetch_followers(hex_pubkey, relays):
    filt = json.dumps({"kinds": [3], "#p": [hex_pubkey]})
    relay_args = relays
    r = subprocess.run(
        ["nak", "req"] + relay_args,
        input=filt, capture_output=True, text=True, timeout=30
    )
    pubkeys = set()
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
            if evt.get("pubkey"):
                pubkeys.add(evt["pubkey"])
        except json.JSONDecodeError:
            continue
    return pubkeys

def main():
    hex_key = npub_to_hex(ANCHOR_NPUB)
    if not hex_key or len(hex_key) != 64:
        print(f"ERROR: could not decode {ANCHOR_NPUB}", file=sys.stderr)
        sys.exit(1)

    followers = fetch_followers(hex_key, RELAYS)
    followers.add(hex_key)  # always include anchor

    # Write to stdout
    print(f"# Blossom upload whitelist — {len(followers)} pubkeys", file=sys.stderr)
    print(f"# Anchor: {ANCHOR_NPUB} ({hex_key[:12]}...)")
    print(f"# Generated: $(date)")
    print(f"# Format: one hex pubkey per line, # for comments")
    for pk in sorted(followers):
        print(pk)

if __name__ == "__main__":
    main()
