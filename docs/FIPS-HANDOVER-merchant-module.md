# FIPS Handover — Hermes + Merchant Module on FIPS Mesh

## Purpose

This document is for a FIPS-focused context window. It explains what the merchant module / Hermes multi-tenant project needs from FIPS so that Hermes agents can run globally reachable without Tailscale/Netbird.

## What We're Building

A multi-tenant Hermes hosting platform where:
- Each friend gets their own Hermes agent in a Docker container
- Hermes communicates via Nostr (Buzz relay on obelisk)
- LLM API calls are paid per-request via Cashu (routstrd proxy)
- The entire stack runs on FIPS mesh for global reachability

## Current State (Aug 14, 2026)

### FIPS Mesh — WORKING
- **T470 (CobradorWave)**: Connected to Andre + VPS2 via FIPS. 2 peers, mesh size ~543.
  - Andre: UDP, RTT ~85ms, 0% loss
  - VPS2: UDP, RTT ~168ms, 0% loss
- **VPS2 (23.182.128.51)**: Connected to Andre + other peers. FIPS v0.4.1 running.
  - Mesh IPv6: fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149
- **DQ05**: Offline. Has Andre peer config but machine unreachable.
- **Andre's network**: npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n, UDP 194.191.252.108:2121

### VPS2 Services — RUNNING (11 Docker containers)
- buzz-relay (obelisk) — NIP-29 group chat for Hermes ↔ friends
- cdk-mintd — Cashu mint (sat unit, fakewallet)
- routstr-proxy — LLM API proxy with Cashu payment gating
- mint-orchestrator — GRPC daemon for mint management
- strfry, strfry-agg, blossom, nsite-gateway, ngit — supporting infra

#### FIPS Mesh Service Access — WORKING (Aug 13, 2026)
- **Architecture**: Host-level FIPS daemon + Caddy HTTP-only ingress on VPS2
- **Pattern**: No per-container FIPS sidecar needed. Caddy on VPS2 listens on [::]:80 (reachable via fips0). HTTP-only site blocks route by Host header to local Docker services.
- **DNS**: fips-dns active on both T470 and VPS2. /etc/fips/hosts entries map service names to VPS2 npub.
- **Verified services** (from T470 via mesh):
  - `http://hermes-mesh.fips/` — health check (returns "FIPS mesh ingress active")
  - `http://buzz-relay.fips/` — Buzz relay (NIP-29, responds)
  - `http://routstr.fips/` — Routstr LLM proxy (full UI loads)
  - `http://mint.fips/` — CDK Cashu mint (web UI loads)
- **T470 DNS fix**: fips.yaml binds DNS to 127.0.0.1:5354 (IPv4), but dns-delegate config pointed to [::1]:5354 (IPv6). Fixed dns-delegate to use 127.0.0.1:5354. Also added global drop-in at /etc/systemd/resolved.conf.d/fips.conf as belt-and-suspenders.

#### T470 Hermes Mesh Access — CONFIGURED (Aug 14, 2026)
- **Architecture**: Host-level FIPS daemon + socat IPv6→IPv4 bridges
- **Pattern**: socat bridges listen on T470's mesh IPv6 (fd97:77d4:cd27:a6ae:1b29:e92e:fd96:dee8) and forward to localhost services
- **Bridges running**:
  - `fips-hermes-bridge.service`: mesh IPv6:8443 → 127.0.0.1:8443 (Hermes gateway)
  - `fips-hermes-node-bridge.service`: mesh IPv6:3001 → 127.0.0.1:3001 (Hermes node app)
- **nftables**: `/etc/fips/fips.d/hermes.nft` allows inbound TCP 8443, 3001, and UDP/TCP 53 on fips0
- **DNS**: `/etc/fips/hosts` entries:
  - `dq05-hermes.fips` → T470 npub (resolves to T470 mesh IPv6)
  - `friend1-hermes.fips` → T470 npub (resolves to T470 mesh IPv6)
- **Local verification**: Ports 8443 and 3001 OPEN on mesh IPv6 via socat bridges
- **External verification**: No inbound connections on 8443/3001 observed from external peers yet (VPS2 attempted SSH on port 22 only). Services are ready for external peers to connect.

### What's NOT Working Yet
- **VPS1 (64.188.7.38)**: DOWN. Was the primary deployment target. Needs provider console access.
- **Hermes containers**: Not yet deployed. Ansible playbook ready (45-multi-tenant-hermes.yml), hermes_tenants role tested (molecule pass), but blocked on VPS.
- **z.ai API keys**: Both exhausted (429). Routstr falls back to Ollama Cloud.
- **HTTPS via mesh**: Caddy 443 has no cert for raw IPv6 mesh address. Mesh traffic uses HTTP only (acceptable — FIPS mesh is encrypted at L3). For HTTPS, would need cert with mesh IPv6 SAN or use .fips hostname with on-demand TLS.

## What We Need From FIPS

### 1. Mesh Reachability for All Friends
Each friend's device needs to join Andre's FIPS network (or our mesh) so they can:
- Reach the Buzz relay at its FIPS mesh address (not just clearnet)
- SSH to their Hermes container via mesh IPv6
- Access routstr proxy via mesh

**Request**: Ensure FIPS daemon can run in Docker containers alongside Hermes. Each Hermes container should have FIPS available for mesh routing.

### 2. FIPS-as-Transport for Hermes Containers
Currently Hermes containers use Docker networking with port mappings via Caddy. The ask:
- Can FIPS run inside each Hermes container? (sidecar pattern)
- Or: one FIPS daemon on the host, containers share the mesh via host networking?
- Goal: friends reach their Hermes agent via `<npub>.fips` DNS, not clearnet domain

### 3. DNS Resolution
- `.fips` domain resolution for Hermes container hostnames
- Each friend's Hermes container gets a mesh hostname (e.g., `friend1-hermes.fips`)
- fips-dns service enabled on VPS2

### 4. Port Exposure via FIPS
- Buzz relay: accessible via mesh (not just Caddy clearnet)
- Routstr proxy: accessible via mesh for Cashu-paid LLM calls
- Hermes agent API: accessible via mesh for direct agent interaction

## Architecture We're Targeting

```
┌─────────────────────────────────────────────────────┐
│  VPS2 (23.182.128.51) — FIPS mesh node               │
│                                                      │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐              │
│  │ Hermes  │  │ Hermes  │  │ Hermes  │  (3 friends) │
│  │ friend1 │  │ friend2 │  │ friend3 │              │
│  └────┬────┘  └────┬────┘  └────┬────┘              │
│       │             │             │                   │
│  ┌────▼─────────────▼─────────────▼────┐             │
│  │  Docker bridge network (per-friend)  │             │
│  │  Each friend isolated, own subnet     │             │
│  └────┬─────────────┬─────────────┬────┘             │
│       │             │             │                   │
│  ┌────▼────┐  ┌─────▼───┐  ┌──────▼──────┐            │
│  │ Buzz    │  │ Routstr │  │ CDK Mint    │            │
│  │ relay   │  │ proxy   │  │ (Cashu)     │            │
│  └─────────┘  └─────────┘  └─────────────┘            │
│                                                      │
│  ┌──────────────────────────────────────┐            │
│  │  FIPS daemon (host-level)             │            │
│  │  Peers: Andre, T470, DQ05, friends    │            │
│  │  All services reachable via .fips DNS │            │
│  └──────────────────────────────────────┘            │
└─────────────────────────────────────────────────────┘
         │
         │ FIPS mesh (UDP 2121, TCP 8443)
         │
┌────────▼────────────────────────────────────────────┐
│  Friend's phone/device — also on FIPS mesh           │
│  ┌──────────┐  ┌──────────┐                         │
│  │ Buzz app │  │ FIPS     │                         │
│  │ (client) │  │ daemon   │                         │
│  └──────────┘  └──────────┘                         │
│                                                      │
│  Friend reaches Hermes via:                          │
│  - Buzz relay on mesh (NIP-29 group chat)            │
│  - SSH to container via mesh IPv6                    │
│  - routstr proxy via mesh for LLM calls             │
└─────────────────────────────────────────────────────┘
```

## What FIPS Needs to Figure Out

1. **Container networking + FIPS** — RESOLVED: No per-container FIPS daemon needed. Host-level FIPS daemon + Caddy HTTP-only ingress works. Caddy on VPS2 listens on [::]:80 (reachable via fips0). HTTP-only site blocks route by Host header to local Docker services. Verified working Aug 13 2026.

2. **Per-container mesh identity** — DEFERRED: Not needed for current architecture. All containers share VPS2's mesh identity. When per-friend isolation is needed, each Hermes container can get its own Caddy site block (e.g., `http://friend1-hermes.fips`) pointing to the container's internal port.

3. **Port mapping on mesh** — RESOLVED: Caddy HTTP-only site blocks on VPS2 proxy mesh traffic to Docker services:
   - `http://buzz-relay.fips` → localhost:3007 (Buzz relay)
   - `http://routstr.fips` → localhost:8009 (Routstr proxy)
   - `http://mint.fips` → localhost:8085 (CDK Mint)
   - `http://hermes-mesh.fips` → health check endpoint
   - Add more blocks as Hermes containers are deployed (e.g., `http://friend1-hermes.fips` → localhost:PORT)

4. **DQ05 reconnection**: DQ05 (192.168.2.12) is offline. It has Andre's peer config but FIPS can't start if the machine is down. When it comes back, verify Andre peer connects.

5. **VPS1 recovery**: VPS1 (64.188.7.38) is down. If it stays down, all multi-tenant deployment moves to VPS2. FIPS on VPS2 is already working.

## What's Already Done (Don't Redo)

- FIPS installed on T470, VPS2, DQ05 (v0.4.1 on T470, v0.4.0-dev on VPS2)
- Andre's peer config added to T470 + VPS2 (connected, verified handshake)
- test-us01 removed (Andre's network only)
- FIPS Ansible role in ~/tollgate-infrastructure-kit/ansible/roles/fips/
- fips-dns service documented (needed for .fips DNS resolution)
- FIPS mesh service access configured (Aug 13, 2026):
  - Caddy HTTP-only site blocks added on VPS2 for buzz-relay.fips, routstr.fips, mint.fips, hermes-mesh.fips
  - /etc/fips/hosts entries added on T470 + VPS2 for mesh service hostnames
  - T470 dns-delegate config fixed (127.0.0.1:5354 instead of [::1]:5354)
  - Global drop-in added at /etc/systemd/resolved.conf.d/fips.conf on T470
  - All services verified reachable from T470 via FIPS mesh
- T470 Hermes mesh access configured (Aug 14, 2026):
  - socat IPv6→IPv4 bridges deployed as systemd services (fips-hermes-bridge, fips-hermes-node-bridge)
  - nftables rules added (/etc/fips/fips.d/hermes.nft) allowing inbound TCP 8443, 3001, UDP/TCP 53 on fips0
  - /etc/fips/hosts entries added for dq05-hermes.fips and friend1-hermes.fips pointing to T470 npub
  - Local connectivity verified: ports 8443 and 3001 OPEN on T470 mesh IPv6

## Key Decisions Already Made

- **Andre's network only** — no test mesh peers
- **VPS2 is the active exit/deployment node** (VPS1 down)
- **FIPS v0.4.1** for servers, **ble-v2 branch** for Android
- **Persistent identity** on all nodes (stable npubs for peering)
- **Nostr discovery: configured_only** policy (not open)