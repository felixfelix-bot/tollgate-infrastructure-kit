# Integrated Operations Guide — Hermes for Friends

> **Status:** Active
> **Created:** 2026-08-12
> **Owner:** Felix (c03rad0r)
> **Repo:** `tollgate-infrastructure-kit` (main branch)
> **Board:** `hermes-for-friends` (Kanban)
> **Related docs:** [FIPS Mesh Operations](FIPS-MESH-OPERATIONS.md), [FIPS Ingress Gate](FIPS-INGRESS-GATE.md), [Friend Onboarding Guide](onboarding-friend-guide.md), [Multi-Tenant Comprehensive Plan](../PLAN-multi-tenant-comprehensive.md), [Roadmap](../ROADMAP.md), [Services Overview](services.md)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Track A — FIPS Mesh Networking](#2-track-a--fips-mesh-networking)
3. [Track B — Multi-Tenant Hermes Hosting](#3-track-b--multi-tenant-hermes-hosting)
4. [Track C — FIPS + Docker Integration](#4-track-c--fips--docker-integration)
5. [Track D — ESP32 & Android Mesh Clients](#5-track-d--esp32--android-mesh-clients)
6. [Track E — Monitoring & Health](#6-track-e--monitoring--health)
7. [Daily Operations Runbook](#7-daily-operations-runbook)
8. [Troubleshooting Cross-Track](#8-troubleshooting-cross-track)
9. [Service Inventory](#9-service-inventory)
10. [Security Posture](#10-security-posture)
11. [Task Status Board](#11-task-status-board)

---

## 1. Overview

### 1.1 What This Is

This document is the single source of truth for operating the integrated
infrastructure that combines three major subsystems:

- **FIPS Mesh** — encrypted overlay network connecting Felix's devices
- **Multi-Tenant Hermes** — Docker-based AI agent hosting for 3 friends
- **FIPS-Docker Integration** — routing Hermes container traffic through FIPS

Plus two supporting tracks:

- **ESP32/Android** — hardware mesh clients for FIPS
- **Monitoring** — health checks, dashboards, cron jobs

### 1.2 Architecture Diagram

```
                         INTERNET
                            │
                    Cloudflare DNS
                            │
    ┌───────────────────────┴───────────────────────────┐
    │                 VPS2 (23.182.128.51)               │
    │                 orangesync.tech                    │
    │                                                    │
    │  Caddy (:80/:443, TLS via CF DNS-01)              │
    │    ├── relay.orangesync.tech    → obelisk :8080   │
    │    ├── routstr.orangesync.tech  → Routstr :8000    │
    │    ├── mints.orangesync.tech    → Cashu mint :8085 │
    │    ├── blossom.orangesync.tech → blossom :3001    │
    │    ├── nsite.orangesync.tech    → nsite-gw :3002   │
    │    ├── git.orangesync.tech      → ngit-grasp :7334│
    │    └── *.orangesync.tech       → Caddy 404        │
    │                                                    │
    │  Internal Docker network (hermes-net):             │
    │    ├── hermes-friend-1  (Hermes + Nostr adapter)   │
    │    ├── hermes-friend-2  (Hermes + Nostr adapter)   │
    │    ├── hermes-friend-3  (Hermes + Nostr adapter)   │
    │    ├── routstr          (LLM proxy + Kalman)       │
    │    ├── obelisk-relay    (NIP-29 group chat)        │
    │    ├── fips-sidecar     (NET_ADMIN, TUN access)    │
    │    └── mint-orchestrator (gRPC → CDK mintd)         │
    │                                                    │
    │  FIPS daemon (fips0 TUN, MTU 1280, IPv6 fd00::/8)  │
    │    UDP:2121  TCP:8443 — hub for private mesh       │
    └───────┬────────────────────────────────────────────┘
            │ fips0
    ┌───────┴────────┐  ┌────────────────┐  ┌────────────────┐
    │ DQ05 (laptop)  │  │ T14Gen5 (laptop)│  │ T470 (backup)  │
    │ wlp58s0 WiFi   │  │ wlp0s20f3 WiFi │  │ wlp58s0 WiFi   │
    │ FIPS 0.4.1     │  │ FIPS 0.4.1     │  │ FIPS 0.4.1    │
    └────────────────┘  └────────────────┘  └────────────────┘
            │
    ┌───────┴────────┐  ┌────────────────┐
    │ ESP32-C3 x2    │  │ Android (fips  │
    │ ESP-NOW mesh   │  │   APK)         │
    │ Path B hybrid  │  │               │
    └────────────────┘  └────────────────┘
```

### 1.3 Kanban Board

All tasks are tracked on the `hermes-for-friends` Kanban board at:
`~/.hermes/kanban/boards/hermes-for-friends/kanban.db`

Task IDs are prefixed by track letter (A, B, C, D, E).

---

## 2. Track A — FIPS Mesh Networking

### 2.1 Summary

Deploy a private FIPS mesh connecting Felix's 4 machines via an encrypted
overlay network. VPS2 serves as the hub (public IP), all laptops are spokes.

### 2.2 Fleet Inventory

| Machine   | Role     | Interface   | Reachable via          | npub                                                              | FIPS ver | Status |
|-----------|----------|-------------|------------------------|-------------------------------------------------------------------|----------|--------|
| VPS2      | Hub      | eth0        | 23.182.128.51 (public) | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82` | 0.4.1   | Active |
| DQ05      | Spoke    | wlp58s0     | Netbird 100.90.22.201   | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72` | 0.4.1   | Pending |
| T14Gen5   | Spoke    | wlp0s20f3   | localhost (local)      | `npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh` | 0.4.1   | Pending |
| T470      | Spoke    | wlp58s0     | Netbird 100.90.101.9    | TBD (discover after install)                                      | 0.4.1   | Pending |
| Andre     | External | —           | 194.191.252.108:2121   | `npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n` | 0.4.1   | Removed from mesh |

> VPS1 (66.92.204.38) is offline since Jul 20 — excluded from the mesh.

### 2.3 Why Private Mesh

The public FIPS test mesh has saturated bloom filters (FPR 10.99% > 5% cap).
FIPS v2 (dynamic bloom filter sizing) is not yet released. A small private
mesh with only Felix's devices avoids the problem entirely.

### 2.4 Tasks

| Task | Title | Assignee | Status | Kanban ID |
|------|-------|----------|--------|-----------|
| A1 | Fix testserver2 bloom filter — switch to private mesh | worker-tollgate | DONE | t_b2668bc2 |
| A2 | Fix testserver2 Nostr relay auth | worker-tollgate | Ready | t_da36eccc |
| A3 | Fix testserver2 UDP buffer clamping | worker-admin | Ready | t_abcddd16 |
| A4 | Install FIPS CLI on T470 | worker-admin | Ready | t_2f0230b7 |
| A5 | Verify T470 persistence — reboot test | worker-inspector | Ready | t_a1cfe86d |
| A6 | Fix .env template bug (ZAI_API_KEY) | worker-admin | Ready | t_7fa5a8bd |
| A7 | Fix Docker Swarm or remove deploy.resources | worker-admin | Ready | t_aa770e8b |
| A8 | Add shared Docker network for routstr+relay+tenants | worker-admin | Ready | t_22dccf3b |
| A9 | Add Caddy routes for Hermes gateway ports | worker-admin | Ready | t_e12444bc |
| A10 | Build hermes-agent:nostr Docker image | worker-admin | Ready | t_b4866a20 |

### 2.5 Key Decisions & Completed Work

**A1 — Bloom Filter Fix (DONE):**
- Removed Andre (npub1k3aer...) from peers — private mesh, only our nodes
- Added `node.bloom.max_inbound_fpr: 0.15` to `/etc/fips/fips.yaml` (was default 0.05)
- Restarted `fips.service` on testserver2 (23.182.128.51)
- Verification: 12+ min post-restart, 0 FilterAnnounce rejections
- Bloom stats: accepted=324, fill_exceeded=0, uptime_secs=733
- Backup: `/etc/fips/fips.yaml.bak-pre-private-mesh`

**WARNING:** The Ansible template (`ansible/roles/fips/templates/fips.yaml.j2`)
does NOT include the `bloom.max_inbound_fpr` config or the `node.bloom` section.
If the fips playbook is re-run, it will overwrite this fix and revert to the
5% default. The template and `defaults/main.yml` need updating to persist
this change. (Follow-up task needed.)

### 2.6 FIPS Config Reference

**Config file:** `/etc/fips/fips.yaml`
**Ansible role:** `ansible/roles/fips/`
**Playbook:** `ansible/playbooks/13-fips.yml`

Key config sections:
```yaml
node:
  bloom:
    max_inbound_fpr: 0.15    # raised from 0.05 default (A1 fix)

peers:
  # Only Felix's nodes — no external peers
  # VPS2 hub config lists DQ05, T14Gen5, T470 npubs

discovery:
  policy: configured_only    # do NOT connect to random peers
  relays:
    - wss://relay.damus.io
    - wss://nos.lol
    - wss://offchain.pub
    - wss://relay.orangesync.tech
  app_tag: "fips-overlay-v1"

transport:
  udp_port: 2121
  tcp_port: 8443
  mtu: 1280
```

### 2.7 Remaining Work

1. **A2:** Remove orangesync/ngit relays from fips_advertise_relays/fips_dm_relays. Use only damus/nos.lol/offchain. Acceptance: no relay auth errors for 10 min.
2. **A3:** Add sysctl `net.core.rmem_max=2097152`, `wmem_max=2097152`, `rmem_default`, `wmem_default`. Add to Ansible FIPS role. Acceptance: sysctl returns 2097152, no clamping warnings.
3. **A4:** Download fips/fipsctl CLI binary to T470. Acceptance: `fips peers` shows Andre connected.
4. **A5:** Restart FIPS on T470, verify auto-connect to Andre within 60s. Acceptance: `journalctl` shows `Peer promoted to active peer=andre`.
5. **A6-A10:** Docker infrastructure setup for multi-tenant (see Track B).

### 2.8 FIPS Operations Cheatsheet

```bash
# Check FIPS status
sudo systemctl status fips
sudo journalctl -u fips -n 50 --no-pager

# Check fips0 interface
ip link show fips0
ip -6 addr show fips0

# Check peers
sudo fipsctl show status
sudo fipsctl peers

# Check bloom filter stats
sudo fipsctl bloom stats

# Restart FIPS
sudo systemctl restart fips

# Check Nostr relay connectivity
sudo fipsctl relays

# Ping a mesh node by npub
ping6 -c 4 fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149

# SSH via FIPS mesh (needs 30s timeout due to mesh latency)
ssh -o ConnectTimeout=30 root@fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149
```

---

## 3. Track B — Multi-Tenant Hermes Hosting

### 3.1 Summary

Deploy 3 Hermes AI agent containers on VPS2, each serving one friend. Friends
interact via Buzz (desktop/mobile Nostr client) connecting to obelisk-relay.
Each friend gets full kanban + quality gates + worker profiles. LLM requests
route through Routstr (with Kalman pricing) to z.ai. Cashu per-token sats from
day 1.

### 3.2 Architecture

```
Friend (Buzz client)
    │ wss://relay.orangesync.tech
    ▼
obelisk-relay (NIP-29 group chat)
    │ kind:9007 create group, kind:9000 add user
    ▼
Hermes container (hermes-friend-N)
    │ Nostr adapter (gateway/platforms/nostr.py)
    │ Processes message, dispatches worker
    ▼
Routstr (LLM proxy, Kalman pricing)
    │ http://routstr:8000/v1/chat/completions
    ▼
z.ai API (glm-5.2)
    │
    ▼
Response back through the chain
```

### 3.3 Tasks

| Task | Title | Assignee | Status | Kanban ID |
|------|-------|----------|--------|-----------|
| B1 | Populate .env with real friend npubs/keys | worker-admin | Ready | t_af3c0c89 |
| B2 | Run playbook 45 on VPS2 (Hermes tenants) | worker-admin | Ready | t_0deb95ed |
| B3 | Verify Hermes containers healthy | worker-inspector | Ready | t_ae076746 |
| B4 | Verify Buzz client → relay → Hermes round-trip | worker-inspector | Ready | t_e2759010 |
| B5 | Verify LLM routing (Hermes → Routstr → z.ai) | worker-inspector | Ready | t_65f88391 |
| B6 | Deploy merchant routing modules to VPS2 | worker-admin | Ready | t_73e4b7fe |
| B7 | Integrate merchant pricing with Routstr | worker-tollgate | Ready | t_f3bc14f1 |

### 3.4 Key Design Decisions

1. **Official Hermes Docker image** — not custom build. Use `docker-compose.override.yml` per friend for customization.
2. **obelisk-relay** for NIP-29 — lightweight (1 vCPU/1GB vs Block Buzz's PostgreSQL+Redis+S3). Already in Ansible kit.
3. **Mount host Docker socket** — workers need Docker. DinD is heavy. Socket mount acceptable for 3 trusted friends. (V2: use socket proxy.)
4. **Full Cashu per-token sats from day 1** — routstrd in each container manages wallet. CDK mint on VPS with gRPC mark-paid.
5. **Hermes native Nostr adapter** — already built at `gateway/platforms/nostr.py`. No Signal/Matrix needed.
6. **Network egress isolation** — internal Docker network for Hermes containers, egress only to Routstr + obelisk.
7. **Per-friend Docker networks** — friends isolated from each other.
8. **Per-friend API keys in Routstr** — quota isolation (one friend can't exhaust everyone).
9. **Deployment admin nsec** — NOT Felix's personal nsec.

### 3.5 Resource Budget

| Component | RAM (MB) |
|-----------|----------|
| Hermes container x3 | 1500-2400 (500-800 each) |
| Routstr | 200 |
| obelisk-relay | 100 |
| Cashu mint (CDK) | 200 |
| mint-orchestrator | 100 |
| Caddy | 50 |
| System + FIPS | 350 |
| **Total** | **2500-3400** |

> VPS needs 4GB RAM minimum. 8GB is tight for 3 active friends. 16GB recommended
> or limit to 2 friends. Smart resource-aware dispatching (task MT-10b) uses
> machine constraints as the natural cap — no hard worker limit.

### 3.6 Docker Network Layout

```
hermes-net (shared bridge)
    ├── hermes-friend-1     ← friend 1 container
    ├── hermes-friend-2     ← friend 2 container
    ├── hermes-friend-3     ← friend 3 container
    ├── routstr             ← LLM proxy
    ├── obelisk-relay       ← NIP-29 relay
    ├── fips-sidecar        ← FIPS TUN access
    └── mint-orchestrator   ← Cashu gRPC

Friend containers reach:
    - routstr:8000          ← LLM calls
    - obelisk-relay:7780    ← NIP-29 messages
    - fips-sidecar (shared netns) ← mesh traffic
```

### 3.7 Hermes Container Config

Each friend gets a `docker-compose.override.yml`:

```yaml
services:
  hermes-friend-N:
    image: hermes-agent:nostr
    environment:
      - ZAI_API_KEY={{ friend_N_zai_key }}
      - NOSTR_RELAYS=wss://relay.orangesync.tech
      - NOSTR_GROUPS={{ friend_N_group_id }}
      - NOSTR_NSEC_PATH=/secrets/nsec
      - LLM_PROXY_URL=http://routstr:8000
    volumes:
      - hermes-friend-N-data:/home/hermes/.hermes
      - /var/run/docker.sock:/var/run/docker.sock
      - ./secrets/friend-N/nsec:/secrets/nsec:ro
    networks:
      - hermes-net
    deploy:
      resources:
        limits:
          memory: 800M
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 3.8 LLM Routing Chain

```
Hermes container
    → POST http://routstr:8000/v1/chat/completions
        Headers: x-cashu: <cashu-token>
    → Routstr validates Cashu token, deducts sats
    → Routstr forwards to z.ai API
    → Response returned to Hermes
    → Logs show routing in zai_usage.db
```

### 3.9 Remaining Work

1. **B1:** Fill `.env` with FRIEND1_NPUB, FRIEND2_NPUB, API keys, admin nsec.
2. **B2:** Deploy 3 Hermes containers via playbook 45.
3. **B3:** Verify healthchecks pass, all 3 containers healthy for 5 min.
4. **B4:** Send message from Buzz → relay → Hermes → response. Acceptance: Hermes responds.
5. **B5:** Send LLM request from Hermes, verify routes through Routstr. Acceptance: logs show routing.
6. **B6:** Deploy merchant-routing-engine to VPS2. Acceptance: modules import.
7. **B7:** Wire pricing engine into Routstr. Acceptance: Routstr uses Kalman pricing.

---

## 4. Track C — FIPS + Docker Integration

### 4.1 Summary

Route Hermes container traffic through the FIPS mesh by running a FIPS
sidecar container with NET_ADMIN capabilities and /dev/net/tun access. The
sidecar's network namespace is shared with Hermes containers so they can
reach mesh addresses.

### 4.2 Tasks

| Task | Title | Assignee | Status | Kanban ID |
|------|-------|----------|--------|-----------|
| C1 | Create FIPS sidecar Dockerfile | worker-admin | Ready | t_031b6829 |
| C2 | Add FIPS sidecar to docker-compose template | worker-admin | Ready | t_698b4fee |
| C3 | Route Hermes traffic through fips0 TUN | worker-tollgate | Ready | t_0d51681d |
| C4 | Test mesh connectivity from Hermes container | worker-inspector | Ready | t_5c6f1220 |
| C5 | Deploy FIPS on SSD VPS when back (48h) | worker-admin | Ready | t_a0a5e498 |
| C6 | Prepare DQ05 FIPS config | worker-admin | Ready | t_ec7458cf |

### 4.2 FIPS Sidecar Design

```
┌─ Docker host (VPS2) ─────────────────────────────────┐
│                                                       │
│  ┌─ hermes-friend-N container ──────────────────────┐│
│  │  Shares network namespace with fips-sidecar      ││
│  │  Can ping fd00::/8 mesh addresses                ││
│  │  Traffic egresses through fips0 TUN             ││
│  └──────────────────────────────────────────────────┘│
│                       │ (shared netns)                │
│  ┌─ fips-sidecar container ─────────────────────────┐│
│  │  Capabilities: NET_ADMIN, NET_RAW                ││
│  │  Devices: /dev/net/tun                           ││
│  │  Config: /etc/fips/fips.yaml                     ││
│  │  Creates fips0 TUN interface                     ││
│  │  FIPS daemon runs inside container               ││
│  └──────────────────────────────────────────────────┘│
│                       │                               │
│                   fips0 TUN                            │
│                   MTU 1280                             │
│                   IPv6 fd00::/8                        │
└───────────────────────────────────────────────────────┘
```

### 4.3 FIPS Sidecar Dockerfile (Planned — C1)

```dockerfile
FROM debian:13-slim

RUN apt-get update && apt-get install -y \
    fips \
    iproute2 \
    iptables \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /dev/net && mknod /dev/net/tun c 10 200

COPY fips.yaml /etc/fips/fips.yaml

ENTRYPOINT ["fips", "--config", "/etc/fips/fips.yaml"]
```

Docker-compose service:
```yaml
  fips-sidecar:
    build: ./fips-sidecar
    cap_add:
      - NET_ADMIN
      - NET_RAW
    devices:
      - /dev/net/tun:/dev/net/tun
    volumes:
      - ./fips-config:/etc/fips:ro
    networks:
      - hermes-net
    restart: unless-stopped
```

### 4.4 Network Namespace Sharing

To route Hermes traffic through FIPS, share the sidecar's network namespace:

```yaml
  hermes-friend-N:
    image: hermes-agent:nostr
    network_mode: "container:fips-sidecar"  # share sidecar's netns
    # ... other config
```

This makes the Hermes container see fips0 and all mesh routes. The container
can `ping6 fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149` to reach VPS2's FIPS
address, or any other mesh node.

### 4.5 Remaining Work

1. **C1:** Write Dockerfile for FIPS sidecar. Acceptance: `docker build` succeeds.
2. **C2:** Add fips-sidecar service to hermes_tenants compose template. Acceptance: `compose up` starts sidecar.
3. **C3:** Share FIPS sidecar network namespace with Hermes container. Acceptance: Hermes container can ping mesh addresses.
4. **C4:** Verify FIPS mesh works from inside Hermes container. Acceptance: can ping Andre's mesh address.
5. **C5:** When SSD VPS online, run `ansible-playbook 13-fips.yml --limit vps1`. Acceptance: handshake confirmed.
6. **C6:** Ansible dry-run for DQ05 FIPS config. Acceptance: dry-run passes.

---

## 5. Track D — ESP32 & Android Mesh Clients

### 5.1 Summary

Extend the FIPS mesh to embedded (ESP32-C3) and mobile (Android) clients.
ESP32 uses ESP-NOW radio transport with a hybrid WiFi init path. Android
uses a native APK that joins the mesh directly.

### 5.2 Tasks

| Task | Title | Assignee | Status | Kanban ID |
|------|-------|----------|--------|-----------|
| D1 | Fix ESP-NOW linker (Path B hybrid) | worker-balloon | Ready | t_055c5911 |
| D2 | Port erasure coding to Rust no_std | worker-balloon | Ready | t_2a8a4ea9 |
| D3 | ESP32-C3 mesh join demo | worker-balloon | Ready | t_0dad56b5 |
| D4 | Build fips-android APK | worker-admin | Ready | t_debbb723 |
| D5 | Android mesh join test | worker-inspector | Ready | t_35ed7bd9 |

### 5.3 ESP32-C3 Mesh Demo (Planned — D3)

```
┌─ ESP32-C3 #1 ──┐     ESP-NOW      ┌─ ESP32-C3 #2 ──┐
│  FIPS handshake │ ◄─────────────► │  FIPS handshake │
│  Serial console │                 │  Serial console │
│  esp-radio WiFi  │                 │  esp-radio WiFi  │
│  esp-wifi-sys FFI│                 │  esp-wifi-sys FFI│
└─────────────────┘                 └─────────────────┘
```

- Flash 2 ESP32-C3 boards
- Verify FIPS handshake over ESP-NOW
- Acceptance: serial logs confirm handshake

### 5.4 Erasure Coding (D2)

Port PRBS23-XOR erasure coding from `balloon-fresh` C codebase to Rust
`no_std`. This is needed for reliable mesh transport over lossy ESP-NOW
radio links.

### 5.5 Android Client (D4-D5)

Build debug APK from `fips-android` repo. Connect Android phone to FIPS mesh.
Acceptance: phone shows connected to mesh.

---

## 6. Track E — Monitoring & Health

### 6.1 Summary

Automated health monitoring for the FIPS mesh and Hermes containers. A
Python script checks peer status, bloom filter health, UDP buffers, and
relay connectivity. A cron job runs it every 30 minutes. A dashboard
shows Hermes container status.

### 6.2 Tasks

| Task | Title | Assignee | Status | Kanban ID |
|------|-------|----------|--------|-----------|
| E1 | FIPS mesh health monitoring script | worker-admin | Ready | t_cb923ae4 |
| E2 | FIPS mesh health cron job | worker-admin | Ready | t_dff04572 |
| E3 | Hermes container health dashboard | worker-admin | Ready | t_1f1eff45 |
| E4 | Integrated operations doc (THIS DOC) | worker-inspector | Running | t_191623cf |

### 6.3 FIPS Health Check Script (Planned — E1)

Python script that checks:

- **Peer status:** `fipsctl peers` — all expected peers connected
- **Bloom filter:** `fipsctl bloom stats` — FPR below threshold, fill not exceeded
- **UDP buffers:** `sysctl net.core.rmem_max` — returns 2097152
- **Relay connectivity:** `fipsctl relays` — all configured relays reachable
- **fips0 interface:** `ip link show fips0` — interface UP
- **Mesh latency:** ping hub node, check RTT < 500ms

Exit codes:
- `0` — all checks pass
- `1` — one or more checks fail

### 6.4 Cron Job (Planned — E2)

```yaml
# Hermes Kanban cron job
schedule: "every 30m"
no_agent: true
deliver: local
script: |
  #!/bin/bash
  /opt/tollgate/scripts/fips-health-check.py
  if [ $? -ne 0 ]; then
    echo "FIPS mesh health check FAILED — check journalctl -u fips"
  fi
```

### 6.5 Hermes Container Dashboard (Planned — E3)

Dashboard showing:
- Container status (running/stopped)
- Healthcheck results
- Memory usage per container
- LLM request count (from Routstr logs)
- Cashu token consumption

### 6.6 Existing Monitoring

The VPS already has a watchdog system:

- **Watchdog script:** `scripts/watchdog.py` with 16 service definitions
- **Watchdog config:** `scripts/watchdog.json`
- **Systemd service:** `tollgate-watchdog.service` running and enabled
- **16/16 services healthy** — watchdog dry-run confirms all green

See [services.md](services.md) for the full service inventory.

---

## 7. Daily Operations Runbook

### 7.1 Morning Check (5 min)

```bash
# 1. Check FIPS mesh health
ssh root@23.182.128.51
fipsctl peers
fipsctl bloom stats
ip link show fips0

# 2. Check Docker containers
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# 3. Check watchdog
systemctl status tollgate-watchdog
python3 /opt/tollgate/scripts/watchdog.py --dry-run

# 4. Check Caddy
docker logs tollgate-caddy --tail 20

# 5. Check disk
df -h
docker system df
```

### 7.2 Adding a New Friend

1. Generate a Nostr keypair for the friend (or use their existing npub)
2. Add their npub to `.env` as `FRIEND_N_NPUB`
3. Generate a z.ai API key for the friend
4. Add the API key to Routstr with quota limits
5. Create a `docker-compose.override.yml` for the new friend
6. Run `docker compose up -d` for the new container
7. Create a NIP-29 group on obelisk-relay for the friend
8. Add the friend to the group
9. Send the friend the onboarding guide: `docs/onboarding-friend-guide.md`

### 7.3 Restarting a Friend's Hermes Container

```bash
# Find the container
docker ps | grep hermes-friend-N

# Restart it
docker restart hermes-friend-N

# Check health
docker ps | grep hermes-friend-N
docker logs hermes-friend-N --tail 20
```

### 7.4 Updating Hermes

```bash
# Pull latest image
docker pull hermes-agent:nostr

# Recreate containers
cd /opt/sovereign/hermes-tenants
docker compose up -d

# Verify
docker ps | grep hermes
```

### 7.5 FIPS Mesh — Adding a New Node

1. Install FIPS on the new machine (via Ansible or manually)
2. Add the new machine's npub to VPS2's peers config
3. Add VPS2's npub to the new machine's peers config
4. Restart FIPS on both machines
5. Verify with `fipsctl peers` on both sides
6. Test with `ping6` to the new machine's FIPS address

### 7.6 Backup

- **Per-friend volumes:** snapshot Docker volumes regularly
- **FIPS config:** `/etc/fips/fips.yaml` (back up before changes)
- **.env file:** contains all secrets — back up securely
- **Ansible configs:** version-controlled in git

---

## 8. Troubleshooting Cross-Track

### 8.1 Friend Can't Connect to Relay

1. Check obelisk-relay is running: `docker ps | grep obelisk`
2. Check relay URL is correct: `wss://relay.orangesync.tech`
3. Check friend's npub is whitelisted on the relay
4. Check Caddy WebSocket upgrade: `docker logs tollgate-caddy | grep relay`
5. Check friend's Buzz relay settings (Read + Write enabled)

### 8.2 Hermes Not Responding to Messages

1. Check container is running: `docker ps | grep hermes-friend-N`
2. Check healthcheck: `docker inspect hermes-friend-N | jq '.[0].State.Health'`
3. Check Nostr adapter logs: `docker logs hermes-friend-N 2>&1 | grep nostr`
4. Check relay connection: `docker logs hermes-friend-N 2>&1 | grep relay`
5. Check LLM routing: `docker logs routstr --tail 50`
6. Check z.ai API key is valid: `curl -H "Authorization: Bearer $KEY" https://api.z.ai/v1/models`

### 8.3 FIPS Mesh Connectivity Issues

1. Check FIPS daemon: `systemctl status fips`
2. Check fips0 interface: `ip link show fips0`
3. Check peers: `fipsctl peers`
4. Check bloom filter: `fipsctl bloom stats` — FPR should be < 15%
5. Check Nostr relay connectivity: `fipsctl relays`
6. Check firewall: `ufw status` — ports 2121/udp and 8443/tcp must be open
7. Check UDP buffers: `sysctl net.core.rmem_max` — should be 2097152
8. Check for FilterAnnounce rejections: `journalctl -u fips | grep FilterAnnounce`
9. If mesh routing is slow: use `ConnectTimeout=30` for SSH (165-333ms RTT is normal)

### 8.4 LLM Routing Failure

1. Check Routstr is running: `docker ps | grep routstr`
2. Test Routstr directly: `curl http://localhost:8000/v1/models`
3. Check Cashu token validity: `docker logs routstr | grep cashu`
4. Check z.ai API: `curl -H "Authorization: Bearer $ZAI_KEY" https://api.z.ai/v1/models`
5. Check Routstr logs: `docker logs routstr --tail 100`
6. Check zai_usage.db for request history

### 8.5 FIPS Sidecar Not Working

1. Check sidecar is running: `docker ps | grep fips-sidecar`
2. Check capabilities: `docker inspect fips-sidecar | jq '.[0].HostConfig.CapAdd'`
3. Check TUN device: `docker exec fips-sidecar ip link show fips0`
4. Check namespace sharing: `docker inspect hermes-friend-N | jq '.[0].HostConfig.NetworkMode'`
5. Ping from Hermes container: `docker exec hermes-friend-N ping6 -c 4 fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149`

---

## 9. Service Inventory

### 9.1 Public Services (Caddy reverse proxy, TLS via Cloudflare DNS-01)

| Service | Subdomain | Port | Tech | Status |
|---------|-----------|------|------|--------|
| obelisk-relay | relay.orangesync.tech | 8080 | Rust (Tokio+Axum) | Deployed |
| Routstr | routstr.orangesync.tech | 8000 | Go (LLM proxy) | Deployed |
| Cashu mint | mints.orangesync.tech | 8085 | CDK mintd (Docker) | Deployed |
| blossom-server | blossom.orangesync.tech | 3001 | Deno 2 + TypeScript | Deployed |
| nsite-gateway | nsite.orangesync.tech | 3002 | Deno 2 + TypeScript | Deployed |
| ngit-grasp | git.orangesync.tech | 7334 | Rust (ngit-grasp) | Deployed |
| strfry relay | relay.orangesync.tech | 7777 | C++ | Deployed |
| Release Explorer | releases.orangesync.tech | — | React 18 | Deployed |
| CI Dashboard | ci.orangesync.tech | — | Vue.js | Deployed |
| Mint dashboard | print.mints.orangesync.tech | — | Svelte | Deployed |

### 9.2 Internal Services (Docker hermes-net, not exposed)

| Service | Port | Tech | Status |
|---------|------|------|--------|
| hermes-friend-1 | 9000-9002 | Hermes Agent (Python) | Pending (B2) |
| hermes-friend-2 | 9000-9002 | Hermes Agent (Python) | Pending (B2) |
| hermes-friend-3 | 9000-9002 | Hermes Agent (Python) | Pending (B2) |
| mint-orchestrator | 8090 | Python daemon | Deployed |
| fips-sidecar | — | FIPS in Docker | Pending (C1-C2) |

### 9.3 System Services (VPS2 host)

| Service | Port | Tech | Status |
|---------|------|------|--------|
| Caddy | 80/443 | Caddy 2 + Cloudflare DNS | Deployed |
| FIPS daemon | 2121/udp, 8443/tcp | Rust, TUN/nftables | Active |
| Shadowsocks/MPTCP | 65101/65001 | systemd | Deployed |
| Watchdog | — | Python systemd service | Deployed |
| Act Runner | runner.orangesync.tech | Python + nektos/act | Deployed |

### 9.4 FIPS Mesh Nodes

| Node | Role | FIPS Address | Status |
|------|------|-------------|--------|
| VPS2 | Hub | `fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149` | Active |
| DQ05 | Spoke | (derived from npub) | Pending |
| T14Gen5 | Spoke | (derived from npub) | Pending |
| T470 | Spoke | (derived from npub) | Pending |

---

## 10. Security Posture

### 10.1 Network Security

- **FIPS mesh:** Private mesh, `configured_only` discovery policy. No random
  peers. All traffic encrypted at L3 (Noise Protocol).
- **Docker isolation:** Per-friend Docker networks. Friends cannot see each
  other's containers or volumes directly.
- **Docker socket:** Mounted into friend containers (V1, trusted friends).
  V2: use tecnativa/docker-socket-proxy to restrict API calls.
- **Routstr:** Per-friend API keys for quota isolation. One friend cannot
  exhaust everyone's LLM budget.
- **Cashu gRPC:** Port 50055 bound to 127.0.0.1 only — NOT exposed to internet.
- **Caddy:** TLS 1.2+, HSTS headers, default 404 for unknown subdomains.

### 10.2 Key Management

- **Deployment admin nsec:** Used for relay admin, group creation. NOT Felix's
  personal nsec.
- **Per-friend nsec:** Stored in Docker secrets, mounted read-only.
- **z.ai API keys:** Stored in Docker secrets, NOT baked into images.
- **Cashu mint keys:** Generated at mint creation, stored in mint config.

### 10.3 Known Security Considerations

1. **Docker socket mount** — any friend can run arbitrary Docker commands on
   the host. Acceptable for V1 with 3 trusted friends. V2: socket proxy.
2. **FIPS mesh latency** — 165-333ms RTT is normal. Use `ConnectTimeout=30`
   for SSH. Not a security issue but affects operations.
3. **Bloom filter config not persisted in Ansible** — if the fips playbook is
   re-run, it will overwrite the A1 fix. Follow-up task needed to update the
   Ansible template.
4. **Hermes Nostr adapter self-echo skip** — bot can't see its own messages.
   If user replies to a bot message via NIP-25 reaction, the bot won't see
   the reaction context. Minor UX issue.

---

## 11. Task Status Board

### Full Task Matrix

| ID | Track | Title | Assignee | Status |
|----|-------|-------|----------|--------|
| A1 | FIPS | Fix testserver2 bloom filter | worker-tollgate | DONE |
| A2 | FIPS | Fix testserver2 Nostr relay auth | worker-tollgate | Ready |
| A3 | FIPS | Fix testserver2 UDP buffer clamping | worker-admin | Ready |
| A4 | FIPS | Install FIPS CLI on T470 | worker-admin | Ready |
| A5 | FIPS | Verify T470 persistence — reboot test | worker-inspector | Ready |
| A6 | FIPS | Fix .env template bug (ZAI_API_KEY) | worker-admin | Ready |
| A7 | FIPS | Fix Docker Swarm or remove deploy.resources | worker-admin | Ready |
| A8 | FIPS | Add shared Docker network | worker-admin | Ready |
| A9 | FIPS | Add Caddy routes for Hermes gateway ports | worker-admin | Ready |
| A10 | FIPS | Build hermes-agent:nostr Docker image | worker-admin | Ready |
| B1 | Hermes | Populate .env with real friend npubs/keys | worker-admin | Ready |
| B2 | Hermes | Run playbook 45 on VPS2 (Hermes tenants) | worker-admin | Ready |
| B3 | Hermes | Verify Hermes containers healthy | worker-inspector | Ready |
| B4 | Hermes | Verify Buzz → relay → Hermes round-trip | worker-inspector | Ready |
| B5 | Hermes | Verify LLM routing (Hermes → Routstr → z.ai) | worker-inspector | Ready |
| B6 | Hermes | Deploy merchant routing modules to VPS2 | worker-admin | Ready |
| B7 | Hermes | Integrate merchant pricing with Routstr | worker-tollgate | Ready |
| C1 | FIPS-Docker | Create FIPS sidecar Dockerfile | worker-admin | Ready |
| C2 | FIPS-Docker | Add FIPS sidecar to docker-compose template | worker-admin | Ready |
| C3 | FIPS-Docker | Route Hermes traffic through fips0 TUN | worker-tollgate | Ready |
| C4 | FIPS-Docker | Test mesh connectivity from Hermes container | worker-inspector | Ready |
| C5 | FIPS-Docker | Deploy FIPS on SSD VPS when back (48h) | worker-admin | Ready |
| C6 | FIPS-Docker | Prepare DQ05 FIPS config | worker-admin | Ready |
| D1 | ESP32 | Fix ESP-NOW linker (Path B hybrid) | worker-balloon | Ready |
| D2 | ESP32 | Port erasure coding to Rust no_std | worker-balloon | Ready |
| D3 | ESP32 | ESP32-C3 mesh join demo | worker-balloon | Ready |
| D4 | Android | Build fips-android APK | worker-admin | Ready |
| D5 | Android | Android mesh join test | worker-inspector | Ready |
| E1 | Monitoring | FIPS mesh health monitoring script | worker-admin | Ready |
| E2 | Monitoring | FIPS mesh health cron job | worker-admin | Ready |
| E3 | Monitoring | Hermes container health dashboard | worker-admin | Ready |
| E4 | Monitoring | Integrated operations doc (this doc) | worker-inspector | Running |

### Dependency Graph

```
A1 (bloom filter) ── DONE
  └→ A2 (relay auth) ──→ A3 (UDP buffers)
                           └→ A4 (FIPS CLI on T470) ──→ A5 (reboot test)

A6 (.env template) ──→ A7 (Docker Swarm) ──→ A8 (shared network) ──→ A9 (Caddy routes)
                                                                              └→ A10 (Docker image)
                                                                                    └→ B1 (.env) ──→ B2 (deploy) ──→ B3 (health check)
                                                                                                                                └→ B4 (round-trip) ──→ B5 (LLM routing)
                                                                                                                                                          └→ B6 (merchant) ──→ B7 (pricing)

C1 (sidecar Dockerfile) ──→ C2 (compose) ──→ C3 (route traffic) ──→ C4 (test connectivity)

C5 (SSD VPS) ── independent (48h wait)
C6 (DQ05 config) ── independent

D1 (ESP-NOW linker) ──→ D2 (erasure coding) ──→ D3 (ESP32 demo)
D4 (Android APK) ──→ D5 (Android test)

E1 (health script) ──→ E2 (cron job)
E3 (dashboard) ── independent
E4 (this doc) ── running
```

### Critical Path

```
A6 → A7 → A8 → A9 → A10 → B1 → B2 → B3 → B4 → B5
```

The critical path runs through Docker infrastructure setup (A6-A10) into
multi-tenant deployment (B1-B5). C1-C4 can proceed in parallel once A8
(shared Docker network) is done.

---

## References

- [FIPS Mesh Operations Guide](FIPS-MESH-OPERATIONS.md) — detailed FIPS config, peer management, troubleshooting
- [FIPS Mesh Setup Plan](../PLAN-FIPS-MESH-SETUP.md) — full deployment scoping document
- [FIPS Ingress Gate](FIPS-INGRESS-GATE.md) — public internet → FIPS mesh reverse proxy
- [FIPS Mesh Deployment Plan](FIPS-MESH-DEPLOYMENT-PLAN.md) — deployment execution plan
- [Friend Onboarding Guide](onboarding-friend-guide.md) — user-facing guide for friends
- [Multi-Tenant Comprehensive Plan](../PLAN-multi-tenant-comprehensive.md) — full implementation plan
- [Roadmap](../ROADMAP.md) — decisions, adversarial review findings, task breakdown
- [Services Overview](services.md) — full service inventory
- [Troubleshooting](troubleshooting.md) — common issues and fixes
- [Getting Started](getting-started.md) — initial setup guide
- [Configuration](configuration.md) — configuration reference