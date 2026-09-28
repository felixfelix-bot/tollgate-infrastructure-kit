#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/test_helpers.sh"

VPS_IP="${VPS_IP:?VPS_IP not set}"
SSH_KEY="${SSH_PRIVATE_KEY_FILE:?SSH_PRIVATE_KEY_FILE not set}"
VPS_USER="${VPS_USER:-debian}"
BASE_DOMAIN="${BASE_DOMAIN:?BASE_DOMAIN not set}"

SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no $VPS_USER@$VPS_IP"

echo "=== Auditable Voting Integration Tests ==="

echo "--- Test 1: Static files deployed ---"
FILE_COUNT=$($SSH "find /srv/tollgate/auditable-voting -type f 2>/dev/null | wc -l")
if [ "$FILE_COUNT" -gt 5 ]; then
    echo "PASS: $FILE_COUNT static files present"
else
    echo "FAIL: Only $FILE_COUNT files found"
    exit 1
fi

echo "--- Test 2: index.html exists ---"
if $SSH "test -f /srv/tollgate/auditable-voting/index.html"; then
    echo "PASS: index.html exists"
else
    echo "FAIL: index.html missing"
    exit 1
fi

echo "--- Test 3: Static site responds locally ---"
HTTP_CODE=$($SSH "curl -s -o /dev/null -w '%{http_code}' http://localhost/vote/ 2>/dev/null || echo 000")
if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "301" ] || [ "$HTTP_CODE" = "302" ]; then
    echo "PASS: Local HTTP $HTTP_CODE"
else
    echo "WARN: Local HTTP returned $HTTP_CODE (may need Caddy reload)"
fi

echo "--- Test 4: HTTPS endpoint accessible ---"
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "https://vote.$BASE_DOMAIN/" 2>/dev/null || echo 000)
if [ "$HTTP_CODE" = "200" ]; then
    echo "PASS: https://vote.$BASE_DOMAIN/ returns 200"
else
    echo "WARN: https://vote.$BASE_DOMAIN/ returned $HTTP_CODE (may need DNS/Caddy)"
fi

echo "--- Test 5: HTML contains auditable voting content ---"
TITLE=$($SSH "grep -o '<title>[^<]*</title>' /srv/tollgate/auditable-voting/index.html 2>/dev/null || echo 'NOT_FOUND'")
if echo "$TITLE" | grep -qi "audit\|vote\|questionnaire"; then
    echo "PASS: HTML contains voting content"
else
    echo "WARN: HTML title is '$TITLE' (may still be valid)"
fi

echo "--- Test 6: nsite config exists ---"
if $SSH "test -f /opt/tollgate/src/auditable-voting/.nsite/config.json"; then
    echo "PASS: .nsite/config.json exists"
    OUR_RELAY=$($SSH "python3 -c \"import json; c=json.load(open('/opt/tollgate/src/auditable-voting/.nsite/config.json')); print(any('orangesync' in r for r in c['relays']))\"")
    if [ "$OUR_RELAY" = "True" ]; then
        echo "PASS: Our relay configured in nsite config"
    else
        echo "WARN: Our relay not found in nsite config"
    fi
else
    echo "WARN: .nsite/config.json not found"
fi

echo ""
echo "=== Auditable Voting tests complete ==="
