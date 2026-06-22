#!/usr/bin/env python3
"""Triage enriched follow dossiers into named sets via an LLM (ppq.ai).

Reads follows-enriched.jsonl + a rubric, batches the dossiers to an
OpenAI-compatible chat API (ppq.ai by default), and writes triage.json:
each pubkey assigned to a set with a rationale and a suggested petname.

Usage:
    follow-triage.py follows-enriched.jsonl --rubric rubric.txt --out triage.json

Env:
    PPQ_API_KEY    ppq_...   (required)
    PPQ_BASE_URL   default https://api.ppq.ai
    PPQ_MODEL      default gpt-5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error

DEFAULT_BASE = "https://api.ppq.ai"
DEFAULT_MODEL = "gpt-5"

SYSTEM_PROMPT = """You are a Nostr social-graph triage assistant. The user will
give you a set of followed npubs as dossiers (profile + recent note samples +
activity) and a rubric describing what they want more/less of. You will:

1. Assign each pubkey to exactly ONE named set. Use descriptive set names that
   reflect real clusters (e.g. "bitcoin-builders", "nostr-infra", "cashu-ecosystem",
   "content-creators", "mutuals-and-friends", "inactive", "low-signal", "spammy").
   Choose the set names that best fit THIS data; do not force a fixed taxonomy.
2. Recommend a disposition per pubkey: "keep", "borderline", or "purge".
3. Suggest a short petname (lowercase, <=20 chars) for keeps/borderlines, derived
   from display name / handle / topic. Omit for purges.
4. Give a one-sentence rationale grounded in the dossier.

Return STRICT JSON only: an object with "sets" mapping set_name -> array of
entries, where each entry is {"pubkey","name","disposition","petname","reason"}.
Do not include prose outside the JSON."""


def chat(messages: list[dict], model: str, base: str, key: str, timeout: int = 120) -> str:
    payload = json.dumps({"model": model, "messages": messages, "temperature": 0.3}).encode()
    req = urllib.request.Request(
        f"{base.rstrip('/')}/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


def dossier_to_text(rec: dict) -> str:
    notes = rec.get("notes") or []
    notes_blob = " || ".join(n["content"][:160] for n in notes[:6])
    return (
        f"pubkey={rec['pubkey']}\n"
        f"name={rec.get('name','')}\n"
        f"nip05={rec.get('nip05','')}\n"
        f"about={(rec.get('about') or '')[:200]}\n"
        f"recent_notes_sampled={rec.get('note_count_sampled',0)}\n"
        f"notes={notes_blob}"
    )


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)
        text = text[1] if len(text) >= 2 else text[0]
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {}
    return json.loads(text[start : end + 1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("enriched", help="follows-enriched.jsonl")
    ap.add_argument("--rubric", required=True, help="text file with seek/avoid criteria")
    ap.add_argument("--out", default="triage.json")
    ap.add_argument("--batch", type=int, default=40, help="dossiers per LLM call")
    ap.add_argument("--model", default=os.environ.get("PPQ_MODEL", DEFAULT_MODEL))
    ap.add_argument("--base", default=os.environ.get("PPQ_BASE_URL", DEFAULT_BASE))
    args = ap.parse_args()

    key = os.environ.get("PPQ_API_KEY", "")
    if not key:
        print("ERROR: set PPQ_API_KEY env var (ppq_...)", file=sys.stderr)
        return 2

    rubric = open(args.rubric).read().strip()
    records = [json.loads(line) for line in open(args.enriched) if line.strip()]
    print(f"[triage] {len(records)} dossiers, batch={args.batch}", file=sys.stderr)

    merged: dict[str, list[dict]] = {}
    for i in range(0, len(records), args.batch):
        chunk = records[i : i + args.batch]
        user_msg = (
            f"RUBRIC:\n{rubric}\n\n"
            f"DOSSIERS ({len(chunk)}):\n"
            + "\n---\n".join(dossier_to_text(r) for r in chunk)
            + "\n\nReturn JSON now."
        )
        print(f"[triage] batch {i//args.batch + 1} ({len(chunk)} dossiers)...", file=sys.stderr)
        try:
            raw = chat(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                args.model,
                args.base,
                key,
            )
            parsed = extract_json(raw)
        except Exception as exc:
            print(f"[triage] batch {i} failed: {exc}", file=sys.stderr)
            continue
        for set_name, entries in (parsed.get("sets") or {}).items():
            merged.setdefault(set_name, []).extend(entries)
        time.sleep(1)

    with open(args.out, "w") as f:
        json.dump({"sets": merged}, f, indent=2, ensure_ascii=False)
    total = sum(len(v) for v in merged.values())
    print(f"[triage] wrote {args.out} ({total} entries in {len(merged)} sets)", file=sys.stderr)
    for name, entries in sorted(merged.items()):
        keeps = sum(1 for e in entries if e.get("disposition") == "keep")
        print(f"  {name}: {len(entries)} ({keeps} keep)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
