#!/usr/bin/env bash
# verify-ngit-ci-identity.sh <expected-hex-pubkey>
#
# Reads the newest kind-19843 coordinator advertisement from the index/outbox
# relays and asserts it is authored by the expected coordinator identity.
# Exit codes: 0 match, 1 mismatch, 2 unavailable (no advertisement / no nak).
set -euo pipefail

EXPECTED="${1:?usage: verify-ngit-ci-identity.sh <hex-pubkey>}"

if ! command -v nak >/dev/null 2>&1; then
    echo "nak not found; skipping coordinator identity verification" >&2
    exit 2
fi

RELAYS="wss://index.ngit.dev wss://relay.ngit.dev wss://gitnostr.com"

author="$(
    # shellcheck disable=SC2086
    nak req -k 19843 -l 100 $RELAYS 2>/dev/null | python3 -c '
import json
import sys

best = None
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("kind") != 19843:
        continue
    if best is None or event.get("created_at", 0) > best.get("created_at", 0):
        best = event
if best:
    print(best.get("pubkey", ""))
'
)"

if [ -z "$author" ]; then
    echo "no coordinator advertisement found on $RELAYS" >&2
    exit 2
fi

if [ "$author" = "$EXPECTED" ]; then
    echo "$author"
    exit 0
fi

echo "advertisement author $author != expected $EXPECTED" >&2
exit 1
