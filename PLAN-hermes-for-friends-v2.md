# Hermes for Friends — v2 Implementation Plan

**Date:** 2026-08-14
**Operator:** Felix
**VPS:** VPS2 (23.182.128.51) — active deployment target
**SSD VPS:** 64.188.7.38 — offline, migration target when back
**Repo:** `felixfelix-bot/tollgate-infrastructure-kit`

## Current State

### Running on VPS2 (verified Aug 14):
- 3 Hermes containers: `hermes-ours`, `hermes-friend1`, `hermes-friend2` (10h uptime, healthy)
- Image: `hermes-agent:nostr` (7.89GB, s6-overlay, Python 3.13, Hermes v0.17.0)
- Gateway process running inside containers (`hermes gateway run --replace`)
- Buzz relay: `ghcr.io/block/buzz:latest` + postgres + redis (2 days uptime)
- Infra: routstr-proxy, cdk-mintd, mint-orchestrator, strfry, blossom, ngit, nsite-gateway

### Known Issues:
1. Container names need renaming: ours→sitarani, friend1→chiefmonkey, friend2→bekka
2. Gateway NOT listening on 8080 inside containers (process runs but no port bound)
3. Hermes image 7.89GB — too heavy, needs multi-stage build
4. docker-compose.tenant.yml.j2 has uncommitted fixes (now committed as fe3c054)
5. No routstrd production Docker image
6. No end-to-end test: Buzz → relay → Hermes → response
7. No backup strategy for container volumes
8. SSD VPS offline — migration blocked

---

## Task Breakdown — 14 Tasks, 4 Phases

### PHASE 1: Fix + Rename + Verify (Tasks 1-4)

---

#### Task 1: Rename Hermes containers + update Ansible role

**Worker:** worker-admin
**Branch:** `hermes-v2/rename-containers`
**Duration:** ~30 min
**Depends on:** nothing
**Quality gates:** G1 (test exists), G2 (tests pass), G4 (atomic commit), G5 (pushed)

**Scope:**
- Update `hermes_tenants/defaults/main.yml` — no code change needed (tenant names are variables)
- Update the playbook `45-multi-tenant-hermes.yml` (or wherever tenants are defined) to use:
  ```yaml
  hermes_tenants_tenants:
    - name: sitarani
      zai_api_key: "{{ sitarani_zai_api_key }}"
    - name: chiefmonkey
      zai_api_key: "{{ chiefmonkey_zai_api_key }}"
    - name: bekka
      zai_api_key: "{{ bekka_zai_api_key }}"
  ```
- On VPS2: stop old containers, rename volumes + networks, start with new names
- Preserve existing data volumes (rename, don't recreate)
- Update `.env` files per tenant

**Deliverables:**
- Ansible role updated to use new tenant names
- VPS2 containers running as hermes-sitarani, hermes-chiefmonkey, hermes-bekka
- Old volumes renamed (data preserved)

**Verification:**
- `docker ps --format '{{.Names}}' | grep hermes` shows 3 containers with new names
- `docker inspect hermes-sitarani --format '{{.State.Health.Status}}'` = healthy
- All 3 containers have running gateway process

**Pitfalls:**
- Docker volume rename requires `docker run --rm -v old:/data -v new:/newdata alpine cp -a /data/. /newdata/` (no direct rename)
- Network names must match: hermes-net-sitarani, hermes-net-chiefmonkey, hermes-net-bekka
- Container gateway ports: 9000 (sitarani), 9001 (chiefmonkey), 9002 (bekka)

---

#### Task 2: Fix Hermes gateway port binding inside containers

**Worker:** worker-admin
**Branch:** `hermes-v2/fix-gateway-port`
**Duration:** ~45 min
**Depends on:** Task 1
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Investigate why `hermes gateway run` process runs but doesn't bind port 8080
- Check Hermes config inside container: `docker exec hermes-sitarani cat /data/config.yaml`
- Check if gateway needs explicit port config: `gateway.port: 8080` or `PORT=8080` env var
- Check s6 service definition: `docker exec hermes-sitarani cat /run/service/main-hermes/run`
- Fix: either config.yaml, env var, or s6 service script
- Verify gateway responds: `docker exec hermes-sitarani curl -s http://localhost:8080/health`
- Update entrypoint/config template in Ansible role if needed

**Deliverables:**
- Gateway listening on 8080 inside all 3 containers
- `curl http://localhost:8080/health` returns 200 inside container
- Fix documented in Ansible role (config template or env var)

**Verification:**
- `docker exec hermes-sitarani curl -s http://localhost:8080/health` = 200
- Same for chiefmonkey + bekka
- From host: `curl -s http://localhost:9000/health` = 200 (port-mapped)

**Pitfalls:**
- s6-overlay may override the command — check `/run/service/main-hermes/run`
- Hermes config may need `gateway.port` not just `PORT` env var
- The `sleep infinity` in compose overrides the image's default entrypoint — may need to remove it and let s6 manage the process

---

#### Task 3: End-to-end test — Buzz relay → Hermes container → response

**Worker:** worker-inspector
**Branch:** `hermes-v2/e2e-buzz-test`
**Duration:** ~1 hour
**Depends on:** Task 2
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Verify Buzz relay is accessible: `wss://relay.orangesync.tech` (or VPS2 IP:port)
- Check Buzz relay port mapping on VPS2: `docker port buzz-relay`
- Create a test NIP-29 group on the relay using buzz CLI or nak
- Configure one Hermes container (hermes-sitarani) to listen on that group
- Send a test message to the group via buzz CLI
- Verify Hermes container receives the message and responds
- Document the full flow: Buzz client → relay → Hermes → LLM proxy → response

**Test script** (`tests/e2e-buzz-hermes.sh`):
```bash
#!/bin/bash
# 1. Check relay is up
# 2. Create test group
# 3. Configure Hermes to listen
# 4. Send message via buzz CLI
# 5. Wait for response (timeout 30s)
# 6. Verify response received
# 7. Cleanup test group
```

**Deliverables:**
- `tests/e2e-buzz-hermes.sh` — executable test script
- Test passes: message sent → response received
- Test results documented

**Verification:**
- Script exits 0
- Response message visible in buzz CLI output
- Hermes container logs show message received + response sent

**Pitfalls:**
- Buzz relay may need NIP-42 auth — ensure nsec is configured
- Hermes nostr adapter may need specific env vars (NOSTR_RELAYS, NOSTR_GROUPS, NOSTR_NSEC_PATH)
- Relay URL inside Docker network may differ from external URL
- The `sleep infinity` command in compose may prevent s6 from starting the gateway properly

---

#### Task 4: Fix docker-compose.tenant.yml.j2 — remove `sleep infinity`, let s6 manage

**Worker:** worker-admin
**Branch:** `hermes-v2/fix-compose-entrypoint`
**Duration:** ~30 min
**Depends on:** Task 2
**Quality gates:** G1, G2, G4, G5

**Scope:**
- The compose template has `command: ["sleep", "infinity"]` which overrides the image's s6 entrypoint
- This is why the gateway process runs (s6 starts it) but may not bind ports correctly
- Remove the `command` override — let the image's default s6-overlay manage services
- OR: replace with `command: ["hermes", "gateway", "run"]` if s6 is not needed
- Test both approaches:
  - Option A: Remove `command` line entirely (s6 manages everything)
  - Option B: `command: ["/opt/hermes/docker/main-wrapper.sh"]` (explicit s6 entrypoint)
- Verify containers stay up + gateway binds port after change

**Deliverables:**
- docker-compose.tenant.yml.j2 updated (no `sleep infinity`)
- Containers restart with new config and stay healthy
- Gateway port bound and responding

**Verification:**
- `docker compose up -d` succeeds
- Container stays up for 5 min without crashing
- `curl http://localhost:9000/health` = 200

---

### PHASE 2: Optimize + Build (Tasks 5-7)

---

#### Task 5: Trim Hermes Docker image (7.89GB → target <2GB)

**Worker:** worker-admin
**Branch:** `hermes-v2/trim-image`
**Duration:** ~2 hours
**Depends on:** Task 4
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Analyze current image layers: `docker history hermes-agent:nostr --no-trunc`
- Identify bloat sources:
  - Playwright browsers (~500MB) — remove if not needed in container
  - ffmpeg + audio deps — remove if not needed
  - Node.js runtime — remove if not needed (Hermes is Python)
  - Build tools (gcc, make) — remove in multi-stage build
  - apt cache — clean in Dockerfile
- Write multi-stage Dockerfile:
  - Stage 1 (builder): install deps, build Hermes
  - Stage 2 (runtime): copy only runtime artifacts
- Build new image: `hermes-agent:nostr-slim`
- Test: container starts, gateway runs, all features work
- Target: <2GB image size

**Deliverables:**
- `hermes-docker/Dockerfile.slim` — multi-stage build
- `hermes-agent:nostr-slim` image built and tested
- Image size <2GB

**Verification:**
- `docker images hermes-agent:nostr-slim --format '{{.Size}}'` < 2GB
- Container starts, gateway binds port, responds to health check
- `hermes --version` works inside container
- Nostr adapter loads (check logs for relay connection)

**Pitfalls:**
- Removing Playwright breaks web testing skill — acceptable for friend containers
- coincurve (Schnorr signatures) needs native libs — keep in runtime stage
- s6-overlay is needed for process management — keep
- Test thoroughly: a smaller image that doesn't work is worse than a big one that does

---

#### Task 6: Build routstrd production Docker image

**Worker:** worker-admin
**Branch:** `hermes-v2/routstrd-docker`
**Duration:** ~2 hours
**Depends on:** nothing (parallel with Task 5)
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Check routstrd repo: `~/repos/routstrd/` or clone from GitHub
- Current Dockerfile is dev-oriented (interactive bash)
- Write production Dockerfile:
  - Multi-stage: build Rust binary in builder stage
  - Runtime: minimal image with just routstrd binary + config dir
  - Entrypoint: `routstrd start` (daemon mode)
  - Health check: `curl http://localhost:8008/health`
  - Volume: `/data` for wallet + config
- Build + test locally
- Test wallet persistence across container restart
- Test Nostr discovery (does routstrd find our Routstr node?)

**Deliverables:**
- `routstrd-docker/Dockerfile` — production multi-stage build
- `routstrd:latest` image built
- Wallet persists across restart
- Discovers Routstr node via Nostr

**Verification:**
- `docker run --rm routstrd:latest routstrd --version`
- `docker run -d routstrd:latest` stays running
- `curl http://localhost:8008/health` = 200
- After restart: wallet balance preserved

**Pitfalls:**
- routstrd needs coincurve for Nostr signing — ensure native deps in runtime
- cocod daemon (wallet) needs persistent storage — mount /data volume
- Nostr discovery needs relay access — ensure network config

---

#### Task 7: Integrate routstrd sidecar into docker-compose.tenant.yml.j2

**Worker:** worker-admin
**Branch:** `hermes-v2/routstrd-sidecar`
**Duration:** ~1 hour
**Depends on:** Tasks 5, 6
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Add routstrd service to docker-compose.tenant.yml.j2:
  ```yaml
  services:
    hermes-{{ tenant_name }}:
      ...existing...
      depends_on:
        - routstrd-{{ tenant_name }}
    
    routstrd-{{ tenant_name }}:
      image: routstrd:latest
      container_name: routstrd-{{ tenant_name }}
      volumes:
        - routstrd-{{ tenant_name }}-data:/data
      networks:
        - routstr_default
        - hermes-net-{{ tenant_name }}
      healthcheck:
        test: ["CMD-SHELL", "curl -sf http://localhost:8008/health || exit 1"]
      mem_limit: 256m
      cpus: "0.5"
  ```
- Update Hermes env: `LLM_PROXY_URL=http://routstrd-{{ tenant_name }}:8008/v1`
- Add routstrd volume to volumes section
- Test: Hermes routes LLM calls through routstrd → Routstr node → z.ai

**Deliverables:**
- docker-compose.tenant.yml.j2 updated with routstrd sidecar
- End-to-end: Hermes → routstrd → Routstr → z.ai → response

**Verification:**
- `docker compose up -d` starts both Hermes + routstrd per tenant
- LLM request from Hermes container gets response
- routstrd logs show Cashu payment + forwarding

---

### PHASE 3: Documentation + Backup (Tasks 8-10)

---

#### Task 8: Complete friend onboarding documentation

**Worker:** worker-inspector
**Branch:** `hermes-v2/onboarding-docs`
**Duration:** ~1.5 hours
**Depends on:** Tasks 3, 7
**Quality gates:** G3 (docs updated), G4, G5

**Scope:**
- Update `docs/onboarding-friend-guide.md` (partially written, committed at a378d7a)
- Add sections:
  - **Getting your Nostr key** — how to generate or import an nsec
  - **Installing Buzz** — Play Store link + desktop app link (github.com/block/buzz/releases)
  - **Connecting to our relay** — `wss://relay.orangesync.tech` (or whatever the URL is)
  - **NIP-42 authentication** — how the relay authenticates you
  - **Your Hermes bot** — how to talk to it, what it can do
  - **Kanban boards** — how to create tasks, dispatch workers
  - **Quality gates** — what they are, why they matter
  - **AI credits** — how to check balance, how to get more
  - **Troubleshooting** — common issues + solutions
- Write `docs/operator-guide.md` (for Felix):
  - How to add/remove friends
  - How to issue AI credits via mint-approve
  - How to monitor containers
  - How to update Hermes images
  - Backup/restore procedures

**Deliverables:**
- `docs/onboarding-friend-guide.md` — complete, tested with a non-technical user
- `docs/operator-guide.md` — complete

**Verification:**
- Docs reviewed by worker-inspector (cross-family review)
- All commands in docs tested against live VPS2

---

#### Task 9: Backup strategy for container volumes

**Worker:** worker-admin
**Branch:** `hermes-v2/backup`
**Duration:** ~1 hour
**Depends on:** Task 1
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Identify volumes to backup:
  - `hermes-sitarani-data`, `hermes-chiefmonkey-data`, `hermes-bekka-data`
  - `buzz-relay-postgres-data` (chat history)
  - `cdk-mintd-data` (mint state)
- Write backup script: `scripts/backup-hermes-volumes.sh`
  - Uses `docker run --rm -v <vol>:/data -v /backup:/backup alpine tar czf /backup/<vol>-$(date).tar.gz /data`
  - Rotates: keep 7 daily, 4 weekly, 3 monthly
  - Sends to testserver2 or T470 via rsync (or Syncthing)
- Create systemd timer: `hermes-backup.timer` (daily at 3am)
- Test restore: stop container, restore volume, start container, verify data intact

**Deliverables:**
- `scripts/backup-hermes-volumes.sh`
- `ansible/roles/backup/` (or add to existing backup role)
- systemd timer deployed on VPS2
- Restore tested + documented

**Verification:**
- Backup runs: `systemctl start hermes-backup && ls /backup/`
- Restore tested: volume restored, container starts with data intact
- Backup size <5GB total

---

#### Task 10: Monitoring + alerting for Hermes containers

**Worker:** worker-admin
**Branch:** `hermes-v2/monitoring`
**Duration:** ~45 min
**Depends on:** Task 2
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Write health check script: `scripts/hermes-health-check.sh`
  - Checks each container: `docker inspect --format '{{.State.Health.Status}}'`
  - Checks gateway: `curl -sf http://localhost:900X/health`
  - Checks Buzz relay: `curl -sf http://localhost:3000/`
  - Checks routstr: `curl -sf http://localhost:8000/v1/models`
  - Exits non-zero if any check fails
- Create cron job (script-only, no_agent=true, silent unless failure):
  - Schedule: every 15 min
  - Deliver: local (save to file)
  - Alert on failure only
- Deploy on VPS2 via Ansible

**Deliverables:**
- `scripts/hermes-health-check.sh`
- Cron job created
- Ansible task to deploy script + cron

**Verification:**
- Script runs clean when all services up
- Script fails when a container is stopped (tested)
- Cron job silent when healthy, alerts on failure

---

### PHASE 4: SSD VPS Migration (Tasks 11-14)

---

#### Task 11: SSD VPS readiness check + migration plan

**Worker:** worker-admin
**Branch:** `hermes-v2/ssd-migration`
**Duration:** ~30 min
**Depends on:** SSD VPS back online
**Quality gates:** G4, G5

**Scope:**
- Check if SSD VPS (64.188.7.38) is back
- If up: SSH in, check OS, RAM, disk, existing content
- Run Ansible dry-run: `ansible-playbook 45-multi-tenant-hermes.yml --check`
- Document what needs to change for SSD VPS vs VPS2
- Update migration plan

**Deliverables:**
- VPS readiness report
- Updated migration plan

---

#### Task 12: Deploy full stack on SSD VPS

**Worker:** worker-admin
**Branch:** `hermes-v2/ssd-deploy`
**Duration:** ~3 hours
**Depends on:** Tasks 5, 6, 7, 11
**Quality gates:** G1, G2, G4, G5

**Scope:**
- Run full Ansible playbook on SSD VPS
- Deploy: Caddy, strfry, Buzz relay, Routstr, Cashu mint, mint-orchestrator
- Deploy 3 Hermes containers with slim image + routstrd sidecar
- Verify all services healthy
- Migrate data from VPS2 (rsync volumes)

**Deliverables:**
- Full stack running on SSD VPS
- All containers healthy
- Data migrated from VPS2

---

#### Task 13: DNS cutover — switch domains to SSD VPS

**Worker:** worker-admin
**Branch:** `hermes-v2/dns-cutover`
**Duration:** ~30 min
**Depends on:** Task 12
**Quality gates:** G4, G5

**Scope:**
- Update Cloudflare DNS A records to point to SSD VPS IP
- Verify TLS certificates provisioned
- Verify all subdomains resolve + respond
- Keep VPS2 as fallback (don't shut down for 48h)

**Deliverables:**
- DNS switched
- All services accessible via domain names
- VPS2 remains as fallback

---

#### Task 14: Integration testing on SSD VPS

**Worker:** worker-inspector
**Branch:** `hermes-v2/ssd-integration-test`
**Duration:** ~1.5 hours
**Depends on:** Task 13
**Quality gates:** G1, G2, G3, G4, G5

**Scope:**
- Run `tests/e2e-buzz-hermes.sh` against SSD VPS
- Full end-to-end:
  1. Buzz client connects to relay
  2. User authenticates (NIP-42)
  3. User sends message to group
  4. Hermes receives + responds
  5. Hermes routes LLM via routstrd → Routstr → z.ai
  6. Cashu payment works (routstrd pays Routstr)
  7. Kanban board creation works
  8. Worker dispatch works
  9. Quality gates enforce
  10. Resource limits respected (no container exceeds limit)
- Write results to `docs/INTEGRATION-TEST-RESULTS-SSD.md`

**Deliverables:**
- All 10 E2E tests pass
- Results documented
- Any failures filed as bugs

---

## Dependency Graph

```
Task 1 (rename containers)
  ├── Task 2 (fix gateway port)
  │     ├── Task 3 (E2E Buzz test)
  │     ├── Task 4 (fix compose entrypoint)
  │     │     └── Task 5 (trim image)
  │     │           └── Task 7 (routstrd sidecar)
  │     │                 └── Task 8 (onboarding docs)
  │     └── Task 10 (monitoring)
  └── Task 9 (backup)

Task 6 (routstrd Docker image) — parallel with Task 5
  └── Task 7 (routstrd sidecar)

Task 11 (SSD readiness) — blocked on VPS
  └── Task 12 (SSD deploy)
        └── Task 13 (DNS cutover)
              └── Task 14 (integration test)
```

**Parallelizable:**
- Tasks 5 + 6 can run in parallel (different workers)
- Task 9 can run parallel with Tasks 2-4
- Task 10 can run parallel with Tasks 3-4
- Tasks 11-14 blocked on SSD VPS availability

---

## Worker Assignments

| Task | Worker | Model | Est | Depends on |
|------|--------|-------|-----|------------|
| 1 — Rename containers | worker-admin | glm-5.2 | 30m | — |
| 2 — Fix gateway port | worker-admin | glm-5.2 | 45m | 1 |
| 3 — E2E Buzz test | worker-inspector | glm-5.2 | 60m | 2 |
| 4 — Fix compose entrypoint | worker-admin | glm-5.2 | 30m | 2 |
| 5 — Trim image | worker-admin | glm-5.2 | 2h | 4 |
| 6 — routstrd Docker | worker-admin | glm-5.2 | 2h | — |
| 7 — routstrd sidecar | worker-admin | glm-5.2 | 1h | 5,6 |
| 8 — Onboarding docs | worker-inspector | glm-5.2 | 1.5h | 3,7 |
| 9 — Backup strategy | worker-admin | glm-5.2 | 1h | 1 |
| 10 — Monitoring | worker-admin | glm-4.5-flash | 45m | 2 |
| 11 — SSD readiness | worker-admin | glm-4.5-flash | 30m | VPS up |
| 12 — SSD deploy | worker-admin | glm-5.2 | 3h | 5,6,7,11 |
| 13 — DNS cutover | worker-admin | glm-4.5-flash | 30m | 12 |
| 14 — Integration test | worker-inspector | glm-5.2 | 1.5h | 13 |

---

## Quality Gates (per task)

Every task MUST pass:
1. **G1 — Test exists:** Test written BEFORE implementation (TDD)
2. **G2 — Tests pass:** Full test suite run, output verified
3. **G3 — Docs updated:** In same commit as code changes
4. **G4 — Atomic commits:** One concern per commit, conventional messages
5. **G5 — Pushed:** `git push` exit 0, remote verified

For infrastructure tasks (1, 4, 7, 12, 13):
- G1 = verification script (bash, not pytest)
- G2 = script exits 0 on live VPS

For documentation tasks (8):
- G3 = docs reviewed by second worker (cross-family)

---

## Resolved Questions (operator answers Aug 14)

1. **Buzz relay URL:** `relay.orangesync.tech` → VPS2 (23.182.128.51). Two relays: `relay.` (general strfry) + `chat.` (Buzz/NIP-29). Both DNS-pointed to VPS2. ✅
2. **Friend npubs:** They have main npubs. Generate fresh nsecs per friend (not main keys). Known npubs: sitarani=npub1a3um269aaf3u5cy37kuykrrrnsg2pyv7za06pxjduv25lq5sdujs2qmdj6, bekka=npub18ekka6n399pskjzjusvduscem5c99dewg2swe3u68vdce92cmxgszeht3g. Chiefmonkey npub TBD (generate fresh nsec regardless).
3. **LLM routing:** All traffic through routstrd → Routstr node → cheapest endpoint. routstrd in each container auto-discovers providers via Nostr, picks cheapest, pays with Cashu. Per-friend wallet for quota isolation. No per-tenant z.ai keys needed.
4. **Domain:** Same domain (orangesync.tech) for SSD VPS.
5. **Buzz relay migration:** Migrate existing Buzz relay to SSD VPS when it comes online. Deploy fresh strfry.
6. **VPS2 SSH:** Currently timing out on banner exchange — likely overloaded (3 Hermes + Buzz + infra on 4GB RAM). Not blocking for planning; workers should use `ssh -o ConnectTimeout=30`.
7. **routstrd:** Bun/TypeScript app (not Rust). Dockerfile exists but dev-oriented. Production image: `CMD ["routstrd", "start"]`. Has `--hermes` client integration.
