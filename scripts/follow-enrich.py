#!/usr/bin/env python3
"""Enrich a pubkey's follow list into triage dossiers.

Reads a list of hex pubkeys (one per line) and writes follows-enriched.jsonl
with, per pubkey: profile, recent notes sample, and (optionally) follow-pack
memberships + mutuals overlap. Uses `nak` for all Nostr I/O.

Usage:
    follow-enrich.py <follows.hex> [--with-packs] [--with-mutuals] [--limit N]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

RELAYS = [
    "wss://relay.damus.io",
    "wss://nos.lol",
    "wss://relay.primal.net",
    "wss://pyramid.fiatjaf.com",
]


def nak_req(filter_obj: dict, limit: int = 0, timeout: int = 120) -> list[dict]:
    cmd = ["nak", "req"]
    if limit:
        cmd += ["-l", str(limit)]
    cmd += RELAYS
    try:
        r = subprocess.run(
            cmd, input=json.dumps(filter_obj), capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return []
    out = []
    for line in (r.stdout or "").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_pubkeys(path: str) -> list[str]:
    pks = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            pks.append(line)
    return pks


def fetch_profiles(pubkeys: list[str]) -> dict[str, dict]:
    newest: dict[str, tuple[int, dict]] = {}
    for i in range(0, len(pubkeys), 150):
        chunk = pubkeys[i : i + 150]
        for e in nak_req({"kinds": [0], "authors": chunk}, limit=400, timeout=90):
            pk = e.get("pubkey")
            if not pk:
                continue
            try:
                meta = json.loads(e.get("content", "{}"))
            except json.JSONDecodeError:
                meta = {}
            if pk not in newest or e.get("created_at", 0) > newest[pk][0]:
                newest[pk] = (e.get("created_at", 0), meta)
    return {pk: meta for pk, (_, meta) in newest.items()}


def fetch_notes(pubkeys: list[str], per_author: int = 8) -> dict[str, list[dict]]:
    by_author: dict[str, list[dict]] = {pk: [] for pk in pubkeys}
    target = len(pubkeys) * per_author
    for i in range(0, len(pubkeys), 150):
        chunk = pubkeys[i : i + 150]
        evs = nak_req({"kinds": [1], "authors": chunk}, limit=target, timeout=120)
        evs.sort(key=lambda e: e.get("created_at", 0), reverse=True)
        for e in evs:
            pk = e.get("pubkey")
            if pk in by_author and len(by_author[pk]) < per_author:
                content = (e.get("content") or "").strip()
                if content and not content.startswith("nostr:"):
                    by_author[pk].append(
                        {"ts": e.get("created_at", 0), "content": content[:400]}
                    )
    return by_author


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("follows", help="file with hex pubkeys, one per line")
    ap.add_argument("--per-author", type=int, default=8)
    ap.add_argument("--out", default="follows-enriched.jsonl")
    args = ap.parse_args()

    pubkeys = load_pubkeys(args.follows)
    print(f"[enrich] {len(pubkeys)} pubkeys", file=sys.stderr)

    print("[enrich] fetching profiles...", file=sys.stderr)
    profiles = fetch_profiles(pubkeys)
    print(f"[enrich] {len(profiles)} profiles resolved", file=sys.stderr)

    print(f"[enrich] fetching ~{args.per_author} notes/author...", file=sys.stderr)
    notes = fetch_notes(pubkeys, per_author=args.per_author)
    have_notes = sum(1 for v in notes.values() if v)
    print(f"[enrich] {have_notes} authors with notes", file=sys.stderr)

    with open(args.out, "w") as f:
        for pk in pubkeys:
            meta = profiles.get(pk, {})
            rec = {
                "pubkey": pk,
                "name": meta.get("display_name") or meta.get("name") or "",
                "nip05": meta.get("nip05", ""),
                "about": (meta.get("about") or "")[:300],
                "picture": meta.get("picture", ""),
                "note_count_sampled": len(notes.get(pk, [])),
                "notes": notes.get(pk, []),
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"[enrich] wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
