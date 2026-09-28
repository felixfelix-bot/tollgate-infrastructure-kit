#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"

echo "Testing Routstr node on $VPS..."
PASS=0
FAIL=0

remote() {
    ssh -T -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o ControlPath=none "$VPS" "$@"
}

echo ""
echo "Routstr container tests:"
echo -n "  [routstr] container running ... "
if remote 'docker ps --format "{{.Names}}" | grep -q "^tollgate-routstr$"'; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL"; FAIL=$((FAIL+1))
fi

echo -n "  [routstr-tor] container running ... "
if remote 'docker ps --format "{{.Names}}" | grep -q "^tollgate-routstr-tor$"'; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL (may be starting)"; FAIL=$((FAIL+1))
fi

echo ""
echo "Routstr mint tests:"
echo -n "  [routstr-mint] container running ... "
if remote 'docker ps --format "{{.Names}}" | grep -q "^mint-routstr-mint$"'; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL"; FAIL=$((FAIL+1))
fi

echo -n "  [routstr-mint] REST API on port 8089 ... "
response=$(remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8089/v1/info" 2>/dev/null || echo "000")
if echo "$response" | grep -qE "200"; then
    echo "OK (HTTP $response)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $response)"; FAIL=$((FAIL+1))
fi

echo ""
echo "Routstr API tests:"
echo -n "  [routstr] /v1/info on port 8000 ... "
response=$(remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/v1/info" 2>/dev/null || echo "000")
if echo "$response" | grep -qE "200"; then
    echo "OK (HTTP $response)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $response)"; FAIL=$((FAIL+1))
fi

echo -n "  [routstr] admin dashboard ... "
response=$(remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/admin" 2>/dev/null || echo "000")
if echo "$response" | grep -qE "200|301|302"; then
    echo "OK (HTTP $response)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $response)"; FAIL=$((FAIL+1))
fi

echo ""
echo "Config persistence:"
echo -n "  [routstr] config file exists ... "
if remote "test -f /opt/tollgate/routstr/routstr.conf"; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL"; FAIL=$((FAIL+1))
fi

echo -n "  [routstr] database exists ... "
if remote "test -f /opt/tollgate/routstr/data/routstr.db"; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL"; FAIL=$((FAIL+1))
fi

echo ""
echo "Tor:"
echo -n "  [routstr] onion address ... "
onion=$(remote "sudo cat /opt/tollgate/routstr/tor-data/ROUTER/hostname 2>/dev/null || echo pending")
if [[ "$onion" == *"onion"* ]]; then
    echo "OK ($onion)"; PASS=$((PASS+1))
else
    echo "PENDING ($onion)"; FAIL=$((FAIL+1))
fi

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
echo "========================================"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
