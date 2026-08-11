# ROADMAP — Multi-Tenant Hermes Hosting v2

**Date:** 2026-08-12
**Status:** DRAFT — awaiting operator approval
**Grill phase:** COMPLETE — 14 issues surfaced, 8 resolved, 6 open

---

## 1. Decisions (locked)

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | obelisk-relay (NOT Block Buzz) | 100MB vs 1GB RAM. Already in Ansible kit. Running in prod. |
| D2 | CDK mintd + fakewallet | No Lightning needed. Felix issues free credits. GRPC approval flow exists. |
| D3 | routstrd as client sidecar in each Hermes container | Friends can use OUR Routstr node OR any other. No lock-in. |
| D4 | Hermes native NIP-29 adapter (branch nostr-adapter) | Already built, coincurve Schnorr, tested 4/5. No Signal/Matrix needed. |
| D5 | Full sovereign engineering setup per friend | Kanban, quality gates, workers, skills, SOUL.md — not stripped down. |
| D6 | 3 friends initial, 8GB VPS minimum | ~6.6GB estimated with all 3 active. Can scale VPS later. |
| D7 | Ansible playbook 50-multi-tenant-hermes.yml | New role `hermes_tenants` + reuse 10 existing roles. |
| D8 | Per-friend Docker volume isolation | Own SQLite, own nsec, own kanban boards, own session DB. |

---

## 2. Adversarial Grill — Issues Surfaced

### RESOLVED (8 issues — answers found during grill)

**G1. Does Hermes Docker image exist?**
NO. `pip install hermes-agent` is the install path. Need custom Dockerfile.
RESOLUTION: Build `hermes-docker/` with Dockerfile (python:3.12-slim + pip install + pre-loaded skills + entrypoint.sh).

**G2. Can Hermes talk to obelisk-relay natively?**
YES. Branch `nostr-adapter` on `felixfelix-bot/hermes-agent`, commit a480d7fbef. Native NIP-29 adapter at `gateway/platforms/nostr.py`. Uses coincurve Schnorr. Config via env vars. Tested 4/5.
RESOLUTION: Use native adapter. Env vars: `NOSTR_RELAYS`, `NOSTR_GROUPS`, `NOSTR_NSEC_PATH`.

**G3. Is routstrd production-ready for Docker?**
PARTIAL. Current Dockerfile is dev-oriented (interactive bash). Need production version with `CMD ["routstrd", "start", "--port", "8008"]`.
RESOLUTION: Write production Dockerfile for routstrd. Volume mount for `/data` (wallet + config persistence).

**G4. Does obelisk-relay support NIP-42 AUTH?**
YES. Admin npub whitelist via `ADMIN_NPUB` env var. Friends authenticate with their nsec.
RESOLUTION: Set `ADMIN_NPUB` to Felix's npub. Ansible task adds each friend's npub to whitelist.

**G5. strfry29 membership enforcement — how does friend's bot join group?**
Kind 9000 (put-user) event from admin. Each friend's Hermes bot needs its own keypair added as group member.
RESOLUTION: Ansible task generates nsec per friend's bot, publishes kind 9000 to add bot to group.

**G6. Is the nostr-adapter branch merged into Hermes main?**
NO. It's on branch `nostr-adapter` of `felixfelix-bot/hermes-agent`. Need to either merge or use the branch.
RESOLUTION: Use the branch for now. Plan a merge to main as a separate task. Dockerfile pulls from branch.

**G7. How does routstrd discover OUR Routstr node specifically?**
routstrd discovers nodes via Nostr (kinds 38421/38423/38425). Our Routstr node publishes these events to our strfry relay. routstrd configured with `--relay ws://strfry:7777` will find it.
RESOLUTION: Ensure strfry relay is running and Routstr node is publishing discovery events. routstrd config: `ROUTSTRD_RELAY=ws://strfry:7777`.

**G8. Can friends use their OWN z.ai keys too?**
YES. routstrd supports `apikeys` mode (pre-fund at provider) and `xcashu` mode (inline payment). Friends can also configure custom providers in their Hermes config.
RESOLUTION: Default to our Routstr node. Friends can add their own providers via `hermes config set`.

### OPEN (6 issues — need operator input or further work)

**O1. BASE_DOMAIN — which domain?**
The plan references `BASE_DOMAIN` but doesn't specify. Options:
- `orangesync.tech` (already used for testserver2 services)
- A new domain for this VPS
- Subdomain of sovereignengineering.io
QUESTION: Felix, which domain for this VPS?

**O2. VPS boot — is 64.188.7.38 actually alive?**
Current status: completely offline (no ping, no SSH, no ports). Felix says he restarted it but it's still not responding. Need to either:
- Boot from provider console (VNC)
- Reinstall OS from provider panel
- Use a different VPS
QUESTION: Can you check the provider panel for boot status?

**O3. Hermes nostr-adapter merge — use branch or merge to main?**
The adapter is on branch `nostr-adapter`. For Docker builds, we either:
- Pin to the branch (fragile — branch could be deleted)
- Merge to main first (clean, but requires upstream PR or fork merge)
QUESTION: Merge to main first, or pin to branch in Dockerfile?

**O4. Worker profile limits — how many workers per friend?**
3 friends × unlimited workers = potential VPS overload.
Options: hard limit (3 per friend), soft limit (Docker mem_limit), or trust-based.
QUESTION: Hard limit workers per friend, or rely on Docker resource limits?

**O5. Cashu mint — deploy on this VPS or use existing testserver2 mint?**
testserver2 already has CDK mint + orchestrator. This VPS could either:
- Deploy its own mint (more resources, ~100MB)
- Use testserver2's mint (network dependency, cross-VPS)
QUESTION: Local mint on this VPS, or reuse testserver2's mint?

**O6. Cost model — flat monthly or per-token SATs?**
Plan mentions both. Need to decide initial model:
- Flat: $5/mo each + usage (simple, but no enforcement)
- Per-token: Cashu tokens via Routstr (enforced, but needs mint + wallet setup)
- Hybrid: flat fee covers base, Cashu for overage
QUESTION: Start with flat monthly or per-token from day 1?

---

## 3. Acceptance Criteria

| # | Criterion | How to Verify |
|---|-----------|---------------|
| AC1 | `ansible-playbook 50-multi-tenant-hermes.yml` deploys all services in one command | Run playbook, check all containers running |
| AC2 | Each friend can chat with their Hermes bot via Buzz client | Friend sends message in Buzz → bot responds within 30s |
| AC3 | Each friend's Hermes has kanban, quality gates, workers | `hermes kanban ls` shows boards, `skills_list` shows gates |
| AC4 | LLM calls route through Routstr node (not direct z.ai) | Check Routstr logs for requests from all 3 containers |
| AC5 | Containers isolated — no cross-friend data access | Docker volume inspection, no shared mounts |
| AC6 | Resource limits enforced | `docker stats` shows mem_limit per container |
| AC7 | Onboarding doc exists | `docs/onboarding-friends.md` in repo |
| AC8 | All code tested | Integration test: `pytest tests/test_multi_tenant.py` |
| AC9 | Hermes NIP-29 adapter works with obelisk-relay | E2E test: message from Buzz → relay → Hermes → response |
| AC10 | Cost tracking works | Routstr logs per-container token usage |

---

## 4. Ordered Pseudo-Steps

### Phase 0: Prerequisites (operator)
- [ ] P0.1 Boot VPS at 64.188.7.38 (or decide alternative)
- [ ] P0.2 Choose BASE_DOMAIN (O1)
- [ ] P0.3 Decide: merge nostr-adapter to main or pin to branch (O3)
- [ ] P0.4 Collect 3 friends' npubs (or auto-generate)

### Phase 1: Infrastructure Ansible roles (reuse existing)
- [ ] P1.1 00-zram → 01-system → 02-docker → 03-cloudflare-dns → 04-caddy
- [ ] P1.2 05-strfry → 06-obelisk-relay
- [ ] P1.3 18-routstr (Routstr node with z.ai keys)
- [ ] P1.4 07-blossom → 08-nsite-gateway (optional, for static sites)
- [ ] P1.5 20-watchdog

### Phase 2: Cashu mint (if local mint — O5)
- [ ] P2.1 16-cashu-brrr (CDK mintd, fakewallet)
- [ ] P2.2 17-mint-orchestrator (GRPC approval daemon)
- [ ] P2.3 Verify: create quote → approve → mint tokens → spend at Routstr

### Phase 3: Hermes Docker image
- [ ] P3.1 Write `hermes-docker/Dockerfile` (python:3.12-slim + hermes-agent + nostr-adapter branch)
- [ ] P3.2 Write `hermes-docker/entrypoint.sh` (config generation from env vars + hermes gateway start)
- [ ] P3.3 Write `hermes-docker/skills/` (pre-loaded skills: quality-gates, kanban-worker-management, etc.)
- [ ] P3.4 Write `hermes-docker/SOUL.md.template` (adapted per friend)
- [ ] P3.5 Build and test image locally: `docker build -t hermes-tenant .`
- [ ] P3.6 Test: container starts, Hermes gateway runs, config correct

### Phase 4: routstrd production Dockerfile
- [ ] P4.1 Write `routstrd-docker/Dockerfile` (CMD ["routstrd", "start"])
- [ ] P4.2 Volume mount for wallet data (`/data`)
- [ ] P4.3 Config: `ROUTSTRD_RELAY=ws://strfry:7777`, `COCOD_DIR=/data/.cocod`
- [ ] P4.4 Build and test: routstrd discovers our Routstr node, can route a test request

### Phase 5: hermes_tenants Ansible role
- [ ] P5.1 Create `ansible/roles/hermes_tenants/` with tasks, templates, defaults
- [ ] P5.2 Task: build Hermes Docker image on VPS
- [ ] P5.3 Task: build routstrd Docker image on VPS
- [ ] P5.4 Task: for each friend — generate nsec, write config, create Docker volume
- [ ] P5.5 Task: for each friend — publish kind 9000 (put-user) to add bot to obelisk group
- [ ] P5.6 Task: for each friend — start Hermes + routstrd containers with resource limits
- [ ] P5.7 Task: verify all containers running (`docker ps`)
- [ ] P5.8 Task: print connection info (Buzz relay URL, friend npubs, bot npubs)

### Phase 6: Master playbook
- [ ] P6.1 Write `ansible/playbooks/50-multi-tenant-hermes.yml`
- [ ] P6.2 Write `Makefile` target: `deploy-multi-tenant`
- [ ] P6.3 Test: dry-run (`--check`) passes
- [ ] P6.4 Test: full deploy on VPS (acceptance criteria AC1-AC10)

### Phase 7: Onboarding documentation
- [ ] P7.1 Write `docs/onboarding-friends.md` (Buzz setup, first message, kanban, workers)
- [ ] P7.2 Write `docs/friend-hermes-guide.md` (quality gates, SOUL.md, skills, cron)
- [ ] P7.3 Write `docs/admin-guide.md` (Felix's perspective: issue credits, monitor, debug)

### Phase 8: Integration tests
- [ ] P8.1 Write `tests/test_multi_tenant.py` (deploy, verify containers, E2E chat)
- [ ] P8.2 Write `tests/test_hermes_nostr_e2e.py` (Buzz → relay → Hermes → response)
- [ ] P8.3 Write `tests/test_routstr_routing.py` (Hermes → routstrd → Routstr → z.ai → response)
- [ ] P8.4 Run full test suite, verify all pass

---

## 5. Trade-offs

### obelisk-relay vs Block Buzz
- **obelisk**: Light (100MB), simple (1 container), already in prod. Missing: FTS, presence, NIP-34.
- **Block Buzz**: Heavy (1GB), 4+ containers (PG, Redis, S3). Has everything.
- **Decision**: obelisk. Migration path clear if needed.

### Local mint vs testserver2 mint
- **Local**: Self-contained, no network dependency. +100MB RAM.
- **testserver2**: Reuse existing infra. Network dependency (if testserver2 down, credits fail).
- **Decision**: OPEN (O5) — needs operator input.

### Branch vs merge for nostr-adapter
- **Branch**: Fast, no upstream work. Fragile (branch could be deleted).
- **Merge**: Clean, stable. Requires PR/merge effort.
- **Decision**: OPEN (O3) — needs operator input.

### Flat vs per-token pricing
- **Flat**: Simple. No enforcement. Friends could abuse.
- **Per-token**: Enforced. Needs mint + wallet setup. More complex.
- **Decision**: OPEN (O6) — needs operator input.

---

## 6. Test Strategy

| Layer | Test | Tool |
|-------|------|------|
| Unit | Ansible role syntax, template rendering | `ansible-lint`, `molecule` |
| Integration | Multi-container deploy on VPS | `pytest` + SSH |
| E2E | Buzz → relay → Hermes → response | Playwright (Buzz web) or `nak` |
| E2E | Hermes → routstrd → Routstr → z.ai | `curl` test request |
| E2E | Cashu quote → approve → mint → spend | `tollgate-mint-approve` CLI |
| Resource | Container mem/cpu limits enforced | `docker stats` |
| Security | Containers isolated (no cross-access) | Docker network inspection |

---

## 7. Kanban Task Breakdown (for worker dispatch)

| Task ID | Phase | Title | Worker | Model | Est. |
|---------|-------|-------|--------|-------|------|
| MT-01 | 3 | Build hermes-docker Dockerfile + entrypoint | worker-admin | kimi-k2.7-code | 30m |
| MT-02 | 3 | Pre-load skills into Docker image | worker-admin | kimi-k2.7-code | 20m |
| MT-03 | 3 | SOUL.md template for friends | worker-admin | glm-5.2 | 15m |
| MT-04 | 4 | Build routstrd production Dockerfile | worker-admin | kimi-k2.7-code | 30m |
| MT-05 | 5 | Create hermes_tenants Ansible role | worker-admin | kimi-k2.7-code | 45m |
| MT-06 | 5 | NIP-29 group creation automation (kind 9000) | worker-admin | kimi-k2.7-code | 20m |
| MT-07 | 6 | Write master playbook 50-multi-tenant-hermes.yml | worker-admin | kimi-k2.7-code | 15m |
| MT-08 | 7 | Write onboarding-friends.md | worker-admin | glm-5.2 | 30m |
| MT-09 | 7 | Write friend-hermes-guide.md | worker-admin | glm-5.2 | 30m |
| MT-10 | 7 | Write admin-guide.md | worker-admin | glm-5.2 | 20m |
| MT-11 | 8 | Integration test: test_multi_tenant.py | worker-admin | kimi-k2.7-code | 45m |
| MT-12 | 8 | E2E test: test_hermes_nostr_e2e.py | worker-admin | kimi-k2.7-code | 30m |
| MT-13 | 8 | E2E test: test_routstr_routing.py | worker-admin | kimi-k2.7-code | 20m |

**Dependencies:**
- MT-02 depends on MT-01 (need Dockerfile before pre-loading)
- MT-05 depends on MT-01 + MT-04 (need both Docker images before role)
- MT-06 depends on MT-05 (group creation is part of role)
- MT-07 depends on MT-05 (playbook references role)
- MT-11 depends on MT-07 (test the playbook)
- MT-12 depends on MT-07 + VPS live (E2E needs running system)
- MT-13 depends on MT-07 + VPS live

**Parallelizable:**
- MT-01 + MT-04 (independent Dockerfiles — build in parallel)
- MT-08 + MT-09 + MT-10 (independent docs — write in parallel)
- MT-11 + MT-12 + MT-13 (independent tests — run in parallel after deploy)

---

## 8. Open Questions (for operator)

1. **BASE_DOMAIN**: Which domain for this VPS? (O1)
2. **VPS boot**: Is 64.188.7.38 actually booting? (O2)
3. **nostr-adapter**: Merge to main first, or pin to branch? (O3)
4. **Worker limits**: Hard cap per friend, or Docker limits only? (O4)
5. **Cashu mint**: Local on this VPS, or reuse testserver2? (O5)
6. **Cost model**: Flat monthly or per-token SATs? (O6)

---

## 9. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| VPS won't boot | MEDIUM | HIGH | Have backup plan (use testserver2 or new VPS) |
| nostr-adapter branch deleted | LOW | HIGH | Fork the branch, or merge to main |
| 8GB RAM insufficient for 3 friends | MEDIUM | MEDIUM | Monitor `docker stats`, upgrade VPS if needed |
| Friends overwhelm Routstr with requests | LOW | MEDIUM | Per-container rate limits in Routstr config |
| obelisk-relay can't handle 3 groups + bots | LOW | LOW | 3 groups is trivial for obelisk |
| routstrd Docker not production-ready | MEDIUM | MEDIUM | Test thoroughly before deploy, fallback to direct z.ai config |
| Friends need support/onboarding | HIGH | LOW | Comprehensive docs (Phase 7) + Felix as admin |
| z.ai quota exhaustion affects all friends | HIGH | HIGH | Per-friend token limits via Cashu, Ollama fallback |

---

## Kimi K3 Adversarial Review (2026-08-12)

[PENDING — run `kimi-plan-review.sh ROADMAP.md` after operator reviews]