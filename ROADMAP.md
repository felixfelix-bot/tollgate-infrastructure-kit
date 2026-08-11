# ROADMAP — Multi-Tenant Hermes Hosting

**Plan file:** `PLAN-multi-tenant-comprehensive.md`
**Date:** 2026-08-08
**Status:** GRILLED — awaiting operator approval

---

## 1. Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Use official Hermes Dockerfile (not custom) | Hermes ships with production Dockerfile + docker-compose.yml using s6-overlay supervision, uv, node22, Debian 13. No need to build custom image. |
| 2 | Use obelisk-relay (not Block Buzz relay) | 1 vCPU/1GB RAM vs Block's PostgreSQL+Redis+S3. Already in Ansible kit. NIP-29 compatible. Buzz client works. |
| 3 | Mount host Docker socket | Worker profiles need Docker. DinD is heavy. Socket mount = shared daemon, acceptable for 3 trusted friends. |
| 4 | V1: no Cashu gating, V2: add it | Simplifies V1 (no routstrd/cocod per container). Track usage per friend via proxy logs. Add Cashu when basics work. |
| 5 | Use Hermes native Nostr adapter | Already built at `gateway/platforms/nostr.py`. No Signal/Matrix needed. coincurve for Schnorr. |
| 6 | Network egress isolation | Hermes has docs for Docker network segmentation. Use internal network for Hermes containers, egress only to Routstr + obelisk. |

---

## 2. Adversarial Review Findings

### BLOCKERS (must fix before building)

**B1: Hermes Dockerfile uses `network_mode: host` — conflicts with multi-tenant isolation**
The shipped docker-compose.yml uses `network_mode: host` for all services. Multi-tenant requires isolated Docker networks. We need a custom docker-compose override that replaces `network_mode: host` with explicit network assignments. Each friend gets their own Docker network (or shared hermes-net with no host networking).
**Fix:** Write `docker-compose.override.yml` per friend that replaces `network_mode: host` with `networks: [hermes-net]`.

**B2: obelisk-relay vs Buzz client compatibility — UNVERIFIED**
Buzz's NOSTR.md says "Buzz is a Nostr relay that speaks NIP-29 natively." It lists features like kind:9007 group creation, kind:9000 add user. obelisk-relay is FORKED from verse-pbc/groups_relay, not from Block/buzz. The NIP-29 spec is the same, but Buzz client may have Buzz-relay-specific expectations (e.g., the `/info`, `/media/*`, `/git/*` HTTP endpoints described in Buzz's architecture). obelisk-relay may not implement these.
**Fix:** Test Buzz client → obelisk-relay connection BEFORE committing to it. If Buzz requires its own relay, we need to either (a) run the full Block Buzz stack or (b) use a different NIP-29 client that works with obelisk. Task 3 must include this verification as a gate.

**B3: Hermes Nostr adapter connects to strfry29, not obelisk-relay**
The adapter docstring says "Connects to strfry relays running the strfry29 plugin." obelisk-relay is a different implementation (forked from groups_relay, not strfry+strfry29). The wire protocol (NIP-29) should be the same, but the adapter may have strfry-specific assumptions (e.g., subscription filters, event acceptance rules, AUTH challenge format).
**Fix:** Test Hermes Nostr adapter → obelisk-relay connection. May need adapter patches if strfry-specific behavior is assumed. This is a SPIKE task before committing to the architecture.

### WARNINGS (should fix, won't block)

**W1: Memory budget — Hermes containers are heavier than estimated**
The official Hermes Dockerfile includes s6-overlay, Python 3.13, Node 22, Playwright browsers, ripgrep, ffmpeg, git, docker-cli. That's NOT a slim image. Each container will likely use 500-800MB baseline (before any worker activity). 3 containers = 1.5-2.4GB just for Hermes. Plus Routstr (200MB), obelisk (100MB), Cashu (200MB), orchestrator (100MB), Caddy (50MB), system (300MB) = 2.8-3.4GB total.
**Action:** VPS needs 4GB RAM minimum. If only 2GB available, limit to 1-2 friends or build a slim Hermes image (strip Playwright, Node, ffmpeg — keep only Python + git + docker-cli).

**W2: Hermes Docker image includes docker-cli but not Docker daemon**
The Dockerfile installs `docker-cli` (for worker profiles), but the daemon runs on the host. Mounting `/var/run/docker.sock` into the container lets workers use Docker, but means any friend can run arbitrary Docker commands on the host — including seeing other friends' containers, accessing their volumes, or stopping their services.
**Action:** For V1 with trusted friends, this is acceptable. For V2, consider Docker socket proxy (tecnativa/docker-socket-proxy) that restricts which Docker API calls are allowed.

**W3: Nostr adapter self-echo skip means bot can't see its own messages**
The adapter skips events it signed. This is correct for normal operation, but means if the bot sends a message and the user replies to that specific event (NIP-25 reaction), the bot won't see the reaction context. Minor UX issue, not a blocker.

**W4: obelisk-relay uses Cloudflare Tunnel (not Caddy) in its setup.sh**
obelisk-relay's setup.sh exposes via Cloudflare Tunnel, not via Caddy reverse proxy. Our Ansible kit deploys it behind Caddy. Need to verify Caddy WebSocket upgrade config works with obelisk. The existing Ansible role should handle this, but hasn't been tested with obelisk specifically (it was tested with the original strfry relay).

**W5: Cashu mint GRPC port exposure**
The CDK mintd GRPC endpoint (port 50055) should NOT be exposed publicly. It allows marking invoices as paid. Currently the plan doesn't explicitly firewall this. Caddy only proxies HTTP, not GRPC. The mint-orchestrator connects via localhost.
**Action:** Ensure GRPC port 50055 is bound to 127.0.0.1 only, not 0.0.0.0. Add to Ansible task.

### SUGGESTIONS (nice to have)

**S1: Use Hermes official Docker image as base, add override compose**
Instead of building a custom image, use `hermes-agent` image as-is. Create per-friend docker-compose.override.yml files that set env vars, mount volumes, assign networks. This is the Docker-native way to customize without maintaining a fork.

**S2: Profile-based config**
Hermes supports profiles (`hermes profile create friend-1`). Instead of separate containers, could run multiple profiles in one Hermes instance. But this breaks isolation (friends share one process). Stick with containers for V1.

**S3: Nostr relay redundancy**
If obelisk-relay goes down, all friends lose bot access. Consider running a second obelisk-relay on T470 as backup. Low priority for V1.

**S4: Usage tracking per friend**
Even without Cashu gating, track per-friend usage. The Routstr proxy already logs to zai_usage.db. Add a friend identifier to the proxy logs (e.g., via API key or header) so Felix can see who's using what.

**S5: Update strategy**
How do we update Hermes in all containers? `docker pull hermes-agent && docker compose up -d` per friend. Add to operator guide.

---

## 3. Revised Task Breakdown

Based on the grill, 3 changes to the plan:

### NEW Task 0: Compatibility Spike (BLOCKER — must pass before Phase 1)
**Profile:** worker-inspector
**Duration:** 2 hours
**Scope:**
1. Build Hermes Docker image locally from `~/.hermes/hermes-agent/Dockerfile`
2. Run container with Nostr adapter pointing at a local obelisk-relay
3. Connect Buzz client to obelisk-relay
4. Send a message → verify Hermes receives it and responds
5. If Buzz client doesn't work with obelisk → test with nostrord or other NIP-29 client
6. If nothing works with obelisk → test with Block Buzz relay (needs PostgreSQL+Redis)
7. Report which relay+client combination actually works

**GATE:** This task MUST pass before any other work begins. If it fails, the architecture changes.

### Task 7 REVISED: Use official Hermes Docker image + override compose
Instead of building custom Dockerfile, use official `hermes-agent` image. Write per-friend `docker-compose.override.yml` files that:
- Replace `network_mode: host` with `networks: [hermes-net]`
- Set env vars (NOSTR_RELAYS, NOSTR_GROUPS, NOSTR_NSEC_PATH, LLM proxy URL)
- Mount Docker socket
- Set resource limits
- Mount per-friend persistent volume

### Task 5 REVISED: Bind GRPC to localhost only
Add explicit `bind: 127.0.0.1` for CDK mintd GRPC port 50055 in the Ansible role. Not exposed via Caddy.

---

## 4. Acceptance Criteria

- [ ] Task 0 spike passes: Buzz client → obelisk-relay → Hermes Nostr adapter → response
- [ ] VPS booted, base Ansible deployed
- [ ] All subdomains resolve in DNS, HTTPS certificates provisioned
- [ ] obelisk-relay running, Felix can connect as admin via Buzz
- [ ] Routstr running, `/v1/chat/completions` returns responses
- [ ] 3 Hermes containers running, each connected to obelisk-relay
- [ ] Each friend can: connect Buzz → authenticate → join group → send message → get response
- [ ] Each friend can: create kanban board → create task → dispatch worker → task completes
- [ ] Docker socket mount works (workers can run Docker commands)
- [ ] Resource limits enforced (no container exceeds limit)
- [ ] GRPC port 50055 NOT accessible from internet
- [ ] Felix can issue Cashu credits via Nostr approval event (if V2 Cashu enabled)

---

## 5. Open Questions (unchanged from plan)

1. Domain: sovereignengineering.io?
2. VPS RAM: how much? (Need 4GB for 3 friends, 2GB for 1-2)
3. Friends have Nostr identities already?
4. V1 (no Cashu gating) or V2 (full Cashu)?
5. Credit amount per friend per month?
6. OK to mount host Docker socket?

---

## 6. Kimi K3 Adversarial Review

[DEFERRED — kimi-k3:cloud unavailable (503, Ollama Cloud down). Proceeding with own adversarial analysis only. Retry when quota resets.]