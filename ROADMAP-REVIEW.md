# ROADMAP Review — Consultant Findings

**Date:** 2026-08-12
**Reviewer:** Manager (post-grill, subagent timeout fallback)
**Plan reviewed:** ROADMAP.md (multi-tenant Hermes hosting v2)

---

## Issues Found

### CRITICAL

**C1. Hermes Docker image — `pip install hermes-agent` may not work**
The plan assumes `pip install hermes-agent` produces a working Hermes. Need to verify:
- Is `hermes-agent` on PyPI? Or is it source-only from GitHub?
- Does the nostr-adapter branch need to be installed from source?
- The Dockerfile should `git clone` the repo + checkout `nostr-adapter` branch + `pip install -e .`
- Without this, the Docker image is a shell with nothing in it

**C2. Nostr adapter not merged — Docker build is fragile**
Branch `nostr-adapter` on `felixfelix-bot/hermes-agent`. If the branch is deleted or force-pushed, all Docker builds break. Options:
- Fork the branch to a stable tag
- Merge to main on the fork
- Pin to a specific commit hash in Dockerfile
RECOMMENDATION: Pin to commit `a480d7fbef` in Dockerfile. Stable, reproducible.

**C3. VPS offline — plan can't proceed without a target**
64.188.7.38 is completely unreachable. No fallback plan in ROADMAP. Need:
- Alternative: deploy on testserver2 (23.182.128.51) — already busy, but could add services
- Alternative: new VPS from same or different provider
- Alternative: wait for boot
RECOMMENDATION: Add Phase 0.5 — "VPS readiness check" with 3 fallback options.

### HIGH

**H1. Resource estimate too optimistic for 3 active friends**
ROADMAP estimates 6.6GB for 3 friends + infra. But:
- Hermes idle ~500MB, but ACTIVE (running workers, building) can spike to 2GB EACH
- 3 friends × 2GB = 6GB just for Hermes
- + infra (Caddy, strfry, obelisk, routstr, mint) = ~1.5GB
- Total peak: ~7.5GB
- 8GB VPS has only ~7.5GB usable (kernel + system overhead ~500MB)
- This is ZERO headroom. One friend running a build will OOM the VPS.
RECOMMENDATION: Either upgrade to 16GB VPS, or limit to 2 friends initially, or enforce strict 1.5GB mem_limit per container (throttles workers but prevents OOM).

**H2. z.ai quota exhaustion — all 3 friends share one Routstr node**
When z.ai quota exhausts (currently BOTH keys are 429), ALL 3 friends lose LLM access simultaneously. The plan doesn't address:
- Per-friend quota limits (one friend could exhaust quota for everyone)
- Fallback to Ollama Cloud (works, but slow + rate-limited)
- Per-friend cost tracking (who used how much)
RECOMMENDATION: Add per-friend API key in Routstr config. Each friend gets their own API key. Routstr tracks usage per key. Cashu payment gating enforces per-friend limits.

**H3. routstrd Docker image doesn't exist yet**
The plan says "build routstrd production Dockerfile" but the current routstrd repo has a dev-oriented Dockerfile. Need to:
- Write production Dockerfile from scratch
- Test wallet persistence across container restarts
- Test Nostr discovery (does routstrd find our Routstr node via strfry?)
- Verify cocod daemon works in Docker (Unix socket in /data)
RECOMMENDATION: Add a spike task — "routstrd Docker spike: verify wallet + discovery + Hermes integration in Docker" before committing to the architecture.

**H4. Hermes config inside container — missing critical pieces**
The entrypoint.sh in the plan generates a minimal config.yaml. Missing:
- `model` — needs to be set to a model available via routstrd
- `max_tokens` — default may be too high for shared VPS
- `timeout` — workers need longer timeouts in containers
- `profile` — needs to be set per friend
- Nostr adapter config — env vars are set but config.yaml also needs `platforms.nostr` section
- Skills path — skills are in Docker image but config needs to point to them
- Kanban DB path — needs to be in the volume, not ephemeral
RECOMMENDATION: Expand entrypoint.sh to generate FULL config.yaml with all sections.

### MEDIUM

**M1. No backup strategy for friend data**
Each friend's Docker volume has their kanban DB, session DB, nsec, memory. If VPS dies, all data lost.
RECOMMENDATION: Add Phase 1.6 — Syncthing or daily backup of Docker volumes to testserver2 or local.

**M2. No log management**
3 Hermes containers + routstrd + routstr + obelisk = lots of logs. No log rotation configured.
RECOMMENDATION: Docker logging driver → `json-file` with max-size 10m, max-file 3. Add to docker-compose template.

**M3. No monitoring/alerting for friends' containers**
If a friend's Hermes crashes, nobody knows. The watchdog role monitors system services, not Docker containers.
RECOMMENDATION: Add `docker-compose healthcheck` to each Hermes container. Watchdog checks `docker inspect --format '{{.State.Health.Status}}'`.

**M4. Onboarding docs don't cover Buzz client installation**
The plan says "friend installs Buzz" but doesn't specify HOW. Buzz is a Rust CLI (cargo install) or web client?
RECOMMENDATION: Add Buzz installation instructions to onboarding doc. Include both web client URL and CLI install.

**M5. Nostr group creation — kind 9000 needs admin nsec**
The plan says "publish kind 9000 (put-user)" but doesn't specify who signs it. The admin (Felix) nsec must be available to the Ansible task. This means Felix's nsec is on the VPS — security risk.
RECOMMENDATION: Generate a per-deployment admin nsec (not Felix's personal nsec). Use that for group management. Felix's personal nsec never touches the VPS.

**M6. NIP-05 identity for friends**
Friends may want NIP-05 verification (name@domain). Not in the plan.
RECOMMENDATION: Add optional Phase 2.5 — NIP-05 via Caddy static file or simple Nostr delegation service.

### LOW

**L1. Playbook numbering — 50 may conflict**
Existing playbooks go up to 40. The plan uses 50. But there might be future playbooks 41-49.
RECOMMENDATION: Use 45 instead of 50 to leave room.

**L2. No .env.example for new vars**
The plan adds friend npubs/nsecs as env vars but no .env.example template.
RECOMMENDATION: Add `.env.example` with FRIEND1_NPUB, FRIEND1_NSEC, etc.

**L3. No CI test for the playbook**
The infrastructure kit has AGENTS.md requiring tests. The new playbook should have a molecule test.
RECOMMENDATION: Add `tests/test_multi_tenant_hermes.yml` molecule scenario.

---

## Recommended Changes to ROADMAP.md

1. **Add Phase 0.5: VPS readiness check** — verify SSH, set hostname, check resources
2. **Add spike task MT-00: routstrd Docker spike** — verify before committing to architecture
3. **Change resource estimate** — 8GB is tight, recommend 16GB or limit to 2 friends
4. **Add per-friend API keys** in Routstr config for quota isolation
5. **Expand entrypoint.sh** — full config.yaml generation with all sections
6. **Pin nostr-adapter to commit hash** `a480d7fbef` in Dockerfile
7. **Use Dockerfile `git clone` not `pip install hermes-agent`** — source install from fork
8. **Add log management** to docker-compose template
9. **Add healthchecks** to Hermes containers
10. **Add backup strategy** — daily Docker volume backup
11. **Use deployment admin nsec** — not Felix's personal nsec
12. **Add Buzz installation instructions** to onboarding docs
13. **Add .env.example** template
14. **Add molecule test** for the new role
15. **Change playbook number** from 50 to 45

---

## Additional Tasks Needed

| ID | Title | Phase | Est |
|----|-------|-------|-----|
| MT-00 | routstrd Docker spike (wallet + discovery + Hermes) | 0 | 30m |
| MT-00b | VPS readiness check script | 0 | 10m |
| MT-04b | routstrd wallet persistence test | 4 | 20m |
| MT-05b | Per-friend API key config in Routstr | 5 | 15m |
| MT-05c | Deployment admin nsec generation (not Felix's) | 5 | 10m |
| MT-06b | Docker log management config | 5 | 10m |
| MT-06c | Container healthcheck config | 5 | 10m |
| MT-09b | .env.example template | 7 | 5m |
| MT-11b | Molecule test for hermes_tenants role | 8 | 30m |
| MT-11c | Backup strategy + daily volume backup task | 8 | 20m |

Total new tasks: 10 additional (23 total, up from 13)

---

## Security Assessment

| Risk | Severity | Mitigation |
|------|----------|-----------|
| Felix's personal nsec on VPS | HIGH | Use deployment admin nsec instead |
| Friend containers accessing host Docker socket | MEDIUM | Don't mount Docker socket in containers |
| Shared Docker network = friend-to-friend access | MEDIUM | Use per-friend Docker networks, only gateway to shared services |
| routstrd wallet keys in Docker volume | MEDIUM | Encrypt volume, or accept risk (tokens are low-value credits) |
| z.ai API keys in Routstr config on VPS | HIGH | Use Docker secrets or .env file, not in image |
| obelisk-relay open to internet | LOW | Caddy + NIP-42 AUTH + admin whitelist |

---

## Updated Resource Estimates

| Component | Idle RAM | Active RAM | Disk |
|-----------|----------|------------|------|
| Caddy | 50 MB | 80 MB | 100 MB |
| strfry | 100 MB | 150 MB | 1 GB |
| obelisk-relay | 100 MB | 150 MB | 500 MB |
| Routstr node | 200 MB | 300 MB | 500 MB |
| Cashu mint | 100 MB | 150 MB | 500 MB |
| Mint orchestrator | 50 MB | 80 MB | 100 MB |
| Hermes #1 | 500 MB | 1.5-2 GB | 5 GB |
| Hermes #2 | 500 MB | 1.5-2 GB | 5 GB |
| Hermes #3 | 500 MB | 1.5-2 GB | 5 GB |
| routstrd ×3 | 150 MB | 300 MB | 500 MB |
| System overhead | 500 MB | 500 MB | 2 GB |
| **Total (idle)** | **~2.2 GB** | | **~21 GB** |
| **Total (active)** | | **~7.5-9.5 GB** | |

**Recommendation:** 16GB VPS for 3 friends. 8GB works for 2 friends with strict limits.

---

## Conclusion

The ROADMAP is architecturally sound. The main risks are:
1. VPS availability (C3) — needs immediate resolution
2. Hermes Docker image correctness (C1) — needs source install, not pip
3. Resource pressure (H1) — 8GB is tight for 3 active friends
4. Quota isolation (H2) — per-friend API keys needed

With the 10 additional tasks and the recommended changes, the plan is ready for operator approval after the 6 open questions are answered.