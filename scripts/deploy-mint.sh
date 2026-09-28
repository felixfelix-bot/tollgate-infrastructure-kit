#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [[ -z "${1:-}" ]]; then
    echo "Usage: $0 <npub> [port]"
    echo "  npub  - Operator's Nostr public key (npub format)"
    echo "  port  - Optional port (auto-assigned if not specified)"
    exit 1
fi

NPUB="$1"

set -a
source "$ENV_FILE"
set +a

PORT="${2:-}"

cd "$PROJECT_DIR"

echo "Deploying Cashu mint for: $NPUB"

ansible-playbook -i ansible/inventory/hosts.yml \
    ansible/playbooks/deploy-mint.yml \
    --extra-vars "npub=$NPUB custom_port=$PORT"

echo "Mint deployed for $NPUB"
