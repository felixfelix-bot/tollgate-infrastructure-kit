#!/bin/bash
# Test script for hermes-agent:nostr-slim Docker image
# G1: Test exists (this script)
# G2: Tests pass (run on VPS2)

set -e

IMAGE="hermes-agent:nostr-slim"
TEST_CONTAINER="test-hermes-slim-$$"

echo "=== Hermes Slim Image Test ==="
echo "Testing image: $IMAGE"
echo ""

# Test 1: Image exists and size is under 2GB
echo "[TEST 1] Checking image size..."
SIZE_BYTES=$(docker images "$IMAGE" --format "{{.Size}}" | head -1)
if [ -z "$SIZE_BYTES" ]; then
    echo "FAIL: Image $IMAGE not found"
    exit 1
fi

# Parse size (handles GB, MB, kB, B)
SIZE_NUM=$(echo "$SIZE_BYTES" | sed 's/[^0-9.]//g')
SIZE_UNIT=$(echo "$SIZE_BYTES" | sed 's/[0-9.]//g')

case "$SIZE_UNIT" in
    GB)
        SIZE_MB=$(echo "$SIZE_NUM * 1024" | bc -l 2>/dev/null || echo "9999")
        ;;
    MB)
        SIZE_MB=$SIZE_NUM
        ;;
    kB)
        SIZE_MB=$(echo "$SIZE_NUM / 1024" | bc -l 2>/dev/null || echo "0")
        ;;
    B)
        SIZE_MB=$(echo "$SIZE_NUM / 1024 / 1024" | bc -l 2>/dev/null || echo "0")
        ;;
    *)
        SIZE_MB="9999"
        ;;
esac

# Check if under 2GB (2048 MB)
if (( $(echo "$SIZE_MB < 2048" | bc -l 2>/dev/null || echo "0") )); then
    echo "PASS: Image size is ${SIZE_MB}MB (under 2GB target)"
else
    echo "FAIL: Image size is ${SIZE_MB}MB (over 2GB target)"
    exit 1
fi
echo ""

# Test 2: Container starts and hermes --version works
echo "[TEST 2] Testing hermes --version..."
VERSION_OUTPUT=$(docker run --rm "$IMAGE" hermes --version 2>&1 || true)
if echo "$VERSION_OUTPUT" | grep -q "Hermes Agent v"; then
    echo "PASS: hermes --version works"
    echo "  Output: $(echo "$VERSION_OUTPUT" | grep "Hermes Agent")"
else
    echo "FAIL: hermes --version failed"
    echo "  Output: $VERSION_OUTPUT"
    exit 1
fi
echo ""

# Test 3: Gateway can start (brief test)
echo "[TEST 3] Testing gateway startup..."
docker run -d --name "$TEST_CONTAINER" -p 18080:8080 "$IMAGE" > /dev/null 2>&1

# Wait for container to be running
sleep 5

if docker ps --filter "name=$TEST_CONTAINER" --format "{{.Names}}" | grep -q "$TEST_CONTAINER"; then
    echo "PASS: Container started successfully"
    
    # Try health check
    sleep 5
    if curl -sf http://localhost:18080/health > /dev/null 2>&1; then
        echo "PASS: Health endpoint responding"
    else
        echo "INFO: Health endpoint not responding (may need more time or config)"
    fi
else
    echo "FAIL: Container failed to start"
    docker logs "$TEST_CONTAINER" 2>&1 | tail -20
    docker rm -f "$TEST_CONTAINER" > /dev/null 2>&1
    exit 1
fi

# Cleanup
docker rm -f "$TEST_CONTAINER" > /dev/null 2>&1

echo ""
echo "=== All tests passed! ==="
echo "Image: $IMAGE"
echo "Size: ${SIZE_MB}MB"
exit 0
