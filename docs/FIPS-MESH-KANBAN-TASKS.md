# FIPS Mesh Kanban Tasks

> **Board:** `fips-mesh-deploy`  
> **Created:** 2026-08-12  
> **Source:** [PLAN-FIPS-MESH-SETUP.md](../../PLAN-FIPS-MESH-SETUP.md)

Each task below is structured as a kanban card. Copy the task block into your kanban board tool of choice.

---

## FIPS-01: Fix DQ05 FIPS config drift

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-01 |
| **Title** | Fix DQ05 FIPS config to match Ansible role output (private mesh, VPS2 peer) |
| **Phase** | 1 |
| **Worker** | worker-dq05 |
| **Description** | DQ05 has FIPS v0.4.1 installed but `/etc/fips/fips.yaml` was manually edited, causing config drift. Run the Ansible `fips` role against DQ05 to deploy the managed config with VPS2 as peer (replacing old test-us03 peer). Back up the old config first. |
| **Dependencies** | None |
| **Estimated time** | 1–2 hours |

### Acceptance Criteria

- [ ] `fipsctl show status` reports npub `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72`
- [ ] `fipsctl show peers` shows at least 1 connected peer (vps2)
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` returns a mesh IPv6
- [ ] `/etc/fips/fips.yaml` matches the template output (no manual drift)
- [ ] `fips` and `fips-dns` systemd services are enabled and active
- [ ] Ansible run is idempotent (no changes on second run with `--check`)

---

## FIPS-02: Add DQ05 to fips_laptops inventory group

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-02 |
| **Title** | Add DQ05 to fips_laptops Ansible inventory group |
| **Phase** | 1 |
| **Worker** | worker-dq05 |
| **Description** | DQ05 is currently only in the `nip29_relays` group. Create a `fips_laptops` group and add DQ05 with correct host vars: `fips_ethernet_interface: wlp58s0`, peer=vps2, `ansible_user: c03rad0r`. |
| **Dependencies** | None |
| **Estimated time** | 30 minutes |

### Acceptance Criteria

- [ ] `ansible-inventory --graph` shows DQ05 in `fips_laptops`
- [ ] `ansible -m ping dq05` succeeds
- [ ] `ansible-inventory --list` produces valid JSON
- [ ] Inventory syntax check passes

---

## FIPS-03: Apply Ansible fips role to T14Gen5

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-03 |
| **Title** | Apply Ansible fips role to T14Gen5 and confirm npub |
| **Phase** | 2 |
| **Worker** | worker-fips |
| **Description** | T14Gen5 has FIPS v0.4.1 with a previously working test-us03 peer (UDP). Run the Ansible `fips` role to formalize the config with VPS2 as peer (replacing test-us03). Confirm the npub via `fipsctl show status`. Ensure ethernet transport is enabled on wlp0s20f3. |
| **Dependencies** | FIPS-01 (DQ05 config fixed — validates role works for laptops) |
| **Estimated time** | 1 hour |

### Acceptance Criteria

- [ ] `fipsctl show status` reports npub `npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh`
- [ ] `fipsctl show peers` shows vps2 connected
- [ ] Ethernet transport shows as active on wlp0s20f3
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` returns a mesh IPv6
- [ ] Ansible run is idempotent (no changes on second run with `--check`)

---

## FIPS-04: Upgrade VPS2 FIPS to v0.4.1

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-04 |
| **Title** | Upgrade VPS2 from FIPS v0.4.0-dev to v0.4.1 preserving exit node config |
| **Phase** | 3 |
| **Worker** | worker-admin |
| **Description** | VPS2 runs FIPS v0.4.0-dev as an exit node and is the hub of the private mesh. Back up config, run the `fips` role to install v0.4.1 .deb and deploy managed config. Verify exit node functionality and inbound connectivity (UDP:2121, TCP:8443) survive the upgrade. Add VPS2 to `fips_vps` inventory group. |
| **Dependencies** | FIPS-01, FIPS-02 (role validated on laptops first) |
| **Estimated time** | 1–2 hours (include rollback window) |

### Acceptance Criteria

- [ ] `fipsctl show status` reports version 0.4.1
- [ ] VPS2 accepts inbound connections on UDP:2121 and TCP:8443
- [ ] Exit node functionality preserved (verify exit routes or `fipsctl show` output)
- [ ] `dig @::1 -p 5354 dq05.fips AAAA +short` returns a mesh IPv6 (after DQ05 connects)
- [ ] `fips` and `fips-dns` systemd services are enabled and active
- [ ] Ansible run is idempotent (no changes on second run with `--check`)

---

## FIPS-05: Install FIPS on T470

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-05 |
| **Title** | Install and configure FIPS v0.4.1 on T470 backup machine |
| **Phase** | 4 |
| **Worker** | worker-fips |
| **Description** | T470 is the backup machine, reachable via SSH (Netbird IP 100.90.101.9). Check if FIPS is installed. Run the `fips` role to install v0.4.1 and configure with VPS2 as peer. Discover and record the npub (persistent identity generated on first run). Add T470 to `fips_laptops` inventory group. |
| **Dependencies** | FIPS-04 (VPS2 upgraded — hub must be on v0.4.1 for T470 to peer) |
| **Estimated time** | 1–2 hours |

### Acceptance Criteria

- [ ] `fipsctl show status` reports version 0.4.1 and a valid npub (recorded)
- [ ] `fipsctl show peers` shows at least 1 connected peer (vps2)
- [ ] Ethernet transport active (if WiFi interface available on wlp58s0)
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` returns a mesh IPv6
- [ ] `fips` and `fips-dns` systemd services enabled and active
- [ ] Ansible run is idempotent (no changes on second run with `--check`)

---

## FIPS-06: Deploy host aliases + Nostr discovery on all nodes

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-06 |
| **Title** | Deploy complete host aliases and enable cross-machine Nostr discovery |
| **Phase** | 5 |
| **Worker** | worker-fips |
| **Description** | With all machines on FIPS v0.4.1 and npubs known, update `fips_mesh_hosts` in Ansible defaults to include all 4 machine shortname→npub mappings (vps2, dq05, t14gen5, t470). Deploy `/etc/fips/hosts` via the `fips-hosts.j2` template to all nodes. Verify cross-discovery works via Nostr (configured_only policy) and LAN discovery. |
| **Dependencies** | FIPS-03 (T14Gen5 npub confirmed), FIPS-04 (VPS2 upgraded), FIPS-05 (T470 npub discovered) |
| **Estimated time** | 1–2 hours |

### Acceptance Criteria

- [ ] Each machine shows 3+ peers in `fipsctl show peers`
- [ ] `/etc/fips/hosts` on each machine contains aliases for all 4 machines (vps2, dq05, t14gen5, t470)
- [ ] `dig @::1 -p 5354 dq05.fips AAAA +short` works from every machine
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` works from every machine
- [ ] `dig @::1 -p 5354 t14gen5.fips AAAA +short` works from every machine
- [ ] `dig @::1 -p 5354 t470.fips AAAA +short` works from every machine
- [ ] Nostr relay advertising confirmed (check relay for app tag `fips-overlay-v1`)
- [ ] LAN discovery: DQ05 and T14Gen5 see each other directly (not just via VPS2)

---

## FIPS-07: Verify host aliases and Nostr discovery on all nodes

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-07 |
| **Title** | Verify /etc/fips/hosts and Nostr discovery are working on all 4 nodes |
| **Phase** | 5 |
| **Worker** | worker-fips |
| **Description** | After deploying host aliases via the `fips-hosts.j2` template, verify that all 4 machine shortnames (vps2, dq05, t14gen5, t470) resolve correctly on every machine. Confirm Nostr discovery (configured_only) is finding peers via relays, and LAN discovery connects DQ05 and T14Gen5 directly. |
| **Dependencies** | FIPS-06 (host aliases deployed) |
| **Estimated time** | 1 hour |

### Acceptance Criteria

- [ ] `cat /etc/fips/hosts` on every machine shows all 4 machine aliases
- [ ] `dig @::1 -p 5354 dq05.fips` works from every machine
- [ ] `ping vps2.fips` works from each laptop (DQ05, T14Gen5, T470)
- [ ] `ping dq05.fips` works from T14Gen5 (LAN discovery)
- [ ] Nostr discovery policy is `configured_only` (NOT `open`) on all nodes
- [ ] No public test mesh nodes (test-usXX) remain in any config or hosts file

---

## FIPS-08: End-to-end SSH-over-FIPS verification

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-08 |
| **Title** | Verify SSH-over-FIPS works bidirectionally between all machine pairs |
| **Phase** | 6 |
| **Worker** | worker-admin |
| **Description** | From each of the 4 machines, SSH to every other machine via `<shortname>.fips`. Record results for all 12 directional pairs. Debug any failures (DNS, firewall, peer, SSH key issues). Configure `~/.ssh/config` with `Host *.fips` entries if needed. |
| **Dependencies** | FIPS-06, FIPS-07 (full mesh peering and DNS verified) |
| **Estimated time** | 1–2 hours |

### Acceptance Criteria

- [ ] All 12 directional SSH pairs succeed (DQ05→T14Gen5, T14Gen5→DQ05, DQ05→VPS2, VPS2→DQ05, etc.)
- [ ] SSH connections use the `fips0` TUN interface (verify with `ss -tn` showing fips0 source)
- [ ] No SSH connection falls back to non-FIPS transport
- [ ] Ansible verification playbook passes on all hosts (tag: `verify`)
- [ ] Latency between machines is reasonable (<500ms cross-continent, <50ms LAN)
- [ ] `~/.ssh/config` entries created for all `.fips` hostnames

---

## FIPS-09: Create unified FIPS mesh Ansible playbook

| Field | Value |
|-------|-------|
| **Task ID** | FIPS-09 |
| **Title** | Create playbook to deploy and verify the entire private FIPS mesh |
| **Phase** | All (supporting) |
| **Worker** | worker-admin |
| **Description** | Create or update `ansible/playbooks/13-fips.yml` to target `fips_all` group, with tags for selective execution (install, config, verify). Include pre-tasks for backup, post-tasks for verification. This playbook ties together all the individual machine deployments into a single reproducible command. |
| **Dependencies** | FIPS-01 through FIPS-07 (individual machine configs validated) |
| **Estimated time** | 1 hour |

### Acceptance Criteria

- [ ] `ansible-playbook 13-fips.yml --tags install` installs FIPS on all hosts
- [ ] `ansible-playbook 13-fips.yml --tags config` deploys config to all hosts
- [ ] `ansible-playbook 13-fips.yml --tags verify` runs all checks on all hosts
- [ ] Playbook is idempotent (`--check` shows no changes after successful run)
- [ ] Playbook syntax check passes
- [ ] Pre-tasks include config backup before template deploy
- [ ] Post-tasks include verification assertions

---

## Task Dependency Graph

```
FIPS-01 (DQ05 config) ──────────────┐
FIPS-02 (DQ05 inventory) ───────────┤
                                     ▼
FIPS-03 (T14Gen5 config) ──────────┐
                                    │
FIPS-04 (VPS2 upgrade) ────────────┤
                                    │
FIPS-05 (T470 install) ────────────┘
                                    │
                                    ▼
FIPS-06 (Host aliases + discovery) ──┐
                                      │
FIPS-07 (Verify discovery) ──────────┘
                                      │
                                      ▼
FIPS-08 (SSH verification) ──────────┐
                                      │
FIPS-09 (Unified playbook) ─────────┘
```

## Quick-Reference: Machine SSH Users

| Machine | SSH user | Connection | .fips hostname |
|---------|----------|------------|----------------|
| DQ05 | c03rad0r | Netbird 100.90.22.201 or localhost | `dq05.fips` |
| T14Gen5 | c03rad0r | localhost (local) | `t14gen5.fips` |
| VPS2 | debian | 23.182.128.51 (public) | `vps2.fips` |
| T470 | c03rad0r | Netbird 100.90.101.9 or localhost | `t470.fips` |