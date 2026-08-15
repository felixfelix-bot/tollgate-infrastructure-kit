#!/usr/bin/env bash
# Hermes VPS health check + alert ladder (T4.2)
# Service checks (containers, gateways, buzz, routstr) + host resource ladder:
#   warn  load>8 (15-min avg) | disk>85% used | RAM avail<10% | swap free<10%
#   page  load>15             | disk>95% used | RAM avail<5%  | swap free<2%
#   meltdown load>30 (this box reached 120 before anyone noticed)
# Delivery: local alert log (always) + ntfy push (if NTFY_URL configured),
# with per-check dedup: repeats warn 6h / page 30m / meltdown 10m, immediate
# on escalation. Samples for post-mortems are persisted separately via
# sysstat (sar, 5-min) and atop (per-process, 5-min) — see monitoring.yml.
# Config file: /etc/default/hermes-health-check (file wins over environment
# for keys it defines). Intended for cron execution every 5 minutes.
# Exit codes: 0 ok/warn, 1 page, 2 meltdown, 3 delivery-channel failure.

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
LOG_FILE="${HERMES_HEALTH_LOG:-/var/log/hermes-health-check.log}"
ALERT_FILE="${HERMES_HEALTH_ALERT:-/var/log/hermes-health-check.alert}"
STATE_DIR="${HERMES_HEALTH_STATE:-/var/lib/hermes-health-check}"
CONFIG_FILE="${HERMES_HEALTH_CONFIG:-/etc/default/hermes-health-check}"
LOADAVG_FILE="${LOADAVG_FILE:-/proc/loadavg}"
MEMINFO_FILE="${MEMINFO_FILE:-/proc/meminfo}"

[ -r "$CONFIG_FILE" ] && . "$CONFIG_FILE"

: "${LOAD_WARN:=8}"
: "${LOAD_PAGE:=15}"
: "${LOAD_MELTDOWN:=30}"
: "${DISK_MOUNT:=/}"
: "${DISK_WARN_PCT:=85}"
: "${DISK_PAGE_PCT:=95}"
: "${RAM_WARN_PCT:=10}"
: "${RAM_PAGE_PCT:=5}"
: "${SWAP_WARN_PCT:=10}"
: "${SWAP_PAGE_PCT:=2}"
: "${NTFY_URL:=}"
: "${REPEAT_WARN:=21600}"
: "${REPEAT_PAGE:=1800}"
: "${REPEAT_MELTDOWN:=600}"

TENANTS=("sitarani" "chiefmonkey" "bekka")
HEALTH_PORTS=(9100 9101 9102)
: "${HERMES_BUZZ_RELAY_URL:=http://localhost:3007}"
: "${HERMES_ROUTSTR_URL:=http://localhost:8009/v1/models}"
BUZZ_RELAY_URL="$HERMES_BUZZ_RELAY_URL"
ROUTSTR_URL="$HERMES_ROUTSTR_URL"

FAILURES=()
WARNINGS=()

LOG_DIR=$(dirname "$LOG_FILE")
if [[ ! -w "$LOG_DIR" ]]; then
    LOG_FILE="${HOME}/.local/log/hermes-health-check.log"
    ALERT_FILE="${HOME}/.local/log/hermes-health-check.alert"
    mkdir -p "$(dirname "$LOG_FILE")"
fi

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG_FILE"
}

# --- pure functions (unit-tested in tests/test-hermes-health-check.sh) ---

gt() { awk -v a="$1" -v b="$2" 'BEGIN { print (a > b) ? "1" : "0" }'; }
lt() { awk -v a="$1" -v b="$2" 'BEGIN { print (a < b) ? "1" : "0" }'; }

classify_load() {
    local v="$1"
    if [[ "$(gt "$v" "$LOAD_MELTDOWN")" == "1" ]]; then echo "meltdown"
    elif [[ "$(gt "$v" "$LOAD_PAGE")" == "1" ]]; then echo "page"
    elif [[ "$(gt "$v" "$LOAD_WARN")" == "1" ]]; then echo "warn"
    else echo "ok"; fi
}

classify_disk() {
    local used_pct="$1"
    if [[ "$(gt "$used_pct" "$DISK_PAGE_PCT")" == "1" ]]; then echo "page"
    elif [[ "$(gt "$used_pct" "$DISK_WARN_PCT")" == "1" ]]; then echo "warn"
    else echo "ok"; fi
}

classify_ram() {
    local avail_pct="$1"
    if [[ "$(lt "$avail_pct" "$RAM_PAGE_PCT")" == "1" ]]; then echo "page"
    elif [[ "$(lt "$avail_pct" "$RAM_WARN_PCT")" == "1" ]]; then echo "warn"
    else echo "ok"; fi
}

classify_swap() {
    local free_pct="$1"
    if [[ "$(lt "$free_pct" "$SWAP_PAGE_PCT")" == "1" ]]; then echo "page"
    elif [[ "$(lt "$free_pct" "$SWAP_WARN_PCT")" == "1" ]]; then echo "warn"
    else echo "ok"; fi
}

level_priority() {
    case "$1" in
        meltdown) echo 3 ;;
        page)     echo 2 ;;
        warn)     echo 1 ;;
        *)        echo 0 ;;
    esac
}

max_level() {
    local best="ok" lvl
    for lvl in "$@"; do
        if [[ "$(level_priority "$lvl")" -gt "$(level_priority "$best")" ]]; then
            best="$lvl"
        fi
    done
    echo "$best"
}

exit_code_for() {
    case "$1" in
        meltdown) echo 2 ;;
        page)     echo 1 ;;
        *)        echo 0 ;;
    esac
}

read_load15() { awk '{print $3}' "$1"; }

read_ram_avail_pct() {
    awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} END {if (t>0) printf "%.0f", a*100/t; else print "100"}' "$1"
}

read_swap_free_pct() {
    awk '/^SwapTotal:/ {t=$2} /^SwapFree:/ {f=$2} END {if (t>0) printf "%.0f", f*100/t; else print "100"}' "$1"
}

read_mem_mb() {
    awk -v k="$1" '$1==k":" {printf "%.0f", $2/1024}' "$MEMINFO_FILE"
}

parse_df_used_pct() { awk '{gsub(/%/, "", $5); print $5; exit}' <<< "$1"; }

build_alert_text() {
    local level="$1" detail="$2" host="$3"
    echo "[${level}] ${host}: ${detail} — ${SCRIPT_NAME} $(date -Iseconds)"
}

# --- delivery ---

ntfy_priority_for() {
    case "$1" in
        meltdown) echo urgent ;;
        page)     echo high ;;
        *)        echo default ;;
    esac
}

push_ntfy() {
    local level="$1" text="$2" rc=0
    if [[ -z "$NTFY_URL" ]]; then
        return 3
    fi
    curl -sS --max-time 10 \
        -H "Title: hermes ${level} — $(hostname -s)" \
        -H "Priority: $(ntfy_priority_for "$level")" \
        -H "Tags: $(ntfy_tags_for "$level")" \
        -d "$text" \
        "$NTFY_URL" >/dev/null 2>&1 || rc=$?
    return "$rc"
}

ntfy_tags_for() {
    case "$1" in
        meltdown) echo fire ;;
        page)     echo rotating_light ;;
        warn)     echo warning ;;
        test)     echo white_check_mark ;;
        *)        echo bell ;;
    esac
}

# state file: "<level> <epoch-of-last-push>"; push on escalation or repeat window
should_push() {
    local key="$1" level="$2" repeat="$3"
    local state_file="$STATE_DIR/${key//\//_}.state" now last_lvl last_ts
    now=$(date +%s)
    if [[ ! -f "$state_file" ]]; then
        return 0
    fi
    read -r last_lvl last_ts < "$state_file" || return 0
    if [[ "$(level_priority "$level")" -gt "$(level_priority "$last_lvl")" ]]; then
        return 0
    fi
    if (( now - last_ts >= repeat )); then
        return 0
    fi
    return 1
}

mark_pushed() {
    local key="$1" level="$2"
    local state_file="$STATE_DIR/${key//\//_}.state"
    echo "$level $(date +%s)" > "$state_file"
}

repeat_for() {
    case "$1" in
        meltdown) echo "$REPEAT_MELTDOWN" ;;
        page)     echo "$REPEAT_PAGE" ;;
        warn)     echo "$REPEAT_WARN" ;;
        *)        echo "$REPEAT_PAGE" ;;
    esac
}

DELIVERY_RC=0

notify() {
    local level="$1" key="$2" detail="$3"
    local host; host=$(hostname -s)
    local text; text=$(build_alert_text "$level" "$detail" "$host")
    echo "$(date '+%Y-%m-%d %H:%M:%S') ALERT [$level] $key: $detail" >> "$ALERT_FILE"
    echo "$text" >&2
    if [[ -n "$NTFY_URL" ]] && should_push "$key" "$level" "$(repeat_for "$level")"; then
        if push_ntfy "$level" "$text"; then
            mark_pushed "$key" "$level"
        else
            local rc=$?
            echo "$(date '+%Y-%m-%d %H:%M:%S') NTFY-DELIVERY-FAILED rc=$rc (url: ${NTFY_URL%%topic=*})" >> "$ALERT_FILE"
            DELIVERY_RC=3
        fi
    fi
}

# --- service checks (V2-10, retained) ---

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
        FAILURES+=("hermes-$name gateway /health: no response on port $port")
        return 1
    fi
    return 0
}

check_buzz_relay() {
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$BUZZ_RELAY_URL" 2>/dev/null || echo 000)
    if [[ "$code" == "000" ]]; then
        WARNINGS+=("Buzz relay: no HTTP response on $BUZZ_RELAY_URL")
        return 1
    fi
    return 0
}

check_routstr() {
    if ! curl -sf --max-time 5 "$ROUTSTR_URL" &>/dev/null; then
        WARNINGS+=("Routstr: no response on $ROUTSTR_URL")
        return 1
    fi
    return 0
}

# --- host resource ladder (T4.2) ---

check_load() {
    local load15 level detail
    load15=$(read_load15 "$LOADAVG_FILE")
    level=$(classify_load "$load15")
    if [[ "$level" != "ok" ]]; then
        detail="load 15-min avg ${load15} exceeds $(threshold_label_for_load "$level") (ladder 8/15/30, $(nproc) cores; 1/5/15: $(awk '{print $1"/"$2"/"$3}' "$LOADAVG_FILE"))"
        notify "$level" "load" "$detail"
    fi
    log "load15=$load15 level=$level"
    echo "$level"
}

threshold_label_for_load() {
    case "$1" in
        meltdown) echo "MELTDOWN threshold $LOAD_MELTDOWN" ;;
        page)     echo "page threshold $LOAD_PAGE" ;;
        warn)     echo "warn threshold $LOAD_WARN" ;;
    esac
}

check_disk() {
    local df_line used_pct avail level
    df_line=$(df -P "$DISK_MOUNT" | tail -1)
    used_pct=$(parse_df_used_pct "$df_line")
    avail=$(awk '{print $4}' <<< "$df_line")
    level=$(classify_disk "$used_pct")
    if [[ "$level" != "ok" ]]; then
        notify "$level" "disk" "disk ${DISK_MOUNT} ${used_pct}% used, $(numfmt --to=iec "$avail" 2>/dev/null || echo "${avail}K") free (ladder warn>${DISK_WARN_PCT}% page>${DISK_PAGE_PCT}%)"
    fi
    log "disk_used_pct=$used_pct level=$level"
    echo "$level"
}

check_ram() {
    local avail_pct level total_mb avail_mb
    avail_pct=$(read_ram_avail_pct "$MEMINFO_FILE")
    level=$(classify_ram "$avail_pct")
    if [[ "$level" != "ok" ]]; then
        total_mb=$(read_mem_mb MemTotal)
        avail_mb=$(read_mem_mb MemAvailable)
        notify "$level" "ram" "RAM available ${avail_pct}% (${avail_mb}MB of ${total_mb}MB)"
    fi
    log "ram_avail_pct=$avail_pct level=$level"
    echo "$level"
}

check_swap() {
    local free_pct level
    free_pct=$(read_swap_free_pct "$MEMINFO_FILE")
    level=$(classify_swap "$free_pct")
    local swap_total_mb; swap_total_mb=$(read_mem_mb SwapTotal)
    if [[ "$swap_total_mb" != "0" && -n "$swap_total_mb" && "$level" != "ok" ]]; then
        notify "$level" "swap" "swap only ${free_pct}% free (thrash signature of the Aug-14 load-120 meltdown)"
    fi
    log "swap_free_pct=$free_pct level=$level"
    echo "$level"
}

# --- main ---

fire_test_alert() {
    local host; host=$(hostname -s)
    local text; text=$(build_alert_text "test" "synthetic alert — delivery-channel verification" "$host")
    echo "$text"
    if [[ -z "$NTFY_URL" ]]; then
        echo "NO DELIVERY CHANNEL: NTFY_URL not set in $CONFIG_FILE or environment" >&2
        return 3
    fi
    if push_ntfy "test" "$text"; then
        echo "PUSHED to ${NTFY_URL} — verify receipt (e.g. curl -s '${NTFY_URL}/json?poll=1')"
        return 0
    fi
    echo "PUSH FAILED (curl rc=$?)" >&2
    return 3
}

usage() {
    cat <<EOF
$SCRIPT_NAME — Hermes VPS health check + load alert ladder (T4.2)
Usage:
  $SCRIPT_NAME              run all checks (cron mode, every 5 min)
  $SCRIPT_NAME --test-alert fire synthetic alert through delivery channel
Levels: warn load>8/disk>85%/ram-avail<10% | page load>15/disk>95%/ram<5% | meltdown load>30
Exit: 0 ok-or-warn, 1 page, 2 meltdown, 3 delivery failure
Config: $CONFIG_FILE (NTFY_URL required for push delivery)
EOF
}

main() {
    mkdir -p "$STATE_DIR" 2>/dev/null || true

    case "${1:-}" in
        --test-alert) fire_test_alert; exit $? ;;
        -h|--help) usage; exit 0 ;;
    esac

    local level="ok"

    if ! command -v docker &>/dev/null; then
        notify "page" "docker" "docker not found in PATH — container checks impossible"
        exit 1
    fi

    for i in "${!TENANTS[@]}"; do
        check_container_health "${TENANTS[$i]}" || true
        check_gateway "${TENANTS[$i]}" "${HEALTH_PORTS[$i]}" || true
    done

    check_buzz_relay || true
    check_routstr || true

    if [[ ${#FAILURES[@]} -gt 0 ]]; then
        local f
        for f in "${FAILURES[@]}"; do
            notify "page" "svc" "$f"
        done
        level=$(max_level "$level" "page")
    fi
    if [[ ${#WARNINGS[@]} -gt 0 ]]; then
        local w
        for w in "${WARNINGS[@]}"; do
            notify "warn" "svc-opt" "$w"
        done
        level=$(max_level "$level" "warn")
    fi

    level=$(max_level "$level" "$(check_load)" "$(check_disk)" "$(check_ram)" "$(check_swap)")

    log "check complete level=$level"
    local final_rc
    final_rc=$(exit_code_for "$level")
    if [[ "$final_rc" == "0" && "$DELIVERY_RC" != "0" ]]; then
        final_rc=3
    fi
    exit "$final_rc"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
