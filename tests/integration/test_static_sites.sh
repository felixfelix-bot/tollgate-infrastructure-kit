#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"
DOMAIN="${2:?Usage: $0 <user@host> <base_domain>}"

echo "Testing static site deployments on $VPS ($DOMAIN)..."
PASS=0
FAIL=0

test_static_site() {
    local name="$1"
    local url="$2"

    echo -n "  [$name] $url ... "
    response=$(curl -s -o /dev/null -w '%{http_code}' "$url" || echo "000")
    if [[ "$response" == "200" ]]; then
        echo "OK (HTTP $response)"
        PASS=$((PASS+1))
    else
        echo "FAIL (HTTP $response, expected 200)"
        FAIL=$((FAIL+1))
    fi
}

test_spa_fallback() {
    local name="$1"
    local url="$2"

    echo -n "  [$name] SPA fallback $url ... "
    response=$(curl -s -o /dev/null -w '%{http_code}' "$url" || echo "000")
    if [[ "$response" == "200" ]]; then
        echo "OK (HTTP $response)"
        PASS=$((PASS+1))
    else
        echo "FAIL (HTTP $response, expected 200)"
        FAIL=$((FAIL+1))
    fi
}

test_path_serving() {
    local name="$1"
    local base="$2"
    local path="$3"

    echo -n "  [$name] path $path ... "
    response=$(curl -s -o /dev/null -w '%{http_code}' "$base$path" || echo "000")
    if [[ "$response" == "200" ]]; then
        echo "OK (HTTP $response)"
        PASS=$((PASS+1))
    else
        echo "FAIL (HTTP $response, expected 200)"
        FAIL=$((FAIL+1))
    fi
}

test_static_site "release-explorer" "https://releases.$DOMAIN/"
test_static_site "awesome-tollgate" "https://awesome.$DOMAIN/"
test_spa_fallback "release-explorer" "https://releases.$DOMAIN/nonexistent-route"
test_spa_fallback "awesome-tollgate" "https://awesome.$DOMAIN/nonexistent-route"
test_path_serving "release-explorer" "https://$DOMAIN" "/releases/"
test_path_serving "awesome-tollgate" "https://$DOMAIN" "/awesome/"

echo
echo "Result: $PASS passed, $FAIL failed"
[[ $FAIL -eq 0 ]]
