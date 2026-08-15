#!/usr/bin/env bash
# =============================================================================
# V2-03 (run 3, decision B): End-to-End Buzz -> relay -> Hermes -> LLM -> response
# Board: hermes-for-friends | Plan: PLAN-hermes-for-friends-v2.md Task 3
#
# Proves the full chain on the LIVE VPS2 (23.182.128.51):
#
#   [e2e member key (stands in for a friend's Buzz client)]
#     --wss--> [Caddy :443 relay.orangesync.tech]
#     --> [buzz-relay NIP-29 (127.0.0.1:3007 -> :3000)]
#     --> [hermes-sitarani nostr adapter]
#     --> [Hermes gateway :8080 -> host :9000]
#     --> [LLM via LLM_PROXY_URL]
#     --> [signed kind-9 reply published to the group]
#     --> [observed via nak req]
#
# FIXED-CHANNEL FLOW (decision B, 2026-08-15): instead of provisioning an
# ephemeral group per run (blocked: kind-9/9000 from non-admin keys is
# restricted; nak group subcommands never NIP-42-auth), this run uses
# permanent fixtures provisioned ONCE by the operator:
#
#   /opt/data/e2e/member-nsec   static e2e member identity (0600)
#   /opt/data/e2e/group-id      dedicated e2e channel id (uuid v4)
#
# Provisioning (owner-signed kind 9007 create-group + kind 9000 put-user +
# relay_members enrollment) is documented verbatim in docs/onboarding.md.
# The e2e channel and member key PERSIST across runs; cleanup only restores
# the container's original NOSTR_GROUPS.
#
# Usage:
#   ./tests/e2e-buzz-hermes.sh
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
E2E_DIR=/opt/data/e2e

PASS=0; FAIL=0
note()   { printf '       %s\n' "$*"; }
ok()     { PASS=$((PASS+1)); printf '[PASS] %s\n' "$*"; }
bad()    { FAIL=$((FAIL+1)); printf '[FAIL] %s\n' "$*"; }
remote() { ssh -o ConnectTimeout=25 "$VPS2_HOST" "$*"; }

CLEANUP_OWNER=0
ORIG_GROUPS=""

cleanup() {
  if [ "$CLEANUP_OWNER" = 1 ]; then
    printf '\n== cleanup ==\n'
    if [ -n "$ORIG_GROUPS" ]; then
      if remote "cd /opt/tollgate/hermes/${CONTAINER#hermes-} && (grep -q '^NOSTR_GROUPS=' .env && sed -i \"s|^NOSTR_GROUPS=.*|NOSTR_GROUPS=${ORIG_GROUPS}|\" .env || echo \"NOSTR_GROUPS=${ORIG_GROUPS}\" >> .env) && docker compose up -d >/dev/null 2>&1"; then
        note "restored NOSTR_GROUPS=${ORIG_GROUPS}"
        deadline=$(( $(date +%s) + 90 ))
        until [ "$(remote "curl -s -o /dev/null -w '%{http_code}' -m 5 http://localhost:9000/health" 2>/dev/null || true)" = 200 ]; do
          [ "$(date +%s)" -ge $deadline ] && { bad "gateway unhealthy after restore"; break; }
          sleep 5
        done
        RESTORED=$(remote "docker exec $CONTAINER printenv NOSTR_GROUPS" 2>/dev/null | tail -1 || true)
        if [ "$RESTORED" = "$ORIG_GROUPS" ]; then
          note "restore verified: container NOSTR_GROUPS=$RESTORED"
        else
          bad "restore mismatch: container NOSTR_GROUPS=${RESTORED:-none} (expected $ORIG_GROUPS)"
        fi
      else
        bad "could not restore NOSTR_GROUPS — manual fix: /opt/tollgate/hermes/${CONTAINER#hermes-}/.env"
      fi
    fi
    note "e2e channel + member key left in place (permanent fixtures, see docs/onboarding.md)"
  fi
}
trap cleanup EXIT

printf 'V2-03 E2E (fixed-channel, run 3): Buzz -> relay -> Hermes -> LLM -> response\n'
printf 'target: %s  container: %s  relay: %s\n\n' "$VPS2_HOST" "$CONTAINER" "$RELAY"

# ---------------------------------------------------------------------------
# P0 — pre-flight: host reachable, containers up, nak present, load, disk
# ---------------------------------------------------------------------------
printf -- '-- P0 pre-flight\n'
if remote "true" 2>/dev/null; then ok "ssh $VPS2_HOST reachable"; else bad "ssh $VPS2_HOST unreachable"; exit 1; fi
if remote "docker inspect -f '{{.State.Running}}' buzz-relay" 2>/dev/null | grep -q true; then ok "buzz-relay running"; else bad "buzz-relay not running"; exit 1; fi
if remote "docker inspect -f '{{.State.Running}}' $CONTAINER" 2>/dev/null | grep -q true; then ok "$CONTAINER running"; else bad "$CONTAINER not running"; exit 1; fi
if remote "command -v nak" 2>/dev/null | grep -q nak; then ok "nak CLI present on VPS2"; else bad "nak CLI missing on VPS2"; exit 1; fi

LOAD15=$(remote "awk '{print \$3}' /proc/loadavg" 2>/dev/null || echo 0)
if remote "awk '{exit !(\$3>15)}' /proc/loadavg" 2>/dev/null; then
  note "load(15m)=${LOAD15} > 15 — pausing up to 120s for load to drop"
  deadline=$(( $(date +%s) + 120 ))
  while remote "awk '{exit !(\$3>15)}' /proc/loadavg" 2>/dev/null; do
    [ "$(date +%s)" -ge $deadline ] && { bad "load still >15 after 120s — aborting"; exit 1; }
    sleep 15
  done
fi
ok "load(15m)=${LOAD15} acceptable"

AVAIL_MB=$(remote "df -BM --output=avail / | tail -1 | tr -dc '0-9'" 2>/dev/null || echo 0)
if [ "${AVAIL_MB:-0}" -lt 50 ]; then
  bad "only ${AVAIL_MB}MB free on / — too low for container recreate"; exit 1
elif [ "${AVAIL_MB:-0}" -lt 150 ]; then
  note "warning: only ${AVAIL_MB}MB free on /"
fi
ok "disk: ${AVAIL_MB}MB free on /"

# ---------------------------------------------------------------------------
# P1 — relay reachable: NIP-11 document over https/wss (Buzz entry point)
# ---------------------------------------------------------------------------
printf -- '-- P1 relay reachable\n'
if remote "nak relay '$RELAY' 2>/dev/null | head -2" </dev/null | grep -q '"name"'; then
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
if [ "$GW_CODE" = 200 ]; then ok "gateway /health = 200 on :9000"; else bad "gateway /health = ${GW_CODE:-none} on :9000"; exit 1; fi

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
# P4 — fixtures: static e2e member key + dedicated e2e channel (verify only)
# Provisioned once by operator; see docs/onboarding.md. Assert:
#   files exist, member can NIP-42-auth, write, and read back its own event,
#   and the hermes bot key can read the channel.
# ---------------------------------------------------------------------------
printf -- '-- P4 e2e fixtures (fixed channel)\n'
if remote "test -s $E2E_DIR/member-nsec && test \$(stat -c %a $E2E_DIR/member-nsec) = 600" 2>/dev/null; then
  ok "$E2E_DIR/member-nsec present (0600)"
else
  bad "$E2E_DIR/member-nsec missing or perms wrong — see docs/onboarding.md provisioning"; exit 1
fi
E2E_GROUP=$(remote "cat $E2E_DIR/group-id" 2>/dev/null | tr -d ' \n' || true)
if [[ "$E2E_GROUP" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  ok "e2e channel id: $E2E_GROUP"
else
  bad "$E2E_DIR/group-id missing or not a uuid v4"; exit 1
fi

# member write + read-back (auth exercised implicitly via --fpa)
NONCE4="p4-$(date +%s)"
PUB4=$(remote "SEC=\$(cat $E2E_DIR/member-nsec); nak event --fpa -k 9 -t h=$E2E_GROUP -c 'e2e fixture $NONCE4' '$RELAY' --sec \"\$SEC\" </dev/null 2>&1 | grep -E 'publishing' | tail -1" 2>/dev/null || true)
if echo "$PUB4" | grep -q 'success'; then
  ok "member key auth + kind-9 write accepted"
else
  bad "member write rejected: ${PUB4:-no output}"; exit 1
fi
sleep 2
READBACK=$(remote "SEC=\$(cat $E2E_DIR/member-nsec); timeout 15 nak req --fpa -k 9 -t h=$E2E_GROUP '$RELAY' --sec \"\$SEC\" </dev/null 2>&1 | grep -F '$NONCE4' | tail -1" 2>/dev/null || true)
if [ -n "$READBACK" ]; then
  ok "member read-back of own event verified"
else
  bad "member could not read back its own event"; exit 1
fi

# hermes bot pubkey (derived from container env, never printed as nsec) + bot read access
HERMES_PUB=$(remote "nak key public \"\$(docker exec $CONTAINER printenv HERMES_NSEC)\" </dev/null" 2>/dev/null | tail -1 || true)
if [[ "$HERMES_PUB" =~ ^[0-9a-f]{64}$ ]]; then ok "hermes pubkey derived (offline)"; else bad "could not derive hermes pubkey"; exit 1; fi
BOTREAD=$(remote "SEC=\$(docker exec $CONTAINER printenv HERMES_NSEC); timeout 15 nak req --fpa -k 9 -t h=$E2E_GROUP '$RELAY' --sec \"\$SEC\" </dev/null 2>&1 | grep -vE '^connecting|^authenticating|^waiting' | tail -1" 2>/dev/null || true)
if ! echo "$BOTREAD" | grep -qiE 'restricted|auth-required|failed|error|closed'; then
  ok "hermes bot key can read e2e channel"
else
  bad "hermes bot key cannot read e2e channel: $BOTREAD"; exit 1
fi
CLEANUP_OWNER=1   # from here on we own state that must be restored

# ---------------------------------------------------------------------------
# P5 — point the Hermes container at the e2e channel (restored in cleanup)
# ---------------------------------------------------------------------------
printf -- '-- P5 hermes listens on e2e channel\n'
TENANT_DIR="/opt/tollgate/hermes/${CONTAINER#hermes-}"
ORIG_GROUPS=$(remote "docker exec $CONTAINER printenv NOSTR_GROUPS" 2>/dev/null | tail -1 || true)
if [ -n "$ORIG_GROUPS" ]; then
  if remote "cd $TENANT_DIR && (grep -q '^NOSTR_GROUPS=' .env && sed -i \"s|^NOSTR_GROUPS=.*|NOSTR_GROUPS=${E2E_GROUP}|\" .env || echo \"NOSTR_GROUPS=${E2E_GROUP}\" >> .env) && docker compose up -d >/dev/null 2>&1"; then
    ok "$CONTAINER retargeted to $E2E_GROUP"
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
# P6 — send a message as the e2e member (Buzz side of the chain)
# nak's exit code lies on publish rejection — parse the publishing result line.
# ---------------------------------------------------------------------------
printf -- '-- P6 send message\n'
NONCE=$(date +%s)
MSG="E2E test $NONCE: what is 2+2? Reply with the number."
SENT_AT=$(date +%s)
PUB6=$(remote "SEC=\$(cat $E2E_DIR/member-nsec); nak event --fpa -k 9 -t h=$E2E_GROUP -t p=$HERMES_PUB -c '$MSG' '$RELAY' --sec \"\$SEC\" </dev/null 2>&1 | grep -E 'publishing' | tail -1" 2>/dev/null || true)
if echo "$PUB6" | grep -q 'success'; then
  ok "message sent to e2e channel as member (mentioning bot)"
else
  bad "message publish rejected: ${PUB6:-no output}"; exit 1
fi

# ---------------------------------------------------------------------------
# P7 — wait for the bot's reply (authored by HERMES_PUB, newer than our send)
# ---------------------------------------------------------------------------
printf -- '-- P7 await bot reply (max %ss)\n' "$E2E_TIMEOUT_SECS"
REPLY=""
deadline=$(( $(date +%s) + E2E_TIMEOUT_SECS ))
while [ "$(date +%s)" -lt $deadline ]; do
  REPLY=$(remote "SEC=\$(cat $E2E_DIR/member-nsec); timeout 25 nak req --fpa -k 9 -a $HERMES_PUB -t h=$E2E_GROUP '$RELAY' --sec \"\$SEC\" </dev/null 2>/dev/null" </dev/null | grep -F '"kind":9' | tail -1 || true)
  REPLY_TS=$(echo "$REPLY" | grep -oE '"created_at": ?[0-9]+' | grep -oE '[0-9]+' | tail -1 || echo 0)
  [ -n "$REPLY" ] && [ "${REPLY_TS:-0}" -ge "$SENT_AT" ] && break
  REPLY=""
  sleep 7
done
if [ -n "$REPLY" ]; then
  ok "bot replied in $(( $(date +%s) - SENT_AT ))s: $(echo "$REPLY" | grep -o '"content":"[^"]*"' | head -1 | cut -c12-100)"
else
  bad "no reply from hermes pubkey within ${E2E_TIMEOUT_SECS}s"
  note "delta: relay accepted our write (P4/P6 proven) — remaining leg is hermes adapter/LLM; check P8 evidence"
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
