# Relatr Web of Trust — GRASP Spam Filtering + Routstr Vision

## Overview

Three deliverables:
1. **Cherry-pick Routstr Vision role** from PR #5a4aab8a (clean, no unrelated changes)
2. **Deploy Relatr (ContextVM)** — WoT trust score service for GRASP spam filtering
3. **GRASP spam analysis & cleanup** — audit existing content, remove bloat

---

## Deliverable 1: Cherry-pick Routstr Vision (Clean)

### Files to apply
- [ ] `.env.example` — add ROUTSTR_VISION_* block
- [ ] `ansible/playbooks/19-routstr-vision.yml` — new playbook
- [ ] `ansible/roles/routstr_vision/` — entire new role (defaults, handlers, tasks, templates)
- [ ] `ansible/inventory/group_vars/all.yml` — routstr_vision vars + cloudflare subdomain
- [ ] `ansible/roles/caddy/templates/Caddyfile.http.j2` — routstr-vision Caddy routes

### Files to revert after cherry-pick
- [ ] `ansible/roles/auditable_voting/tasks/main.yml` — sha256 keygen is wrong for Nostr
- [ ] `ansible/roles/voting_worker/tasks/main.yml` — same sha256 issue
- [ ] `ansible/roles/grasp_mirror/templates/config.toml.j2` — unrelated health_port removal
- [ ] `docs/voting-5-person-test.md` — unrelated deletion
- [ ] `static/services/index.html` — unrelated service removals
- [ ] Partial revert of `Caddyfile.http.j2` — restore grasp mirror health endpoint
- [ ] Partial revert of `all.yml` — restore `grasp_mirror_health_port` variable

---

## Deliverable 2: Relatr WoT Deployment

### Architecture
```
Internet → strfry (ngit relay :7778)
  → write-policy plugin queries Relatr (:3000)
    → trust score > 0.1 → accept event
    → trust score <= 0.1 → reject event

GRASP mirror sync → pre-filter discovered repos via Relatr
  → skip repos from untrusted npubs

Relatr (Docker, port 3000)
  → DuckDB database at /opt/tollgate/relatr/data/
  → Social graph from Nostr relays (2-hop)
  → Config UI at wot.{{ base_domain }}
```

### Key Configuration
| Variable | Value | Notes |
|----------|-------|-------|
| `relatr_port` | 3000 | Config UI + API |
| `DEFAULT_SOURCE_PUBKEY` | Owner npub (hex) | Root of WoT |
| `NUMBER_OF_HOPS` | 2 | Contacts-of-contacts |
| `NOSTR_RELAYS` | strfry + ngit + public | Social graph source |
| `CACHE_TTL_HOURS` | 72 | 3-day trust cache |
| `DECAY_FACTOR` | 0.1 | Distance matters more |
| `IS_PUBLIC_SERVER` | false | Private MCP server |
| Min trust score | 0.1 | Moderate threshold |

### New Files
- [ ] `ansible/roles/relatr/defaults/main.yml`
- [ ] `ansible/roles/relatr/tasks/main.yml`
- [ ] `ansible/roles/relatr/handlers/main.yml`
- [ ] `ansible/roles/relatr/templates/docker-compose.relatr.yml.j2`
- [ ] `ansible/playbooks/31-relatr.yml`
- [ ] `scripts/strfry-wot-policy.sh` — write-policy for ngit strfry
- [ ] `scripts/grasp-trust-filter.sh` — pre-sync filter for grasp-mirror

### Modified Files
- [ ] `.env.example` — RELATR_SERVER_SECRET_KEY, RELATR_SOURCE_NPUB_HEX
- [ ] `ansible/inventory/group_vars/all.yml` — relatr vars, wot subdomain
- [ ] `ansible/roles/caddy/templates/Caddyfile.http.j2` — wot route
- [ ] `ansible/roles/ngit_relay/tasks/main.yml` — strfry write-policy config
- [ ] `static/services/index.html` — add Relatr + Routstr Vision entries
- [ ] `ansible/playbooks/setup-all.yml` — add relatr playbook

---

## Deliverable 3: GRASP Spam Analysis & Cleanup

### Phase A — Audit
- [ ] `scripts/grasp-audit.py` — collect disk usage per repo/npub, output CSV report

### Phase B — Cleanup
- [ ] `scripts/grasp-cleanup.py` — flag/remove repos from untrusted npubs, --dry-run default

### Phase C — Integration
- [ ] Add cleanup task to grasp_mirror role or new role
- [ ] Optional systemd timer for weekly cleanup

---

## Execution Notes

- Using git worktree `feat/relatr-wot-vision` to avoid collisions
- Build Relatr from source (ContextVM/relatr Dockerfile + bun)
- Both strfry write-policy AND grasp-mirror filter (defense in depth)
- Public config UI at `wot.{{ base_domain }}`
