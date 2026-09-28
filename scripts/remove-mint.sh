#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [[ -z "${1:-}" ]]; then
    echo "Usage: $0 <npub_or_subdomain>"
    exit 1
fi

MINT_ID="$1"

set -a
source "$ENV_FILE"
set +a

cd "$PROJECT_DIR"

echo "Removing mint: $MINT_ID"

ansible-playbook -i ansible/inventory/hosts.yml \
    ansible/playbooks/remove-mint.yml \
    --extra-vars "mint_id=$MINT_ID"

echo "Mint removed: $MINT_ID"
