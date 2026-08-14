#!/usr/bin/env bash
# Hermes container health check script
# Checks: container health, gateway, Buzz relay, routstr
# Silent on success, alerts on failure
# Intended for cron execution every 15 minutes

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${HERMES_HEALTH_LOG:-/var/log/hermes-health-check.log}"
ALERT_FILE="${HERMES_HEALTH_ALERT:-/var/log/hermes-health-check.alert}"

# Ensure log directory exists and is writable
LOG_DIR=$(dirname "$LOG_FILE")
if [[ ! -d "$LOG_DIR" ]] || [[ ! -w "$LOG_DIR" ]]; then
    # Fallback to user's home directory if system log dir not writable
    LOG_FILE="${HOME}/.local/log/hermes-health-check.log"
    ALERT_FILE="${HOME}/.local/log/hermes-health-check.alert"
    mkdir -p "$(dirname "$LOG_FILE")"
fi

# Configuration - tenant gateway ports (base 9000 + index)
TENANTS=("sitarani" "chiefmonkey" "bekka")
GATEWAY_PORTS=(9000 9001 9002)

# Service endpoints
BUZZ_RELAY_URL="http://localhost:3000"
ROUTSTR_URL="http://localhost:8000/v1/models"

# Track failures
FAILURES=()
WARNINGS=()

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"
}

alert() {
    local msg="$1"
    echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT: $msg" >> "$ALERT_FILE"
    echo "$msg" >&2
}

check_container_health() {
    local name="$1"
    local container_name="hermes-$name"
    
    if ! docker inspect "$container_name" &>/dev/null; then
        FAILURES+=("$container_name: container does not exist")
        return 1
    fi
    
    local health_status
    health_status=$(docker inspect --format '{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "unknown")
    
    if [[ "$health_status" != "healthy" ]]; then
        FAILURES+=("$container_name: health status is '$health_status'")
        return 1
    fi
    
    return 0
}

check_gateway() {
    local name="$1"
    local port="$2"
    local url="http://localhost:$port/health"
    
    if ! curl -sf --max-time 5 "$url" &>/dev/null; then
        FAILURES+=("hermes-$name gateway: no response on port $port")
        return 1
    fi
    
    return 0
}

check_buzz_relay() {
    if ! curl -sf --max-time 5 "$BUZZ_RELAY_URL" &>/dev/null; then
        # Buzz relay is optional - warn but don't fail
        WARNINGS+=("Buzz relay: no response on $BUZZ_RELAY_URL")
        return 1
    fi
    return 0
}

check_routstr() {
    if ! curl -sf --max-time 5 "$ROUTSTR_URL" &>/dev/null; then
        # Routstr is optional - warn but don't fail
        WARNINGS+=("Routstr: no response on $ROUTSTR_URL")
        return 1
    fi
    return 0
}

# Main checks
main() {
    local exit_code=0
    
    # Check Docker is available
    if ! command -v docker &>/dev/null; then
        alert "Docker not found in PATH"
        exit 1
    fi
    
    # Check each Hermes tenant
    for i in "${!TENANTS[@]}"; do
        tenant="${TENANTS[$i]}"
        port="${GATEWAY_PORTS[$i]}"
        
        if ! check_container_health "$tenant"; then
            exit_code=1
        fi
        
        if ! check_gateway "$tenant" "$port"; then
            exit_code=1
        fi
    done
    
    # Check optional services (warnings only)
    check_buzz_relay || true
    check_routstr || true
    
    # Output results if there are failures or warnings
    if [[ ${#FAILURES[@]} -gt 0 ]] || [[ ${#WARNINGS[@]} -gt 0 ]]; then
        {
            echo "=== Hermes Health Check ==="
            echo "Time: $(date '+%Y-%m-%d %H:%M:%S %Z')"
            echo ""
            
            if [[ ${#FAILURES[@]} -gt 0 ]]; then
                echo "FAILURES:"
                for f in "${FAILURES[@]}"; do
                    echo "  - $f"
                done
                echo ""
            fi
            
            if [[ ${#WARNINGS[@]} -gt 0 ]]; then
                echo "WARNINGS:"
                for w in "${WARNINGS[@]}"; do
                    echo "  - $w"
                done
            fi
        } | tee -a "$ALERT_FILE"
        
        exit "$exit_code"
    fi
    
    # Silent success - only log at debug level
    log "All checks passed"
    exit 0
}

main "$@"
