#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

set -a
source "$ENV_FILE"
set +a

echo "========================================"
echo "Tollgate Infrastructure Kit - Teardown"
echo "========================================"
echo "This will remove ALL Tollgate services."
echo "VPS: ${VPS_USER:-debian}@${VPS_IP}"
read -p "Are you sure? [y/N] " confirm

if [[ "$confirm" != "y" && "$confirm" != "Y" ]]; then
    echo "Aborted."
    exit 0
fi

cd "$PROJECT_DIR"

ssh "${VPS_USER:-debian}@${VPS_IP}" bash -s <<'TEARDOWN'
set -e

echo "Stopping all Docker containers..."
cd /opt/tollgate
for dir in caddy strfry obelisk blossom nsite-gateway mints/*/; do
    if [[ -d "$dir" && -f "$dir/docker-compose.yml" ]]; then
        docker compose -f "$dir/docker-compose.yml" down --remove-orphans --volumes 2>/dev/null || true
    fi
done

echo "Removing Docker images..."
docker image prune -af 2>/dev/null || true

echo "Stopping system services..."
systemctl stop shadowsocks-libev 2>/dev/null || true
systemctl disable shadowsocks-libev 2>/dev/null || true
systemctl stop fips 2>/dev/null || true
systemctl disable fips 2>/dev/null || true

echo "Removing data directories..."
rm -rf /opt/tollgate/*
rm -rf /srv/tollgate/*

echo "Teardown complete."
TEARDOWN
