# Multi-Tenant Hermes Hosting — Implementation Plan

## Overview

Deploy a single VPS that hosts Hermes AI agent instances for 1-3 friends,
with a shared Routstr AI inference node, Cashu mint for AI credits,
and NIP-29 relay for chat interface. Each friend gets their own Hermes
container with the full sovereign engineering setup (kanban, quality
gates, worker profiles).

## Target VPS

- **Host**: SSD VPS (64.188.7.38) — currently offline, needs booting
- **OS**: Debian (assume 12 or 13)
- **Capacity**: Enough for 1-3 concurrent Hermes instances + infrastructure
- **Assumption**: Friends won't all use it simultaneously; slowdowns OK

## Architecture

```
Internet → Cloudflare DNS → Caddy (:80/:443, auto TLS)
  ├── relay.BASE_DOMAIN       → strfry (:7777) — general Nostr relay
  ├── chat.BASE_DOMAIN        → obelisk-relay (:8080) — NIP-29 group chat
  ├── routstr.BASE_DOMAIN     → Routstr node (:8000) — AI inference proxy
  ├── mint.BASE_DOMAIN        → Cashu mint REST (:8085) — CDK mintd
  ├── mint-api.BASE_DOMAIN    → Mint orchestrator (:8090) — approval API
  └── *.nsite.BASE_DOMAIN     → nsite gateway (:3002) — optional, for static sites

  Docker network: sovereign-net

  Containers:
  ├── caddy                    — reverse proxy + TLS
  ├── strfry                   — general Nostr relay
  ├── obelisk-relay            — NIP-29 group chat (admin: Felix's npub)
  ├── routstr-node             — AI inference proxy (z.ai upstream)
  ├── cashu-mint               — CDK mintd (fakewallet, GRPC management)
  ├── mint-orchestrator        — Python daemon (systemd, GRPC approvals)
  ├── hermes-friend-1          — Hermes agent instance #1
  │   └── routstrd-1           — routstrd sidecar (LLM routing + Cashu wallet)
  ├── hermes-friend-2          — Hermes agent instance #2
  │   └── routstrd-2           — routstrd sidecar
  └── hermes-friend-3          — Hermes agent instance #3
      └── routstrd-3           — routstrd sidecar
```

## Component Details

### 1. Caddy (Reverse Proxy + TLS)

Already have: `ansible/roles/caddy/` + `ansible/playbooks/04-caddy.yml`

Config:
- On-demand TLS via Cloudflare DNS-01
- Routes for relay, chat, routstr, mint, mint-api subdomains
- WebSocket upgrade headers for relay + obelisk

### 2. strfry (General Nostr Relay)

Already have: `ansible/roles/strfry/` + `ansible/playbooks/05-strfry.yml`

Purpose: General-purpose Nostr relay for event distribution.
Friends' Hermes instances publish here, discover Routstr nodes here.

### 3. obelisk-relay (NIP-29 Group Chat)

Already have: `ansible/roles/obelisk_relay/` + `ansible/playbooks/06-obelisk-relay.yml`

Config:
- `ADMIN_NPUB` = Felix's npub (admin rights)
- Each friend gets a NIP-29 group for their Hermes chat
- Friends use Buzz app (desktop/mobile) to connect to `wss://chat.BASE_DOMAIN`
- Hermes instances connect via NIP-29 client (buzz-cli or direct Nostr)

**Why obelisk over Block Buzz:** 1 container (~100MB RAM) vs 4 containers
(~500MB-1GB + PostgreSQL + Redis + S3). We already have the Ansible role,
it's running in production, and NIP-29 group chat is its core feature.
The extra features (full-text search, presence, typing indicators, NIP-34
git events, workflow engine) are not needed for 1-3 friends chatting with
their Hermes bots.

### 4. Routstr Node (AI Inference Proxy)

Already have: `ansible/roles/routstr/` + `ansible/playbooks/18-routstr.yml`

Config:
- `UPSTREAM_BASE_URL` = z.ai API endpoint
- `UPSTREAM_API_KEY` = Felix's z.ai API key
- `CASHU_MINTS` = the Cashu mint URL on this VPS
- `NSEC` = generated Nostr keypair for the node
- `RELAYS` = local strfry relay
- Publishes availability on Nostr so routstrd clients can discover it

The node accepts Cashu tokens, verifies them, and proxies LLM requests
to z.ai. It takes a margin (configurable) on each request.

### 5. Cashu Mint (AI Credits)

Already have: `ansible/roles/cashu_mint/` + `ansible/roles/mint_orchestrator/`

Config:
- CDK mintd with `fakewallet` backend (no real Lightning needed)
- GRPC management API enabled (port 50051)
- REST API on port 8085
- SQLite database
- Units: `sat` (for AI credits, 1 sat = 1 API credit unit)
- Felix approves quotes via `mint-approve` CLI or web dashboard

**Free credit issuance flow:**
1. Friend creates a NUT-04 mint quote (via Cashu wallet)
2. Felix approves via `mint-approve --nsec <nsec> --mint <url> --quote <id> --amount <N> --unit sat`
3. Orchestrator receives kind 38010 event, calls GRPC `UpdateNut04Quote(id, "PAID")`
4. Friend's wallet mints tokens against the paid quote
5. Friend's routstrd spends tokens at the Routstr node

### 6. Mint Orchestrator (systemd)

Already have: `ansible/roles/mint_orchestrator/`

Python daemon that:
- Listens for Nostr kind 38010 events on local relay
- Validates event signature (must be from Felix's npub)
- Calls CDK GRPC to mark quotes as paid
- Logs all approvals to `/var/log/tollgate/mint-approvals.jsonl`
- REST API on port 8090 for health/audit

### 7. Hermes Containers (1 per friend)

**NEW Ansible role needed: `hermes_instance`**

Each friend gets a Docker container with:
- Hermes Agent (from hermes-agent.nousresearch.com)
- routstrd sidecar (LLM routing + Cashu wallet)
- Full sovereign engineering setup:
  - Kanban system (unlimited boards, per-project)
  - Quality gates (7 gates, cross-family cold review)
  - Worker profiles (can create as many as needed)
  - SOUL.md with unbreakable principles
  - Skills system
  - Cron jobs (quota-gated)
  - Memory (durable across sessions)

**Container spec:**
- Base: `oven/bun:1-slim` (for routstrd) + Python venv (for Hermes)
- Volumes:
  - `hermes-data-{name}` → `/home/hermes/.hermes/` (config, profiles, kanban, skills)
  - `hermes-repos-{name}` → `/home/hermes/repos/` (git repos)
  - `routstrd-data-{name}` → `/data` (routstrd config + cocod wallet)
- Network: `sovereign-net` (Docker bridge)
- Resource limits: 2GB RAM, 2 CPU cores per container (adjustable)
- Environment:
  - `ROUTSTRD_DIR=/data`
  - `COCOD_DIR=/data/.cocod`
  - `HERMES_PROVIDER=http://routstrd-{name}:8008/v1` (routstrd as LLM provider)

**routstrd setup inside container:**
1. `routstrd onboard` — initialize config, generate Nostr identity
2. `routstrd start --provider https://routstr.BASE_DOMAIN` — connect to our node
3. `routstrd clients add --hermes` — auto-configure Hermes to use routstrd
4. Fund wallet: `routstrd receive <cashu-token>` (Felix issues credits)

**Hermes onboarding (full setup from day 1):**
- Load `hermes-agent` skill (configuration, tools, features)
- Configure NIP-29 client to connect to `wss://chat.BASE_DOMAIN`
- Create first kanban board for the friend's primary project
- Set up worker profiles with quality gates
- Configure quota gate (routstrd handles pricing, but local gate prevents runaway)
- Create default SOUL.md with sovereign engineering principles
- Install core skills: quality-gates, kanban-worker-management, etc.

### 8. NIP-29 Chat Integration

Each friend communicates with their Hermes via NIP-29 group chat:
1. Friend installs Buzz app (desktop or mobile)
2. Connects to `wss://chat.BASE_DOMAIN` with their Nostr key
3. Felix creates a NIP-29 group for them (or they create their own if obelisk allows)
4. Hermes instance is configured to listen on that group
5. Friend sends messages in Buzz → NIP-29 relay → Hermes receives → responds

**Buzz CLI for automation:** The `buzz-cli` skill already exists in our
skills. It can send/receive NIP-29 messages programmatically. Hermes
instances can use this for:
- Status updates (post to a #status group)
- PR review notifications (post to a #pr-reviews group)
- Error alerts (post to an #alerts group)

## Ansible Playbook Structure

```
ansible/
├── playbooks/
│   ├── 00-zram.yml              # existing
│   ├── 01-system.yml            # existing
│   ├── 02-docker.yml            # existing
│   ├── 03-cloudflare-dns.yml    # existing
│   ├── 04-caddy.yml             # existing (add new routes)
│   ├── 05-strfry.yml            # existing
│   ├── 06-obelisk-relay.yml     # existing
│   ├── 07-blossom.yml           # existing (optional, for media)
│   ├── 18-routstr.yml           # existing (Routstr node)
│   ├── 41-cashu-mint.yml        # existing (rename/reuse)
│   ├── 42-mint-orchestrator.yml # existing (rename/reuse)
│   └── 43-hermes-instances.yml  # NEW — deploys N Hermes containers
├── roles/
│   ├── hermes_instance/         # NEW
│   │   ├── defaults/main.yml    # container config, resource limits
│   │   ├── tasks/main.yml        # build + deploy containers
│   │   ├── templates/
│   │   │   ├── Dockerfile.hermes.j2
│   │   │   ├── docker-compose.hermes.j2
│   │   │   ├── hermes-config.yaml.j2
│   │   │   ├── soul.md.j2
│   │   │   └── routstrd-config.json.j2
│   │   └── handlers/main.yml    # restart on config change
│   └── ... (existing roles)
```

### New Role: `hermes_instance`

**defaults/main.yml:**
```yaml
hermes_instances:
  - name: "friend1"
    nostr_npub: "npub1..."        # friend's Nostr public key
    nip29_group: "friend1-hermes"  # group ID on obelisk
    api_credits_sat: 10000        # initial AI credits (sat)
    ram_limit: "2g"
    cpu_limit: "2"
    model_default: "glm-4.5-flash" # default model via routstrd
  - name: "friend2"
    nostr_npub: "npub1..."
    nip29_group: "friend2-hermes"
    api_credits_sat: 10000
    ram_limit: "2g"
    cpu_limit: "2"
    model_default: "glm-4.5-flash"
  # ... add more friends as needed
```

**tasks/main.yml** (simplified):
1. Create Docker network `sovereign-net`
2. For each instance in `hermes_instances`:
   a. Generate routstrd config (Nostr identity, provider URL)
   b. Build Hermes Docker image (if not cached)
   c. Deploy docker-compose with Hermes + routstrd sidecar
   d. Wait for health check
   e. Initialize routstrd (onboard + start)
   f. Fund routstrd wallet (issue Cashu credits via mint-approve)
   g. Configure Hermes (load skills, create kanban board, set up NIP-29)
   h. Create NIP-29 group on obelisk relay
   i. Verify end-to-end: friend can chat via Buzz → Hermes responds

## Deployment Order

1. **Boot VPS** (manual — Felix boots from provider panel)
2. **Check what's on it** (SSH in, surface existing services)
3. **Base system** (00-zram, 01-system, 02-docker)
4. **DNS** (03-cloudflare-dns — set up BASE_DOMAIN)
5. **Caddy** (04-caddy — reverse proxy + TLS)
6. **strfry** (05-strfry — general relay)
7. **obelisk-relay** (06-obelisk-relay — NIP-29 chat)
8. **Routstr node** (18-routstr — AI inference proxy)
9. **Cashu mint** (41-cashu-mint — CDK mintd with fakewallet)
10. **Mint orchestrator** (42-mint-orchestrator — GRPC approval daemon)
11. **Hermes instances** (43-hermes-instances — one container per friend)
12. **Onboard friends** (issue credits, create NIP-29 groups, verify chat)

## Resource Budget (estimated)

| Component | RAM | CPU | Disk |
|-----------|-----|-----|------|
| Caddy | 50 MB | 0.1 | 100 MB |
| strfry | 100 MB | 0.1 | 1 GB |
| obelisk-relay | 100 MB | 0.1 | 500 MB |
| Routstr node | 200 MB | 0.2 | 500 MB |
| Cashu mint | 100 MB | 0.1 | 500 MB |
| Mint orchestrator | 50 MB | 0.1 | 100 MB |
| Hermes #1 | 2 GB | 2 | 5 GB |
| Hermes #2 | 2 GB | 2 | 5 GB |
| Hermes #3 | 2 GB | 2 | 5 GB |
| **Total** | **~6.6 GB** | **~6.8** | **~18 GB** |

For a VPS with 8GB+ RAM and 40GB+ disk, this fits. If friends are not
all active simultaneously, RAM pressure is lower (Hermes idle ~500MB).

## Onboarding Plan (per friend)

### Step 1: Issue AI Credits
```bash
# Felix approves a mint quote for the friend
tollgate-mint-approve \
  --nsec <felix-nsec> \
  --mint https://mint.BASE_DOMAIN \
  --quote <quote-id> \
  --amount 10000 \
  --unit sat
```

### Step 2: Create NIP-29 Group
```bash
# Using buzz CLI or direct Nostr
buzz groups create \
  --relay wss://chat.BASE_DOMAIN \
  --id friend1-hermes \
  --name "Friend1's Hermes" \
  --admin <friend-npub>
```

### Step 3: Deploy Hermes Container
```bash
# Ansible deploys with friend's config
ansible-playbook 43-hermes-instances.yml \
  -e "hermes_instances=[{name: 'friend1', nostr_npub: 'npub1...', ...}]"
```

### Step 4: Configure Hermes
Inside the container:
1. Load `hermes-agent` skill
2. Set up NIP-29 listener on the friend's group
3. Create default kanban board ("my-first-project")
4. Install quality-gates skill
5. Configure worker profiles (start with 1-2 simple ones)
6. Set up quota gate (prevent runaway spending)
7. Create SOUL.md with sovereign principles

### Step 5: Verify End-to-End
1. Friend opens Buzz app
2. Connects to `wss://chat.BASE_DOMAIN`
3. Sees their Hermes group
4. Sends a message → Hermes responds
5. Hermes can create kanban tasks, run workers, push code

## Friend's Hermes Setup (what they get)

Each friend's Hermes instance includes:

### Core
- Hermes Agent (latest) with Python venv
- routstrd sidecar (LLM routing via Routstr, Cashu payments)
- NIP-29 chat interface (Buzz app on their phone/desktop)
- Nostr identity (generated, stored in container volume)

### Sovereign Engineering
- Kanban system (unlimited boards, per-project)
- Quality gates (7 gates, force-loaded)
- Worker profiles (create as many as needed)
- SOUL.md (unbreakable principles: push, delegate, quota-gate)
- Skills system (install from our skill library)
- Cron jobs (quota-gated)
- Memory (durable across sessions)
- Session search (find past work)

### Pre-installed Skills
- `quality-gates` — 7 mandatory gates
- `kanban-worker-management` — task lifecycle, dispatch
- `kanban-quota-aware-dispatch` — model tiering, quota gates
- `hermes-agent` — configuration, tools, features
- `buzz-cli` — NIP-29 group chat interaction
- `github-pr-workflow` — PR lifecycle
- `test-driven-development` — TDD enforcement
- `systematic-debugging` — root-cause debugging

### Models Available (via routstrd → Routstr node → z.ai)
- glm-5.2 (heavy — architecture, complex reasoning)
- glm-4.5-flash (fast — simple tasks)
- glm-4.5-air (mid — coding)
- kimi-k2.7-code (code/spatial — if Ollama Cloud available)

## Open Questions

1. **VPS boot**: SSD VPS (64.188.7.38) is offline. Felix needs to boot it
   from provider panel. Then we check what's on it before deploying.

2. **BASE_DOMAIN**: What domain to use? Currently testserver2 uses
   `orangesync.tech`. Could use same domain with different subdomains,
   or a separate domain for this project.

3. **Hermes Docker image**: Is there a prebuilt Hermes Docker image?
   Or do we need to build from source? Check hermes-agent.nousresearch.com
   for Docker instructions.

4. **routstrd in Docker**: The routstrd Dockerfile is dev-oriented.
   Need to create a production-ready Dockerfile that runs `routstrd start`
   as a daemon (not interactive bash).

5. **NIP-29 client in Hermes**: How does Hermes listen for NIP-29 messages?
   Is there a built-in NIP-29 client, or do we need to write one?
   The `buzz-cli` skill exists but it's a CLI tool, not a listener daemon.

6. **Cashu wallet for friends**: Friends need a Cashu wallet to receive
   credits. Options: (a) Cashu nuts.com web wallet, (b) nutshell CLI,
   (c) built into routstrd (cocod wallet). routstrd's cocod wallet can
   receive tokens directly via `routstrd receive <token>`.

## Next Steps

1. Felix boots the SSD VPS
2. We SSH in and check what's on it
3. Felix decides: wipe or keep existing
4. We configure BASE_DOMAIN in .env
5. We run the Ansible playbooks in order
6. We create the first friend's Hermes instance
7. We verify end-to-end (Buzz → NIP-29 → Hermes → routstrd → Routstr → z.ai)
8. We onboard the friend (show them Buzz app, how to chat with Hermes)
9. Repeat for each friend