# Multi-Tenant Hermes Hosting — Comprehensive Implementation Plan

**Status:** READY FOR SCHEDULING
**Date:** 2026-08-08
**Operator:** Felix
**VPS:** SSD VPS 64.188.7.38 (Debian, $15.12/mo)
**Users:** 3 friends, full Hermes setup from day 1

---

## System Architecture

```
Internet → Cloudflare DNS → VPS (Debian, 64.188.7.38)
  → Caddy (:80/:443, auto HTTPS via Cloudflare DNS-01)
    ├── relay.sovereignengineering.io    → obelisk-relay (Docker :8080)   [NIP-29 group chat]
    ├── routstr.sovereignengineering.io  → Routstr Core (Docker :8000)    [LLM proxy + Kalman pricing]
    ├── mints.sovereignengineering.io    → Cashu mint (Docker :8085)     [AI credit issuance]
    ├── blossom.sovereignengineering.io  → blossom-server (Docker :3001) [blob storage]
    ├── nsite.sovereignengineering.io    → nsite-gateway (Docker :3002)  [static sites]
    ├── git.sovereignengineering.io      → ngit-grasp (Systemd :7334)    [nostr git]
    │
    └── Internal Docker network (not exposed):
        ├── mint-orchestrator (:8090)     [GRPC mark-invoice-paid daemon]
        ├── hermes-friend-1    (Hermes container, Nostr adapter → obelisk)
        ├── hermes-friend-2    (Hermes container, Nostr adapter → obelisk)
        └── hermes-friend-3    (Hermes container, Nostr adapter → obelisk)
            └── All route LLM → http://routstr:8000
```

**Key design decisions:**
- obelisk-relay for NIP-29 (lightweight, no PostgreSQL/Redis, already in Ansible kit)
- Hermes has native Nostr adapter at `gateway/platforms/nostr.py` — no Signal/Matrix needed
- Cashu mint (CDK mintd) with GRPC mark-paid via mint-orchestrator — no real Lightning
- Friends interact via Buzz client (desktop/web) connecting to obelisk-relay
- Each friend gets own Hermes container with full kanban + quality gates + worker profiles

---

## Task Breakdown — 12 Tasks

### PHASE 1: Infrastructure Foundation (Tasks 1-4)

---

#### Task 1: Boot + provision VPS + base Ansible

**Profile:** worker-admin
**Branch:** `multi-tenant/vps-base`
**Duration:** ~2 hours
**Depends on:** VPS booted (Felix action)

**Scope:**
- SSH into 64.188.7.38 (debian / ***REDACTED-ssh-64.188.7.38-20260817***)
- Check existing content, wipe if not relevant
- Install Debian 13 packages: docker, docker-compose, curl, jq, git, python3
- Set hostname to `sovereign-vps`
- Configure SSH key auth (Felix's public key)
- Set timezone to Felix's timezone
- Enable Docker daemon, add debian user to docker group
- Create Docker network `hermes-net` for inter-container communication
- Create directory structure: `/opt/sovereign/{routstr,obelisk,blossom,nsite,grasp,mints,hermes}`

**Deliverables:**
- VPS accessible via SSH key
- Docker running, hermes-net network created
- Directory structure in place

**Verification:**
- `ssh debian@64.188.7.38 docker ps` returns empty container list
- `ssh debian@64.188.7.38 docker network ls | grep hermes-net` exists

**Ansible:** Reuse `ansible/roles/system/` + `ansible/roles/docker/` + `ansible/roles/zram/`

---

#### Task 2: Deploy Caddy + Cloudflare DNS

**Profile:** worker-admin
**Branch:** `multi-tenant/caddy-dns`
**Duration:** ~1 hour
**Depends on:** Task 1

**Scope:**
- Deploy Caddy via existing `ansible/roles/caddy/` role
- Configure Cloudflare DNS A records for subdomains:
  - relay.sovereignengineering.io
  - routstr.sovereignengineering.io
  - mints.sovereignengineering.io
  - blossom.sovereignengineering.io
  - nsite.sovereignengineering.io
  - git.sovereignengineering.io
- Caddy auto-HTTPS via Cloudflare DNS-01 challenge
- Create Caddyfile template with all subdomain routes (placeholder backends for now)

**Deliverables:**
- Caddy running on :80/:443
- All subdomains resolve in DNS
- HTTPS certificates provisioned

**Verification:**
- `curl -sI https://relay.sovereignengineering.io` returns 502 (no backend yet, but TLS works)

**Ansible:** Reuse `ansible/roles/caddy/` + `ansible/roles/cloudflare_dns/`

---

#### Task 3: Deploy obelisk-relay (NIP-29 group chat)

**Profile:** worker-admin
**Branch:** `multi-tenant/obelisk`
**Duration:** ~1 hour
**Depends on:** Task 2

**Scope:**
- Deploy obelisk-relay via existing `ansible/roles/obelisk_relay/` role
- Configure with Felix's admin npub
- Generate relay nsec (server identity key)
- Set `relay_url` to `wss://relay.sovereignengineering.io`
- Enable NIP-42 authentication
- Add Caddy reverse proxy route: `relay.sovereignengineering.io` → `localhost:8080`
- Verify WebSocket upgrade headers in Caddy config

**Deliverables:**
- obelisk-relay running in Docker on :8080
- Caddy proxies wss://relay.sovereignengineering.io → :8080
- Felix can connect via Buzz client as admin

**Verification:**
- `curl -s https://relay.sovereignengineering.io/` returns relay info
- Connect via Buzz desktop client → see admin UI
- NIP-42 AUTH challenge works

---

#### Task 4: Deploy Routstr node (LLM proxy)

**Profile:** worker-admin
**Branch:** `multi-tenant/routstr`
**Duration:** ~1.5 hours
**Depends on:** Task 2

**Scope:**
- Deploy Routstr via existing `ansible/roles/routstr/` role
- Configure with Felix's z.ai API keys (ZAI_OUR_KEY + ZAI_API_KEY)
- Set pricing margins (configurable per-model)
- Enable Kalman-filter pricing
- Add Caddy route: `routstr.sovereignengineering.io` → `localhost:8000`
- Verify OpenAI-compatible endpoint responds

**Deliverables:**
- Routstr running in Docker on :8000
- `/v1/chat/completions` endpoint works with z.ai backend
- `/v1/models` returns available models
- Caddy reverse proxy configured

**Verification:**
- `curl -s https://routstr.sovereignengineering.io/v1/models` returns model list
- `curl -s -X POST https://routstr.sovereignengineering.io/v1/chat/completions -H "Content-Type: application/json" -d '{"model":"glm-5.2","messages":[{"role":"user","content":"hello"}]}'` returns response

---

### PHASE 2: Cashu Credit System (Tasks 5-6)

---

#### Task 5: Deploy Cashu mint (CDK mintd)

**Profile:** worker-admin
**Branch:** `multi-tenant/cashu-mint`
**Duration:** ~1.5 hours
**Depends on:** Task 2

**Scope:**
- Deploy CDK mintd via existing `ansible/roles/cashu_mint/` role
- Configure as testnut mint (no real Lightning)
- Enable GRPC endpoint for `UpdateNut04Quote` (mark invoice paid)
- Set mint units: `sat,msat` (for AI credit denomination)
- Add Caddy route: `mints.sovereignengineering.io` → `localhost:8085`
- Generate mint nsec (Nostr identity for the mint)

**Deliverables:**
- CDK mintd running in Docker with GRPC enabled on :50055
- Mint accessible at `https://routstr-mint.mints.sovereignengineering.io`
- GRPC `UpdateNut04Quote` endpoint functional
- `GetInfo` returns mint metadata

**Verification:**
- `grpcurl -plaintext localhost:50055 cdk_mint_management_v1.CdkMint/GetInfo` returns mint info
- Cashu wallet can connect and request mint quote

---

#### Task 6: Deploy mint-orchestrator (GRPC mark-paid daemon)

**Profile:** worker-admin
**Branch:** `multi-tenant/mint-orchestrator`
**Duration:** ~2 hours
**Depends on:** Task 5

**Scope:**
- Deploy mint-orchestrator from `~/tollgate-infrastructure-kit/mint-orchestrator/`
- Configure to listen for Nostr kind 38010 approval events on relay
- Connect to CDK mintd GRPC endpoint (:50055)
- When Felix signs an approval event → daemon calls `update_nut04_quote(quote_id, "PAID")`
- Deploy as systemd service (not Docker — needs access to relay WebSocket)
- Configure `ORCHESTRATOR_RELAY_URL=ws://localhost:7777` (strfry or obelisk)
- Set `ORCHESTRATOR_REGISTRY_PATH` to mint registry

**Deliverables:**
- mint-orchestrator running as systemd service
- Listens for kind 38010 events on the relay
- GRPC client connects to CDK mintd
- End-to-end: Felix signs approval → quote marked PAID → friend mints tokens

**Verification:**
- Felix creates a mint quote (request tokens)
- Felix signs a kind 38010 Nostr event approving the quote
- Daemon logs: `Approved quote <id> for <amount> sat`
- Friend can mint tokens with the paid quote

**Also deploy:** `mint-approve` CLI tool + `mint-operator-proxy` (REST API for mint management)

---

### PHASE 3: Hermes Containers (Tasks 7-10)

---

#### Task 7: Build Hermes Docker image

**Profile:** worker-admin
**Branch:** `multi-tenant/hermes-docker`
**Duration:** ~3 hours
**Depends on:** Task 1

**Scope:**
- Create `hermes-docker/` directory in tollgate-infrastructure-kit
- Write Dockerfile:
  - Base: `python:3.12-slim`
  - Install: git, curl, jq, sqlite3, openssh-client, docker.io (for worker containers — or use host Docker socket)
  - Install Hermes: `pip install hermes-agent` (or from source for nostr-adapter branch)
  - Install coincurve (for Schnorr signatures in Nostr adapter)
  - Pre-load skills: quality-gates, kanban-worker-management, cron-llm-escalation, hermes-agent, hermes-messaging-platforms
  - Create non-root `hermes` user
  - Entrypoint script that generates config.yaml from env vars
- Write `entrypoint.sh`:
  - Generate `~/.hermes/config.yaml` from environment variables
  - Set LLM proxy to `http://routstr:8000`
  - Set Nostr relay to `ws://obelisk:8080`
  - Set Nostr groups from env var
  - Load nsec from file path
  - Start Hermes gateway
- Build and tag image: `sovereign-hermes:latest`
- Test image locally (docker run --rm, verify Hermes starts)

**Deliverables:**
- `hermes-docker/Dockerfile` committed
- `hermes-docker/entrypoint.sh` committed
- `hermes-docker/skills/` directory with pre-loaded skills
- Docker image built and tagged

**Verification:**
- `docker run --rm sovereign-hermes:latest hermes --version` returns version
- `docker run --rm -e NOSTR_RELAYS=ws://test:8080 sovereign-hermes:latest` starts gateway

---

#### Task 8: Create hermes_tenants Ansible role

**Profile:** worker-admin
**Branch:** `multi-tenant/hermes-role`
**Duration:** ~3 hours
**Depends on:** Task 7

**Scope:**
- Create `ansible/roles/hermes_tenants/` with:
  - `defaults/main.yml`: default config (mem_limit, cpu, disk, skills list)
  - `tasks/main.yml`: main deployment logic
  - `templates/docker-compose.hermes.yml.j2`: per-friend compose template
  - `templates/config.yaml.j2`: per-friend Hermes config
  - `templates/soul.md.j2`: per-friend SOUL.md template
- Tasks:
  1. Build Hermes Docker image on VPS (copy Dockerfile, docker build)
  2. For each friend in `hermes_tenants` list:
     a. Generate Nostr keypair (nsec/npub) if not provided
     b. Write nsec to `{{ hermes_data_dir }}/{{ name }}/state/nip29-relay-nsec.key`
     c. Generate config.yaml from template
     d. Generate SOUL.md from template (with friend's name)
     e. Create Docker volume
     f. Start container with resource limits
     g. Register friend's npub in obelisk-relay whitelist
     h. Create NIP-29 group for friend + bot (kind 9000 put-user)
  3. Verify all containers running
  4. Print connection info (Buzz relay URL, friend npubs, bot npubs, group IDs)
- Variables per friend: name, npub (optional), nsec (optional), signal_number (optional)

**Deliverables:**
- `ansible/roles/hermes_tenants/` complete with templates
- Role tested with dry-run (--check)
- Commit + push

**Verification:**
- `ansible-playbook --check 50-multi-tenant-hermes.yml` runs without errors
- Template rendering produces valid config.yaml

---

#### Task 9: Write master playbook

**Profile:** worker-admin
**Branch:** `multi-tenant/playbook`
**Duration:** ~1 hour
**Depends on:** Tasks 1-8

**Scope:**
- Write `ansible/playbooks/50-multi-tenant-hermes.yml`:
  ```yaml
  ---
  - name: Deploy multi-tenant Hermes + Routstr + NIP-29 + Cashu
    hosts: sovereign_vps
    become: yes
    gather_facts: yes
    roles:
      - zram
      - system
      - docker
      - cloudflare_dns
      - caddy
      - obelisk_relay
      - routstr
      - cashu_mint
      - mint_orchestrator
      - mint_operator_proxy
      - blossom
      - nsite_gateway
      - grasp
      - watchdog
      - hermes_tenants
    vars:
      base_domain: sovereignengineering.io
      hermes_tenants:
        - name: friend-1
          # npub/nsec auto-generated if not provided
        - name: friend-2
        - name: friend-3
  ```
- Add `sovereign_vps` to `ansible/inventory/hosts.yml` with IP 64.188.7.38
- Add inventory group_vars for sovereign_vps (domain, Cloudflare token, z.ai keys)
- Update Makefile with `deploy-multi-tenant` target

**Deliverables:**
- Playbook committed
- Inventory updated
- Makefile target added

---

#### Task 10: Deploy + configure Hermes containers

**Profile:** worker-admin
**Branch:** `multi-tenant/deploy-hermes`
**Duration:** ~2 hours
**Depends on:** Tasks 3, 4, 6, 8, 9

**Scope:**
- Run `ansible-playbook 50-multi-tenant-hermes.yml --tags hermes_tenants`
- For each friend:
  - Container starts, Hermes gateway boots
  - Nostr adapter connects to obelisk-relay
  - Bot's npub registered in relay whitelist
  - NIP-29 group created (friend + bot)
  - Friend's Buzz client can connect and see their bot
- Configure Caddy routes for all services
- Verify end-to-end:
  1. Friend connects Buzz to `wss://relay.sovereignengineering.io`
  2. Friend authenticates with their nsec
  3. Friend joins their group
  4. Friend sends "hello" → Hermes bot responds
  5. Hermes routes LLM call through Routstr → z.ai → response

**Deliverables:**
- 3 Hermes containers running
- 3 NIP-29 groups created (one per friend)
- End-to-end test: message via Buzz → bot responds

---

### PHASE 4: Onboarding + Polish (Tasks 11-12)

---

#### Task 11: Friend onboarding documentation

**Profile:** worker-admin
**Branch:** `multi-tenant/onboarding-docs`
**Duration:** ~2 hours
**Depends on:** Task 10

**Scope:**
- Write `docs/FRIEND-ONBOARDING.md`:
  - How to install Buzz client (desktop + web)
  - How to import your Nostr key (or generate new one)
  - How to connect to `wss://relay.sovereignengineering.io`
  - How to authenticate (NIP-42)
  - How to talk to your Hermes bot
  - How to create kanban boards
  - How to spawn worker profiles
  - How quality gates work
  - How to get AI credits (Felix issues via Cashu mint)
  - How to check your credit balance
  - Troubleshooting guide
- Write `docs/OPERATOR-GUIDE.md` (for Felix):
  - How to add/remove friends
  - How to issue AI credits via GRPC/Nostr
  - How to monitor containers
  - How to scale (add more friends, upgrade VPS)
  - How to update Hermes images
  - Backup/restore procedures
- Write `docs/ARCHITECTURE-DIAGRAM.md`:
  - System diagram (updated with Cashu mint)
  - Data flow: Buzz → obelisk → Hermes → Routstr → z.ai
  - Credit flow: Felix approves → GRPC mark-paid → friend mints tokens → spend at Routstr

---

#### Task 12: Integration testing + deploy verification

**Profile:** worker-inspector
**Branch:** `multi-tenant/integration-test`
**Duration:** ~2 hours
**Depends on:** Task 10

**Scope:**
- Full end-to-end test:
  1. VPS fresh deploy via `make deploy-multi-tenant`
  2. All services start (Caddy, obelisk, Routstr, Cashu mint, orchestrator, 3 Hermes containers)
  3. Felix connects via Buzz → sees admin UI
  4. Felix creates approval event → mint marks quote paid
  5. Friend mints Cashu tokens
  6. Friend connects via Buzz → authenticates → joins group
  7. Friend sends message → Hermes responds (via Routstr → z.ai)
  8. Friend creates kanban board → creates task → dispatches worker
  9. Worker runs, quality gates pass, task completes
  10. Resource limits verified (no container exceeds 1GB RAM)
- Write test results to `docs/INTEGRATION-TEST-RESULTS.md`
- Cross-family review: have a different model family review the plan + code

---

## Dependency Graph

```
Task 1 (VPS base)
  ├── Task 2 (Caddy + DNS)
  │     ├── Task 3 (obelisk-relay) ──────────────┐
  │     ├── Task 4 (Routstr) ─────────────────── ┤
  │     └── Task 5 (Cashu mint) ─────────────── ┤
  │           └── Task 6 (mint-orchestrator) ──── ┤
  └── Task 7 (Hermes Docker image) ──────────────┤
        └── Task 8 (hermes_tenants role) ────────┤
              └── Task 9 (master playbook) ──────┤
                    └── Task 10 (deploy) ────────┤
                          ├── Task 11 (docs) ───┤
                          └── Task 12 (test) ───┘
```

**Parallelizable:** Tasks 3, 4, 5 can run in parallel (all depend on Task 2). Task 7 can run parallel to Tasks 3-6 (depends only on Task 1).

---

## Resource Budget

| Component | RAM | Disk | CPU |
|-----------|-----|------|-----|
| Caddy | 50MB | 100MB | minimal |
| obelisk-relay | 100MB | 1GB | minimal |
| Routstr | 200MB | 500MB | low |
| Cashu mint (CDK) | 200MB | 500MB | low |
| mint-orchestrator | 100MB | 50MB | minimal |
| Hermes container × 3 | 512MB × 3 = 1.5GB | 5GB × 3 = 15GB | fair-share |
| blossom | 100MB | 2GB | minimal |
| nsite-gateway | 50MB | 500MB | minimal |
| ngit-grasp | 50MB | 500MB | minimal |
| System overhead | 300MB | 1GB | — |
| **TOTAL** | **~2.7GB** | **~22GB** | — |

**Recommendation:** 4GB RAM VPS minimum. If VPS has 2GB, reduce to 2 friends or use 256MB per Hermes container.

---

## What Exists vs What Needs Building

### EXISTS (reuse directly):
- `ansible/roles/routstr/` — Routstr Docker deployment ✅
- `ansible/roles/obelisk_relay/` — obelisk NIP-29 relay ✅
- `ansible/roles/cashu_mint/` — CDK mintd Docker ✅
- `ansible/roles/mint_orchestrator/` — mint approval daemon ✅
- `ansible/roles/mint_operator_proxy/` — mint REST API ✅
- `ansible/roles/caddy/` — reverse proxy + TLS ✅
- `ansible/roles/docker/` — Docker runtime ✅
- `ansible/roles/cloudflare_dns/` — DNS automation ✅
- `ansible/roles/blossom/` — blob storage ✅
- `ansible/roles/nsite_gateway/` — static sites ✅
- `ansible/roles/grasp/` — Nostr git ✅
- `ansible/roles/system/` — base system ✅
- `ansible/roles/zram/` — memory optimization ✅
- `ansible/roles/watchdog/` — health monitoring ✅
- `mint-orchestrator/` — GRPC mark-paid code ✅
- `mint-orchestrator/protos/cdk-mint-rpc.proto` — GRPC proto ✅
- `mint-orchestrator/src/tollgate_mint_orchestrator/grpc_client.py` — GRPC client ✅
- Hermes `gateway/platforms/nostr.py` — native NIP-29 adapter ✅
- Hermes quality-gates skill ✅
- Hermes kanban-worker-management skill ✅

### NEEDS BUILDING:
- `hermes-docker/` — Dockerfile + entrypoint for Hermes container
- `ansible/roles/hermes_tenants/` — multi-container deployment role
- `ansible/playbooks/50-multi-tenant-hermes.yml` — master playbook
- Inventory entry for sovereign_vps
- Caddy template updates for all subdomains
- Friend onboarding documentation
- Operator guide
- Integration test suite

---

## Cashu Credit Flow (End-to-End)

Routstr Core uses Cashu tokens as the API authentication mechanism. The flow:

```
1. Felix signs Nostr kind 38010 approval event
   → mint-orchestrator daemon sees it
   → calls GRPC UpdateNut04Quote(quote_id, "PAID")
   → CDK mintd marks the invoice as paid

2. Friend's Cashu wallet mints tokens from the paid quote
   → Friend now has Cashu tokens (sat-denominated)

3. Friend's Hermes container uses routstrd as LLM proxy
   → routstrd manages Cashu wallet (via cocod)
   → Each LLM request includes x-cashu header with Cashu token
   → Routstr Core validates token, deducts cost, forwards to z.ai

4. Cost accounting:
   → Routstr charges per-token (Kalman pricing + margin)
   → Friend's Cashu balance decreases per request
   → When balance low: Felix issues more credits via GRPC
```

**Key:** routstrd (https://github.com/Routstr/routstrd) is the client-side daemon that manages the Cashu wallet and injects the `x-cashu` header. Each Hermes container runs routstrd alongside Hermes. routstrd connects to the shared Routstr node on the VPS.

**Hermes container LLM config:**
```yaml
llm:
  base_url: http://routstrd:9000  # local routstrd daemon
  api_key: ""  # routstrd injects the Cashu token header
```

Or if Hermes supports custom headers, point directly at the Routstr node:
```yaml
llm:
  base_url: http://routstr:8000
  extra_headers:
    x-cashu: "{{ cashu_token }}"  # refreshed by sidecar script
```

**Simpler approach for V1:** Skip per-token payment gating. Friends use the Routstr node freely (Felix's z.ai keys). Add Cashu gating in V2 once the basics work. This avoids the complexity of running routstrd + cocod in each container.

---

## Self-Review (consultant was unavailable due to quota)

### BLOCKER: Docker-in-Docker for worker profiles
Hermes worker profiles spawn subprocesses that use terminal, git, file tools. Inside a Docker container, this works fine for basic operations. But if workers need to run `docker` commands (e.g., for kanban worker containers), they need Docker-in-Docker or Docker socket mounting. **Recommendation:** Mount the host Docker socket into each Hermes container (`-v /var/run/docker.sock:/var/run/docker.sock`). This lets workers use Docker without DinD, but means containers share the Docker daemon (not fully isolated). For 3 trusted friends, this is acceptable.

### WARNING: Memory budget tight for 4GB VPS
3 Hermes containers at 512MB each = 1.5GB. Plus Routstr (200MB), obelisk (100MB), Cashu mint (200MB), mint-orchestrator (100MB), Caddy (50MB), system (300MB) = ~2.5GB. Leaves 1.5GB headroom. **OK if VPS has 4GB.** If 2GB, reduce to 256MB per Hermes container or limit to 2 friends.

### WARNING: Hermes Docker image needs testing
Hermes is designed to run as a system package, not in Docker. The Docker image needs to handle: persistent state (volumes), gateway restart, signal handling, Nostr adapter (coincurve), Python 3.11+ compatibility. **Recommendation:** Task 7 should include a smoke test (docker run → hermes gateway starts → Nostr adapter connects to relay → basic chat works).

### SUGGESTION: Start without Cashu gating
V1: Friends use shared Routstr freely (Felix's keys). Track usage per friend via zai_usage.db (already tracks per-container). V2: Add Cashu payment gating once basics work. This simplifies Tasks 5-6 and removes the routstrd + cocod dependency from each container.

### SUGGESTION: Use obelisk-relay's built-in Cashu wallet
obelisk-relay has a built-in NIP-60/61 Cashu wallet. If we enable it, friends can tip each other or pay for services within the Buzz interface. Future enhancement, not needed for V1.

### SUGGESTION: Backup strategy
Add `ansible/roles/syncthing/` to the playbook for incremental backup to T470 (like testserver2 setup). Each friend's Docker volume gets synced. Low priority — add after initial deployment works.

---

## Open Questions for Felix

1. **Domain:** Use `sovereignengineering.io` or another domain?
2. **VPS RAM:** How much RAM does the SSD VPS have? Need 4GB for 3 friends.
3. **Friend npubs:** Do friends already have Nostr identities, or generate fresh ones?
4. **V1 or V2 Cashu gating:** Start without payment gating (simpler) or full Cashu from day 1?
5. **Credit amount:** If using Cashu, how much credit per friend per month?
6. **Docker socket:** OK to mount host Docker socket into friend containers (needed for worker profiles)?