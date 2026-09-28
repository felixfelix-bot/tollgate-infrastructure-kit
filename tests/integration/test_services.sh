#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"

echo "Testing services on $VPS..."
PASS=0
FAIL=0

test_service() {
    local name="$1"
    local port="$2"
    local expected="${3:-}"
    
    echo -n "  [$name] port $port ... "
    if ssh "$VPS" "ss -tlnp | grep -q ':${port} '"; then
        if [[ -n "$expected" ]]; then
            response=$(ssh "$VPS" "curl -s -o /dev/null -w '%{http_code}' http://localhost:${port}/ 2>/dev/null" || echo "000")
            if echo "$response" | grep -qE "$expected"; then
                echo "OK (HTTP $response)"
                ((PASS++))
            else
                echo "FAIL (HTTP $response, expected $expected)"
                ((FAIL++))
            fi
        else
            echo "OK (listening)"
            ((PASS++))
        fi
    else
        echo "FAIL (not listening)"
        ((FAIL++))
    fi
}

echo ""
echo "Service port tests:"
test_service "strfry" "7777" ""
test_service "obelisk" "8080" ""
test_service "blossom" "3001" "200|302|404"
test_service "nsite-gateway" "3002" "200|302|404"
test_service "caddy" "80" "200|404"
test_service "caddy-tls" "443" ""
test_service "shadowsocks" "65101" ""
test_service "ngit-grasp" "7334" ""

echo ""
echo "Static file tests:"
echo -n "  [releases] /srv/tollgate/releases/index.html ... "
if ssh "$VPS" "test -f /srv/tollgate/releases/index.html"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL"
    ((FAIL++))
fi

echo -n "  [hive-ci] /srv/tollgate/hive-ci/index.html ... "
if ssh "$VPS" "test -f /srv/tollgate/hive-ci/index.html"; then
    echo "OK"
    ((PASS++))
else
    echo "FAIL (may not be built yet)"
    ((FAIL++))
fi

echo ""
echo "Docker container tests:"
for container in tollgate-caddy tollgate-strfry tollgate-obelisk tollgate-blossom tollgate-nsite-gateway; do
    echo -n "  [$container] ... "
    if ssh "$VPS" "docker ps --format '{{.Names}}' | grep -q '^${container}$'"; then
        echo "OK (running)"
        ((PASS++))
    else
        echo "FAIL (not running)"
        ((FAIL++))
    fi
done

echo ""
echo "System service tests:"
for svc in shadowsocks-libev ngit-grasp; do
    echo -n "  [$svc] ... "
    if ssh "$VPS" "systemctl is-active --quiet $svc 2>/dev/null"; then
        echo "OK (active)"
        ((PASS++))
    else
        echo "FAIL (inactive)"
        ((FAIL++))
    fi
done

echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
echo "========================================"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
