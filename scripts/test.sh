#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PROJECT_DIR/.env"

set -a
source "$ENV_FILE"
set +a

VPS="${VPS_USER:-debian}@${VPS_IP}"

echo "========================================"
echo "Tollgate Infrastructure Kit - Tests"
echo "========================================"

echo ""
echo "--- Integration Tests ---"
bash "$SCRIPT_DIR/../tests/integration/test_services.sh" "$VPS"

echo ""
echo "--- E2E Tests (Playwright) ---"
cd "$PROJECT_DIR/tests/e2e"
if [[ ! -d "node_modules" ]]; then
    npm install
fi
npx playwright install --with-deps
npx playwright test

echo ""
echo "========================================"
echo "All tests complete!"
echo "========================================"
