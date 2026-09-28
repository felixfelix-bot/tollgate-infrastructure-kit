#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"

echo "Testing cross-service connectivity..."
PASS=0
FAIL=0

echo ""
echo "WebSocket test (strfry relay):"
echo -n "  wss connection ... "
ws_result=$(ssh "$VPS" "echo '[\"REQ\",\"test\",{\"limit\":1}]' | timeout 5 websocat -1 ws://localhost:7777 2>/dev/null || echo 'FAIL'")
if echo "$ws_result" | grep -q "EVENT\|EOSE"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL (no relay response)"
    ((FAIL++))
fi

echo ""
echo "Caddy proxy test (HTTP to backend):"
for path in "blossom" "nsite"; do
    echo -n "  /$path via Caddy ... "
    code=$(ssh "$VPS" "curl -s -o /dev/null -w '%{http_code}' --resolve ${path}.${BASE_DOMAIN}:80:127.0.0.1 http://${path}.${BASE_DOMAIN}/ 2>/dev/null || echo '000'")
    if [[ "$code" != "000" ]]; then
        echo "OK (HTTP $code)"
        ((PASS++))
    else
        echo "FAIL"
        ((FAIL++))
    fi
done

echo ""
echo "========================================"
echo "Connectivity Results: $PASS passed, $FAIL failed"
echo "========================================"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
