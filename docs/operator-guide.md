# Operator Guide — Hermes for Friends

Operations runbook for the operator (Felix). This is the counterpart to
`docs/onboarding-friend-guide.md` (what friends see). Everything here is written
against the **live VPS2 deployment** (verified Aug 2026):

- Containers: `hermes-sitarani`, `hermes-chiefmonkey`, `hermes-bekka`,
  `buzz-relay` (+ `buzz-relay-postgres`, `buzz-relay-redis`), `routstr-proxy`,
  `cdk-mintd`, `mint-orchestrator`, `tollgate-strfry`, `tollgate-strfry-agg`,
  `tollgate-nsite-gateway`, `blossom`, `ngit`
- Caddy runs as a **host systemd service** (`caddy`, config
  `/etc/caddy/Caddyfile`) — it is *not* a container. (An unused docker-caddy
  setup exists at `/opt/tollgate/caddy/` — ignore it.)

Related docs: `INTEGRATED-OPERATIONS.md` (overall infra), `services.md`
(service inventory), `troubleshooting.md`, `FIPS-MESH-OPERATIONS.md` (mesh),
`docs/onboarding-friend-guide.md` (friend-facing).

---

## 1. Architecture

```text
Internet
    │
    ▼
Caddy  (host systemd, :80/:443, /etc/caddy/Caddyfile)
    │
    ├── relay.orangesync.tech ──► 127.0.0.1:3007  buzz-relay
    │                                 │           (NIP-42 AUTH, NIP-29 groups)
    │                                 ├── buzz-relay-postgres
    │                                 └── buzz-relay-redis
    │
    ├── ai.orangesync.tech ─────► localhost:8009  routstr-proxy
    │                                 (LLM proxy, z.ai GLM, per-friend API keys)
    │
    ├── mint.orangesync.tech ───► localhost:8085  cdk-mintd
    │                                 (Cashu mint)
    │                                 ▲
    │                                 └── mint-orchestrator
    │                                     (watches kind:38010 approvals on the
    │                                      relay, mints Cashu tokens)
    │
    └── hermes-mesh.fips ───────► Hermes tenant gateways (:9000-9002)

Hermes tenants:   hermes-sitarani :9000   hermes-chiefmonkey :9001
                  hermes-bekka    :9002   (image hermes-agent:nostr)

FIPS mesh routes (from mesh machines):
    http://buzz-relay.fips  → 3007     http://routstr.fips → 8009
    http://mint.fips        → 8085
```

Notes:

- **One relay for friends.** `wss://relay.orangesync.tech` is the Buzz relay
  (NIP-29 group chat + NIP-42 auth). There is **no** `chat.` subdomain — do not
  hand friends a `wss://chat.…` URL. (The relay serves its NIP-11-style JSON
  at `https://relay.orangesync.tech/` — handy as a health check.)
- strfry (`tollgate-strfry`, 127.0.0.1:7777) is internal infrastructure, not
  the friends' chat relay. Friends never connect to it.
- **LLM proxy**: routstr-proxy, host port **8009** (container port 8000).
  Compose/config lives in `/home/debian/routstr/`. Public URL
  `https://ai.orangesync.tech` (self-identifies at `/v1/info`).
- **Mint**: cdk-mintd on localhost:8085, public `https://mint.orangesync.tech`
  (also `http://mint.fips` over the mesh).
- **routstrd sidecar (V2-07)** is being integrated per-tenant; until it lands,
  tenants reach the LLM proxy through `routstr-proxy` at
  `https://ai.orangesync.tech`.

### Where things live

| Component | Path on VPS2 |
|---|---|
| Caddy config | `/etc/caddy/Caddyfile` (host systemd unit `caddy`) |
| Buzz relay compose | `/opt/buzz-relay/docker-compose.yml` |
| Hermes tenant dirs | `/opt/tollgate/hermes/<tenant>/` (sitarani, chiefmonkey, bekka) |
| routstr compose | `/home/debian/routstr/` |
| This kit (ansible, scripts, docs) | `~/tollgate-infrastructure-kit` |

### URL map

| URL | Service | Purpose |
|---|---|---|
| `wss://relay.orangesync.tech` | buzz-relay (127.0.0.1:3007) | Friends' NIP-29 groups, NIP-42 auth |
| `https://ai.orangesync.tech` | routstr-proxy (:8009) | LLM proxy for Hermes tenants |
| `https://mint.orangesync.tech` | cdk-mintd (:8085) | Cashu mint backing AI credits |
| `https://relay.orangesync.tech/` | buzz-relay | NIP-11-style status JSON (health check) |

---

## 2. Adding a friend

Prerequisites: ssh access (`ssh debian@vps2.fips` from a mesh machine, or
`root@23.182.128.51`), the friend's npub, and a name for their tenant
(short, lowercase — e.g. `chiefmonkey`).

### Step 1 — Get the friend set up on the mesh (optional but recommended)

Have the friend complete Sections 1–4 of `docs/onboarding-friend-guide.md`:
install FIPS, add your mesh peer config, install the Buzz desktop app (their
identity is created there — the mobile app is only a paired companion and
cannot create one), and send you the npub from desktop Settings → Profile.
If they are not on the mesh, they can still use the relay over the public
internet — the mesh is a convenience, not a requirement.

### Step 2 — Create their NIP-29 group on the relay

The relay is a full NIP-29 implementation. As the group admin (a key the relay
already recognises — check `BUZZ_ADMIN_*` / env in `/opt/buzz-relay/docker-compose.yml`),
create a group and add the friend:

```bash
# create-group (kind 9007) — h tag is the group id (use the tenant name)
nak event --sec <admin-nsec> --kind 9007 \
  --tag h=<tenant-name> \
  --tag name="<Friend Name>" \
  --relay wss://relay.orangesync.tech

# put-user (kind 9000) — adds the friend's pubkey to the group
nak event --sec <admin-nsec> --kind 9000 \
  --tag h=<tenant-name> \
  --tag p=<friend-pubkey-hex> \
  --relay wss://relay.orangesync.tech
```

NIP-29 admin kinds for reference (see NIP-29 for the full list):

| Kind | Meaning |
|---|---|
| 9007 | create-group |
| 9000 | put-user (add member) |
| 9001 | remove-user |
| 9002 | edit-metadata |
| 9008 | delete-group |
| 9021 | join request (sent by users) |

> If you do not have an admin key handy, you can also create the group from
> the Buzz client itself (signed in as your admin identity) — the relay treats
> the group creator as its admin.

### Step 3 — Whitelist the friend for NIP-42 auth

The relay challenges every connection (NIP-42). Access is controlled from
`/opt/buzz-relay/docker-compose.yml` (env vars such as
`BUZZ_REQUIRE_AUTH_TOKEN`, `BUZZ_REQUIRE_RELAY_MEMBERSHIP`) plus group
membership from Step 2:

```bash
cd /opt/buzz-relay
# review env: BUZZ_REQUIRE_AUTH_TOKEN / BUZZ_REQUIRE_RELAY_MEMBERSHIP / etc.
$EDITOR docker-compose.yml
docker compose up -d      # recreate with new env
docker logs buzz-relay --tail 20
```

Buzz clients complete the NIP-42 challenge automatically — friends never see
this step; it just works when their key is authorised.

### Step 4 — Deploy their Hermes tenant

Per-tenant compose lives in `/opt/tollgate/hermes/<tenant>/`:

```bash
ssh debian@vps2.fips
cd /opt/tollgate/hermes/<tenant>
$EDITOR docker-compose.yml       # tenant name, ports, gateway, LLM proxy URL
docker compose up -d
docker ps --filter name=hermes-<tenant>
docker logs hermes-<tenant> --tail 50
```

Conventions: container `hermes-<tenant>`, network `hermes-net-<tenant>`,
gateway port 9000 (sitarani) / 9001 (chiefmonkey) / 9002 (bekka). Volumes must
be **copied**, never recreated, when migrating (see `PLAN-hermes-for-friends-v2.md`).

The tenant's LLM access goes through the proxy:

```yaml
# inside the tenant compose / env
LLM_PROXY_URL: "https://ai.orangesync.tech"
```

### Step 5 — Create their LLM proxy key

routstr-proxy holds one API key per friend with isolated quota. Its config is
managed in `/home/debian/routstr/` (compose + env):

```bash
cd /home/debian/routstr
$EDITOR .env            # add the friend's key / quota entry
docker compose up -d
curl -s http://localhost:8009/v1/info | head    # confirm the node answers
```

Then reference that key in the tenant's environment (Step 4).

### Step 6 — Point the friend at the right relay

Send the friend:

- relay URL: `wss://relay.orangesync.tech`
- their group name (they join via the invite you created in Step 2)
- the onboarding guide: `docs/onboarding-friend-guide.md`

### Step 7 — Smoke test

```bash
# relay healthy?
curl -s https://relay.orangesync.tech/ | head -c 200
# tenant healthy?
docker ps --filter name=hermes-<tenant> --format '{{.Names}} {{.Status}}'
# have the friend send "@<botname> ping" in the group and watch it arrive:
docker logs -f hermes-<tenant>
```

---

## 3. Removing a friend

```bash
# 1. Remove from the NIP-29 group (kind 9001, remove-user)
nak event --sec <admin-nsec> --kind 9001 \
  --tag h=<tenant-name> --tag p=<friend-pubkey-hex> \
  --relay wss://relay.orangesync.tech

# 2. Stop their Hermes tenant
cd /opt/tollgate/hermes/<tenant> && docker compose down

# 3. Revoke their LLM proxy key (edit + recreate routstr-proxy)
cd /home/debian/routstr && $EDITOR .env && docker compose up -d

# 4. Optional: delete the group entirely (kind 9008)
nak event --sec <admin-nsec> --kind 9008 \
  --tag h=<tenant-name> --relay wss://relay.orangesync.tech
```

Keep the tenant's data volume until you are sure they will not return
(backup first — Section 7).

---

## 4. Issuing AI credits (Cashu)

The credits pipeline:

```text
you publish kind:38010 #mint-approval on the relay
        → mint-orchestrator sees it (watches the relay)
        → cdk-mintd mints Cashu tokens (mint.orangesync.tech)
        → tokens land in the friend's Hermes wallet
        → Hermes spends them at the LLM proxy (routstr)
```

Approvals are published with the kit's CLI (`mint-approve/src/tollgate_mint_approve/cli.py`):

```bash
cd ~/tollgate-infrastructure-kit/mint-approve/src
python -m tollgate_mint_approve.cli \
  --nsec  <operator-nsec> \
  --mint  https://mint.orangesync.tech \
  --quote <quote-or-reference> \
  --amount <sats> \
  --unit  sat
  # --relay defaults to wss://relay.orangesync.tech
```

> Never paste a real nsec into shell history — prefer a bunker or prompt.

Verify the pipeline end-to-end:

```bash
docker logs mint-orchestrator --tail 30   # should log the approval + mint
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8085/   # mint answers (200)
# then ask the friend to check their balance in the group ("balance")
```

---

## 5. Monitoring and health checks

Quick daily check (safe to run any time):

```bash
ssh debian@vps2.fips '
  docker ps --format "{{.Names}}\t{{.Status}}" | sort
  echo ---
  curl -s -o /dev/null -w "relay:%{http_code}\n"  https://relay.orangesync.tech/
  curl -s -o /dev/null -w "ai:%{http_code}\n"     https://ai.orangesync.tech/
  curl -s -o /dev/null -w "mint:%{http_code}\n"   http://localhost:8085/
'
```

What "healthy" looks like:

- `docker ps`: all containers `Up ... (healthy)` — especially the three
  `hermes-*` tenants, `buzz-relay`, `routstr-proxy`, `cdk-mintd`,
  `mint-orchestrator`
- `relay:` → `200` (Buzz Relay status JSON)
- `ai:` → `200`
- `mint:` → `200`

Logs by component:

| Component | Command |
|---|---|
| Hermes tenant | `docker logs -f hermes-<tenant>` |
| Relay | `docker logs -f buzz-relay` |
| Relay DB | `docker logs buzz-relay-postgres --tail 50` |
| LLM proxy | `docker logs -f routstr-proxy` |
| Mint | `docker logs -f cdk-mintd` |
| Credit approvals | `docker logs -f mint-orchestrator` |
| Caddy (TLS/routing) | `journalctl -u caddy -f` |
| Host | `journalctl -xe --no-pager | tail -50` |

A `tollgate-watchdog` unit exists for auto-restarts but is currently
**inactive** — do not rely on it until it is enabled deliberately.

---

## 6. Updating Hermes images

The tenants run `hermes-agent:nostr` (s6-overlay, Python 3.13). To roll a new
image:

```bash
ssh debian@vps2.fips
docker pull hermes-agent:nostr          # or build/tag your updated image
for t in sitarani chiefmonkey bekka; do
  (cd /opt/tollgate/hermes/$t && docker compose up -d)
done
docker ps --format '{{.Names}}\t{{.Status}}' | grep hermes-
```

Roll one tenant first, smoke test (`@bot ping` in its group), then the rest.
Volumes are preserved across `up -d` recreations — never delete them.

---

## 7. Backup and restore

What matters, in order:

1. **Relay state** — group definitions and membership live in postgres:

```bash
ssh debian@vps2.fips
docker exec buzz-relay-postgres pg_dump -U <pg-user> buzz > \
  ~/backups/buzz-relay-$(date +%F).sql    # adjust db/user from /opt/buzz-relay compose
```

2. **Hermes tenant volumes** (agent data, kanban DBs, memories):

```bash
docker run --rm -v <volume>:/src -v ~/backups:/dst alpine \
  tar czf /dst/<tenant>-$(date +%F).tgz -C /src .
```

3. **Config trees**: `/opt/buzz-relay/`, `/opt/tollgate/hermes/`,
   `/home/debian/routstr/`, `/etc/caddy/Caddyfile`, and this kit (git remote).

Restore = recreate the compose project, then restore the volume tarball /
`psql < dump`. Test the restore path at least once before you need it.

---

## 8. Relay and group management

```bash
# relay status JSON (also proves Caddy + WebSocket routing)
curl -s https://relay.orangesync.tech/ | head -c 300

# restart the relay stack
cd /opt/buzz-relay && docker compose restart

# edit relay config (NIP-42 requirements, admin, membership policy)
cd /opt/buzz-relay && $EDITOR docker-compose.yml && docker compose up -d

# relay logs (auth failures show up here with the client pubkey)
docker logs buzz-relay --tail 100

# Caddy: routing for relay./ai./mint. lives in /etc/caddy/Caddyfile
#   relay.orangesync.tech  → reverse_proxy localhost:3007
#   ai.orangesync.tech     → reverse_proxy localhost:8009
#   mint.orangesync.tech   → reverse_proxy localhost:8085
sudo $EDITOR /etc/caddy/Caddyfile && sudo systemctl reload caddy
journalctl -u caddy --since today | tail -30
```

Group operations (as admin, all via `nak … --relay wss://relay.orangesync.tech`):
create `9007`, add member `9000`, remove member `9001`, edit metadata `9002`,
delete group `9008`. See the NIP-29 table in Section 2.

---

## 9. Troubleshooting

**Friend cannot connect / sees no groups**

1. `curl -s https://relay.orangesync.tech/` → 200? If not: Caddy
   (`systemctl status caddy`, `journalctl -u caddy`) then the container
   (`docker ps | grep buzz-relay`, `docker logs buzz-relay`).
2. NIP-42 failure: their key is not authorised — check Step 3 of Section 2
   (`/opt/buzz-relay/docker-compose.yml`), then
   `docker logs buzz-relay | grep -i auth`.
3. Not in any group: re-send the `9000` put-user event for their pubkey
   (hex, not npub).

**Hermes tenant not answering**

```bash
docker ps -a | grep hermes-          # exited? restarting?
docker logs hermes-<tenant> --tail 100
cd /opt/tollgate/hermes/<tenant> && docker compose up -d
```

**AI requests failing (credits spent but no reply)**

```bash
docker logs routstr-proxy --tail 50          # key valid? quota exhausted?
curl -s http://localhost:8009/v1/info        # proxy alive?
docker logs cdk-mintd --tail 50              # mint errors?
docker logs mint-orchestrator --tail 50      # approvals stuck?
```

**LLM proxy unreachable from a tenant**

Check the tenant env points at `https://ai.orangesync.tech` and that
`curl -s https://ai.orangesync.tech/` answers from the host. Remember the
proxy only listens on host port **8009** — port 8000 is container-internal
and will not answer from the host.

**Wrong relay URL handed out**

If a friend was told `wss://chat.…` or anything other than
`wss://relay.orangesync.tech`, correct them — there is no `chat.` subdomain.
`https://relay.orangesync.tech/` returning the "Buzz Relay" JSON is the
proof you gave them the right one.

---

## Quick reference

```bash
# relay
curl -s https://relay.orangesync.tech/ | head -c 200     # health/status
docker logs buzz-relay --tail 50                          # relay logs
cd /opt/buzz-relay && docker compose up -d                # apply config

# group admin (NIP-29) — all need --relay wss://relay.orangesync.tech
nak event --sec <nsec> --kind 9007 --tag h=<group> ...    # create
nak event --sec <nsec> --kind 9000 --tag h=<group> --tag p=<pubkey-hex> ...  # add
nak event --sec <nsec> --kind 9001 --tag h=<group> --tag p=<pubkey-hex> ...  # remove

# tenants
docker ps --format '{{.Names}}\t{{.Status}}' | grep hermes-
docker logs -f hermes-<tenant>
cd /opt/tollgate/hermes/<tenant> && docker compose up -d

# credits
docker logs -f mint-orchestrator
cd ~/tollgate-infrastructure-kit/mint-approve/src && \
  python -m tollgate_mint_approve.cli --nsec <nsec> \
    --mint https://mint.orangesync.tech --quote <id> --amount 500 --unit sat

# LLM proxy
curl -s http://localhost:8009/v1/info
docker logs routstr-proxy --tail 50

# caddy (host service, not a container)
systemctl status caddy && journalctl -u caddy --since today | tail
```
