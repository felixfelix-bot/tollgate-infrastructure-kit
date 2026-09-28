#!/usr/bin/env bash
# verify-onboarding-docs.sh — V2-08 quality gate
# Checks that the onboarding docs (docs/onboarding-friend-guide.md,
# docs/operator-guide.md) contain only live-verified facts:
#   1. local:  stale-token scan + required-token scan
#   2. live:   public endpoints answer (relay / ai); mint checked when local
# Usage: scripts/verify-onboarding-docs.sh   (from repo root or anywhere)
set -u
cd "$(dirname "$0")/.."

FAIL=0
note() { printf '%s\n' "$*"; }
bad()  { printf 'FAIL: %s\n' "$*"; FAIL=1; }

FRIEND=docs/onboarding-friend-guide.md
OP=docs/operator-guide.md

[ -f "$FRIEND" ] || { bad "$FRIEND missing"; exit 1; }
[ -f "$OP" ]     || { bad "$OP missing"; exit 1; }

note "== 1. stale-token scan (docs must NOT contain these) =="
for f in "$FRIEND" "$OP"; do
  while IFS= read -r line; do
    bad "$f:$line"
  done < <(grep -nE 'chat\.<|chat\.orangesync|obelisk|tollgate-caddy|tollgate-obelisk|mints\.orangesync|localhost:8000|hermes-health-check' "$f" || true)
done
note "   stale scan done"

note "== 2. required-token scan (docs must contain these) =="
for tok in 'wss://relay.orangesync.tech' 'NIP-42' 'NIP-29' 'block/buzz' 'buzz-relay.fips'; do
  grep -q -- "$tok" "$FRIEND" || bad "$FRIEND lacks '$tok'"
done
for tok in 'wss://relay.orangesync.tech' 'buzz-relay' 'routstr-proxy' '8009' '3007' '8085' 'mint.orangesync.tech' '/opt/buzz-relay' '/etc/caddy/Caddyfile' '--kind 9000' 'mint-approve'; do
  grep -q -- "$tok" "$OP" || bad "$OP lacks '$tok'"
done
note "   required scan done"

note "== 3. live endpoint probes =="
probe() { # url expect-substr
  code=$(curl -s -o /tmp/vod-body -w '%{http_code}' --max-time 10 "$1" 2>/dev/null || echo 000)
  if [ "$code" = "000" ]; then bad "$1 unreachable"; return; fi
  grep -q -- "$2" /tmp/vod-body 2>/dev/null || bad "$1 ok ($code) but body lacks '$2'"
  note "   $1 -> $code, body contains '$2'"
}
probe https://relay.orangesync.tech/ 'Buzz Relay'
probe https://ai.orangesync.tech/    ''

# mint: local probe works on VPS2; from elsewhere use the public URL
if curl -s -o /dev/null --max-time 3 http://localhost:8085/ 2>/dev/null; then
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8085/ || echo 000)
  [ "$code" != "000" ] || bad "localhost:8085 (cdk-mintd) not answering"
  note "   localhost:8085 -> $code"
else
  probe https://mint.orangesync.tech/ ''
fi

note "== 4. referenced files exist =="
for f in docs/INTEGRATED-OPERATIONS.md docs/services.md docs/troubleshooting.md docs/FIPS-MESH-OPERATIONS.md \
         docs/onboarding-friend-guide.md docs/operator-guide.md \
         mint-approve/src/tollgate_mint_approve/cli.py; do
  [ -f "$f" ] || bad "referenced file missing: $f"
done

[ "$FAIL" -eq 0 ] && { note 'RESULT: PASS — docs match live infra'; exit 0; }
note 'RESULT: FAIL'; exit 1
