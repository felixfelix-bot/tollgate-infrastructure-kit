#!/usr/bin/env bash
# Render-check the deployed ngit-ci dashboard (ci.orangesync.tech) from a
# workstation that has Google Chrome. HTTP 200 is not acceptance — this drives
# a real browser, waits for the SPA's first render pass and reports what the
# page actually contains (shell rendered? how many run rows?).
#
#   scripts/verify-ngit-ci-dashboard.sh
#   scripts/verify-ngit-ci-dashboard.sh ci.orangesync.tech /tmp/report.json 20000
#   REQUIRE_RUN_ROWS=1 scripts/verify-ngit-ci-dashboard.sh   # fail on zero rows
#
# NODE/PLAYWRIGHT: the script reuses the ngit-ci-dashboard checkout's
# node_modules (override with PLAYWRIGHT_DIR=<dir containing node_modules>).
set -euo pipefail

DOMAIN="${1:-ci.orangesync.tech}"
REPORT="${2:-/tmp/ngit-ci-dashboard-verify.json}"
WAIT_MS="${3:-20000}"
REQUIRE_RUN_ROWS="${REQUIRE_RUN_ROWS:-0}"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERIFY_SRC="$ROOT/ansible/roles/ngit_ci_dashboard/files/verify_dashboard.mjs"
PLAYWRIGHT_DIR="${PLAYWRIGHT_DIR:-$HOME/repos/ngit-ci-dashboard}"

command -v node >/dev/null || { echo "FAIL: node is required"; exit 2; }
command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null || {
  echo "FAIL: Google Chrome is required (channel:'chrome')"; exit 2; }
[ -f "$VERIFY_SRC" ] || { echo "FAIL: $VERIFY_SRC not found"; exit 2; }
[ -d "$PLAYWRIGHT_DIR/node_modules" ] || {
  echo "FAIL: $PLAYWRIGHT_DIR/node_modules missing — set PLAYWRIGHT_DIR to a checkout with playwright installed"
  exit 2; }

# node resolves bare imports relative to the importing file, so the script has
# to run from inside the tree that owns node_modules.
TMP_SCRIPT="$PLAYWRIGHT_DIR/.verify_dashboard.mjs"
cp "$VERIFY_SRC" "$TMP_SCRIPT"
trap 'rm -f "$TMP_SCRIPT"' EXIT

echo "== HTTP status =="
curl -sS -o /dev/null -w 'https://%{url_effective} -> %{http_code} (tls_verify=%{ssl_verify_result})\n' \
  "https://$DOMAIN/" || true

echo "== Playwright render check =="
( cd "$PLAYWRIGHT_DIR" && node .verify_dashboard.mjs "https://$DOMAIN/" "$REPORT" "$WAIT_MS" ) || {
  echo "FAIL: the render check could not drive the page"; exit 2; }

node -e '
const r = require(process.argv[1]);
console.log(`url            ${r.url}`);
console.log(`http status    ${r.httpStatus}`);
console.log(`title          ${r.title}`);
console.log(`header         ${r.headerText}`);
console.log(`shell rendered ${r.shellRendered}`);
console.log(`run rows       ${r.runRows}`);
if (r.runRowTexts?.length) console.log("run rows:", r.runRowTexts);
' "$REPORT"

SHELL_OK="$(node -e "console.log(require(process.argv[1]).shellRendered ? 1 : 0)" "$REPORT")"
ROWS="$(node -e "console.log(require(process.argv[1]).runRows || 0)" "$REPORT")"

if [ "$SHELL_OK" != "1" ]; then
  echo "FAIL: the dashboard shell did not render"; exit 1
fi
if [ "$REQUIRE_RUN_ROWS" = "1" ] && [ "$ROWS" -lt 1 ]; then
  echo "FAIL: REQUIRE_RUN_ROWS=1 but the page rendered $ROWS run row(s)"; exit 1
fi
echo "OK: shell rendered, $ROWS run row(s) — report at $REPORT"
