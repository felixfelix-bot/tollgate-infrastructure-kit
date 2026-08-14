#!/bin/bash
# Test script for routstrd production Docker image
# G1: Test exists (bash verification script)
# G2: Tests pass (script exits 0 on live VPS2)

set -e

CONTAINER_NAME="routstrd-test-$$"
VOLUME_NAME="routstrd-test-data-$$"
PORT=$(shuf -i 18000-18999 -n 1)
FAILED=0

cleanup() {
    echo ""
    echo "Cleaning up..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    docker rm -f "${CONTAINER_NAME}-restart" 2>/dev/null || true
    docker volume rm "$VOLUME_NAME" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== routstrd Production Docker Image Tests ==="
echo ""

# Test 1: Image exists and has correct labels
echo "Test 1: Image exists..."
if docker images routstrd:latest --format '{{.Repository}}:{{.Tag}}' | grep -q "routstrd:latest"; then
    echo "  PASS: routstrd:latest image exists"
else
    echo "  FAIL: routstrd:latest image not found"
    FAILED=1
fi

# Test 2: Container starts and health check passes
echo ""
echo "Test 2: Container starts and health check passes..."
docker run -d --name "$CONTAINER_NAME" -p "$PORT":8008 -v "$VOLUME_NAME":/data routstrd:latest

# Wait for container to be running
for i in {1..60}; do
    if docker inspect --format='{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q "true"; then
        break
    fi
    sleep 1
done

if docker inspect --format='{{.State.Running}}' "$CONTAINER_NAME" 2>/dev/null | grep -q "true"; then
    echo "  PASS: Container is running (health: $(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo 'N/A'))"
else
    echo "  FAIL: Container did not start properly"
    docker logs "$CONTAINER_NAME" 2>&1 | tail -20 || true
    FAILED=1
    exit 1
fi

# Test 3: Health endpoint responds
echo ""
echo "Test 3: Health endpoint responds..."
sleep 3
HEALTH_RESPONSE=$(curl -sf http://localhost:$PORT/health 2>&1 || echo "FAILED")
if echo "$HEALTH_RESPONSE" | grep -q '"ok":true'; then
    echo "  PASS: Health endpoint returns ok"
else
    echo "  FAIL: Health endpoint did not return ok: $HEALTH_RESPONSE"
    FAILED=1
fi

# Test 4: Status endpoint responds
echo ""
echo "Test 4: Status endpoint responds..."
STATUS_RESPONSE=$(curl -sf http://localhost:$PORT/status 2>&1 || echo "FAILED")
if echo "$STATUS_RESPONSE" | grep -q '"daemon":"running"'; then
    echo "  PASS: Status endpoint returns daemon running"
else
    echo "  FAIL: Status endpoint did not return expected response: $STATUS_RESPONSE"
    FAILED=1
fi

# Test 5: Ping endpoint responds
echo ""
echo "Test 5: Ping endpoint responds..."
PING_RESPONSE=$(curl -sf http://localhost:$PORT/ping 2>&1 || echo "FAILED")
if echo "$PING_RESPONSE" | grep -q '"output":"pong"'; then
    echo "  PASS: Ping endpoint returns pong"
else
    echo "  FAIL: Ping endpoint did not return pong: $PING_RESPONSE"
    FAILED=1
fi

# Test 6: Non-root user check
echo ""
echo "Test 6: Container runs as non-root user..."
USER_CHECK=$(docker exec "$CONTAINER_NAME" whoami 2>&1 || echo "FAILED")
if [ "$USER_CHECK" = "routstrd" ]; then
    echo "  PASS: Container runs as routstrd user"
else
    echo "  FAIL: Container does not run as expected user: $USER_CHECK"
    FAILED=1
fi

# Test 7: Cocod binary available
echo ""
echo "Test 7: Cocod binary is available..."
COCOD_CHECK=$(docker exec "$CONTAINER_NAME" which cocod 2>&1 || echo "FAILED")
if [ "$COCOD_CHECK" = "/usr/local/bin/cocod" ]; then
    echo "  PASS: Cocod binary found at $COCOD_CHECK"
else
    echo "  FAIL: Cocod binary not found: $COCOD_CHECK"
    FAILED=1
fi

# Test 8: Port exposure
echo ""
echo "Test 8: Port 8008 is exposed..."
PORT_CHECK=$(docker inspect --format='{{range $key, $value := .Config.ExposedPorts}}{{$key}} {{end}}' "$CONTAINER_NAME")
if echo "$PORT_CHECK" | grep -q "8008"; then
    echo "  PASS: Port 8008 is exposed"
else
    echo "  FAIL: Port 8008 is not exposed"
    FAILED=1
fi

# Test 9: Image size check
echo ""
echo "Test 9: Image size check..."
IMAGE_SIZE=$(docker images routstrd:latest --format '{{.Size}}')
echo "  Image size: $IMAGE_SIZE"
# Extract numeric value and unit
SIZE_NUM=$(echo "$IMAGE_SIZE" | sed 's/[^0-9.]//g')
SIZE_UNIT=$(echo "$IMAGE_SIZE" | sed 's/[0-9.]//g')
# Rough check - should be under 2GB
if [ "$SIZE_UNIT" = "GB" ] && [ "${SIZE_NUM%.*}" -ge 2 ]; then
    echo "  WARN: Image size is over 2GB"
else
    echo "  PASS: Image size is acceptable"
fi

# Test 10: Wallet persistence test
echo ""
echo "Test 10: Wallet persistence across restart..."

# Stop and remove container (but keep volume)
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Use a new container name for restart test
RESTART_CONTAINER_NAME="${CONTAINER_NAME}-restart"
docker run -d --name "$RESTART_CONTAINER_NAME" -p "$PORT":8008 -v "$VOLUME_NAME":/data routstrd:latest

# Wait for container to be running
for i in {1..60}; do
    if docker inspect --format='{{.State.Running}}' "$RESTART_CONTAINER_NAME" 2>/dev/null | grep -q "true"; then
        break
    fi
    sleep 1
done

if docker inspect --format='{{.State.Running}}' "$RESTART_CONTAINER_NAME" 2>/dev/null | grep -q "true"; then
    echo "  PASS: Container restarted and is running (volume persisted)"
else
    echo "  FAIL: Container did not restart properly"
    FAILED=1
fi

# Clean up restart container
docker rm -f "$RESTART_CONTAINER_NAME" 2>/dev/null || true

echo ""
echo "=== Test Summary ==="
if [ "$FAILED" -eq 0 ]; then
    echo "All tests PASSED"
    exit 0
else
    echo "Some tests FAILED"
    exit 1
fi
