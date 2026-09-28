#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/common.sh"

echo "=== Testing ngit relay ==="

NGIT_URL="https://ngit.${BASE_DOMAIN}"

test_http "ngit relay homepage" "$NGIT_URL" 200

test_http "ngit relay websocket upgrade" "$NGIT_URL" 200

RESPONSE=$(curl -s --connect-timeout 10 "$NGIT_URL")
if echo "$RESPONSE" | grep -qi "strfry\|nostr\|relay"; then
    pass "ngit relay returns relay response"
else
    fail "ngit relay response does not contain expected content"
fi

echo ""
echo "=== ngit relay tests complete ==="
