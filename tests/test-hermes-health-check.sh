#!/usr/bin/env bash
# =============================================================================
# G1/G2 Test: hermes-health-check.sh — threshold ladder unit tests + structure
# =============================================================================
# Unit tests source the script (guarded main) and exercise the pure
# classification functions with injected values — no live system needed.
# Boundary semantics: thresholds are strictly-greater-than per T4.2 spec
# (warn at load>8, page at >15, meltdown at >30).
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

assert_equals() {
    local expected="$1" actual="$2" label="$3"
    if [[ "$expected" == "$actual" ]]; then
        test_pass "$label (got '$actual')"
    else
        test_fail "$label — expected '$expected', got '$actual'"
    fi
}

echo "=== Testing hermes-health-check.sh ==="
echo ""

# G1: Script exists and is executable
echo "G1: Script exists and is executable"
if [[ -f "$HEALTH_SCRIPT" && -x "$HEALTH_SCRIPT" ]]; then
    test_pass "Script exists and is executable"
else
    test_fail "Script missing or not executable"
    exit 1
fi

# G2: Syntax valid
echo ""
echo "G2: Script syntax is valid bash"
if bash -n "$HEALTH_SCRIPT" 2>/dev/null; then
    test_pass "Bash syntax check passed"
else
    test_fail "Bash syntax errors detected"
fi

# G2: Sourcing must not execute main (guarded entry point)
echo ""
echo "G2: Script is sourceable without side effects"
SOURCE_OUTPUT="$(SOURCE_OK=1 bash -c "source '$HEALTH_SCRIPT' && echo sourced-ok" 2>&1 || true)"
if [[ "$SOURCE_OUTPUT" == "sourced-ok" ]]; then
    test_pass "Sourcing runs no main loop"
else
    test_fail "Sourcing executed something: $SOURCE_OUTPUT"
fi

# Load script under test
# shellcheck source=/dev/null
source "$HEALTH_SCRIPT"

echo ""
echo "Unit: load ladder thresholds (strictly greater: 8 / 15 / 30)"
assert_equals "ok"        "$(classify_load 0.5)"  "classify_load 0.5"
assert_equals "ok"        "$(classify_load 7.9)"  "classify_load 7.9"
assert_equals "ok"        "$(classify_load 8)"    "classify_load 8 (boundary, not >8)"
assert_equals "warn"      "$(classify_load 8.1)"  "classify_load 8.1"
assert_equals "warn"      "$(classify_load 14.9)" "classify_load 14.9"
assert_equals "warn"      "$(classify_load 15)"   "classify_load 15 (boundary, not >15)"
assert_equals "page"      "$(classify_load 15.1)" "classify_load 15.1"
assert_equals "page"      "$(classify_load 29.9)" "classify_load 29.9"
assert_equals "page"      "$(classify_load 30)"   "classify_load 30 (boundary, not >30)"
assert_equals "meltdown"  "$(classify_load 30.1)" "classify_load 30.1"
assert_equals "meltdown"  "$(classify_load 120)"  "classify_load 120 (Aug-14 incident level)"

echo ""
echo "Unit: disk headroom thresholds (>85 warn, >95 page, percent used)"
assert_equals "ok"    "$(classify_disk 84.9)" "classify_disk 84.9"
assert_equals "ok"    "$(classify_disk 85)"   "classify_disk 85 (boundary)"
assert_equals "warn"  "$(classify_disk 85.1)" "classify_disk 85.1"
assert_equals "warn"  "$(classify_disk 95)"   "classify_disk 95 (boundary)"
assert_equals "page"  "$(classify_disk 95.1)" "classify_disk 95.1"
assert_equals "page"  "$(classify_disk 99)"   "classify_disk 99"

echo ""
echo "Unit: RAM headroom thresholds (available <10% warn, <5% page)"
assert_equals "ok"    "$(classify_ram 100)"  "classify_ram 100"
assert_equals "ok"    "$(classify_ram 10.1)" "classify_ram 10.1"
assert_equals "warn"  "$(classify_ram 9.9)"  "classify_ram 9.9"
assert_equals "warn"  "$(classify_ram 5.1)"  "classify_ram 5.1"
assert_equals "warn"  "$(classify_ram 5)"    "classify_ram 5 (boundary)"
assert_equals "page"  "$(classify_ram 4.9)"  "classify_ram 4.9"

echo ""
echo "Unit: level precedence and exit codes"
assert_equals 0 "$(level_priority ok)"       "priority ok"
assert_equals 1 "$(level_priority warn)"     "priority warn"
assert_equals 2 "$(level_priority page)"     "priority page"
assert_equals 3 "$(level_priority meltdown)" "priority meltdown"
assert_equals "page" "$(max_level warn page)"     "max_level warn page"
assert_equals "page" "$(max_level page warn)"     "max_level page warn (order-independent)"
assert_equals "meltdown" "$(max_level ok meltdown)" "max_level ok meltdown"
assert_equals "ok"   "$(max_level ok ok)"    "max_level ok ok"
assert_equals 0 "$(exit_code_for ok)"       "exit code ok"
assert_equals 0 "$(exit_code_for warn)"     "exit code warn (informational)"
assert_equals 1 "$(exit_code_for page)"     "exit code page"
assert_equals 2 "$(exit_code_for meltdown)" "exit code meltdown"

echo ""
echo "Unit: readers parse fixture files"
FIX_DIR="$(mktemp -d)"
trap 'rm -rf "$FIX_DIR"' EXIT
printf '2.05 3.10 33.42 1/500 12345\n' > "$FIX_DIR/loadavg"
assert_equals "33.42" "$(read_load15 "$FIX_DIR/loadavg")" "read_load15 takes field 3"

printf 'MemTotal:       8000000 kB\nMemFree:         100000 kB\nMemAvailable:   4000000 kB\nSwapTotal:     2000000 kB\nSwapFree:         20000 kB\n' > "$FIX_DIR/meminfo"
assert_equals "50" "$(read_ram_avail_pct "$FIX_DIR/meminfo")" "read_ram_avail_pct 4.0G/8.0G"
assert_equals "1"  "$(read_swap_free_pct "$FIX_DIR/meminfo")" "read_swap_free_pct 20k/2M"

DF_LINE="overlay  103G  102G  1.2G  99% /"
assert_equals "99" "$(parse_df_used_pct "$DF_LINE")" "parse_df_used_pct field 5"

echo ""
echo "Unit: alert text builder includes level and host"
ALERT_TEXT="$(build_alert_text meltdown "load average 120.5" testhost)"
if [[ "$ALERT_TEXT" == *meltdown* && "$ALERT_TEXT" == *testhost* && "$ALERT_TEXT" == *"120.5"* ]]; then
    test_pass "build_alert_text contains level, host, detail"
else
    test_fail "build_alert_text incomplete: $ALERT_TEXT"
fi

echo ""
echo "Unit: push dedup — escalation always pushes, same level respects window"
STATE_DIR="$FIX_DIR/state"; mkdir -p "$STATE_DIR"
if should_push "load" "page" 1800; then
    test_pass "should_push true when no prior state"
else
    test_fail "should_push false with no state"
fi
mark_pushed "load" "page"
if should_push "load" "page" 1800; then
    test_fail "should_push true within repeat window (spam bug)"
else
    test_pass "should_push false within repeat window"
fi
if should_push "load" "meltdown" 600; then
    test_pass "should_push true on escalation page->meltdown"
else
    test_fail "escalation suppressed (dangerous)"
fi
mark_pushed "disk" "warn"
if should_push "disk" "page" 1800; then
    test_pass "should_push true on escalation warn->page"
else
    test_fail "warn->page escalation suppressed"
fi
echo "meltdown 1" > "$STATE_DIR/ram.state"
if should_push "ram" "meltdown" 600; then
    test_pass "should_push true when window elapsed (stale timestamp)"
else
    test_fail "stale state still suppresses"
fi

echo ""
echo "Unit: notify writes local alert log even without NTFY_URL"
ALERT_FILE="$FIX_DIR/alert.log"; touch "$ALERT_FILE"
NTFY_URL=""
notify "warn" "load" "unit-test detail" >/dev/null 2>&1 || true
if grep -q "ALERT \[warn\] load: unit-test detail" "$ALERT_FILE"; then
    test_pass "notify appends leveled line to ALERT_FILE"
else
    test_fail "notify did not log: $(cat "$ALERT_FILE")"
fi

echo ""
echo "Unit: tenant + gateway regression (V2-10 checks retained)"
assert_equals "sitarani chiefmonkey bekka" "${TENANTS[*]}" "TENANTS list"
assert_equals "9100 9101 9102" "${HEALTH_PORTS[*]}" "HEALTH_PORTS list (role health_port_base 9100)"
assert_equals "http://localhost:3007" "$BUZZ_RELAY_URL" "BUZZ_RELAY_URL host-binding 127.0.0.1:3007"
assert_equals "http://localhost:8009/v1/models" "$ROUTSTR_URL" "ROUTSTR_URL routstr-proxy 8009"

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
