# VPS Infrastructure: Default vs Opt-In Service Audit

> Date: 2026-07-04
> VPS: orangeclaw.dns4sats.xyz (VPS1, primary)
> Goal: Slim down to essential Nostr infrastructure. Reduce disk/CPU/RAM usage.

## Current State — 30 Roles Deployed on VPS1

The setup-vps-1.yml playbook deploys EVERYTHING on a single VPS. That's
~30 Docker containers competing for resources on one machine.

## Service Classification

### TIER 1 — CORE (keep running, must be reliable)

These are the Nostr infrastructure services that must stay up.

| # | Service | Role | Why Essential | Disk Impact |
|---|---------|------|---------------|-------------|
| 05 | strfry | strfry | Primary Nostr relay | MEDIUM (LMDB grows) |
| 37 | strfry-agg | strfry_agg | Aggregated relay (WoT-filtered) | HIGH (LMDB grows) |
| 06 | obelisk | obelisk_relay | Second relay implementation | LOW |
| 07 | blossom | blossom | Nostr file storage (Blossom protocol) | VERY HIGH (~1G/day) |
| 08 | nsite-gateway | nsite_gateway | Nostr website hosting | MEDIUM |
| 14 | nsyte | nsyte_cli | Nostr site deployment CLI | MINIMAL |
| 19 | ngit-relay | ngit_relay | Nostr git relay (strfry instance) | MEDIUM |
| 04 | caddy | caddy | Reverse proxy / TLS termination | MINIMAL |

**Supporting infrastructure (required for Tier 1):**
| # | Service | Role | Why Essential |
|---|---------|------|---------------|
| 00 | zram | zram | Memory compression (helps everything) |
| 01 | system | system | Base OS config, packages, log rotation |
| 02 | docker | docker | Container runtime |
| 03 | cloudflare-dns | cloudflare_dns | DNS records for services |

**Tier 1 total: 11 roles** (8 services + 3 infra)

### TIER 2 — USEFUL BUT NOT CRITICAL (opt-in)

| # | Service | Role | What It Does | Verdict |
|---|---------|------|--------------|---------|
| 15 | grasp | grasp | Nostr git mirror | Useful but redundant with ngit |
| 30 | grasp-mirror | grasp_mirror | Auto-mirrors repos | High disk usage |
| 36 | grasp-snapshot | grasp_snapshot | Periodic snapshots | Disk consumer |
| 09 | release-explorer | release_explorer | GitHub release browser | Nice-to-have |
| 40 | wot-sync | wot_sync | Web of trust sync | Useful for strfry-agg |
| 20 | watchdog | watchdog | Health monitor | Already local |
| 22 | backup | backup | Docker volume backups | IMPORTANT but heavy |
| 23 | relay-adv | relay_advertisement | Publish relay list events | Minimal impact |
| 24 | gitworkshop | gitworkshop | Git workshop tool | Low priority |

### TIER 3 — NOT NEEDED ON THIS VPS (opt-in, deploy elsewhere)

| # | Service | Role | What It Does | Verdict |
|---|---------|------|--------------|---------|
| 10 | hive-ci | hive_ci | CI/CD runner | Deploy on dedicated CI box |
| 11 | mint-orch | mint_orchestrator | Cashu mint orchestration | Heavy, move to own VPS |
| 16 | cashu-brrr | cashu_brrr | Cashu mint | Multiple mint containers! |
| 17 | mint-op-proxy | mint_operator_proxy | Mint management proxy | Goes with mints |
| 10-17 | (test mints) | deploy-test-mints | 5 test mint containers | HUGE waste of resources |
| 12 | mptcp | mptcp_server | Multipath TCP | Network optimization |
| 13 | fips | fips | FIPS mesh node | Separate from Nostr infra |
| 18 | routstr | routstr | HTTP proxy service | Separate service |
| 17 | auditable-voting | auditable_voting | Voting system | Separate project |
| 21 | syncthing | syncthing | File sync | Heavy disk I/O |
| 27 | act-runner | act_runner | GitHub Actions runner | CI, separate concern |
| 28 | voting-worker | voting_worker | Voting computation | Separate project |
| 31 | micro-vpn | micro_vpn | VPN server | Network, separate |
| 32 | relatr | relatr | WoT relay aggregator | Move to VPS2 |
| 33 | jitsi | jitsi_meet | Video conferencing | VERY HEAVY (JVB+Jicofo+Prosody+Web) |
| 34 | bitcoin-core | bitcoin_core | Full Bitcoin node | 500GB+ disk! Separate machine |
| 35 | bitcoin-knots | bitcoin_knots | Bitcoin Knots node | Same — 500GB+ |
| 39 | plebeian-agg | plebeian_market_agg | Market aggregator | Separate project |

## Recommended New Playbook: setup-nostr-core.yml

A minimal playbook that deploys ONLY Tier 1 services:

```yaml
---
- name: Deploy Nostr core infrastructure (minimal)
  hosts: vps1
  become: yes
  gather_facts: yes
  ignore_unreachable: true
  roles:
    # Base infrastructure
    - zram
    - system
    - docker
    - cloudflare_dns
    - caddy
    # Core Nostr services
    - strfry
    - strfry_agg
    - obelisk_relay
    - blossom
    - nsite_gateway
    - ngit_relay
    - nsyte_cli
  vars:
    blossom_mirror_enabled: false
    blossom_upload_max_size: 10485760  # 10MB
    strfry_agg_mapsize: "10G"
    docker_log_max_size: "50m"
    docker_log_max_file: "3"

- name: Deploy watchdog (health monitor + auto-redeploy)
  hosts: localhost
  connection: local
  become: no
  roles:
    - watchdog
```

## Disk Impact Estimate

| Category | Current | After Slimming | Saved |
|----------|---------|----------------|-------|
| Docker images | ~36 GB (22+ containers) | ~12 GB (8 containers) | ~24 GB |
| Docker volumes | ~30 GB | ~15 GB | ~15 GB |
| Bitcoin blockchain | 0 (if not deployed) | 0 | 0 |
| Jitsi containers | ~2 GB | 0 | ~2 GB |
| Test mints (5x) | ~3 GB | 0 | ~3 GB |
| Syncthing data | ~5 GB | 0 | ~5 GB |
| Grasp mirrors | ~3 GB | 0 | ~3 GB |
| **Total estimated savings** | | | **~52 GB** |

## Implementation

1. Create `setup-nostr-core.yml` playbook (Tier 1 only)
2. Create `teardown-non-core.yml` playbook to stop+remove Tier 3 containers
3. Add `--tags` support to individual roles for granular deploys
4. Document in Makefile: `make deploy-core` vs `make deploy-full`
