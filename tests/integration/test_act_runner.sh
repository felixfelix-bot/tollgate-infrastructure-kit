#!/usr/bin/env bash
set -euo pipefail

VPS="${1:?Usage: $0 <user@host>}"
BASE_DOMAIN="${BASE_DOMAIN:-orangesync.tech}"

echo "Testing ACT Runner on $VPS..."
PASS=0
FAIL=0

remote() {
    ssh -T -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o ControlPath=none "$VPS" "$@"
}

echo ""
echo "ACT Runner service tests:"

echo -n "  [act-runner] systemd service active ... "
if remote 'systemctl is-active tollgate-act-runner | grep -q active'; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL"; FAIL=$((FAIL+1))
fi

echo -n "  [act-runner] health endpoint (localhost) ... "
HEALTH=$(remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8095/api/health" || echo "000")
if echo "$HEALTH" | grep -q "200"; then
    echo "OK (HTTP $HEALTH)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $HEALTH)"; FAIL=$((FAIL+1))
fi

echo -n "  [act-runner] health response body ... "
BODY=$(remote "curl -s http://localhost:8095/api/health" || echo "")
if echo "$BODY" | grep -q '"status"'; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL (got: $BODY)"; FAIL=$((FAIL+1))
fi

echo -n "  [act-runner] repos endpoint ... "
REPOS=$(remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8095/api/repos" || echo "000")
if echo "$REPOS" | grep -q "200"; then
    echo "OK (HTTP $REPOS)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $REPOS)"; FAIL=$((FAIL+1))
fi

echo -n "  [act-runner] builds endpoint ... "
BUILDS=$(remote "curl -s -o /dev/null -w '%{http_code}' http://localhost:8095/api/builds" || echo "000")
if echo "$BUILDS" | grep -q "200"; then
    echo "OK (HTTP $BUILDS)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $BUILDS)"; FAIL=$((FAIL+1))
fi

echo ""
echo "Caddy proxy tests:"

echo -n "  [runner] HTTPS proxy to API ... "
RUNNER_HTTPS=$(remote "curl -s -o /dev/null -w '%{http_code}' -k https://runner.${BASE_DOMAIN}/api/health" || echo "000")
if echo "$RUNNER_HTTPS" | grep -q "200"; then
    echo "OK (HTTP $RUNNER_HTTPS)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $RUNNER_HTTPS)"; FAIL=$((FAIL+1))
fi

echo -n "  [runner] dashboard static files ... "
DASH=$(remote "curl -s -o /dev/null -w '%{http_code}' -k https://runner.${BASE_DOMAIN}/" || echo "000")
if echo "$DASH" | grep -q "200"; then
    echo "OK (HTTP $DASH)"; PASS=$((PASS+1))
else
    echo "FAIL (HTTP $DASH)"; FAIL=$((FAIL+1))
fi

echo -n "  [act] binary installed ... "
if remote 'test -x /usr/local/bin/act'; then
    echo "OK"; PASS=$((PASS+1))
else
    echo "FAIL"; FAIL=$((FAIL+1))
fi

echo -n "  [act] act version ... "
ACT_VER=$(remote "/usr/local/bin/act --version" 2>/dev/null || echo "not found")
echo "$ACT_VER"; PASS=$((PASS+1))

echo ""
echo "Results: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
