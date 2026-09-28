# FIPS Private Mesh — Roadmap

> **Created:** 2026-08-12  
> **Owner:** Felix (c03rad0r)  
> **Repo:** `tollgate-infrastructure-kit`

## Overview

Deploy a private FIPS mesh across 4 machines (VPS2, DQ05, T14Gen5, T470) for device-to-device SSH connectivity over an IPv6 overlay. VPS2 serves as the hub with a public IP; all laptops peer to it. See [ADRs](docs/adr/) for architectural decisions.

## Machine Inventory

| Machine | Role | FIPS Version | npub | Status |
|---------|------|-------------|------|--------|
| VPS2 | Hub + exit node | v0.4.0-dev → v0.4.1 | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82` | Needs upgrade |
| DQ05 | Laptop (spoke) | v0.4.1 | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72` | Config drift |
| T14Gen5 | Laptop (spoke) | v0.4.1 | `npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh` | Config needs Ansible |
| T470 | Backup (spoke) | Not installed | TBD (discover after install) | Pending |

## Phases

### Phase 0: Foundation (DONE)

- [x] FIPS v0.4.1 installed on DQ05
- [x] FIPS v0.4.1 installed on T14Gen5
- [x] VPS2 running FIPS v0.4.0-dev as exit node
- [x] Ansible role created (`ansible/roles/fips/`)
- [x] T14Gen5 npub discovered: `npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh`
- [x] T14Gen5 mesh IPv6: `fd79:f451:67b1:8084:2b2a:5b1e:9110:26d0`

### Phase 1: Fix DQ05 Config Drift

- [ ] Back up DQ05's manually-edited `/etc/fips/fips.yaml`
- [ ] Add DQ05 to `fips_laptops` Ansible inventory group
- [ ] Run Ansible `fips` role against DQ05 (tag: `config`) — VPS2 as peer
- [ ] Verify: npub correct, vps2 peer connected, DNS resolves, idempotent

**Tasks:** FIPS-01, FIPS-02  
**Worker:** worker-dq05  
**Estimate:** 1–2 hours

### Phase 2: Apply Ansible Role to T14Gen5

- [ ] Run `fipsctl show status` on T14Gen5 to confirm npub
- [ ] Ensure T14Gen5 inventory vars correct (`fips_ethernet_interface: wlp0s20f3`)
- [ ] Run Ansible `fips` role against T14Gen5 (tag: `config`) — VPS2 as peer
- [ ] Verify: vps2 peer connected, ethernet transport active, DNS resolves, idempotent

**Task:** FIPS-03  
**Worker:** worker-fips  
**Estimate:** 1 hour

### Phase 3: Upgrade VPS2 to v0.4.1

- [ ] Back up VPS2's current `/etc/fips/fips.yaml` and exit node config
- [ ] Add VPS2 to `fips_vps` inventory group
- [ ] Run Ansible `fips` role against VPS2 — installs v0.4.1 .deb, deploys managed config
- [ ] Verify: version 0.4.1, exit node preserved, accepts inbound UDP:2121 + TCP:8443, idempotent

**Task:** FIPS-04  
**Worker:** worker-admin  
**Estimate:** 1–2 hours (include rollback window)

### Phase 4: Install FIPS on T470

- [ ] Check if FIPS is already installed on T470
- [ ] Add T470 to `fips_laptops` inventory group
- [ ] Run Ansible `fips` role (full: install + config + verify) — VPS2 as peer
- [ ] Run `fipsctl show status` to discover and record T470's npub
- [ ] Verify: v0.4.1, peer connected, DNS resolves, services enabled, idempotent

**Task:** FIPS-05  
**Worker:** worker-fips  
**Estimate:** 1–2 hours

### Phase 5: Two-Pass — Deploy Host Aliases + Cross-Discovery

- [ ] Update `fips_mesh_hosts` in Ansible defaults with all 4 machine npubs
- [ ] Deploy `/etc/fips/hosts` to all nodes via `fips-hosts.j2` template
- [ ] Run Ansible `fips` role against all machines (tag: `config`)
- [ ] Wait for Nostr discovery to propagate (configured_only policy)
- [ ] Verify cross-machine peering: each machine sees 3+ peers
- [ ] Verify LAN discovery: DQ05 and T14Gen5 connect directly on same WiFi
- [ ] Verify `.fips` DNS resolves all 4 shortnames from every machine

**Tasks:** FIPS-06, FIPS-07  
**Worker:** worker-fips  
**Estimate:** 1–2 hours

### Phase 6: End-to-End SSH-over-FIPS Verification

- [ ] Ensure `ssh.nft` firewall rule deployed on all machines
- [ ] Test all 12 directional SSH pairs (4 machines × 3 targets)
- [ ] Verify connections route through `fips0` (not fallback to non-FIPS)
- [ ] Configure `~/.ssh/config` with `Host *.fips` entries
- [ ] Run full Ansible verification playbook (tag: `verify`)
- [ ] Document any failures with root cause

**Task:** FIPS-08  
**Worker:** worker-admin  
**Estimate:** 1–2 hours

### Phase 7 (FUTURE): FIPS Ingress Gate

- [ ] Configure Caddy `reverse_proxy` on VPS2 to forward to FIPS mesh IPv6 addresses
- [ ] Set up SSH `ProxyJump` through VPS2 for external access to home machines
- [ ] Configure TCP services via Caddy layer4 or nftables DNAT
- [ ] PoC verified 2026-08-12 — productionize

**Related:** [FIPS Ingress Gate](docs/FIPS-INGRESS-GATE.md)  
**Estimate:** TBD

### Phase 8 (FUTURE): FIPS v2 Upgrade

- [ ] Wait for FIPS v2 release with dynamic bloom filter sizing
- [ ] Test v2 in staging before fleet upgrade
- [ ] Consider rejoining public mesh if bloom filter issue is resolved
- [ ] Evaluate Nym mixnet integration

**Estimate:** TBD (dependent on upstream release)

### Phase 9 (FUTURE): Android FIPS Client

- [ ] Track ble-v2 branch for Android/BLE support
- [ ] Test Android FIPS client connecting to private mesh
- [ ] Add Android device to mesh inventory if viable

**Estimate:** TBD (dependent on upstream ble-v2 branch)

## Milestone Summary

| Milestone | Phases | Target | Status |
|-----------|--------|--------|--------|
| Foundation | 0 | 2026-08-12 | ✅ Done |
| DQ05 repaired | 1 | 2026-08-13 | Pending |
| T14Gen5 in Ansible | 2 | 2026-08-13 | Pending |
| VPS2 upgraded | 3 | 2026-08-14 | Pending |
| T470 in mesh | 4 | 2026-08-15 | Pending |
| Full mesh peering | 5 | 2026-08-16 | Pending |
| SSH verification | 6 | 2026-08-16 | Pending |
| Ingress gate | 7 | TBD | Future |
| FIPS v2 | 8 | TBD | Future |
| Android client | 9 | TBD | Future |

## References

- [FIPS Mesh Setup Plan](PLAN-FIPS-MESH-SETUP.md) — detailed deployment plan
- [FIPS Mesh Deployment Plan](docs/FIPS-MESH-DEPLOYMENT-PLAN.md) — implementation task graph
- [Kanban Tasks](docs/FIPS-MESH-KANBAN-TASKS.md) — kanban-ready task cards
- [ADRs](docs/adr/) — architecture decision records
- [FIPS Ingress Gate](docs/FIPS-INGRESS-GATE.md) — reverse proxy plan for home hosting