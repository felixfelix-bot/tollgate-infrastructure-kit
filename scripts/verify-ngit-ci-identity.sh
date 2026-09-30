#!/usr/bin/env bash
# verify-ngit-ci-identity.sh <expected-hex-pubkey> [freshness-window-seconds]
#
# Asserts that the expected coordinator has published a kind-19843 coordinator
# advertisement recently. Many coordinators share the index relay, so this checks
# for a *fresh ad by the expected author*, not for the newest ad overall.
#
# Exit codes: 0 fresh ad found, 1 missing/stale, 2 unavailable (no nak/relay).
set -euo pipefail

EXPECTED="${1:?usage: verify-ngit-ci-identity.sh <hex-pubkey> [window-s]}"
WINDOW="${2:-2400}"

if ! command -v nak >/dev/null 2>&1; then
    echo "nak not found; skipping coordinator identity verification" >&2
    exit 2
fi

RELAYS="wss://index.ngit.dev wss://relay.ngit.dev wss://gitnostr.com"
NOW="$(date +%s)"

result="$(
    # shellcheck disable=SC2086
    nak req -k 19843 -l 200 $RELAYS 2>/dev/null | \
    EXPECTED="$EXPECTED" WINDOW="$WINDOW" NOW="$NOW" python3 -c '
import json
import os
import sys

expected = os.environ["EXPECTED"]
window = int(os.environ["WINDOW"])
now = int(os.environ["NOW"])

newest = 0
for line in sys.stdin:
    line = line.strip()
    if not line.startswith("{"):
        continue
    try:
        event = json.loads(line)
    except ValueError:
        continue
    if event.get("kind") != 19843 or event.get("pubkey") != expected:
        continue
    newest = max(newest, int(event.get("created_at", 0)))

if newest == 0:
    print("no advertisement by %s" % expected, file=sys.stderr)
    sys.exit(1)

age = now - newest
print("%s (age %ds)" % (expected, age))
if age > window:
    print("advertisement is stale (age %ds > %ds)" % (age, window), file=sys.stderr)
    sys.exit(1)
'
)"

if [ -n "$result" ]; then
    echo "$result"
fi
