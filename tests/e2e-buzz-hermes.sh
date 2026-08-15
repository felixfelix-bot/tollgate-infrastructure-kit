#!/usr/bin/env bash
# =============================================================================
# V2-03: End-to-End Buzz → relay → Hermes → LLM → response test
# Board: hermes-for-friends | Plan: PLAN-hermes-for-friends-v2.md Task 3
#
# Proves the full chain on the LIVE VPS2 (23.182.128.51):
#
#   [test user (nak stands in for Buzz)]
#     --wss--> [Caddy :443 relay.orangesync.tech]
#     --> [buzz-relay NIP-29 (127.0.0.1:3007 -> :3000)]
#     --> [hermes-sitarani nostr adapter]
#     --> [Hermes gateway :8080 -> host :9000]
#     --> [LLM via LLM_PROXY_URL]
#     --> [signed kind-9 reply published to the group]
#     --> [observed via nak req]
#
# Uses an ephemeral NIP-29 group (kind 9 create event, nak >= 0.18 syntax)
# so the production group 8ce5ea86-... is untouched. Cleanup restores the
# container's original NOSTR_GROUPS and deletes the test group.
#
# Usage:
#   ./tests/e2e-buzz-hermes.sh                    # run against live VPS2
#   E2E_KEEP_GROUP=1 ./tests/e2e-buzz-hermes.sh   # keep test group (debug)
#
# Environment overrides:
#   VPS2_HOST          default root@23.182.128.51
#   HERMES_CONTAINER   default hermes-sitarani
#   RELAY              default wss://relay.orangesync.tech
#   E2E_TIMEOUT_SECS   default 150 (max wait for the bot's reply)
# =============================================================================
set -euo pipefail

VPS2_HOST="${VPS2_HOST:-root@23.182.128.51}"
CONTAINER="${HERMES_CONTAINER:-hermes-sitarani}"
RELAY="${RELAY:-wss://relay.orangesync.tech}"
E2E_TIMEOUT_SECS="${E2E_TIMEOUT_SECS:-150}"

PASS=0; FAIL=0
note()   { printf '       %s\n' "$*"; }
ok()     { PASS=$((PASS+1)); printf '[PASS] %s\n' "$*"; }
bad()    { FAIL=$((FAIL+1)); printf '[FAIL] %s\n' "$*"; }
remote() { ssh -o ConnectTimeout=25 "$VPS2_HOST" "$*"; }

CLEANUP_OWNER=0
ORIG_GROUPS=""
TEST_GROUP=""; TEST_NSEC=""

cleanup() {
  if [ "$CLEANUP_OWNER" = 1 ]; then
    printf '\n== cleanup ==\n'
    if [ -n "$ORIG_GROUPS" ]; then
      if remote "cd /opt/tollgate/hermes/${CONTAINER#hermes-} && (grep -q '^NOSTR_GROUPS=' .env && sed -i \"s|^NOSTR_GROUPS=.*|NOSTR_GROUPS=${ORIG_GROUPS}|\" .env || echo \"NOSTR_GROUPS=${ORIG_GROUPS}\" >> .env) && docker compose up -d >/dev/null 2>&1"; then
        note "restored NOSTR_GROUPS=${ORIG_GROUPS}"
      else
        bad "could not restore NOSTR_GROUPS — manual fix: /opt/tollgate/hermes/${CONTAINER#hermes-}/.env"
      fi
    fi
    if [ -n "$TEST_GROUP" ] && [ "${E2E_KEEP_GROUP:-0}" != 1 ] && [ -n "$TEST_NSEC" ]; then
      if remote "nak group delete-group \"${RELAY}'${TEST_GROUP}\" --sec '${TEST_NSEC}' >/dev/null 2>&1"; then
        note "deleted test group ${TEST_GROUP}"
      else
        note "test group ${TEST_GROUP} left in place — delete manually if needed"
      fi
    fi
  fi
}
trap cleanup EXIT

printf 'V2-03 E2E: Buzz -> relay -> Hermes -> LLM -> response\n'
printf 'target: %s  container: %s  relay: %s\n\n' "$VPS2_HOST" "$CONTAINER" "$RELAY"

# ---------------------------------------------------------------------------
# P0 — pre-flight: host reachable, containers up, nak present
# ---------------------------------------------------------------------------
printf -- '-- P0 pre-flight\n'
if remote "true" 2>/dev/null; then ok "ssh $VPS2_HOST reachable"; else bad "ssh $VPS2_HOST unreachable"; exit 1; fi
if remote "docker inspect -f '{{.State.Running}}' buzz-relay" 2>/dev/null | grep -q true; then ok "buzz-relay running"; else bad "buzz-relay not running"; exit 1; fi
if remote "docker inspect -f '{{.State.Running}}' $CONTAINER" 2>/dev/null | grep -q true; then ok "$CONTAINER running"; else bad "$CONTAINER not running"; exit 1; fi
if remote "command -v nak" 2>/dev/null | grep -q nak; then ok "nak CLI present on VPS2"; else bad "nak CLI missing on VPS2"; exit 1; fi

# ---------------------------------------------------------------------------
# P1 — relay reachable: NIP-11 document over https/wss (Buzz entry point)
# ---------------------------------------------------------------------------
printf -- '-- P1 relay reachable\n'
if remote "nak relay '$RELAY' 2>/dev/null | head -2" | grep -q '"name"'; then
  ok "relay $RELAY answering (NIP-11)"
else
  bad "relay $RELAY not answering"; exit 1
fi

# ---------------------------------------------------------------------------
# P2 — Hermes gateway healthy (HTTP API :8080 -> host :9000)
# NOTE: docker's pgrep healthcheck false-positives; only /health counts.
# ---------------------------------------------------------------------------
printf -- '-- P2 hermes gateway health\n'
GW_CODE=$(remote "curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:9000/health" 2>/dev/null || true)
if [ "$GW_CODE" = 200 ]; then ok "gateway /health = 200 on :9000"; else bad "gateway /health = ${GW_CODE:-none} on :9000"; fi

# ---------------------------------------------------------------------------
# P3 — nostr adapter loaded (gateway log evidence)
# ---------------------------------------------------------------------------
printf -- '-- P3 nostr adapter loaded\n'
NOSTR_LOG=$(remote "docker exec $CONTAINER sh -c 'tail -300 /opt/data/logs/agent.log 2>/dev/null | grep -iE \"nostr.*(connect|subscri|listen|start|group)\" | tail -3'" 2>/dev/null || true)
if [ -n "$NOSTR_LOG" ]; then
  ok "nostr adapter active: $(echo "$NOSTR_LOG" | tail -1 | cut -c1-100)"
else
  bad "no nostr adapter lines in /opt/data/logs/agent.log"
fi

# ---------------------------------------------------------------------------
# P4 — ephemeral test group + hermes membership
# ---------------------------------------------------------------------------
printf -- '-- P4 test group\n'
TEST_NSEC=$(remote "nak key generate" 2>/dev/null | tail -1 || true)
if [[ "$TEST_NSEC" =~ ^[0-9a-f]{64}$ ]]; then ok "ephemeral test keypair generated"; else bad "nak key generate failed"; exit 1; fi
TEST_PUB=$(remote "nak key public '$TEST_NSEC'" 2>/dev/null | tail -1 || true)
[[ "$TEST_PUB" =~ ^[0-9a-f]{64}$ ]] || { bad "nak key public failed"; exit 1; }
TEST_GROUP="e2e$(remote "cat /proc/sys/kernel/random/uuid" 2>/dev/null | tr -d -- '-\n')"
[ ${#TEST_GROUP} -ge 20 ] || { bad "uuid generation failed"; exit 1; }
ok "test group id: $TEST_GROUP"
CLEANUP_OWNER=1   # from here on we own state that must be restored

# NIP-29 group creation = kind 9 event with h tag, content = group name
if remote "nak event -k 9 -t h=$TEST_GROUP -c 'e2e test group' '$RELAY' --sec '$TEST_NSEC' >/dev/null 2>&1"; then
  ok "created group $TEST_GROUP (kind 9)"
else
  bad "group creation event rejected"; exit 1
fi

# hermes bot pubkey: derived from container env HERMES_NSEC, never printed
HERMES_PUB=$(remote "nak key public \"\$(docker exec $CONTAINER printenv HERMES_NSEC)\"" 2>/dev/null | tail -1 || true)
if [[ "$HERMES_PUB" =~ ^[0-9a-f]{64}$ ]]; then ok "hermes pubkey derived (offline)"; else bad "could not derive hermes pubkey"; exit 1; fi
if remote "nak group put-user \"${RELAY}'${TEST_GROUP}\" --pubkey $HERMES_PUB --role member --sec '$TEST_NSEC' >/dev/null 2>&1"; then
  ok "hermes added as group member (kind 9000)"
else
  bad "put-user hermes failed"; exit 1
fi

# ---------------------------------------------------------------------------
# P5 — point the Hermes container at the test group (restored in cleanup)
# ---------------------------------------------------------------------------
printf -- '-- P5 hermes listens on test group\n'
TENANT_DIR="/opt/tollgate/hermes/${CONTAINER#hermes-}"
ORIG_GROUPS=$(remote "docker exec $CONTAINER printenv NOSTR_GROUPS" 2>/dev/null | tail -1 || true)
if [ -n "$ORIG_GROUPS" ]; then
  if remote "cd $TENANT_DIR && (grep -q '^NOSTR_GROUPS=' .env && sed -i \"s|^NOSTR_GROUPS=.*|NOSTR_GROUPS=${TEST_GROUP}|\" .env || echo \"NOSTR_GROUPS=${TEST_GROUP}\" >> .env) && docker compose up -d >/dev/null 2>&1"; then
    ok "$CONTAINER retargeted to $TEST_GROUP"
  else
    bad "failed to retarget NOSTR_GROUPS"; exit 1
  fi
else
  bad "NOSTR_GROUPS not set in container env"; exit 1
fi

deadline=$(( $(date +%s) + 90 ))
until [ "$(remote "curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:9000/health" 2>/dev/null || true)" = 200 ]; do
  if [ "$(date +%s)" -ge $deadline ]; then bad "gateway did not become healthy after retarget"; exit 1; fi
  sleep 5
done
ok "gateway healthy again after retarget"
sleep 10   # nostr adapter (re)subscribe grace

# ---------------------------------------------------------------------------
# P6 — send a message as the test user (Buzz side of the chain)
# ---------------------------------------------------------------------------
printf -- '-- P6 send message\n'
NONCE=$(date +%s)
MSG="E2E test $NONCE: what is 2+2? Reply with the number."
SENT_AT=$(date +%s)
if remote "nak group chat send \"${RELAY}'${TEST_GROUP}\" '$MSG' --sec '$TEST_NSEC' >/dev/null 2>&1"; then
  ok "message sent to group as test user"
else
  bad "nak group chat send failed"; exit 1
fi

# ---------------------------------------------------------------------------
# P7 — wait for the bot's reply (authored by HERMES_PUB after SENT_AT)
# ---------------------------------------------------------------------------
printf -- '-- P7 await bot reply (max %ss)\n' "$E2E_TIMEOUT_SECS"
REPLY=""
deadline=$(( $(date +%s) + E2E_TIMEOUT_SECS ))
while [ "$(date +%s)" -lt $deadline ]; do
  REPLY=$(remote "timeout 25 nak req --auth -k 9 -a $HERMES_PUB --tag h=$TEST_GROUP $RELAY 2>/dev/null" </dev/null | grep -F '"kind":9' | tail -1 || true)
  [ -n "$REPLY" ] && break
  sleep 7
done
if [ -n "$REPLY" ]; then
  ok "bot replied in $(( $(date +%s) - SENT_AT ))s: $(echo "$REPLY" | grep -o '"content":"[^"]*"' | head -1 | cut -c12-100)"
else
  bad "no reply from hermes pubkey within ${E2E_TIMEOUT_SECS}s"; exit 1
fi

# ---------------------------------------------------------------------------
# P8 — LLM leg evidence in gateway logs (receive -> process -> respond)
# ---------------------------------------------------------------------------
printf -- '-- P8 LLM leg evidence\n'
EVID=$(remote "docker exec $CONTAINER sh -c 'tail -400 /opt/data/logs/agent.log 2>/dev/null | grep -iE \"(nostr|message|session|llm|complet).*(receiv|process|complet|respond|reply|send)\" | tail -4'" 2>/dev/null || true)
if [ -n "$EVID" ]; then
  ok "gateway log shows processing: $(echo "$EVID" | tail -1 | cut -c1-100)"
else
  bad "no processing evidence in agent.log"
fi

# ---------------------------------------------------------------------------
# summary (cleanup runs via EXIT trap)
# ---------------------------------------------------------------------------
printf '\n== RESULT: %d passed, %d failed ==\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
