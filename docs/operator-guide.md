# Operator Guide — Hermes for Friends

> **Audience:** Felix (c03rad0r), the operator of the Tollgate infrastructure.
> **Purpose:** How to add/remove friends, issue AI credits, monitor containers, update Hermes images, and back up / restore data.
> **Related docs:** [Integrated Operations](INTEGRATED-OPERATIONS.md), [Friend Onboarding Guide](onboarding-friend-guide.md), [Services Overview](services.md), [Troubleshooting](troubleshooting.md)

---

## Table of Contents

1. [Architecture Recap](#1-architecture-recap)
2. [Adding a New Friend](#2-adding-a-new-friend)
3. [Removing a Friend](#3-removing-a-friend)
4. [Issuing AI Credits](#4-issuing-ai-credits)
5. [Monitoring Containers](#5-monitoring-containers)
6. [Updating Hermes Images](#6-updating-hermes-images)
7. [Backup and Restore](#7-backup-and-restore)
8. [Relay and Group Management](#8-relay-and-group-management)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. Architecture Recap

```
Friend (Buzz client)
    │ wss://chat.<domain>  (Caddy → obelisk-relay :8080)
    ▼
obelisk-relay (NIP-29 group chat, NIP-42 auth)
    │ kind:9007 create group, kind:9000 add user
    ▼
Hermes container (hermes-<tenant-name>)
    │ Nostr adapter reads group messages
    │ LLM calls route through routstrd sidecar
    ▼
routstrd sidecar (per-tenant LLM proxy, :8008)
    │ Per-friend Cashu wallet + token payment
    │ Auto-discovers cheapest provider via Nostr
    ▼
Routstr node → z.ai API (glm-5.2)
```

> **Note:** The routstrd sidecar (V2-07) is being integrated. In the current V1 deployment, Hermes containers connect to a shared Routstr proxy on the `routstr_default` Docker network. The V2 architecture deploys a routstrd sidecar per tenant for wallet isolation and provider auto-discovery.

Key infrastructure paths on VPS2:

| Path | Purpose |
|------|---------|
| `/opt/tollgate/hermes/<tenant>/` | Per-tenant compose, .env, nsec, data |
| `/opt/tollgate/hermes/<tenant>/docker-compose.yml` | Tenant compose (from j2 template) |
| `/opt/tollgate/hermes/<tenant>/.env` | Tenant env vars (nsec, API key, relay URL) |
| `/opt/tollgate/hermes/<tenant>/nsec/nsec.txt` | Friend's Nostr private key |
| `/opt/tollgate/mints/registry.json` | Cashu mint registry |
| `/opt/tollgate/obelisk/` | obelisk-relay docker-compose |
| `/opt/tollgate/caddy/Caddyfile` | Caddy reverse proxy config |
| `/etc/fips/fips.yaml` | FIPS mesh config |

Two relays are deployed via Caddy:

| Subdomain | Backend | Port | Purpose |
|-----------|--------|------|---------|
| `chat.<domain>` | obelisk-relay | 8080 | NIP-29 group chat (friends connect here) |
| `relay.<domain>` | strfry | 7777 | General-purpose Nostr relay (optional for friends) |

> **Critical:** Friends must connect to `wss://chat.<domain>`, not `wss://relay.<domain>`. The `relay.` subdomain serves strfry, which does not host NIP-29 groups. The onboarding guide reflects this.

---

## 2. Adding a New Friend

### Prerequisites

- SSH access to VPS2 (`ssh debian@vps2.fips` or `ssh root@23.182.128.51`)
- `.env` file at `/opt/tollgate/hermes/.env` or the repo root
- Ansible installed on your controller machine
- The friend's npub (ask them to send it from Buzz)

### Step-by-step

1. **Generate or collect the friend's Nostr keypair.**

   If the friend already has a Nostr key (from Damus, Amethyst, etc.), use their existing npub. Otherwise generate a fresh keypair:

   ```bash
   python3 -c "
   from pynostr.key import PrivateKey
   pk = PrivateKey()
   print('nsec:', pk.bech32())
   print('npub:', pk.public_key.bech32())
   "
   ```

   Store the nsec securely. The friend gets the npub; you keep the nsec for their Hermes container.

2. **Add the friend to `.env`.**

   Edit the `.env` file in the repo root (or `/opt/tollgate/hermes/.env` on VPS2). Add:

   ```bash
   FRIEND<N>_NPUB=npub1...
   FRIEND<N>_NSEC=nsec1...
   ZAI_API_KEY_FRIEND<N>=sk-...
   ```

   Use the next available friend number (FRIEND4, FRIEND5, etc.).

3. **Add the friend to the Ansible playbook.**

   Edit `ansible/playbooks/45-multi-tenant-hermes.yml`. Under `hermes_tenants_tenants`, add a new entry:

   ```yaml
   hermes_tenants_tenants:
     - name: "sitarani"          # existing
       npub: "{{ lookup('env', 'FRIEND1_NPUB') }}"
       nsec: "{{ lookup('env', 'FRIEND1_NSEC') }}"
       zai_api_key: "{{ lookup('env', 'ZAI_API_KEY_OURS') }}"
     - name: "chiefmonkey"       # existing
       npub: "{{ lookup('env', 'FRIEND2_NPUB') }}"
       nsec: "{{ lookup('env', 'FRIEND2_NSEC') }}"
       zai_api_key: "{{ lookup('env', 'ZAI_API_KEY_FRIEND') }}"
     - name: "bekka"             # existing
       npub: "{{ lookup('env', 'FRIEND3_NPUB') }}"
       nsec: "{{ lookup('env', 'FRIEND3_NSEC') }}"
       zai_api_key: "{{ lookup('env', 'ZAI_API_KEY_FRIEND') }}"
     - name: "newfriend"         # NEW
       npub: "{{ lookup('env', 'FRIEND4_NPUB') }}"
       nsec: "{{ lookup('env', 'FRIEND4_NSEC') }}"
       zai_api_key: "{{ lookup('env', 'ZAI_API_KEY_FRIEND4') }}"
   ```

   The `name` becomes the container name (`hermes-newfriend`), the Docker network (`hermes-net-newfriend`), and the volume (`hermes-newfriend-data`).

4. **Run the playbook.**

   ```bash
   cd /path/to/tollgate-infrastructure-kit
   ansible-playbook ansible/playbooks/45-multi-tenant-hermes.yml \
     --extra-vars "target_ip=23.182.128.51"
   ```

   This creates the per-tenant directories, Docker network, volume, compose file, .env, and starts the container. The healthcheck waits for the container to be healthy.

5. **Create a NIP-29 group on obelisk-relay.**

   The obelisk-relay needs a group for the friend. Use the relay admin nsec (NOT your personal nsec) to create a group and add the friend's npub:

   ```bash
   # Create a group (kind 9007) — replace GROUP_ID and GROUP_NAME
   # Add the friend to the group (kind 9000)
   # This is done via Nostr events to the obelisk-relay
   # Use nak or buzz-cli for this:
   nak event --kind 9007 --content '{"name":"newfriend-ai"}' \
     --tag d:newfriend-ai \
     --tag p:<FRIEND_NPUB> \
     wss://chat.orangesync.tech
   ```

   Or use the obelisk-relay admin UI at `https://chat.<domain>/admin` (if available).

6. **Whitelist the friend's npub on the relay.**

   The obelisk-relay uses NIP-42 authentication. The friend's npub must be in the relay's whitelist. Check the relay config:

   ```bash
   docker exec tollgate-obelisk cat /app/data/config.json
   ```

   Add the friend's npub to the allowed pubkeys list and restart the relay:

   ```bash
   docker restart tollgate-obelisk
   ```

7. **Issue initial AI credits.**

   See [Section 4](#4-issuing-ai-credits) below.

8. **Send the friend the onboarding guide.**

   Point them to `docs/onboarding-friend-guide.md` (or send the URL if hosted on nsite). They need:
   - Their npub (you generated it or they provided it)
   - The chat relay URL: `wss://chat.<your-domain>`
   - The Buzz download link: `https://github.com/block/buzz/releases`

### Verification

```bash
# Container is running and healthy
docker ps --filter name=hermes-newfriend --format "{{.Names}}: {{.Status}}"

# Gateway process is running inside
docker exec hermes-newfriend pgrep -f "hermes gateway run"

# Relay sees the friend's group
docker logs tollgate-obelisk --tail 20 | grep newfriend
```

---

## 3. Removing a Friend

1. **Stop and remove the container:**

   ```bash
   cd /opt/tollgate/hermes/<tenant-name>
   docker compose down
   ```

2. **Remove the Docker volume** (destroys all friend data — back up first if needed):

   ```bash
   docker volume rm hermes-<tenant-name>-data
   docker network rm hermes-net-<tenant-name>
   ```

3. **Remove the friend from the Ansible playbook** (`45-multi-tenant-hermes.yml`):
   Delete their entry from `hermes_tenants_tenants`.

4. **Remove the friend from `.env`:**
   Delete `FRIEND<N>_NPUB`, `FRIEND<N>_NSEC`, `ZAI_API_KEY_FRIEND<N>`.

5. **Remove the friend from the relay whitelist and group:**
   - Remove their npub from obelisk-relay's allowed pubkeys.
   - Delete or deactivate the NIP-29 group (kind 9007 with the group ID).

6. **Revoke their Routstr API key** (if per-friend keys are used):
   ```bash
   curl -X DELETE http://localhost:8000/admin/keys/<key-id> \
     -H "Authorization: Bearer $ROUTSTR_ADMIN_PASSWORD"
   ```

7. **Commit and push** the Ansible and .env changes.

---

## 4. Issuing AI Credits

AI credits are Cashu tokens. The flow: you create a mint quote, sign a Nostr approval event (kind 38010), the mint-orchestrator marks the quote as paid, and the friend's Hermes instance mints tokens from it.

### Prerequisites

- The Cashu mint is running (`docker ps | grep cdk-mint`)
- The mint-orchestrator is running (`docker ps | grep mint-orchestrator`)
- You have the deployment admin nsec (NOT your personal nsec)
- The friend's Hermes container is configured with `LLM_PROXY_URL` pointing to Routstr

### Issuing credits

1. **Create a mint quote on the Cashu mint:**

   ```bash
   # Get a quote from the CDK mint
   curl -X POST http://localhost:8085/v1/quote/mint \
     -H "Content-Type: application/json" \
     -d '{"amount": 10000, "unit": "sat"}'
   ```

   This returns a `quote_id`. Note it.

2. **Sign and publish a kind 38010 approval event:**

   Use the `mint-approve` CLI tool:

   ```bash
   cd /path/to/tollgate-infrastructure-kit
   python -m tollgate_mint_approve.cli \
     --nsec "$DEPLOYMENT_ADMIN_NSEC" \
     --mint "https://mints.orangesync.tech" \
     --quote "<quote_id>" \
     --amount 10000 \
     --unit sat \
     --relay "wss://relay.orangesync.tech"
   ```

   Or via the installed CLI:

   ```bash
   mint-approve \
     --nsec "$DEPLOYMENT_ADMIN_NSEC" \
     --mint "https://mints.orangesync.tech" \
     --quote "<quote_id>" \
     --amount 10000 \
     --unit sat
   ```

   The `--relay` defaults to `wss://relay.orangesync.tech`. The mint-orchestrator listens on this relay for kind 38010 events.

3. **Verify the orchestrator processed the approval:**

   ```bash
   # Check orchestrator logs
   docker logs mint-orchestrator --tail 20

   # Check audit log
   tail -5 /var/log/tollgate/mint-approvals.jsonl
   ```

   You should see the quote marked as PAID.

4. **Verify the friend's balance increased:**

   Ask the friend to check in Buzz:
   ```
   How many AI credits do I have left?
   ```

   Or check Routstr directly:
   ```bash
   curl http://localhost:8000/v1/info
   ```

### Credit amounts

| Amount (sat) | Approximate usage |
|--------------|-------------------|
| 1,000 | ~20-50 short messages |
| 10,000 | ~200-500 messages, or a few complex coding tasks |
| 50,000 | ~1000+ messages, heavy daily use for a month |

Typical cost per message: 1-50 sats depending on input/output length and model. A short question costs ~1-5 sats; a long coding task costs ~20-50 sats.

### Per-friend isolation

Each friend has their own API key in Routstr with its own quota. One friend cannot exhaust another's credits. Quotas are managed centrally via the Routstr admin API.

---

## 5. Monitoring Containers

### Quick health check

```bash
# All Hermes containers
docker ps --filter name=hermes- --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# All infrastructure containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "obelisk|routstr|caddy|mint|orchestrator"

# FIPS mesh
sudo fipsctl show status
sudo fipsctl show peers
```

### Per-container health

```bash
# Check healthcheck status
docker inspect --format '{{.State.Health.Status}}' hermes-sitarani
docker inspect --format '{{.State.Health.Status}}' hermes-chiefmonkey
docker inspect --format '{{.State.Health.Status}}' hermes-bekka

# Check gateway process inside container
docker exec hermes-sitarani pgrep -f "hermes gateway run"

# Check memory usage
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}" | grep hermes
```

### Relay health

```bash
# obelisk-relay (chat relay)
curl -sf http://localhost:8080/health || echo "obelisk DOWN"

# strfry (general relay)
curl -sf http://localhost:7777/ || echo "strfry DOWN"
```

### LLM routing health

```bash
# Routstr is responding
curl -sf http://localhost:8000/v1/info || echo "routstr DOWN"

# Check recent LLM requests
docker logs routstr --tail 50 | grep -E "POST|200|error"

# Check z.ai API key is valid
curl -sf -H "Authorization: Bearer $ZAI_API_KEY" https://api.z.ai/v1/models | head -5
```

### Watchdog

The VPS has a watchdog system that monitors 16 services:

```bash
# Check watchdog status
systemctl status tollgate-watchdog

# Dry-run all checks
python3 /opt/tollgate/scripts/watchdog.py --dry-run
```

### Hermes health-check script

A dedicated health-check script (`scripts/hermes-health-check.sh`) runs every 15 minutes via cron. It checks:

- Container health status for all tenants (sitarani, chiefmonkey, bekka)
- Gateway endpoints on ports 9000-9002
- Buzz relay (optional, warning only)
- Routstr / LLM proxy (optional, warning only)

The script is silent on success and writes alerts to a log file on failure. Deploy it via the Ansible monitoring tasks:

```bash
# Run the health check manually
bash scripts/hermes-health-check.sh

# Check recent alerts
tail -20 /var/log/hermes-health-check.log

# The cron job is deployed by the Ansible playbook
ansible-playbook ansible/playbooks/45-multi-tenant-hermes.yml \
  --extra-vars "target_ip=23.182.128.51" \
  --tags hermes_tenants_monitoring
```

### Log locations

| Service | Log location |
|---------|-------------|
| Hermes containers | `docker logs hermes-<tenant>` |
| obelisk-relay | `docker logs tollgate-obelisk` |
| Routstr | `docker logs routstr` |
| Cashu mint | `docker logs cdk-mintd` |
| mint-orchestrator | `docker logs mint-orchestrator` |
| Caddy | `docker logs tollgate-caddy` |
| FIPS | `journalctl -u fips` |
| Mint approvals | `/var/log/tollgate/mint-approvals.jsonl` |

---

## 6. Updating Hermes Images

### Pull and rebuild

```bash
# Pull the latest image
docker pull hermes-agent:nostr

# Or build from source if using a custom image
cd /path/to/tollgate-infrastructure-kit
docker build -t hermes-agent:nostr -f hermes-docker/Dockerfile .
```

### Recreate containers

```bash
cd /opt/tollgate/hermes
# Recreate all tenant containers with the new image
for tenant in sitarani chiefmonkey bekka; do
  cd /opt/tollgate/hermes/$tenant
  docker compose up -d
done
```

Or via Ansible:

```bash
ansible-playbook ansible/playbooks/45-multi-tenant-hermes.yml \
  --extra-vars "target_ip=23.182.128.51" \
  --tags hermes_tenants
```

### Verify after update

```bash
# All containers healthy
docker ps --filter name=hermes- --format "{{.Names}}: {{.Status}}"

# Hermes version inside container
docker exec hermes-sitarani hermes --version

# Nostr adapter loaded
docker logs hermes-sitarani 2>&1 | grep -i "nostr\|relay\|adapter"
```

### Rollback

If the new image is broken:

```bash
# Pull the previous known-good image
docker pull hermes-agent:nostr-previous  # if tagged

# Or use the image ID
docker tag <old-image-id> hermes-agent:nostr

# Recreate containers
for tenant in sitarani chiefmonkey bekka; do
  cd /opt/tollgate/hermes/$tenant
  docker compose up -d
done
```

---

## 7. Backup and Restore

### What to back up

| Data | Location | Priority |
|------|----------|----------|
| Per-friend Hermes data | Docker volume `hermes-<tenant>-data` | High |
| obelisk-relay data (chat history) | Docker volume `obelisk-data` | High |
| Cashu mint state | Docker volume `cdk-mintd-data` | Critical |
| FIPS config | `/etc/fips/fips.yaml` | Medium |
| .env file (all secrets) | Repo root or `/opt/tollgate/hermes/.env` | Critical |
| Ansible configs | Git repo (version-controlled) | Medium |
| Mint registry | `/opt/tollgate/mints/registry.json` | High |

### Backup script

```bash
#!/bin/bash
# scripts/backup-hermes-volumes.sh
BACKUP_DIR="/backup/hermes-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

# Hermes tenant volumes
for vol in $(docker volume ls --format '{{.Name}}' | grep hermes-); do
  echo "Backing up $vol..."
  docker run --rm -v "$vol:/data:ro" -v "$BACKUP_DIR:/backup" alpine \
    tar czf "/backup/${vol}.tar.gz" -C /data .
done

# obelisk-relay data
docker run --rm -v obelisk-data:/data:ro -v "$BACKUP_DIR:/backup" alpine \
  tar czf /backup/obelisk-data.tar.gz -C /data .

# Cashu mint data
docker run --rm -v cdk-mintd-data:/data:ro -v "$BACKUP_DIR:/backup" alpine \
  tar czf /backup/cdk-mintd-data.tar.gz -C /data .

# Config files
tar czf "$BACKUP_DIR/configs.tar.gz" \
  /etc/fips/fips.yaml \
  /opt/tollgate/mints/registry.json \
  /opt/tollgate/hermes/.env 2>/dev/null

echo "Backup complete: $BACKUP_DIR"
du -sh "$BACKUP_DIR"
```

### Rotation

Keep 7 daily, 4 weekly, 3 monthly backups:

```bash
# Daily (keep 7)
find /backup -maxdepth 1 -name "hermes-*" -type d -mtime +7 -exec rm -rf {} \;

# Weekly (keep 4 weeks = 28 days)
find /backup -maxdepth 1 -name "hermes-*" -type d -mtime +28 -exec rm -rf {} \;
```

Or use a systemd timer:

```ini
# /etc/systemd/system/hermes-backup.timer
[Unit]
Description=Daily Hermes volume backup

[Timer]
OnCalendar=03:00
Persistent=true

[Install]
WantedBy=timers.target
```

### Restore

```bash
# Stop the container
docker compose -f /opt/tollgate/hermes/<tenant>/docker-compose.yml down

# Restore the volume
docker run --rm -v hermes-<tenant>-data:/data -v /backup/hermes-YYYYMMDD:/backup alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/hermes-<tenant>-data.tar.gz -C /data"

# Start the container
docker compose -f /opt/tollgate/hermes/<tenant>/docker-compose.yml up -d

# Verify
docker ps --filter name=hermes-<tenant>
docker exec hermes-<tenant> pgrep -f "hermes gateway run"
```

### Offsite backup

Sync backups to another machine via rsync:

```bash
rsync -avz /backup/ c03rad0r@t470.fips:/backup/
```

Or use Syncthing for continuous sync.

---

## 8. Relay and Group Management

### obelisk-relay (chat relay)

The chat relay runs as a Docker container (`tollgate-obelisk`) behind Caddy at `chat.<domain>`.

```bash
# Check relay status
docker ps | grep obelisk
curl -sf http://localhost:8080/health

# View relay config
docker exec tollgate-obelisk cat /app/data/config.json

# Restart relay
docker restart tollgate-obelisk

# View relay logs
docker logs tollgate-obelisk --tail 50
```

### Creating a NIP-29 group

Use `nak` or any Nostr client with the deployment admin nsec:

```bash
# Create a group (kind 9007)
nak event --kind 9007 \
  --content '{"name":"friend-ai","about":"AI assistant group"}' \
  --tag d:friend-ai \
  wss://chat.orangesync.tech

# Add a user to the group (kind 9000)
nak event --kind 9000 \
  --tag d:friend-ai \
  --tag p:<friend-npub> \
  wss://chat.orangesync.tech
```

### Whitelisting npubs

The obelisk-relay uses NIP-42 authentication. Only whitelisted npubs can connect. To add/remove:

```bash
# Check current whitelist
docker exec tollgate-obelisk cat /app/data/config.json | jq '.allowed_pubkeys'

# Add an npub (edit config and restart)
docker exec tollgate-obelisk sh -c "
  cat /app/data/config.json | jq '.allowed_pubkeys += [\"npub1...\"]' > /tmp/config.json
  cp /tmp/config.json /app/data/config.json
"
docker restart tollgate-obelisk
```

### strfry (general relay)

The general relay runs as `tollgate-strfry` behind Caddy at `relay.<domain>`. Friends do not need this relay for Hermes, but it can be used for profile metadata and public Nostr posts.

```bash
docker ps | grep strfry
curl -sf http://localhost:7777/
```

---

## 9. Troubleshooting

### Friend can't connect to relay

1. Check obelisk-relay is running: `docker ps | grep obelisk`
2. Check relay URL is correct: friend must use `wss://chat.<domain>`, not `wss://relay.<domain>`
3. Check friend's npub is whitelisted: `docker exec tollgate-obelisk cat /app/data/config.json | jq '.allowed_pubkeys'`
4. Check Caddy WebSocket upgrade: `docker logs tollgate-caddy | grep chat`
5. Check friend's Buzz relay settings (Read + Write enabled)

### Hermes not responding to messages

1. Check container is running: `docker ps | grep hermes-<tenant>`
2. Check healthcheck: `docker inspect hermes-<tenant> | jq '.[0].State.Health'`
3. Check Nostr adapter logs: `docker logs hermes-<tenant> 2>&1 | grep nostr`
4. Check relay connection: `docker logs hermes-<tenant> 2>&1 | grep relay`
5. Check LLM routing: `docker logs routstr --tail 50`
6. Check z.ai API key: `curl -sf -H "Authorization: Bearer $ZAI_API_KEY" https://api.z.ai/v1/models`

### Credits not working

1. Check Cashu mint is running: `docker ps | grep cdk-mint`
2. Check mint-orchestrator is running: `docker ps | grep mint-orchestrator`
3. Check recent approvals: `tail -10 /var/log/tollgate/mint-approvals.jsonl`
4. Check Routstr: `curl -sf http://localhost:8000/v1/info`
5. Check mint-orchestrator logs: `docker logs mint-orchestrator --tail 50`

### FIPS mesh issues

See [FIPS Mesh Operations](FIPS-MESH-OPERATIONS.md) for detailed FIPS troubleshooting.

Quick check:
```bash
sudo systemctl is-active fips fips-dns fips-firewall
sudo fipsctl show status
sudo fipsctl show peers
sudo dig @::1 -p 5354 vps2.fips AAAA +short
```

### Container won't start

```bash
# Check container logs
docker logs hermes-<tenant>

# Check port conflicts
ss -tlnp | grep 8080

# Check Docker disk space
df -h
docker system df

# Check memory
free -h
docker stats --no-stream
```

### Gateway port not binding

The Hermes gateway process may run but not bind port 8080 inside the container. This is often caused by the `command: ["sleep", "infinity"]` override in the compose template, which prevents s6-overlay from managing the gateway service.

Check:
```bash
# Is the gateway process running?
docker exec hermes-<tenant> pgrep -f "hermes gateway run"

# Is port 8080 bound?
docker exec hermes-<tenant> ss -tlnp | grep 8080

# Check the compose command
grep command /opt/tollgate/hermes/<tenant>/docker-compose.yml
```

If `command: ["sleep", "infinity"]` is present, remove it and let s6-overlay manage the process (see Task 4 in the v2 plan).

---

## Quick Reference

| Task | Command |
|------|---------|
| Add a friend | Edit `.env` + playbook → `ansible-playbook 45-multi-tenant-hermes.yml` |
| Remove a friend | `docker compose down` → `docker volume rm` → edit playbook |
| Issue credits | `mint-approve --nsec ... --mint ... --quote ... --amount ...` |
| Check containers | `docker ps --filter name=hermes-` |
| Check relay | `curl http://localhost:8080/health` |
| Check LLM | `curl http://localhost:8000/v1/info` |
| Update image | `docker pull hermes-agent:nostr` → `docker compose up -d` |
| Backup | `scripts/backup-hermes-volumes.sh` |
| Restore | `docker run --rm -v <vol>:/data -v /backup:/backup alpine tar xzf ...` |
| Relay logs | `docker logs tollgate-obelisk` |
| Mint approvals | `tail /var/log/tollgate/mint-approvals.jsonl` |

---

## References

- [Integrated Operations Guide](INTEGRATED-OPERATIONS.md) — full infrastructure operations manual
- [Friend Onboarding Guide](onboarding-friend-guide.md) — user-facing guide for friends
- [Services Overview](services.md) — full service inventory
- [Troubleshooting](troubleshooting.md) — general troubleshooting
- [FIPS Mesh Operations](FIPS-MESH-OPERATIONS.md) — FIPS mesh config and peer management
- [Hermes for Friends v2 Plan](../PLAN-hermes-for-friends-v2.md) — implementation plan
