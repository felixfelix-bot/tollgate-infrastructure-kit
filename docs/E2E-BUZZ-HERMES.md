# V2-03 — End-to-End: Buzz → relay → Hermes → LLM → response

Status: fixed-channel flow (decision B, 2026-08-15) · Test: `tests/e2e-buzz-hermes.sh`
Plan: `PLAN-hermes-for-friends-v2.md` Task 3 · Fixtures: `docs/onboarding.md`

## The chain under test

```
Buzz client (nak stands in for Buzz in CI)          VPS2
──────────────────────────────────────────────────────────────────────
[e2e member key — permanent fixture, /opt/data/e2e/member-nsec]
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
[nak req observes the reply in the group] ◄─────────┘
```

## How to run

```bash
./tests/e2e-buzz-hermes.sh
```

Requires: ssh root access to VPS2, `nak` on VPS2, running `buzz-relay` and
`hermes-sitarani` containers, and permanent e2e fixtures (see
`docs/onboarding.md` for provisioning). The script:

1. **P0** pre-flight — ssh reachable, containers running, load < 15, disk > 50MB free.
2. **P1** relay answers NIP-11 at `wss://relay.orangesync.tech`.
3. **P2** gateway healthy on `:9000` (exit on failure).
4. **P3** nostr adapter lines present in `/opt/data/logs/agent.log`.
5. **P4** fixture verification (not creation): `/opt/data/e2e/member-nsec`
   exists with 0600 perms, group id is uuid v4, member key can auth + write +
   read back, bot key can read the e2e channel.
6. **P5** retargets `NOSTR_GROUPS` to the e2e channel, recreates the container,
   waits for `/health` = 200. Restored in cleanup.
7. **P6** sends `"E2E test <ts>: what is 2+2?"` as the e2e member, mentioning
   the bot's pubkey. Parses the `publishing … success.` line (nak exit code
   lies on rejection).
8. **P7** polls `nak req -k 9 -a <bot-pub>` for a reply newer than SENT_AT.
   On failure: continues to P8 (does NOT exit).
9. **P8** greps agent.log for receive/process/respond evidence (LLM leg).
10. **cleanup** restores original `NOSTR_GROUPS`, recreates the container,
    verifies restore. E2e channel + member key persist.

Exit 0 only if every phase passes (P7 failure = non-zero exit but P8 evidence
is still captured for delta analysis).

## Permanent fixtures (provision once, see docs/onboarding.md)

- `/opt/data/e2e/member-nsec` — static e2e member identity (0600)
- `/opt/data/e2e/group-id` — dedicated e2e channel id (uuid v4 lowercase)
- e2e member + bot enrolled in channel via admin-signed kind 9000
- e2e member enrolled in relay community via DB INSERT (NIP-42 auth gate)

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
   outgoing events with BIP-340 via `coincurve`. Without it the adapter
   can receive but cannot reply (`RuntimeError: coincurve not installed`).
   Fix: `docker exec <c> /opt/hermes/.venv/bin/pip install coincurve`
   (runtime fix; bake it into the image build for permanence — T2.1).
3. **Healthcheck false positive.** `pgrep -f 'hermes gateway run'` matches its
   own `sh -c` wrapper, so the container reports `healthy` even when the
   gateway is crash-looping or dead. Trust `curl :9000/health` instead.
4. **Docker-restart ≠ adapter up.** After `docker compose up -d`, wait for
   `/health` = 200 *and* a nostr line in agent.log before sending traffic.
5. **nak 0.20.x `nak group` subcommands never NIP-42-auth** — use `nak event --fpa` / `nak req --fpa`.
6. **`nak event` exits 0 on relay rejection** — parse the `publishing … success.` / `failed:` line.
7. **h tag grammar is uuid-v4-lowercase** — no-dash or uppercase uuids rejected.
8. **kind-9000 community event does not create relay_members row** — use DB INSERT (see onboarding.md).
9. **Disk pressure causes relay writes to fail** with "rate-limited: shared admission unavailable" — misleading; free disk and retry.
