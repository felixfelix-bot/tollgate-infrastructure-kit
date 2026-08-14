#!/usr/bin/env bash
# =============================================================================
# G1/G2 Test: Verify hermes-health-check.sh exists and is valid bash
# =============================================================================
# This test runs locally (not on VPS2) to verify the script structure.
# For full integration testing, run against VPS2 with live containers.
#
# Usage: bash tests/test-hermes-health-check.sh
# Exit: 0 = all tests pass, 1 = any failure
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
HEALTH_SCRIPT="$PROJECT_DIR/scripts/hermes-health-check.sh"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS=0
FAIL=0

test_pass() {
    echo -e "  ${GREEN}PASS${NC}: $1"
    PASS=$((PASS + 1))
}

test_fail() {
    echo -e "  ${RED}FAIL${NC}: $1"
    FAIL=$((FAIL + 1))
}

echo "=== Testing hermes-health-check.sh ==="
echo ""

# G1: Test exists
echo "G1: Script exists"
if [[ -f "$HEALTH_SCRIPT" ]]; then
    test_pass "Script exists at $HEALTH_SCRIPT"
else
    test_fail "Script not found at $HEALTH_SCRIPT"
    exit 1
fi

# G1: Script is executable
echo ""
echo "G1: Script is executable"
if [[ -x "$HEALTH_SCRIPT" ]]; then
    test_pass "Script has execute permission"
else
    test_fail "Script is not executable"
fi

# G2: Script is valid bash (syntax check)
echo ""
echo "G2: Script syntax is valid bash"
if bash -n "$HEALTH_SCRIPT" 2>/dev/null; then
    test_pass "Bash syntax check passed"
else
    test_fail "Bash syntax errors detected"
fi

# G2: Script has required functions
echo ""
echo "G2: Script has required functions"
required_funcs=("check_container_health" "check_gateway" "check_buzz_relay" "check_routstr")
for func in "${required_funcs[@]}"; do
    if grep -q "^$func()" "$HEALTH_SCRIPT"; then
        test_pass "Function $func defined"
    else
        test_fail "Function $func missing"
    fi
done

# G2: Script checks expected tenants
echo ""
echo "G2: Script checks expected tenants"
if grep -q 'TENANTS=("sitarani" "chiefmonkey" "bekka")' "$HEALTH_SCRIPT"; then
    test_pass "Tenants list includes sitarani, chiefmonkey, bekka"
else
    test_fail "Tenants list incorrect or missing"
fi

# G2: Script uses correct gateway ports
echo ""
echo "G2: Script uses correct gateway ports"
if grep -q 'GATEWAY_PORTS=(9000 9001 9002)' "$HEALTH_SCRIPT"; then
    test_pass "Gateway ports are 9000, 9001, 9002"
else
    test_fail "Gateway ports incorrect or missing"
fi

# G2: Script exits silently on success (no output when healthy)
echo ""
echo "G2: Script has silent success mode"
if grep -q "Silent on success" "$HEALTH_SCRIPT" && grep -q "exit 0" "$HEALTH_SCRIPT"; then
    test_pass "Script designed for silent success"
else
    test_fail "Script may not be silent on success"
fi

# G2: Script logs to expected locations
echo ""
echo "G2: Script logs to expected locations"
if grep -q "/var/log/hermes-health-check.log" "$HEALTH_SCRIPT" && \
   grep -q "/var/log/hermes-health-check.alert" "$HEALTH_SCRIPT"; then
    test_pass "Script logs to /var/log/hermes-health-check.{log,alert}"
else
    test_fail "Script log paths incorrect"
fi

# Summary
echo ""
echo "========================================"
echo "Results: $PASS passed, $FAIL failed"
if [[ $FAIL -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi
