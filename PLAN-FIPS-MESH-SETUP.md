# FIPS Mesh Setup Plan

> **Status:** Scoping / Planning Document  
> **Created:** 2026-08-12  
> **Owner:** Felix (c03rad0r)  
> **Repo:** `tollgate-infrastructure-kit` (main branch)  
> **Ansible Role:** `ansible/roles/fips/`  
> **Playbook:** `ansible/playbooks/13-fips.yml`  

This document defines the full scope of work for deploying FIPS mesh networking across all machines so they can SSH into each other over the FIPS overlay. It is a scoping document for kanban worker tasks — not the implementation itself.

> **Related:** [FIPS Ingress Gate](docs/FIPS-INGRESS-GATE.md) — public internet → VPS2 → FIPS mesh (reverse proxy for hosting services from home machines). Inspired by [fr34aky/fips-exit-gate](https://github.com/fr34aky/fips-exit-gate) (outbound exit service).

---

## 0. WHY PRIVATE MESH

The original plan connected all machines to the public FIPS test mesh (test-us01 through test-uk01). This approach has been abandoned in favor of a **private mesh** with only Felix's own devices.

**Problem: Bloom Filter Saturation on Public Mesh**

The public FIPS test mesh has grown to the point where its bloom filters are saturated. FIPS uses bloom filters to track connected peers and route discovery efficiently. When too many nodes join the mesh:

- Bloom filter false-positive rates skyrocket, causing unnecessary connection attempts and wasted bandwidth
- Discovery messages become unreliable — nodes may miss or misinterpret peer advertisements
- The mesh becomes noisy with traffic from unrelated nodes, degrading performance for actual peer-to-peer communication
- Memory and CPU overhead from maintaining large filter state impacts laptops on WiFi

**Mitigation: FIPS v2 (Not Yet Released)**

FIPS v2 is expected to introduce dynamic bloom filter sizing that adapts to mesh size. Until this is released and stable, the public test mesh remains problematic for small groups of nodes.

**Solution: Private Mesh**

We run our own small mesh with only 4 machines (VPS2, DQ05, T14Gen5, T470). With a small node count:

- Bloom filters stay small and accurate (4 nodes vs hundreds)
- No traffic from unrelated nodes
- Full control over peering topology and routing
- VPS2 serves as the hub (public IP, accepts inbound), all laptops peer to it
- Nostr discovery (configured_only policy) still works — machines find each other via relays but only connect to peers in their config
- LAN discovery enabled for same-network machines (DQ05 and T14Gen5 on same WiFi)

---

## 1. Architecture Overview

### 1.1 ASCII Network Diagram

```
                         PRIVATE FIPS MESH (Felix's devices only)
                              ┌──────────────────────────┐
                              │          VPS2 (HUB)      │
                              │       23.182.128.51      │
                              │   UDP:2121  TCP:8443     │
                              │   Public IP — inbound    │
                              │       eth0  Debian       │
                              └───┬──────────┬──────────┬┘
                                  │          │          │
                     ┌────────────┘          │          └────────────┐
                     │                       │                       │
                     ▼                       ▼                       ▼
              ┌──────────┐           ┌──────────┐           ┌──────────┐
              │   DQ05   │◄─ LAN ──►│  T14Gen5 │           │   T470   │
              │ (laptop) │  discovery│ (laptop) │           │ (backup) │
              │  x86_64  │           │  x86_64  │           │  x86_64  │
              │ wlp58s0  │           │ wlp0s20f3│           │ wlp58s0  │
              │  WiFi    │           │  WiFi    │           │  WiFi    │
              └────┬─────┘           └────┬─────┘           └────┬─────┘
                   │                      │                      │
                   └──────────┬───────────┴──────────────────────┘
                              │
                         ┌────┴─────┐
                         │ fips0    │
                         │ TUN IF   │
                         │ MTU 1280 │
                         │ IPv6 LL  │
                         └──────────┘

     ┌──────────────────────────────────────────────────────────┐
     │                  Nostr Discovery Layer                     │
     │                                                          │
     │  Each node advertises its npub + transport addrs to:      │
     │    wss://relay.damus.io                                  │
     │    wss://nos.lol                                         │
     │    wss://offchain.pub                                    │
     │    wss://relay.orangesync.tech                           │
     │    wss://ngit.orangesync.tech                            │
     │                                                          │
     │  App tag: "fips-overlay-v1"  Policy: configured_only      │
     │  → Nodes find each other by npub, establish direct p2p    │
     │  → Only connects to peers in local config (NOT random)    │
     └──────────────────────────────────────────────────────────┘

     ┌──────────────────────────────────────────────────────────┐
     │                  .fips DNS Resolution                     │
     │                                                          │
     │  fips-dns listens on [::1]:5354                          │
     │  systemd-resolved routes *.fips → 127.0.0.1:5354         │
     │  /etc/fips/hosts maps shortnames → npubs                 │
     │  e.g.  ssh dq05.fips  →  fips0 TUN → peer's mesh IPv6    │
     │                                                          │
     │  Host aliases: vps2, dq05, t14gen5, t470                 │
     └──────────────────────────────────────────────────────────┘
```

### 1.2 Machine Identity & Transport Summary

| Machine   | npub (known)                                      | Transport         | Mesh IPv6 | Notes                          |
|-----------|---------------------------------------------------|-------------------|-----------|--------------------------------|
| VPS2 (HUB)| `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82` | UDP + TCP (inbound) | TBD (auto-assigned by fips0) | Public IP 23.182.128.51, accepts inbound on UDP:2121 + TCP:8443 |
| DQ05      | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72` | UDP + Ethernet | TBD (auto-assigned by fips0) | FIPS v0.4.1 installed, config manually edited |
| T14Gen5   | TBD (run `fipsctl show status`)                    | UDP + Ethernet    | TBD       | FIPS v0.4.1 installed, was peering with test-us03 (working). npub discovered after FIPS restarts with new config |
| T470      | TBD                                                | UDP + Ethernet    | TBD       | Backup machine, not yet set up. npub discovered after first FIPS install |

> **Note on npub discovery:** T14Gen5 and T470 npubs are not yet known. FIPS generates a persistent identity on first run — the npub is created and stored in the identity file. After FIPS starts on these machines, run `fipsctl show status` to discover and record their npubs. Then add them to `fips_mesh_hosts` in the Ansible defaults and to `/etc/fips/hosts` on all other machines.

### 1.3 Nostr Discovery

FIPS nodes use Nostr as a discovery layer. Each node publishes a kind 0 (or app-specific) event to configured relay list with:
- `app: "fips-overlay-v1"` tag
- Its own npub and transport addresses (UDP/TCP endpoints)
- STUN-resolved public endpoint for NAT traversal

Other nodes in the mesh subscribe to the same relays with the same app tag and learn peer endpoints. This means any two nodes that both advertise to the same relay set can find and connect to each other without manual IP exchange.

**Policy:** `configured_only` — nodes only discover peers whose npubs appear in their local peer config (or `/etc/fips/hosts`). This prevents random peerings while still using Nostr for endpoint discovery. We do NOT use `open` policy because we don't want to connect to random public mesh nodes.

### 1.4 .fips DNS Resolution

1. `fips-dns` service listens on `[::1]:5354` (DNS-over-UDP)
2. `fips-dns-setup` integrates with `systemd-resolved` to route `*.fips` queries to the fips-dns resolver
3. `fips-dns` reads `/etc/fips/hosts` for name→npub mappings
4. When a query for `dq05.fips` arrives, fips-dns resolves the npub to the peer's mesh IPv6 address on fips0
5. Applications (ssh, curl, etc.) can then connect to `<hostname>.fips` and traffic flows over the FIPS TUN interface

---

## 2. Per-Machine Configuration Table

### 2.1 Machine Inventory

| Field                | DQ05                          | T14Gen5                       | VPS2                          | T470 (Backup)                 |
|----------------------|-------------------------------|-------------------------------|-------------------------------|-------------------------------|
| **Machine name**     | DQ05                          | T14Gen5                       | VPS2                          | T470                          |
| **Hostname**         | c03rad0r-DQ05proplus          | t14gen5                       | vps2                          | t470                          |
| **Public IP**        | N/A (laptop, behind NAT)      | N/A (laptop, behind NAT)      | 23.182.128.51                 | N/A (behind NAT via Netbird)  |
| **Netbird IP**       | 100.90.22.201                 | N/A                           | N/A                           | 100.90.101.9                  |
| **Primary interface**| wlp58s0 (WiFi)                | wlp0s20f3 (WiFi)              | eth0 (VPS NIC)                | wlp58s0 (WiFi)                |
| **Role**             | Laptop (spoke)                | Laptop (spoke)                | VPS (hub, exit node)          | Backup (spoke)                |
| **FIPS version**     | v0.4.1 (installed)            | v0.4.1 (installed)            | v0.4.0-dev (needs upgrade)    | TBD (not yet installed)       |
| **Target version**   | v0.4.1                        | v0.4.1                        | v0.4.1                        | v0.4.1                        |
| **npub**             | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72` | TBD (discover after restart) | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82` | TBD (discover after install) |
| **Mesh IPv6**        | Auto-assigned by fips0         | Auto-assigned by fips0        | Auto-assigned by fips0        | Auto-assigned by fips0        |
| **Peer (private mesh)** | vps2 (23.182.128.51, UDP:2121 + TCP:8443) | vps2 (23.182.128.51, UDP:2121 + TCP:8443) | — (hub, accepts inbound from all laptops) | vps2 (23.182.128.51, UDP:2121 + TCP:8443) |
| **Ethernet iface**   | wlp58s0 (auto-detect or manual)| wlp0s20f3 (set in inventory)  | N/A (VPS, no ethernet transport) | wlp58s0 (auto-detect or manual) |
| **SSH user**         | c03rad0r                      | c03rad0r (local)              | debian                        | c03rad0r                      |
| **Ansible host**     | via Netbird IP or localhost    | localhost (ansible_connection: local) | via VPS2_IP env var           | via Netbird IP or localhost    |

### 2.2 Private Mesh Topology

| Node      | Role | Peers with         | Transport                    |
|-----------|------|--------------------|------------------------------|
| VPS2      | Hub  | (accepts inbound)  | UDP:2121 + TCP:8443 on 23.182.128.51 |
| DQ05      | Spoke| VPS2 (hub)         | UDP + Ethernet (wlp58s0)     |
| T14Gen5   | Spoke| VPS2 (hub)         | UDP + Ethernet (wlp0s20f3)   |
| T470      | Spoke| VPS2 (hub)         | UDP + Ethernet (wlp58s0)     |

> **Hub-and-spoke topology:** All laptops peer to VPS2. VPS2 has a public IP and accepts inbound connections on UDP:2121 and TCP:8443. Laptops behind NAT initiate outbound connections to VPS2. Nostr discovery (configured_only) and LAN discovery allow laptops on the same network to also find and connect to each other directly.

### 2.3 Per-Machine Peer Assignment Rationale

| Machine   | Peers with | Rationale                                                    |
|-----------|------------|--------------------------------------------------------------|
| DQ05      | vps2       | VPS2 is the hub with public IP — all laptops connect to it. NAT traversal via STUN + Nostr discovery |
| T14Gen5   | vps2       | Same as DQ05 — VPS2 is the reliable hub. LAN discovery also connects to DQ05 if on same WiFi |
| VPS2      | (hub)      | Accepts inbound from all laptops. No outbound peer needed — laptops connect to it |
| T470      | vps2       | Same as other laptops — VPS2 hub provides connectivity to all other machines |

### 2.4 Bootstrap Peer (VPS2)

All laptops use VPS2 as their bootstrap peer:

- **npub:** `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`
- **Public IP:** 23.182.128.51
- **UDP transport:** 23.182.128.51:2121
- **TCP transport:** 23.182.128.51:8443
- **Connect policy:** auto_connect

This is configured in `fips_peers` in the Ansible role defaults (`ansible/roles/fips/defaults/main.yml`).

### 2.5 Host Aliases

The following aliases are configured in `/etc/fips/hosts` on all machines:

| Alias     | npub                                                                 |
|-----------|----------------------------------------------------------------------|
| vps2      | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`  |
| dq05      | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72`  |
| t14gen5   | TBD (add after discovering npub via `fipsctl show status`)          |
| t470      | TBD (add after discovering npub via `fipsctl show status`)          |

> T14Gen5 and T470 npubs are added to `fips_mesh_hosts` in the Ansible defaults and to the `fips-hosts.j2` template after their persistent identities are generated on first FIPS run.

---

## 3. Phased Rollout Plan

### Phase 1: Fix DQ05 FIPS Configuration

**Objective:** Repair DQ05's FIPS installation so it matches what the Ansible `fips` role would produce. DQ05 already has FIPS v0.4.1 installed but the config was manually edited, causing drift from the Ansible-managed state. Switch DQ05's peer from the old test mesh node to VPS2 (private mesh hub).

**Prerequisites:**
- DQ05 is reachable via SSH (Netbird IP 100.90.22.201 or localhost)
- FIPS v0.4.1 .deb package is available for amd64
- Ansible inventory has `dq05` defined (currently in `nip29_relays` group; may need a `fips_laptops` group entry)
- Ansible role `fips` exists with correct defaults (v0.4.1, peer=vps2)

**Steps (high-level):**
1. Review current `/etc/fips/fips.yaml` on DQ05 to identify manual edits
2. Back up the current config (snapshot to `/etc/fips/fips.yaml.bak.<timestamp>`)
3. Add `dq05` to the Ansible inventory under a `fips_laptops` group with correct host vars (interface=wlp58s0, peer=vps2)
4. Run the `fips` role against DQ05 (tag: `config`) to deploy the Ansible-managed config with VPS2 as peer
5. Verify FIPS service restarts and connects to VPS2
6. Run verification tasks (tag: `verify`) — peer count, DNS resolution, status

**Quality Gates:**
- [ ] `fipsctl show status` reports npub `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72`
- [ ] `fipsctl show peers` shows at least 1 connected peer (vps2)
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` returns a mesh IPv6
- [ ] `/etc/fips/fips.yaml` matches the template output (no manual drift)
- [ ] `fips` and `fips-dns` systemd services are enabled and active
- [ ] Ansible run is idempotent (no changes on second run with `--check`)

**Worker:** worker-dq05  
**Estimated time:** 1–2 hours

---

### Phase 2: Set Up T14Gen5 FIPS Configuration

**Objective:** Apply the Ansible `fips` role to T14Gen5, formalizing its FIPS setup into an Ansible-managed state. Switch peer from the old test-us03 to VPS2 (private mesh hub).

**Prerequisites:**
- T14Gen5 is reachable (currently `localhost` with `ansible_connection: local` in inventory)
- FIPS v0.4.1 is already installed on T14Gen5
- Inventory entry `t14gen5` exists with `fips_ethernet_interface: wlp0s20f3`
- Confirm T14Gen5's npub by running `fipsctl show status` before Ansible run

**Steps (high-level):**
1. Run `fipsctl show status` on T14Gen5 to discover and record the npub (persistent identity already exists from previous FIPS runs)
2. Add T14Gen5's npub to the machine table in this document and to `/etc/fips/hosts` on other machines (via `fips_mesh_hosts` in Ansible defaults)
3. Ensure `t14gen5` inventory host has correct vars: `fips_ethernet_interface: wlp0s20f3`, peer=vps2
4. Run the `fips` role against T14Gen5 (tag: `config`) — deploys config with VPS2 as peer
5. Verify ethernet transport is active alongside UDP
6. Run verification tasks (tag: `verify`) — confirm peer connection to VPS2

**Quality Gates:**
- [ ] `fipsctl show status` reports a valid npub (recorded in this plan)
- [ ] `fipsctl show peers` shows vps2 connected
- [ ] Ethernet transport shows as active (check `fipsctl show transports` or equivalent)
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` returns a mesh IPv6
- [ ] Ansible run is idempotent

**Worker:** worker-fips  
**Estimated time:** 1 hour

---

### Phase 3: Upgrade VPS2 from v0.4.0-dev to v0.4.1

**Objective:** Upgrade VPS2's FIPS installation from v0.4.0-dev to v0.4.1 while preserving its exit node configuration and ensuring no service interruption. VPS2 is the hub of the private mesh — all laptops depend on it being reachable.

**Prerequisites:**
- VPS2 is reachable via SSH (23.182.128.51, env var `VPS2_IP`)
- FIPS v0.4.1 .deb for amd64 is available at the GitHub releases URL
- VPS2's current exit node config is documented/backed up before upgrade
- VPS2 npub: `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`

**Steps (high-level):**
1. SSH to VPS2 and back up current `/etc/fips/fips.yaml` and any exit node config
2. Document VPS2's current FIPS version and peer status
3. Add `vps2` to a `fips_vps` inventory group with appropriate vars (no outbound peer needed — VPS2 is the hub, accepts inbound; no ethernet transport; external_addr if needed)
4. Run the `fips` role against VPS2 — this will download v0.4.1 .deb, install it (replacing v0.4.0-dev), and deploy the managed config
5. Verify the exit node config is preserved or re-applied via the template
6. Run verification tasks (tag: `verify`) — confirm VPS2 accepts inbound on UDP:2121 and TCP:8443

**Quality Gates:**
- [ ] `fipsctl show status` reports version 0.4.1
- [ ] VPS2 accepts inbound connections on UDP:2121 and TCP:8443
- [ ] Exit node functionality preserved (verify by checking exit routes or `fipsctl show` output)
- [ ] `dig @::1 -p 5354 dq05.fips AAAA +short` returns a mesh IPv6 (after DQ05 connects)
- [ ] `fips` and `fips-dns` systemd services are enabled and active
- [ ] Ansible run is idempotent

**Worker:** worker-admin  
**Estimated time:** 1–2 hours (include rollback window)

---

### Phase 4: Set Up Backup/T470 FIPS Configuration

**Objective:** Install and configure FIPS v0.4.1 on the T470 backup machine, bringing it into the private mesh with VPS2 as its peer (hub).

**Prerequisites:**
- T470 is reachable via SSH (Netbird IP 100.90.101.9 or localhost)
- FIPS v0.4.1 .deb for amd64 is available
- T470 may or may not already have FIPS installed — check first
- T470's npub is unknown — discover via `fipsctl show status` after install (persistent identity generates on first run)

**Steps (high-level):**
1. SSH to T470 and check if FIPS is already installed (`which fipsctl` or `systemctl status fips`)
2. Add `t470` to a `fips_laptops` inventory group with correct vars (interface=wlp58s0 or auto-detect, peer=vps2)
3. Run the `fips` role against T470 (full run: install + config + verify)
4. After FIPS starts, run `fipsctl show status` to discover T470's npub (persistent identity generated on first run)
5. Record T470's npub in this plan and add it to `fips_mesh_hosts` in Ansible defaults and `/etc/fips/hosts` on all other machines
6. Run verification tasks (tag: `verify`) — confirm peer connection to VPS2

**Quality Gates:**
- [ ] `fipsctl show status` reports version 0.4.1 and a valid npub (recorded)
- [ ] `fipsctl show peers` shows at least 1 connected peer (vps2)
- [ ] Ethernet transport active (if WiFi interface available)
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` returns a mesh IPv6
- [ ] `fips` and `fips-dns` systemd services enabled and active
- [ ] Ansible run is idempotent

**Worker:** worker-fips  
**Estimated time:** 1–2 hours

---

### Phase 5: Add Machines to Each Other's Host Aliases & Nostr Discovery

**Objective:** With all four machines on FIPS v0.4.1 and connected to VPS2 (hub), add each machine's npub to every other machine's `/etc/fips/hosts` and enable Nostr discovery so machines can find and connect to each other directly (not just through VPS2).

**Prerequisites:**
- All four machines have FIPS v0.4.1 running with VPS2 as peer (Phases 1–4 complete)
- All four machines' npubs are known and recorded
- The `fips` role template already has Nostr discovery enabled (`discovery.nostr.enabled: true`, `policy: configured_only`)
- The `fips-hosts.j2` template uses `fips_mesh_hosts` dict for mesh-wide aliases

**Steps (high-level):**
1. Compile the full list of machine npubs:
   - VPS2: `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`
   - DQ05: `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72`
   - T14Gen5: (from Phase 2 — discovered via `fipsctl show status`)
   - T470: (from Phase 4 — discovered via `fipsctl show status`)
2. Update `fips_mesh_hosts` in `ansible/roles/fips/defaults/main.yml` to include all 4 machine shortname→npub mappings
3. Update `/etc/fips/hosts` on each machine via the `fips-hosts.j2` template to include aliases for all 4 machines (vps2, dq05, t14gen5, t470)
4. Run the `fips` role against all machines (tag: `config`) to deploy updated host aliases
5. Wait for Nostr discovery to propagate — machines should find each other via Nostr relays (configured_only policy means they only connect to npubs in their config/hosts)
6. Verify cross-machine peering: each machine should see the other 3 machines as peers (in addition to or instead of just VPS2)
7. Verify LAN discovery: DQ05 and T14Gen5 on the same WiFi should discover each other directly

**Quality Gates:**
- [ ] All machines have `discovery.nostr.enabled: true` with `policy: configured_only` in their config
- [ ] `fipsctl show peers` on each machine shows 3+ connected peers (the other 3 machines)
- [ ] `/etc/fips/hosts` on each machine contains aliases for all 4 machines (vps2, dq05, t14gen5, t470)
- [ ] `dig @::1 -p 5354 dq05.fips AAAA +short` works from every machine
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` works from every machine
- [ ] `dig @::1 -p 5354 t14gen5.fips AAAA +short` works from every machine
- [ ] `dig @::1 -p 5354 t470.fips AAAA +short` works from every machine
- [ ] Nostr relay advertising confirmed (check relay for app tag `fips-overlay-v1`)
- [ ] LAN discovery: DQ05 and T14Gen5 see each other directly (not just via VPS2 relay)

**Worker:** worker-fips  
**Estimated time:** 1–2 hours

---

### Phase 6: End-to-End SSH-over-FIPS Verification

**Objective:** Verify that SSH works bidirectionally between every pair of machines over the FIPS mesh, using `<shortname>.fips` hostnames.

**Prerequisites:**
- All four machines are peered (Phase 5 complete)
- `*.fips` DNS resolves on all machines
- SSH is installed and configured on all machines
- fips-firewall allows SSH on fips0 (the `ssh.nft` rule is deployed)
- SSH keys are distributed or password auth works between machines

**Steps (high-level):**
1. Ensure the `ssh.nft` firewall rule is deployed on all machines (tag: `config` already handles this)
2. From each machine, attempt SSH to every other machine via `.fips` hostname:
   - `ssh c03rad0r@dq05.fips`
   - `ssh c03rad0r@t14gen5.fips`
   - `ssh debian@vps2.fips`
   - `ssh c03rad0r@t470.fips`
3. Record success/failure for each pair (4×3 = 12 directional pairs)
4. For any failures, debug: DNS resolution, peer connectivity, firewall rules, SSH config
5. Optionally configure `~/.ssh/config` with `Host *.fips` entries for convenience
6. Run the full Ansible verification playbook (tag: `verify`) against all machines

**Quality Gates:**
- [ ] All 12 directional SSH pairs succeed (DQ05→T14Gen5, T14Gen5→DQ05, DQ05→VPS2, VPS2→DQ05, etc.)
- [ ] SSH connection uses the fips0 TUN interface (verify with `ss -tn` showing fips0 source)
- [ ] No SSH connection falls back to non-FIPS transport
- [ ] Ansible verification playbook passes on all hosts
- [ ] Latency between machines is reasonable (<500ms for cross-continent, <50ms for LAN)

**Worker:** worker-admin  
**Estimated time:** 1–2 hours

---

## 4. Verification Checklist

This is the master checklist to confirm the entire private FIPS mesh is operational:

- [ ] Each machine has FIPS v0.4.1 running (`fipsctl show status` on each)
- [ ] Each machine has 1+ connected peer (`fipsctl show peers` on each)
- [ ] VPS2 accepts inbound connections on UDP:2121 and TCP:8443
- [ ] `ping vps2.fips` works from each laptop (DQ05, T14Gen5, T470)
- [ ] `ping dq05.fips` works from T14Gen5 (LAN discovery)
- [ ] .fips DNS resolves on each machine (`dig @::1 -p 5354 vps2.fips AAAA +short` returns IPv6)
- [ ] SSH works from each machine to every other machine via .fips (12 directional pairs)
- [ ] Nostr discovery advertising on all nodes (check relay for `fips-overlay-v1` app tag events)
- [ ] Nostr discovery policy is `configured_only` (NOT `open`) on all nodes
- [ ] Ethernet/LAN transport active on all laptops (DQ05, T14Gen5, T470 — not VPS2)
- [ ] fips-dns service enabled on all nodes (`systemctl is-enabled fips-dns` → enabled)
- [ ] Host aliases configured in `/etc/fips/hosts` on all nodes (vps2, dq05, t14gen5, t470 present)
- [ ] No public test mesh nodes (test-usXX) remain in any config or hosts file
- [ ] Ansible playbook runs idempotently on all hosts (`ansible-playbook --check` shows no changes)
- [ ] VPS2 exit node functionality preserved after upgrade

---

## 5. Worker Task Breakdown

Each task is designed as a kanban card suitable for assignment to a worker profile.

### TASK-FIPS-01: Fix DQ05 FIPS config drift

| Field              | Value |
|--------------------|-------|
| **Title**          | Fix DQ05 FIPS config to match Ansible role output (private mesh, VPS2 peer) |
| **Phase**          | 1 |
| **Worker**         | worker-dq05 |
| **Description**    | DQ05 has FIPS v0.4.1 installed but `/etc/fips/fips.yaml` was manually edited. Run the Ansible `fips` role against DQ05 to deploy the managed config with VPS2 as peer (replacing old test-us03 peer). Back up the old config first. |
| **Acceptance criteria** | `fipsctl show status` shows correct npub; `fipsctl show peers` shows vps2 connected; `/etc/fips/fips.yaml` matches template; services enabled and active |
| **Quality gates**  | TDD: verify role is idempotent (second run with `--check` shows no changes); tests: Ansible `--check` passes; docs: update PROGRESS.md; atomic commit; push to origin |

### TASK-FIPS-02: Add DQ05 to fips_laptops inventory group

| Field              | Value |
|--------------------|-------|
| **Title**          | Add DQ05 to fips_laptops Ansible inventory group |
| **Phase**          | 1 |
| **Worker**         | worker-dq05 |
| **Description**    | DQ05 is currently only in `nip29_relays` group. Create a `fips_laptops` group and add DQ05 with correct host vars: `fips_ethernet_interface: wlp58s0`, peer=vps2, `ansible_user: c03rad0r`. |
| **Acceptance criteria** | `ansible-inventory --graph` shows DQ05 in `fips_laptops`; `ansible -m ping dq05` succeeds |
| **Quality gates**  | TDD: inventory syntax check passes; tests: `ansible-inventory --list` is valid JSON; docs: update this plan; atomic commit; push |

### TASK-FIPS-03: Apply Ansible fips role to T14Gen5

| Field              | Value |
|--------------------|-------|
| **Title**          | Apply Ansible fips role to T14Gen5 and record npub |
| **Phase**          | 2 |
| **Worker**         | worker-fips |
| **Description**    | T14Gen5 has FIPS v0.4.1 with a previously working test-us03 peer (UDP). Run the Ansible `fips` role to formalize the config with VPS2 as peer (replacing test-us03). Discover and record the npub via `fipsctl show status`. Ensure ethernet transport is enabled on wlp0s20f3. |
| **Acceptance criteria** | npub recorded in this plan; `fipsctl show peers` shows vps2; ethernet transport active; DNS resolves; idempotent |
| **Quality gates**  | TDD: role idempotency check; tests: `--check` passes; docs: update machine table with npub; atomic commit; push |

### TASK-FIPS-04: Upgrade VPS2 FIPS to v0.4.1

| Field              | Value |
|--------------------|-------|
| **Title**          | Upgrade VPS2 from FIPS v0.4.0-dev to v0.4.1 preserving exit node config |
| **Phase**          | 3 |
| **Worker**         | worker-admin |
| **Description**    | VPS2 runs FIPS v0.4.0-dev as an exit node and is the hub of our private mesh. Back up config, run the `fips` role to install v0.4.1 .deb and deploy managed config. Verify exit node functionality and inbound connectivity (UDP:2121, TCP:8443) survive the upgrade. Add VPS2 to `fips_vps` inventory group. |
| **Acceptance criteria** | `fipsctl show status` reports v0.4.1; exit node routing works; accepts inbound on UDP:2121 and TCP:8443; DNS resolves; idempotent |
| **Quality gates**  | TDD: role idempotency; tests: `--check` passes; docs: update PROGRESS.md with upgrade notes; atomic commit; push |

### TASK-FIPS-05: Install FIPS on T470 backup machine

| Field              | Value |
|--------------------|-------|
| **Title**          | Install and configure FIPS v0.4.1 on T470 |
| **Phase**          | 4 |
| **Worker**         | worker-fips |
| **Description**    | T470 is the backup machine, reachable via SSH. Check if FIPS is installed. Run the `fips` role to install v0.4.1 and configure with VPS2 as peer. Discover and record the npub (persistent identity generated on first run). Add T470 to `fips_laptops` inventory group. |
| **Acceptance criteria** | `fipsctl show status` reports v0.4.1 and valid npub; peer connected (vps2); DNS resolves; services enabled; idempotent |
| **Quality gates**  | TDD: role idempotency; tests: `--check` passes; docs: update machine table with npub; atomic commit; push |

### TASK-FIPS-06: Add host aliases and enable Nostr discovery on all nodes

| Field              | Value |
|--------------------|-------|
| **Title**          | Deploy complete host aliases and enable cross-machine Nostr discovery |
| **Phase**          | 5 |
| **Worker**         | worker-fips |
| **Description**    | With all machines on FIPS v0.4.1 and npubs known, update `fips_mesh_hosts` in Ansible defaults to include all 4 machine shortname→npub mappings (vps2, dq05, t14gen5, t470). Deploy `/etc/fips/hosts` via the `fips-hosts.j2` template to all nodes. Verify cross-discovery works via Nostr (configured_only policy) and LAN discovery. |
| **Acceptance criteria** | Each machine shows 3+ peers in `fipsctl show peers`; `/etc/fips/hosts` has all 4 machine aliases on every node; `dig @::1 -p 5354 <machine>.fips` works from every machine |
| **Quality gates**  | TDD: verify cross-peering with assertion tasks; tests: Ansible verify tag passes; docs: update this plan with discovered mesh IPv6 addresses; atomic commit; push |

### TASK-FIPS-07: Verify host aliases and Nostr discovery on all nodes

| Field              | Value |
|--------------------|-------|
| **Title**          | Verify /etc/fips/hosts and Nostr discovery are working on all 4 nodes |
| **Phase**          | 5 |
| **Worker**         | worker-fips |
| **Description**    | After deploying host aliases via the `fips-hosts.j2` template, verify that all 4 machine shortnames (vps2, dq05, t14gen5, t470) resolve correctly on every machine. Confirm Nostr discovery (configured_only) is finding peers via relays, and LAN discovery connects DQ05 and T14Gen5 directly. |
| **Acceptance criteria** | `cat /etc/fips/hosts` on every machine shows all 4 machine aliases; `dig @::1 -p 5354 dq05.fips` works from every machine; `ping vps2.fips` works from each laptop; `ping dq05.fips` works from T14Gen5 |
| **Quality gates**  | TDD: template renders correctly; tests: DNS queries for all 4 shortnames succeed; docs: update verification checklist; atomic commit; push |

### TASK-FIPS-08: End-to-end SSH-over-FIPS verification

| Field              | Value |
|--------------------|-------|
| **Title**          | Verify SSH-over-FIPS works bidirectionally between all machine pairs |
| **Phase**          | 6 |
| **Worker**         | worker-admin |
| **Description**    | From each of the 4 machines, SSH to every other machine via `<shortname>.fips`. Record results for all 12 directional pairs. Debug any failures (DNS, firewall, peer, SSH key issues). Configure `~/.ssh/config` with `Host *.fips` entries if needed. |
| **Acceptance criteria** | All 12 directional SSH pairs succeed; connections route through fips0; no fallback to non-FIPS transport; Ansible verify tag passes on all hosts |
| **Quality gates**  | TDD: create Ansible assertion task for SSH-over-FIPS; tests: verify tag passes; docs: fill in verification checklist in this plan; atomic commit; push |

### TASK-FIPS-09: Create unified FIPS mesh Ansible playbook

| Field              | Value |
|--------------------|-------|
| **Title**          | Create playbook to deploy and verify the entire private FIPS mesh |
| **Phase**          | All (supporting) |
| **Worker**         | worker-admin |
| **Description**    | Create or update `ansible/playbooks/13-fips.yml` to target `fips_all` group, with tags for selective execution (install, config, verify). Include pre-tasks for backup, post-tasks for verification. |
| **Acceptance criteria** | `ansible-playbook 13-fips.yml --tags install` installs FIPS on all hosts; `--tags config` deploys config; `--tags verify` runs all checks; playbook is idempotent |
| **Quality gates**  | TDD: playbook syntax check; tests: `--check` passes on all hosts; docs: update this plan's Ansible section; atomic commit; push |

---

## 6. Ansible Playbook Structure

### 6.1 Playbook: `ansible/playbooks/13-fips.yml`

The existing playbook (`13-fips.yml`) targets `all` hosts with the `fips` role. It should be updated to target the `fips_all` group and support tagged execution.

```yaml
---
- name: Deploy and verify private FIPS mesh
  hosts: fips_all
  serial: 1
  become: yes
  gather_facts: yes
  ignore_unreachable: true
  roles:
    - role: fips
      tags: [install, config, verify]
```

### 6.2 Inventory Groups

The inventory (`ansible/inventory/hosts.yml`) should be updated with three new groups:

```yaml
# Add to hosts.yml children section:
  children:
    fips_laptops:
      hosts:
        dq05:
          ansible_host: "{{ lookup('env', 'DQ05_NETBIRD_IP') | default('100.90.22.201', true) }}"
          ansible_user: c03rad0r
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
          ansible_python_interpreter: /usr/bin/python3
          ansible_ssh_common_args: "-o StrictHostKeyChecking=no -o ConnectTimeout=15"
          fips_ethernet_interface: wlp58s0
        t14gen5:
          ansible_host: localhost
          ansible_connection: local
          ansible_user: c03rad0r
          ansible_python_interpreter: /usr/bin/python3
          fips_ethernet_interface: wlp0s20f3
        t470:
          ansible_host: "{{ lookup('env', 'T470_NETBIRD_IP') | default('100.90.101.9', true) }}"
          ansible_user: c03rad0r
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
          ansible_python_interpreter: /usr/bin/python3
          ansible_ssh_common_args: "-o StrictHostKeyChecking=no -o ConnectTimeout=15"
          fips_ethernet_interface: wlp58s0

    fips_vps:
      hosts:
        vps2:
          ansible_host: "{{ lookup('env', 'VPS2_IP') }}"
          ansible_user: "{{ lookup('env', 'VPS2_USER') | default('debian', true) }}"
          ansible_ssh_private_key_file: ~/.ssh/id_ed25519
          ansible_python_interpreter: /usr/bin/python3
          ansible_ssh_common_args: "-o StrictHostKeyChecking=no -o ConnectTimeout=15"
          ansible_become_password: "{{ lookup('env', 'VPS2_PASSWORD') | default('', true) }}"
          fips_ethernet_interface: ""
          fips_external_addr: "{{ lookup('env', 'VPS2_IP') }}:2121"

    fips_all:
      children:
        fips_laptops:
        fips_vps:
```

### 6.3 Variables Per Host Group

#### Group: `fips_laptops` (DQ05, T14Gen5, T470)

| Variable                  | Value                                      | Notes                         |
|---------------------------|--------------------------------------------|-------------------------------|
| `fips_version`             | `"0.4.1"`                                  | From role defaults            |
| `fips_lan_discovery`       | `true`                                     | LAN/ethernet discovery on     |
| `fips_ethernet_interface`  | Per-host (wlp58s0, wlp0s20f3, wlp58s0)     | Set in inventory              |
| `fips_peers`               | vps2 (UDP:2121 + TCP:8443, 23.182.128.51)  | From role defaults — hub peer |
| `fips_advertise_relays`    | damus, nos.lol, offchain, orangesync, ngit | From role defaults            |
| `fips_dm_relays`           | Same as advertise                           | From role defaults            |
| `fips_mesh_ssh_port`       | `22`                                        | SSH over FIPS                 |
| `fips_mesh_hosts`          | All machine shortnames → npubs             | From role defaults            |
| `fips_extra_hosts`         | (empty by default)                          | Per-host overrides if needed  |

#### Group: `fips_vps` (VPS2)

| Variable                  | Value                                      | Notes                         |
|---------------------------|--------------------------------------------|-------------------------------|
| `fips_version`             | `"0.4.1"`                                  | Upgrade from 0.4.0-dev       |
| `fips_lan_discovery`       | `false`                                    | VPS has no ethernet transport |
| `fips_ethernet_interface`  | `""` (empty)                               | No ethernet transport on VPS  |
| `fips_external_addr`        | `"<VPS2_IP>:2121"`                          | Advertise public endpoint     |
| `fips_peers`               | (empty — VPS2 is hub, accepts inbound)     | No outbound peer needed       |
| `fips_advertise_relays`    | Same as laptops                            | From role defaults            |

#### Group: `fips_all`

| Variable                  | Value                                      | Notes                         |
|---------------------------|--------------------------------------------|-------------------------------|
| `fips_version`             | `"0.4.1"`                                  | All machines on same version  |
| `fips_stun_servers`        | Google, Cloudflare, Twilio STUN            | For NAT traversal             |
| `fips_mesh_ssh_port`       | `22`                                        | SSH over FIPS                 |

### 6.4 Tags for Selective Execution

The `fips` role tasks should be tagged to allow selective execution:

| Tag       | Tasks                                                        | Use case                           |
|-----------|--------------------------------------------------------------|------------------------------------|
| `install` | Download .deb, install package, ensure fips group, add user  | Install or upgrade FIPS            |
| `config`  | Deploy fips.yaml, deploy /etc/fips/hosts, deploy ssh.nft     | Apply config changes only          |
| `verify`  | Wait for socket, check peers, check status, check DNS       | Verify mesh health without changes |
| `dns`     | Enable fips-dns, run fips-dns-setup, restart resolved        | DNS-specific operations            |
| `firewall`| Deploy ssh.nft, reload nftables                              | Firewall-specific operations        |

**Usage examples:**
```bash
# Full deploy (all tags)
ansible-playbook 13-fips.yml

# Install only
ansible-playbook 13-fips.yml --tags install

# Config only (after install)
ansible-playbook 13-fips.yml --tags config

# Verify only (read-only checks)
ansible-playbook 13-fips.yml --tags verify

# DNS setup only
ansible-playbook 13-fips.yml --tags dns

# Single machine
ansible-playbook 13-fips.yml --tags config -l dq05
```

### 6.5 Role Task Tagging Plan

The existing `fips` role tasks need tag annotations added:

| Task                                | Tags              |
|-------------------------------------|-------------------|
| Set deb architecture                | (always)          |
| Download FIPS deb package           | install           |
| Install FIPS deb package            | install           |
| Ensure fips group exists            | install           |
| Add ansible_user to fips group      | install           |
| Create /etc/fips directory          | config            |
| Auto-detect ethernet/wifi interface | config            |
| Deploy fips.yaml config             | config            |
| Deploy /etc/fips/hosts             | config            |
| Create /etc/fips/fips.d directory   | config            |
| Deploy SSH firewall rule            | config, firewall  |
| Enable and start fips               | install, config   |
| Enable and start fips-dns           | dns               |
| Run fips-dns-setup                  | dns               |
| Enable and start fips-firewall      | firewall          |
| Wait for FIPS to initialize         | verify            |
| Verify peer connectivity            | verify            |
| Check peer count                    | verify            |
| Show FIPS status                    | verify            |
| Verify .fips DNS resolution         | verify, dns       |

---

## Appendix A: Risk & Rollback Notes

- **VPS2 upgrade risk:** If the v0.4.0-dev → v0.4.1 upgrade breaks the exit node or inbound connectivity, roll back by reinstalling the old .deb and restoring `/etc/fips/fips.yaml.bak`. Keep a backup of the .deb file. Since VPS2 is the hub, all laptops lose mesh connectivity if VPS2 is down.
- **Config drift on DQ05:** If Ansible-managed config breaks something that the manual config had, compare diffs before restarting FIPS. Use `--check` mode first.
- **Nostr relay availability:** If a configured relay is down, discovery may be delayed. All machines advertise to 5 relays for redundancy.
- **VPS1 offline:** VPS1 (66.92.204.38) has been offline since July 20 and is excluded from this plan. If it comes back online, it can be added to `fips_vps` and configured in a follow-up.
- **Bloom filter saturation (public mesh):** The public FIPS test mesh has saturated bloom filters due to too many nodes. This is why we run a private mesh. If FIPS v2 with dynamic bloom filter sizing is released, we may reconsider joining the public mesh. See section 0 ("WHY PRIVATE MESH") for details.

## Appendix B: Machine SSH User Reference

| Machine   | SSH user   | SSH key                | Connection method          |
|-----------|------------|------------------------|----------------------------|
| DQ05      | c03rad0r   | ~/.ssh/id_ed25519      | Netbird IP or localhost     |
| T14Gen5   | c03rad0r   | ~/.ssh/id_ed25519      | localhost (local)           |
| VPS2      | debian     | ~/.ssh/id_ed25519      | VPS2_IP (public)            |
| T470      | c03rad0r   | ~/.ssh/id_ed25519      | Netbird IP or localhost     |

## Appendix C: References

- FIPS releases: `https://github.com/jmcorgan/fips/releases`
- Private mesh hub: VPS2 (23.182.128.51) — npub `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`
- Ansible role: `ansible/roles/fips/`
- Ansible playbook: `ansible/playbooks/13-fips.yml`
- Ansible inventory: `ansible/inventory/hosts.yml`
- Group vars: `ansible/inventory/group_vars/all.yml`
- AGENTS.md conventions: commit discipline, testing, no secrets in git