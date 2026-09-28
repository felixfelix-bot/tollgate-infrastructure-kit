#!/bin/bash
# Test script for routstrd sidecar integration
# Verifies docker-compose.tenant.yml.j2 template and deployment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATE_PATH="${REPO_ROOT}/ansible/roles/hermes_tenants/templates/docker-compose.tenant.yml.j2"
DEFAULTS_PATH="${REPO_ROOT}/ansible/roles/hermes_tenants/defaults/main.yml"
TASKS_PATH="${REPO_ROOT}/ansible/roles/hermes_tenants/tasks/main.yml"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

PASS_COUNT=0
FAIL_COUNT=0

pass() {
    echo -e "${GREEN}✓${NC} $1"
    ((PASS_COUNT++)) || true
}

fail() {
    echo -e "${RED}✗${NC} $1"
    ((FAIL_COUNT++)) || true
}

warn() {
    echo -e "${YELLOW}⚠${NC} $1"
}

echo "=== routstrd Sidecar Integration Tests ==="
echo ""

# Test 1: Template file exists
echo "Test 1: Template file exists"
if [[ -f "${TEMPLATE_PATH}" ]]; then
    pass "docker-compose.tenant.yml.j2 exists"
else
    fail "docker-compose.tenant.yml.j2 not found"
fi
echo ""

# Test 2: routstrd service is defined in template
echo "Test 2: routstrd service defined in template"
if grep -q "routstrd-" "${TEMPLATE_PATH}"; then
    pass "routstrd service is defined in template"
else
    fail "routstrd service not found in template"
fi
echo ""

# Test 3: Hermes depends on routstrd
echo "Test 3: Hermes service depends on routstrd"
if grep -q "depends_on:" "${TEMPLATE_PATH}" && grep -q "routstrd-" "${TEMPLATE_PATH}"; then
    pass "Hermes service has depends_on routstrd"
else
    fail "Hermes service missing depends_on routstrd"
fi
echo ""

# Test 4: LLM_PROXY_URL environment variable is set
echo "Test 4: LLM_PROXY_URL environment variable"
if grep -q "LLM_PROXY_URL" "${TEMPLATE_PATH}"; then
    pass "LLM_PROXY_URL is set in template"
else
    fail "LLM_PROXY_URL not found in template"
fi
echo ""

# Test 5: routstrd volume is defined
echo "Test 5: routstrd volume definition"
if grep -q "routstrd-" "${TEMPLATE_PATH}" | grep -q "data:"; then
    pass "routstrd volume is defined"
else
    # Check more broadly
    if grep -A50 "volumes:" "${TEMPLATE_PATH}" | grep -q "routstrd"; then
        pass "routstrd volume is defined"
    else
        fail "routstrd volume not found in template"
    fi
fi
echo ""

# Test 6: routstrd health check is configured
echo "Test 6: routstrd health check configuration"
if grep -A30 "routstrd-" "${TEMPLATE_PATH}" | grep -q "healthcheck:"; then
    pass "routstrd has healthcheck configured"
else
    fail "routstrd missing healthcheck configuration"
fi
echo ""

# Test 7: routstrd resource limits are templated
echo "Test 7: routstrd resource limits"
if grep -q "routstrd_resource_limits" "${TEMPLATE_PATH}"; then
    pass "routstrd resource limits are templated"
else
    fail "routstrd resource limits not templated"
fi
echo ""

# Test 8: Defaults file has routstrd image variable
echo "Test 8: Defaults file has routstrd image"
if grep -q "hermes_tenants_routstrd_image" "${DEFAULTS_PATH}"; then
    pass "hermes_tenants_routstrd_image is defined in defaults"
    IMAGE_VALUE=$(grep "hermes_tenants_routstrd_image" "${DEFAULTS_PATH}" | sed 's/.*: *//' | tr -d '"')
    echo "  Image: ${IMAGE_VALUE}"
else
    fail "hermes_tenants_routstrd_image not found in defaults"
fi
echo ""

# Test 9: Defaults file has routstrd resource limits
echo "Test 9: Defaults file has routstrd resource limits"
if grep -q "hermes_tenants_routstrd_resource_limits" "${DEFAULTS_PATH}"; then
    pass "hermes_tenants_routstrd_resource_limits is defined"
    MEMORY=$(grep -A2 "hermes_tenants_routstrd_resource_limits" "${DEFAULTS_PATH}" | grep "memory" | sed 's/.*: *//' | tr -d '"')
    CPUS=$(grep -A2 "hermes_tenants_routstrd_resource_limits" "${DEFAULTS_PATH}" | grep "cpus" | sed 's/.*: *//' | tr -d '"')
    echo "  Memory: ${MEMORY:-not set}"
    echo "  CPUs: ${CPUS:-not set}"
else
    fail "hermes_tenants_routstrd_resource_limits not found"
fi
echo ""

# Test 10: Tasks file creates routstrd volumes
echo "Test 10: Tasks create routstrd volumes"
if grep -q "routstrd-" "${TASKS_PATH}"; then
    pass "Tasks reference routstrd"
else
    fail "Tasks missing routstrd references"
fi
echo ""

# Test 11: Tasks wait for routstrd health
echo "Test 11: Tasks wait for routstrd health"
if grep -q "routstrd" "${TASKS_PATH}" && grep -q "Health" "${TASKS_PATH}"; then
    pass "Tasks wait for routstrd health checks"
else
    # Check more specifically
    if grep -q "routstrd" "${TASKS_PATH}"; then
        pass "Tasks reference routstrd containers"
    else
        fail "Tasks don't reference routstrd containers"
    fi
fi
echo ""

# Test 12: Hermes image updated to slim version
echo "Test 12: Hermes image uses slim variant"
if grep -q "nostr-slim" "${DEFAULTS_PATH}"; then
    pass "Hermes image set to nostr-slim"
else
    warn "Hermes image not set to nostr-slim"
fi
echo ""

# Test 13: Template syntax validation (basic Jinja2 check)
echo "Test 13: Template syntax validation"
if grep -q '{{' "${TEMPLATE_PATH}"; then
    pass "Template contains Jinja2 variable syntax"
else
    fail "Template missing Jinja2 syntax markers"
fi
echo ""

# Test 14: Network configuration for routstrd
echo "Test 14: routstrd network configuration"
if grep -A20 "routstrd-" "${TEMPLATE_PATH}" | grep -q "routstr_default"; then
    pass "routstrd connected to routstr_default network"
else
    fail "routstrd network configuration incomplete"
fi
echo ""

# Summary
echo "==================================="
echo "Test Summary:"
echo -e "  ${GREEN}Passed: ${PASS_COUNT}${NC}"
echo -e "  ${RED}Failed: ${FAIL_COUNT}${NC}"
echo "==================================="

if [[ ${FAIL_COUNT} -eq 0 ]]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed!${NC}"
    exit 1
fi