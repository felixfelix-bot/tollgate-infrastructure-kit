#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"

echo "Testing Plebeian Market test instance on $VPS..."
PASS=0
FAIL=0

echo ""
echo "Container tests:"
echo -n "  [test-market] container running ... "
if ssh "$VPS" "docker ps --format '{{.Names}}' | grep -q 'tollgate-test-market'"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL (container not running)"
    ((FAIL++))
fi

echo -n "  [test-relay] container running ... "
if ssh "$VPS" "docker ps --format '{{.Names}}' | grep -q 'tollgate-test-relay'"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL (container not running)"
    ((FAIL++))
fi

echo ""
echo "Port tests:"
echo -n "  [test-market] port 34568 ... "
if ssh "$VPS" "ss -tlnp | grep -q ':34568 '"; then
    response=$(ssh "$VPS" "curl -s -o /dev/null -w '%{http_code}' http://localhost:34568/ 2>/dev/null" || echo "000")
    if echo "$response" | grep -qE "200|301|302"; then
        echo "OK (HTTP $response)"
        ((PASS++))
    else
        echo "FAIL (HTTP $response)"
        ((FAIL++))
    fi
else
    echo "FAIL (not listening)"
    ((FAIL++))
fi

echo -n "  [test-relay] port 10548 ... "
if ssh "$VPS" "ss -tlnp | grep -q ':10548 '"; then
    echo "OK (listening)"
    ((PASS++))
else
    echo "FAIL (not listening)"
    ((FAIL++))
fi

echo ""
echo "Caddy routing tests:"
source "$(dirname "$0")/../../.env" 2>/dev/null || true
BASE_DOMAIN="${BASE_DOMAIN:-orangesync.tech}"

echo -n "  [test-market.$BASE_DOMAIN] HTTPS ... "
response=$(ssh "$VPS" "curl -sk -o /dev/null -w '%{http_code}' https://test-market.$BASE_DOMAIN/ 2>/dev/null" || echo "000")
if echo "$response" | grep -qE "200|301|302"; then
    echo "OK (HTTP $response)"
    ((PASS++))
else
    echo "FAIL (HTTP $response)"
    ((FAIL++))
fi

echo -n "  [test-relay.$BASE_DOMAIN] HTTPS ... "
response=$(ssh "$VPS" "curl -sk -o /dev/null -w '%{http_code}' https://test-relay.$BASE_DOMAIN/ 2>/dev/null" || echo "000")
if echo "$response" | grep -qE "200|101|400|403"; then
    echo "OK (HTTP $response)"
    ((PASS++))
else
    echo "FAIL (HTTP $response)"
    ((FAIL++))
fi

echo ""
echo "Docker compose project tests:"
echo -n "  [compose file] exists ... "
if ssh "$VPS" "test -f /opt/tollgate/plebeian-market-test/docker-compose.yml"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL"
    ((FAIL++))
fi

echo -n "  [caddy route] configured ... "
if ssh "$VPS" "grep -q 'test-market.$BASE_DOMAIN' /opt/tollgate/caddy/Caddyfile"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL"
    ((FAIL++))
fi

echo ""
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
