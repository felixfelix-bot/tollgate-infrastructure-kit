#!/usr/bin/env bash
# Unit test for ansible/roles/ngit_ci/files/harvest-secrets.sh.
#
# The harvest step is what keeps the live DQ05 per-repo CI secrets alive across
# a role run that rewrites .env: if it silently dropped one, jobs of that repo
# would lose their secret with no error anywhere. These cases pin the four
# behaviours the role relies on: secrets move, non-secrets do not, existing
# values are never overwritten, and no value is ever printed.
#
#   tests/test-ngit-ci-secret-harvest.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARVEST="$ROOT/ansible/roles/ngit_ci/files/harvest-secrets.sh"

FAKE_SECRET="4f2a1b9c8d7e6f5a4b3c2d1e0f9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a"
OTHER_SECRET="1111111111111111111111111111111111111111111111111111111111111111"
FAKE_BUNKER="nbunksec1qfakevaluefortests"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1"; FAILED=1; }
FAILED=0
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

write_env() {
  cat > "$SANDBOX/.env" <<EOF
NGIT_CI_REPOS=npub1fake#TMBG,npub1other
NGIT_CI_MAX_CONCURRENT_JOBS=1
NGIT_CI_SECRET_TMBG__NSEC_HEX=$FAKE_SECRET
NGIT_CI_OPERATOR_BUNKER=$FAKE_BUNKER
NGIT_CI_INDEX_RELAYS=wss://index.ngit.dev
EOF
}

secrets_file="$SANDBOX/ngit-ci-secrets.env"
output="$SANDBOX/out.log"

echo "=== harvest into an empty secrets file ==="
write_env
rm -f "$secrets_file"
bash "$HARVEST" "$SANDBOX/.env" "$secrets_file" > "$output" 2>&1

[ -f "$secrets_file" ] || fail "secrets file was not created"
mode="$(stat -c '%a' "$secrets_file" 2>/dev/null || echo '')"
[ "$mode" = "600" ] && pass "secrets file is 0600" || fail "secrets file mode is '$mode', expected 600"
grep -qx "NGIT_CI_SECRET_TMBG__NSEC_HEX=$FAKE_SECRET" "$secrets_file" \
  && pass "per-repo secret value moved byte-for-byte" \
  || fail "per-repo secret value is missing or altered"
grep -qx "NGIT_CI_OPERATOR_BUNKER=$FAKE_BUNKER" "$secrets_file" \
  && pass "operator bunker moved" || fail "operator bunker is missing"
grep -q "NGIT_CI_REPOS\|NGIT_CI_MAX_CONCURRENT_JOBS\|NGIT_CI_INDEX_RELAYS" "$secrets_file" \
  && fail "non-secret keys leaked into the secrets file" \
  || pass "non-secret keys are not copied"
[ "$(wc -l < "$secrets_file")" -eq 2 ] \
  && pass "exactly the two secret lines were copied" \
  || fail "expected 2 lines, found $(wc -l < "$secrets_file")"
grep -q "$FAKE_SECRET" "$output" && fail "the secret value reached stdout/stderr" \
  || pass "no secret value in script output"

echo "=== re-run is a no-op ==="
before="$(sha256sum "$secrets_file" | cut -d' ' -f1)"
bash "$HARVEST" "$SANDBOX/.env" "$secrets_file" > "$output" 2>&1
after="$(sha256sum "$secrets_file" | cut -d' ' -f1)"
[ "$before" = "$after" ] && pass "second run leaves the file unchanged" \
  || fail "second run rewrote the secrets file"

echo "=== an existing value wins over the .env value ==="
printf 'NGIT_CI_SECRET_TMBG__NSEC_HEX=%s\n' "$OTHER_SECRET" > "$secrets_file"
bash "$HARVEST" "$SANDBOX/.env" "$secrets_file" > "$output" 2>&1
grep -qx "NGIT_CI_SECRET_TMBG__NSEC_HEX=$OTHER_SECRET" "$secrets_file" \
  && pass "preserved value was not overwritten" \
  || fail "preserved value was clobbered by the .env value"
grep -qx "NGIT_CI_OPERATOR_BUNKER=$FAKE_BUNKER" "$secrets_file" \
  && pass "keys absent from the secrets file are still added" \
  || fail "missing key was not added next to a preserved key"
[ "$(grep -c 'NGIT_CI_SECRET_TMBG__NSEC_HEX=' "$secrets_file")" -eq 1 ] \
  && pass "no duplicate key lines" || fail "duplicate key lines were appended"

echo "=== missing .env is a no-op, not an error ==="
rm -f "$SANDBOX/.env" "$secrets_file"
bash "$HARVEST" "$SANDBOX/.env" "$secrets_file" > "$output" 2>&1 \
  && pass "missing source file exits 0" || fail "missing source file failed the script"
[ -s "$secrets_file" ] && fail "missing source file still wrote content" \
  || pass "missing source file produced an empty secrets file"

echo "=== the source .env is never modified ==="
write_env
env_before="$(sha256sum "$SANDBOX/.env" | cut -d' ' -f1)"
bash "$HARVEST" "$SANDBOX/.env" "$secrets_file" > "$output" 2>&1
env_after="$(sha256sum "$SANDBOX/.env" | cut -d' ' -f1)"
[ "$env_before" = "$env_after" ] && pass ".env untouched (the role template owns it)" \
  || fail "the harvest modified the source .env"

echo ""
if [ "$FAILED" -eq 0 ]; then
  echo "ALL PASS: ngit-ci secret harvest"
else
  echo "FAILURES PRESENT"
  exit 1
fi
