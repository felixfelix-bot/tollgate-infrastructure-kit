# V2-03 — End-to-End: Buzz → relay → Hermes → LLM → response

Status: verified live on VPS2 (23.182.128.51) · 2026-08-14
Test: `tests/e2e-buzz-hermes.sh` · Plan: `PLAN-hermes-for-friends-v2.md` Task 3

## The chain under test

```
Buzz client (nak stands in for Buzz in CI)          VPS2
──────────────────────────────────────────────────────────────────────
[nak: ephemeral key]
   │ wss (NIP-01/42)
   ▼
[Caddy :443 relay.orangesync.tech] ──► [buzz-relay :3000 (127.0.0.1:3007)]
                                          │  NIP-29 group (kind 9, h=<group>)
                                          ▼
                                    [hermes-sitarani  nostr adapter]
                                          │  MessageEvent
                                          ▼
                                    [Hermes gateway :8080 → host :9000]
                                          │  LLM call (LLM_PROXY_URL)
                                          ▼
                                    [response signed & published as kind 9]
                                          ▼
[nak req observes the reply in the group] ◄────────┘
```

## How to run

```bash
./tests/e2e-buzz-hermes.sh                    # from the workstation
E2E_KEEP_GROUP=1 ./tests/e2e-buzz-hermes.sh   # keep the test group for debugging
```

Requires: ssh root access to VPS2, `nak` on VPS2, running `buzz-relay` and
`hermes-sitarani` containers. The script:

1. **P0/P1** pre-flight — ssh reachable, containers running, relay answers
   NIP-11 at `wss://relay.orangesync.tech`.
2. **P2/P3** gateway healthy on `:9000` and nostr adapter lines present in
   `/opt/data/logs/agent.log`.
3. **P4** creates an **ephemeral** NIP-29 group with a throwaway keypair
   (`nak key generate`), adds hermes-sitarani's npub as member (`put-user`).
4. **P5** retargets `NOSTR_GROUPS` in `/opt/tollgate/hermes/sitarani/.env` to
   the test group and recreates the container (`docker compose up -d`).
5. **P6** sends `"E2E test <ts>: what is 2+2?"` as the test user.
6. **P7** polls `nak req -k 9` for a reply authored by the bot's npub.
7. **P8** greps agent.log for receive/process/respond evidence (LLM leg).
8. **cleanup** restores the original `NOSTR_GROUPS`, recreates the container,
   deletes the test group (unless `E2E_KEEP_GROUP=1`).

Exit 0 only if every phase passes.

## Pitfalls found while bringing this up (all hit live)

1. **Root-owned log files kill the gateway silently.** If anything runs
   hermes as root inside the container (`docker exec` defaults to root!),
   `/opt/data/logs/{agent,errors}.log` become root-owned and the s6-supervised
   gateway (user `hermes`) crash-loops with
   `PermissionError: '/opt/data/logs/agent.log'`. The crash is visible only in
   `/opt/data/logs/gateway-exit-diag.log` — docker health stays green (see #3).
   Fix: `docker exec <c> chown hermes:hermes /opt/data/logs/*.log`.
   Prevention: always `docker exec -u hermes` (or root + chown after).
2. **`coincurve` missing from the image venv** — the nostr adapter signs
   outgoing events with BIP-340 via `coincurve`. Without it the adapter can
   receive but cannot reply (`RuntimeError: coincurve not installed`).
   Fix: `docker exec <c> /opt/hermes/.venv/bin/pip install coincurve`
   (runtime fix; bake it into the image build for permanence).
3. **Healthcheck false positive.** `pgrep -f 'hermes gateway run'` matches its
   own `sh -c` wrapper, so the container reports `healthy` even when the
   gateway is crash-looping or dead. Trust `curl :9000/health` instead.
4. **Docker-restart ≠ adapter up.** After `docker compose up -d`, wait for
   `/health` = 200 *and* a nostr line in agent.log before sending traffic.

## Manual reproduction (one-liners on VPS2)

```bash
# watch the group stream as a member
nak group chat monitor "wss://relay.orangesync.tech'<group-id>"

# send as a member
nak group chat send "wss://relay.orangesync.tech'<group-id>" "ping" --sec <nsec>

# observe everything in a group
nak req -k 9 --relay wss://relay.orangesync.tech 'h=<group-id>'
```
