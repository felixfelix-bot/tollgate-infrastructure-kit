#!/bin/bash
# Test script for Hermes gateway port binding fix
# Verifies that gateway is listening on port 8080 inside containers
# and responding to health checks

set -e

VPS2="root@23.182.128.51"
FAILED=0

echo "=== Hermes Gateway Port Binding Test ==="
echo "Testing VPS2: $VPS2"
echo ""

# Test 1: Check containers are running
echo "--- Test 1: Containers are running ---"
for container in hermes-sitarani hermes-chiefmonkey hermes-bekka; do
    status=$(ssh -o ConnectTimeout=10 $VPS2 "docker inspect --format '{{.State.Status}}' $container 2>/dev/null || echo 'not_found'")
    if [ "$status" = "running" ]; then
        echo "✓ $container is running"
    else
        echo "✗ $container is NOT running (status: $status)"
        FAILED=1
    fi
done
echo ""

# Test 2: Check gateway process is running inside containers
echo "--- Test 2: Gateway process is running ---"
for container in hermes-sitarani hermes-chiefmonkey hermes-bekka; do
    # Check if hermes gateway process exists (not just sleep)
    procs=$(ssh -o ConnectTimeout=10 $VPS2 "docker exec $container ps aux 2>/dev/null | grep -c 'hermes gateway' || echo '0'")
    if [ "$procs" -gt 0 ]; then
        echo "✓ $container has hermes gateway process running"
    else
        echo "✗ $container does NOT have hermes gateway process"
        FAILED=1
    fi
done
echo ""

# Test 3: Check health endpoint responds inside container
echo "--- Test 3: Health endpoint responds (inside container) ---"
for container in hermes-sitarani hermes-chiefmonkey hermes-bekka; do
    if ssh -o ConnectTimeout=10 $VPS2 "docker exec $container curl -sf http://localhost:8080/health" > /dev/null 2>&1; then
        echo "✓ $container responds to localhost:8080/health"
    else
        echo "✗ $container does NOT respond to localhost:8080/health"
        FAILED=1
    fi
done
echo ""

# Test 4: Check health endpoint responds from host (via port mapping)
echo "--- Test 4: Health endpoint responds (from host) ---"
for port in 9000 9001 9002; do
    if ssh -o ConnectTimeout=10 $VPS2 "curl -sf http://localhost:$port/health" > /dev/null 2>&1; then
        echo "✓ Port $port responds to /health"
    else
        echo "✗ Port $port does NOT respond to /health"
        FAILED=1
    fi
done
echo ""

# Test 5: Check container health status
echo "--- Test 5: Container health status ---"
for container in hermes-sitarani hermes-chiefmonkey hermes-bekka; do
    health=$(ssh -o ConnectTimeout=10 $VPS2 "docker inspect --format '{{.State.Health.Status}}' $container 2>/dev/null || echo 'unknown'")
    if [ "$health" = "healthy" ]; then
        echo "✓ $container health status: $health"
    else
        echo "✗ $container health status: $health (expected: healthy)"
        FAILED=1
    fi
done
echo ""

# Summary
echo "=== Test Summary ==="
if [ $FAILED -eq 0 ]; then
    echo "✓ All tests PASSED"
    exit 0
else
    echo "✗ Some tests FAILED"
    exit 1
fi
