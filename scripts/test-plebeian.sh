#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: .env file not found at $ENV_FILE"
    exit 1
fi

set -a
source "$ENV_FILE"
set +a

: "${VPS_IP:?VPS_IP is required}"
: "${BASE_DOMAIN:?BASE_DOMAIN is required}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"

VPS="${VPS_USER:-debian}@${VPS_IP}"
ACTION="${1:-deploy}"
export ANSIBLE_CONFIG="$PROJECT_DIR/ansible/ansible.cfg"

usage() {
    echo "Usage: $0 [deploy|test|teardown|full]"
    echo ""
    echo "  deploy    - Deploy plebeian market test instance (default)"
    echo "  test      - Run tests against deployed instance"
    echo "  teardown  - Remove plebeian market test instance"
    echo "  full      - Deploy → test → teardown"
    exit 1
}

do_deploy() {
    echo "========================================"
    echo "Plebeian Market Test - Deploy"
    echo "========================================"
    echo "VPS: $VPS"
    echo "Domain: test-market.$BASE_DOMAIN"
    echo "Relay: test-relay.$BASE_DOMAIN"
    echo "========================================"

    ansible-playbook -i ansible/inventory/hosts.yml \
        ansible/playbooks/26-plebeian-market-test.yml \
        --extra-vars "@ansible/inventory/group_vars/all.yml"
}

do_test() {
    echo ""
    echo "Running integration tests..."
    bash "$PROJECT_DIR/tests/integration/test_plebeian_market.sh" "$VPS"

    echo ""
    echo "Running E2E smoke tests..."
    cd "$PROJECT_DIR/tests/e2e"
    npm install --silent 2>/dev/null
    BASE_DOMAIN="$BASE_DOMAIN" npx playwright test --grep "Plebeian Market|Test Relay"
}

do_teardown() {
    echo ""
    echo "========================================"
    echo "Plebeian Market Test - Teardown"
    echo "========================================"

    ansible-playbook -i ansible/inventory/hosts.yml \
        ansible/playbooks/26-plebeian-market-test.yml \
        --extra-vars "@ansible/inventory/group_vars/all.yml" \
        --tags teardown

    echo "Teardown complete."
}

case "$ACTION" in
    deploy)
        do_deploy
        echo ""
        echo "Test with: $0 test"
        echo "Remove with: $0 teardown"
        ;;
    test)
        do_test
        ;;
    teardown)
        do_teardown
        ;;
    full)
        do_deploy
        do_test
        do_teardown
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        echo "Unknown action: $ACTION"
        usage
        ;;
esac
