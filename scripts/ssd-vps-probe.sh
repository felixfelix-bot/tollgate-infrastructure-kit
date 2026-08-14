#!/bin/bash
# SSD VPS dual-vantage probe cron
# Probes 64.188.7.38 + 66.92.204.38 (ICMP + TCP:22) every minute from >=2 vantages
# On first success: auto-notify manager + set V2-11 ready

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROBE_STATE_DIR="${PROBE_STATE_DIR:-/var/lib/ssd-vps-probe}"
PROBE_LOG="${PROBE_LOG:-/var/log/ssd-vps-probe.log}"
KANBAN_DB="${KANBAN_DB:-$HOME/.hermes/kanban/boards/hermes-for-friends/kanban.db}"

# Target IPs
IP1="64.188.7.38"
IP2="66.92.204.38"

# V2-11 task ID (to set ready on success)
V2_11_TASK_ID="${V2_11_TASK_ID:-t_v2_11_ssd_ready}"

# Notification targets
MANAGER_NOTIFY="${MANAGER_NOTIFY:-manager}"

# Probe configuration
ICMP_TIMEOUT=3
TCP_TIMEOUT=3
SUCCESS_THRESHOLD=2

log() {
    echo "$(date -Iseconds) $*" | tee -a "$PROBE_LOG"
}

ensure_state_dir() {
    if [[ ! -d "$PROBE_STATE_DIR" ]]; then
        mkdir -p "$PROBE_STATE_DIR"
    fi
}

# Probe a single target from this vantage point
# Returns 0 if both ICMP and TCP:22 respond
probe_target() {
    local ip="$1"
    local icmp_ok=0
    local tcp_ok=0

    # ICMP ping
    if ping -c 1 -W "$ICMP_TIMEOUT" "$ip" >/dev/null 2>&1; then
        icmp_ok=1
    fi

    # TCP port 22
    if timeout "$TCP_TIMEOUT" bash -c "</dev/tcp/$ip/22" 2>/dev/null; then
        tcp_ok=1
    fi

    if [[ $icmp_ok -eq 1 && $tcp_ok -eq 1 ]]; then
        return 0
    fi
    return 1
}

# Record probe result from this vantage
record_vantage_result() {
    local ip="$1"
    local result="$2"
    local vantage="${VANTAGE_ID:-$(hostname -s)}"
    local timestamp
    timestamp=$(date +%s)

    echo "${timestamp},${vantage},${result}" >> "$PROBE_STATE_DIR/${ip//./_}.log"

    # Keep only last 1000 lines
    if [[ -f "$PROBE_STATE_DIR/${ip//./_}.log" ]]; then
        tail -n 1000 "$PROBE_STATE_DIR/${ip//./_}.log" > "$PROBE_STATE_DIR/${ip//./_}.log.tmp"
        mv "$PROBE_STATE_DIR/${ip//./_}.log.tmp" "$PROBE_STATE_DIR/${ip//./_}.log"
    fi
}

# Check if we have success from >=2 vantages within last 2 minutes
check_dual_vantage_success() {
    local ip="$1"
    local now
    now=$(date +%s)
    local cutoff=$((now - 120))
    local logfile="$PROBE_STATE_DIR/${ip//./_}.log"

    if [[ ! -f "$logfile" ]]; then
        return 1
    fi

    # Count unique vantages with success in last 2 minutes
    local vantages
    vantages=$(awk -F, -v cutoff="$cutoff" '$1 > cutoff && $3 == "success" {print $2}' "$logfile" 2>/dev/null | sort -u | wc -l)

    if [[ "$vantages" -ge "$SUCCESS_THRESHOLD" ]]; then
        return 0
    fi
    return 1
}

# Check if already notified for this IP
already_notified() {
    local ip="$1"
    local flagfile="$PROBE_STATE_DIR/${ip//./_}.notified"
    [[ -f "$flagfile" ]]
}

# Mark as notified
mark_notified() {
    local ip="$1"
    touch "$PROBE_STATE_DIR/${ip//./_}.notified"
    log "NOTIFIED: $ip is reachable from >=2 vantages"
}

# Send notification to manager
notify_manager() {
    local ip="$1"
    local message="SSD VPS $ip is now reachable from >=2 vantages. V2-11 can proceed."

    # Try hermes kanban comment if available
    if command -v hermes >/dev/null 2>&1; then
        hermes kanban comment "$V2_11_TASK_ID" "$message" 2>/dev/null || true
    fi

    # Log to systemd journal if available
    if command -v systemd-cat >/dev/null 2>&1; then
        echo "$message" | systemd-cat -t ssd-vps-probe -p info
    fi

    # Write to notification log
    echo "$(date -Iseconds) NOTIFY: $message" >> "$PROBE_STATE_DIR/notifications.log"
}

# Set V2-11 task to ready (if using kanban CLI)
set_v2_11_ready() {
    if command -v hermes >/dev/null 2>&1; then
        # Try to unblock/ready the task
        hermes kanban unblock "$V2_11_TASK_ID" 2>/dev/null || true
    fi
    log "V2-11 task marked ready (or attempted)"
}

# Main probe function
run_probe() {
    local ip="$1"

    if probe_target "$ip"; then
        record_vantage_result "$ip" "success"
        log "PROBE_SUCCESS: $ip (from $(hostname -s))"

        # Check if we have dual-vantage success
        if check_dual_vantage_success "$ip"; then
            if ! already_notified "$ip"; then
                notify_manager "$ip"
                mark_notified "$ip"
                set_v2_11_ready
            fi
        fi
    else
        record_vantage_result "$ip" "fail"
        log "PROBE_FAIL: $ip (from $(hostname -s))"
    fi
}

# Simulate mode for testing
simulate_flip() {
    local test_ip="${1:-127.0.0.1}"
    log "SIMULATE: Testing with IP $test_ip"

    # Force a success record from "vantage2"
    echo "$(date +%s),vantage2,success" >> "$PROBE_STATE_DIR/${test_ip//./_}.log"

    # Now probe from this vantage
    VANTAGE_ID="vantage1" run_probe "$test_ip"
}

# Cleanup old state (for testing)
cleanup_state() {
    rm -rf "$PROBE_STATE_DIR"
    log "STATE_CLEANED: $PROBE_STATE_DIR removed"
}

# Main entry point
main() {
    local cmd="${1:-probe}"

    ensure_state_dir

    case "$cmd" in
        probe)
            run_probe "$IP1"
            run_probe "$IP2"
            ;;
        simulate)
            simulate_flip "${2:-127.0.0.1}"
            ;;
        cleanup)
            cleanup_state
            ;;
        status)
            echo "=== SSD VPS Probe Status ==="
            echo "State dir: $PROBE_STATE_DIR"
            echo ""
            for ip in "$IP1" "$IP2"; do
                echo "--- $ip ---"
                local logfile="$PROBE_STATE_DIR/${ip//./_}.log"
                if [[ -f "$logfile" ]]; then
                    echo "Recent probes:"
                    tail -5 "$logfile"
                    if already_notified "$ip"; then
                        echo "Status: NOTIFIED (dual-vantage success)"
                    else
                        echo "Status: waiting for dual-vantage success"
                    fi
                else
                    echo "No probe history"
                fi
                echo ""
            done
            ;;
        *)
            echo "Usage: $0 {probe|simulate [test_ip]|cleanup|status}"
            exit 1
            ;;
    esac
}

main "$@"
