#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"

echo "Testing DNS resolution for services..."
PASS=0
FAIL=0

set -a
source "$(dirname "$0")/../../.env"
set +a

test_dns() {
    local subdomain="$1"
    local fqdn="${subdomain}.${BASE_DOMAIN}"
    
    echo -n "  [$fqdn] ... "
    ip=$(dig +short "$fqdn" A 2>/dev/null | head -1)
    if [[ "$ip" == "$VPS_IP" ]]; then
        echo "OK ($ip)"
        ((PASS++))
    elif [[ -n "$ip" ]]; then
        echo "FAIL (resolved to $ip, expected $VPS_IP)"
        ((FAIL++))
    else
        echo "SKIP (no DNS record found - may not be configured yet)"
        ((FAIL++))
    fi
}

echo ""
for sub in relay chat blossom nsite releases ci; do
    test_dns "$sub"
done

echo ""
echo "========================================"
echo "DNS Results: $PASS passed, $FAIL failed"
echo "========================================"

if [[ $FAIL -gt 0 ]]; then
    echo "Note: DNS failures are expected if Cloudflare is not configured."
fi
