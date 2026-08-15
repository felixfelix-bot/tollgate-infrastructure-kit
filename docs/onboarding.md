# Onboarding: Buzz Relay E2E Fixture Provisioning

The E2E test (`tests/e2e-buzz-hermes.sh`) uses permanent fixtures: a static e2e
member key and a dedicated e2e channel. These are provisioned **once** by the
operator and persist across runs. This runbook documents the exact commands.

## Background

The buzz relay (block/buzz) is a NIP-29 group-chat relay with strict admission:
`BUZZ_REQUIRE_RELAY_MEMBERSHIP=true` means every connecting key must be a
member of the relay community before NIP-42 AUTH succeeds. Anonymous keys are
rejected with `relay_membership_required`. The nostr adapter in hermes-sitarani
uses the bot key (enrolled as community admin). The E2E test needs a second
key (the "e2e member") that stands in for a friend's Buzz client.

## Prerequisites

- SSH root access to VPS2 (23.182.128.51)
- `nak` CLI v0.20.x on VPS2
- buzz-relay + buzz-relay-postgres containers running
- hermes-sitarani container running

## Variables used throughout

```bash
RELAY="wss://relay.orangesync.tech"
E2E_DIR=/opt/data/e2e
COMMUNITY="a3312780-4cfe-48eb-af8a-f405f369a4f8"   # the relay community uuid

# admin key (relay owner) — from buzz-relay container env
ADMIN_SEC=$(docker inspect buzz-relay --format '{{range .Config.Env}}{{println .}}{{end}}' \
  | grep '^BUZZ_RELAY_PRIVATE_KEY=' | cut -d= -f2- | tr -d '\r')

# hermes bot key (community admin) — from sitarani container env
BOT_SEC=$(docker exec hermes-sitarani printenv HERMES_NSEC)
BOT_PUB=$(nak key public "$BOT_SEC" </dev/null 2>/dev/null | tail -1)
```

## Step 1: Generate fixtures (once)

```bash
mkdir -p $E2E_DIR && chmod 700 $E2E_DIR

# static member identity (persists across runs)
nak key generate </dev/null 2>/dev/null | tail -1 > $E2E_DIR/member-nsec
chmod 600 $E2E_DIR/member-nsec

# static group id (uuid v4 lowercase — relay enforces this grammar)
cat /proc/sys/kernel/random/uuid | tr -d '\n' > $E2E_DIR/group-id

E2E_SEC=$(cat $E2E_DIR/member-nsec)
E2E_PUB=$(nak key public "$E2E_SEC" </dev/null 2>/dev/null | tail -1)
E2E_GROUP=$(cat $E2E_DIR/group-id)

echo "member pubkey: $E2E_PUB"
echo "group id:      $E2E_GROUP"
```

## Step 2: Create the e2e channel (kind 9007, admin-signed)

The relay only accepts channel-creation events (kind 9007) signed by the
relay admin key. Anonymous channel creation is rejected.

```bash
nak event --fpa -k 9007 -t h=$E2E_GROUP -c 'e2e' $RELAY --sec "$ADMIN_SEC" </dev/null 2>&1
# expect: "publishing to relay.orangesync.tech... success."
```

## Step 3: Enroll member + bot in the e2e channel (kind 9000, admin-signed)

```bash
# e2e member → channel member
nak event --fpa -k 9000 -t h=$E2E_GROUP -t p=$E2E_PUB -c 'member' $RELAY --sec "$ADMIN_SEC" </dev/null 2>&1

# hermes bot → channel member (so it can subscribe + reply)
nak event --fpa -k 9000 -t h=$E2E_GROUP -t p=$BOT_PUB -c 'member' $RELAY --sec "$ADMIN_SEC" </dev/null 2>&1
```

## Step 4: Enroll e2e member in the relay community (DB INSERT)

**This is the critical step.** The kind-9000 community enrollment event does
not reliably persist to the `relay_members` table (the relay's NIP-42 AUTH
check reads from this table, not from events). The only method that works is
a direct DB INSERT:

```bash
PG=buzz-relay-postgres
docker exec $PG psql -U buzz -d buzz -c "
  INSERT INTO relay_members (community_id, pubkey, role, added_by, created_at, updated_at)
  SELECT '${COMMUNITY}'::uuid, decode('${E2E_PUB}','hex'), 'member', 'e2e-fixtures', now(), now()
  WHERE NOT EXISTS (
    SELECT 1 FROM relay_members
    WHERE community_id='${COMMUNITY}'::uuid AND pubkey=decode('${E2E_PUB}','hex')
  )"
```

Note: `pubkey` column is bytea — use `decode('…','hex')`, not a plain string.

## Step 5: Verify

```bash
# member can NIP-42-auth + read + write
timeout 15 nak req --fpa -k 9 -t h=$E2E_GROUP $RELAY --sec "$E2E_SEC" </dev/null 2>&1 | tail -2
nak event --fpa -k 9 -t h=$E2E_GROUP -c "fixture verify $(date +%s)" $RELAY --sec "$E2E_SEC" </dev/null 2>&1 | grep publishing

# bot can read the channel
timeout 15 nak req --fpa -k 9 -t h=$E2E_GROUP $RELAY --sec "$BOT_SEC" </dev/null 2>&1 | grep -c kind

# DB state
docker exec $PG psql -U buzz -d buzz -c "select pubkey, role, added_by from relay_members"
```

All three checks should succeed (member read returns events or empty, member
write says "success.", bot read returns events without error).

## Pitfalls

1. **nak 0.20.x `nak group` subcommands never NIP-42-auth** — use `nak event --fpa` and `nak req --fpa` instead.
2. **`nak event` exits 0 even on relay rejection** — always parse the `publishing … success.` / `failed:` line.
3. **h tag grammar is uuid-v4-lowercase** — no-dash or uppercase uuids are rejected.
4. **kind-9000 to the community uuid does NOT create a relay_members row** — use the DB INSERT (step 4).
5. **All nak invocations need `</dev/null`** — nak consumes stdin and will hang scripts otherwise.
6. **Disk pressure causes relay writes to fail with "rate-limited: shared admission unavailable"** — this is
   misleading; free disk space and retry.
