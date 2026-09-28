#!/bin/bash
set -euo pipefail

DB="{{ tollgate_base_dir | default('/opt/tollgate') }}/relatr/data/relatr.db"
THRESHOLD="{{ relatr_trust_threshold | default(0.1) }}"

if [ ! -f "$DB" ]; then
    echo "accept"
    exit 0
fi

INPUT=$(cat)

EVENT_ID=$(echo "$INPUT" | jq -r '.id // empty' 2>/dev/null || true)
PUBKEY=$(echo "$INPUT" | jq -r '.pubkey // empty' 2>/dev/null || true)
KIND=$(echo "$INPUT" | jq -r '.kind // empty' 2>/dev/null || true)

if [ -z "$PUBKEY" ] || [ -z "$EVENT_ID" ]; then
    echo "reject"
    exit 0
fi

TRUST=$(duckdb "$DB" -noheader -list -c "
    SELECT COALESCE(
        (SELECT latest_rank / 100.0 FROM ta WHERE pubkey = '$PUBKEY'),
        (SELECT CASE WHEN distance IS NOT NULL THEN 1.0 / (1.0 + distance * $(echo "$THRESHOLD" | awk '{print 1/$1}')) ELSE 0.0 END FROM pubkey_distances WHERE pubkey = '$PUBKEY' LIMIT 1),
        0.0
    ) AS trust
" 2>/dev/null || echo "0.0")

if [ "$(echo "$TRUST >= $THRESHOLD" | bc -l 2>/dev/null || echo 1)" = "1" ]; then
    echo "accept"
else
    echo "reject"
fi
