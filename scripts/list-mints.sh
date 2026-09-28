#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

set -a
source "$ENV_FILE"
set +a

ssh "debian@${VPS_IP}" "cat /opt/tollgate/mints/registry.json 2>/dev/null | python3 -m json.tool || echo 'No mints deployed yet'"
