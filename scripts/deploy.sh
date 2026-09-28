#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    echo "Copy .env.example to .env and fill in your values."
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${VPS_IP:?VPS_IP is required}"
: "${BASE_DOMAIN:?BASE_DOMAIN is required}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"
: "${SHADOWSOCKS_PASSWORD:?SHADOWSOCKS_PASSWORD is required}"

cd "$PROJECT_DIR"

echo "========================================"
echo "Tollgate Infrastructure Kit - Deploy"
echo "========================================"
echo "VPS: ${VPS_USER:-debian}@${VPS_IP}"
echo "Domain: ${BASE_DOMAIN}"
echo "========================================"

ansible-playbook -i ansible/inventory/hosts.yml \
    ansible/playbooks/setup-all.yml \
    --extra-vars "@ansible/group_vars/all.yml"

echo ""
echo "========================================"
echo "Deployment complete!"
echo "Running integration tests..."
echo "========================================"

bash "$SCRIPT_DIR/test.sh"

echo ""
echo "========================================"
echo "All done! Your services:"
echo "  relay.${BASE_DOMAIN}    - Nostr relay"
echo "  chat.${BASE_DOMAIN}     - NIP-29 group chat"
echo "  blossom.${BASE_DOMAIN}  - Blob storage"
echo "  nsite.${BASE_DOMAIN}    - nsite gateway"
echo "  releases.${BASE_DOMAIN} - Release explorer"
echo "  ci.${BASE_DOMAIN}       - Hive CI"
echo "  *.mints.${BASE_DOMAIN}  - Cashu mints"
echo "========================================"
