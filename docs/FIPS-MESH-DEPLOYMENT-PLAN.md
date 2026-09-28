# FIPS Private Mesh Deployment Plan — Fleet Interconnectivity

**Status:** DRAFT v4 — private mesh, hub-and-spoke via VPS2, all consultant blockers resolved  
**Date:** 2026-08-12  
**Author:** Manager (Felix)  
**Review history:** v2 kimi review (public mesh), v3 kimi review (5 blockers found), v4 resolves all

## Why Private Mesh

Public FIPS test mesh bloom filters saturate with too many nodes for v0.4.1's static sizes. FIPS v2 (dynamic bloom filters) not released yet. Solution: small private mesh (~5 nodes), all nodes known, direct peering via VPS2 hub.

## Topology: Hub-and-Spoke via VPS2

```
                    VPS2 (hub + exit node)
                    23.182.128.51 (public IP)
                    npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82
                   /       |        \
                  /        |         \
    T470        T14Gen5      DQ05
    wlp58s0     wlp0s20f3    Netbird/LAN
    (LAN)       (LAN)        (remote)
```

**NOT full mesh.** Hub-and-spoke: all machines peer with VPS2. VPS2 forwards traffic transitively between any two machines that can't reach each other directly. Machines on the same LAN (T470 + T14Gen5) also peer directly for lower latency.

**No public test nodes.** No Nostr discovery on any machine. No connection to public FIPS mesh. Bloom filters stay at ~5 entries.

## Fleet

| Machine | Interface | Reachable via | FIPS npub |
|---------|-----------|---------------|-----------|
| T470 | wlp58s0 | LAN | npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72 |
| T14Gen5 | wlp0s20f3 | LAN | ephemeral -> persistent (T4) |
| VPS2 | eth0 | Public 23.182.128.51 | npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82 |
| DQ05 | auto-detect | Netbird 100.90.22.201 | unknown -> persistent (T10) |
| Backup | auto-detect | env-configured | unknown |

VPS1 skipped — down since Jul 20.

## Key Design Decisions

1. **No Nostr discovery on ANY machine** — including VPS2. Consultant blocker: VPS2 keeping Nostr would re-contaminate bloom filters via gossip. All machines: `nostr.enabled: false`.

2. **Hub-and-spoke, not full mesh.** All machines peer with VPS2 (public IP, always reachable). Same-LAN machines also peer directly. Cross-LAN traffic transits through VPS2.

3. **VPS2 as stable endpoint.** All machines configure VPS2 as a peer with its public IP. VPS2 is the only machine with a guaranteed-reachable address. LAN IPs are secondary/best-effort.

4. **Peering addresses:** VPS2 uses public IP. LAN machines use LAN IPs for direct peering (best-effort). DQ05 uses Netbird IP. No DNS-based addresses for peering.

5. **Two-pass deployment:** Pass 1 installs + generates persistent identity. Pass 2 configures full peer lists + fleet hosts.

6. **SSH firewall restricted to mesh peers.** Not open to all fips0 traffic. Each machine's ssh.nft only accepts connections from known mesh peer IPv6 addresses.

7. **DQ05/Backup deployed in Pass 1** (not Pass 2) to avoid chicken-and-egg npub problem. All machines deploy in Pass 1, all npubs collected in T6, all peers configured in Pass 2.

## Task Graph

```
Phase 0: Ansible Role Overhaul (worker-fips, sequential)
  T1: Rewrite role for private mesh
  T2: ansible-lint + molecule tests
         │
Phase 1: Deploy Pass 1 — Install + Identity (worker-fips, parallel)
  T3: Deploy FIPS to T470
  T4: Deploy FIPS to T14Gen5
  T5: Upgrade VPS2 to v0.4.1
  T6: Deploy FIPS to DQ05 (if reachable)
  T7: Deploy FIPS to Backup (if reachable)
         │
Phase 1.5: Identity Collection (worker-fips)
  T8: Collect all npubs, create fleet registry
         │
Phase 2: Deploy Pass 2 — Mesh Peering + Fleet DNS (worker-fips, parallel)
  T9: Redeploy T470 with all peers + fleet hosts
  T10: Redeploy T14Gen5 with all peers + fleet hosts
  T11: Redeploy VPS2 with all peers + fleet hosts
  T12: Redeploy DQ05 with all peers + fleet hosts (if deployed in T6)
  T13: Redeploy Backup with all peers + fleet hosts (if deployed in T7)
         │
Phase 3: Cross-Mesh Verification (worker-inspector)
  T14: Verify all-to-all reachability + SSH over FIPS
         │
Phase 4: Documentation (worker-admin)
  T15: Write deployment runbook + ssh config + authorized_keys
```

## Phase 0: Ansible Role Overhaul

**T1: Rewrite role for private mesh** (worker-fips, no deps)

Files to change:
- `defaults/main.yml`: Remove public test node peer (test-us03), remove public relay URLs, remove fips_lan_discovery. Add `fips_mesh_peers: []`, `fips_nostr_enabled: false`, `fips_init_timeout: 30`, `fips_ssh_restrict_to_peers: true`.
- `templates/fips.yaml.j2`: Nostr block only when `fips_nostr_enabled: true`. Remove LAN discovery block. Peers from `fips_mesh_peers`.
- `templates/fips-hosts.j2`: REMOVE all 7 public test node entries. Only include entries from `fips_extra_hosts`.
- `templates/ssh.nft.j2`: Add `flush table inet fips-ssh` at top. When `fips_ssh_restrict_to_peers: true`, generate per-peer source IP allow rules instead of blanket accept.
- `tasks/main.yml`: Remove json_query usage → direct Jinja2 (`(fips_status.stdout | from_json).npub`). Make peer count assertion conditional on `fips_mesh_peers | length > 0`. DNS check uses first `fips_extra_hosts` key or skips if empty. Use `fips_init_timeout` variable for wait_for. Add config backup step before template deploy. Add fips-firewall restart handler. Remove `fips-dns-setup` command task if fips-dns service handles it (verify).
- `handlers/main.yml`: Add `restart fips-firewall` handler.
- `group_vars/all.yml`: Remove ALL fips_* variables (fips_advertise_relays, fips_dm_relays, fips_identity_nsec, fips_mesh_ipv6, fips_mesh_http_port, fips_relay_urls).
- `.gitignore`: Add `ansible/inventory/group_vars/fips_mesh.yml`.

Gate 2.5: kimi-consultant cold review on full diff.

**T2: ansible-lint + molecule** (worker-fips, depends on T1)
- ansible-lint clean (FQCN, task names, no json_query)
- Molecule: default (no peers, no nostr)
- Molecule: with peers + ethernet + ssh restrict
- Syntax check passes
- Gate 2.5: kimi-consultant cold review

## Phase 1: Deploy Pass 1

**T3: Deploy FIPS to T470** (worker-fips, depends on T2)
- Backup: `cp /etc/fips/fips.yaml /etc/fips/fips.yaml.pre-upgrade`
- ethernet: wlp58s0, no peers, no nostr
- Verify: version 0.4.1, transports > 0, persistent npub
- Record npub (should be unchanged: npub1eak909...)

**T4: Deploy FIPS to T14Gen5** (worker-fips, depends on T2, parallel)
- Backup existing config
- ethernet: wlp0s20f3, no peers, no nostr
- NOTE: switches from ephemeral to persistent — npub WILL change
- Verify: version 0.4.1, transports > 0
- Record new persistent npub

**T5: Upgrade VPS2** (worker-fips, depends on T2, parallel)
- Backup: `cp /etc/fips/fips.yaml /etc/fips/fips.yaml.pre-upgrade`
- No ethernet, fips_external_addr: "23.182.128.51"
- No nostr (private mesh — no discovery)
- Preserve WireGuard wgexit0 + nftables MASQUERADE
- Verify: version 0.4.1, wg show wgexit0, nft list table inet fips-exit
- Record npub (should be unchanged: npub1sqg8fd4ea...)
- Gate 2.5: kimi-consultant cold review (exit node safety)

**T6: Deploy FIPS to DQ05** (worker-fips, depends on T2, parallel)
- Verify reachable: `ping -c 1 100.90.22.201`
- If unreachable: skip, mark blocked, move on
- Check port conflicts: `ss -tulnp | grep -E ':2121|:8443|:5354'`
- Auto-detect interface, no peers, no nostr
- Record npub

**T7: Deploy FIPS to Backup** (worker-fips, depends on T2, parallel)
- Verify reachable
- If unreachable: skip
- Auto-detect interface, no peers, no nostr
- Record npub

## Phase 1.5: Identity Collection

**T8: Collect all npubs, create fleet registry** (worker-fips, depends on T3-T7)
- Run `fipsctl show status` on every deployed machine
- Extract npub + fips0 IPv6 address
- Get LAN IP of each machine: `ip -4 addr show <interface> | grep inet`
- Create `ansible/inventory/group_vars/fips_mesh.yml` (gitignored):
  ```yaml
  fips_extra_hosts:
    t470: "<npub>"
    t14gen5: "<npub>"
    vps2: "npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82"
    dq05: "<npub>"  # if deployed

  fips_mesh_peers:
    # All machines peer with VPS2 (hub)
    # Same-LAN machines also peer directly
    # For T470:
    #   - vps2 at 23.182.128.51:2121
    #   - t14gen5 at <lan_ip>:2121 (if same LAN)
    # For T14Gen5:
    #   - vps2 at 23.182.128.51:2121
    #   - t470 at <lan_ip>:2121 (if same LAN)
    # For VPS2:
    #   - t470 at <lan_ip>:2121
    #   - t14gen5 at <lan_ip>:2121
    #   - dq05 at <netbird_ip>:2121
    # For DQ05:
    #   - vps2 at 23.182.128.51:2121
  ```

## Phase 2: Deploy Pass 2

**T9-T13: Redeploy all machines with full mesh config** (worker-fips, parallel)
- Each machine gets its peer list + fleet hosts entries
- ssh.nft now restricts SSH to known peer IPv6 addresses only
- Verify on each: `fipsctl show peers` — shows configured peers connected
- Verify: `dig @::1 -p 5354 <shortname>.fips AAAA +short` for each fleet member
- Verify: `ping6 -c 3 <shortname>.fips`

## Phase 3: Verification

**T14: All-to-all verification** (worker-inspector, depends on T9-T13)
- Test matrix: ping6 -c 3 for every pair
- SSH tests:
  - `ssh c03rad0r@t470.fips` from T14Gen5 (primary)
  - `ssh c08rad0r@t14gen5.fips` from T470 (reverse)
  - `ssh root@vps2.fips` from T470
- Reboot one machine: verify npub unchanged
- `fipsctl show bloom` on all machines: < 10 entries (private mesh, no public nodes)
- Document any failures with root cause

## Phase 4: Documentation

**T15: Runbook + SSH config + keys** (worker-admin, depends on T14)
- Deployment runbook with prerequisites, commands, verification
- How to add a new machine to the private mesh
- Troubleshooting guide
- ~/.ssh/config entries for all .fips hostnames
- Ensure authorized_keys distributed across all machines for mesh SSH
- Update PROGRESS.md
- Commit + push

## Worker Profiles

| Profile | Model | Tasks |
|---------|-------|-------|
| worker-fips | glm-5.2 | T1-T13 |
| worker-inspector | glm-5.2 | T14 |
| worker-admin | glm-5.2 | T15 |
| kimi-consultant | kimi-k2.7-code | Cold review: T1, T2, T5 |

## Quality Gates

1. Gate 1 (TDD): molecule tests first
2. Gate 2 (tests pass): ansible-lint + molecule + syntax-check
3. Gate 2.5 (cold review): kimi on T1, T2, T5
4. Gate 3 (docs): PROGRESS.md updated with each phase
5. Gate 4 (atomic commits): one concern per commit
6. Gate 5 (pushed): git push verified
7. Gate 6 (manager review): status = review
8. Bloom filter check: `fipsctl show bloom` < 10 entries on all machines

## Kanban Board

Board: `fips-mesh-deploy`
```bash
hermes kanban boards create fips-mesh-deploy \
  --name "FIPS Private Mesh" \
  --description "Private FIPS mesh for fleet SSH connectivity" \
  --icon "🔒" --color "#0066cc" --switch
```

## Acceptance Criteria

1. T470, T14Gen5, VPS2 run FIPS v0.4.1
2. Persistent identity on all (reboot test on one)
3. No public test mesh peers — private mesh only
4. No Nostr discovery on any machine
5. Bloom filter < 10 entries on all machines
6. .fips DNS resolves all fleet shortnames
7. SSH firewall restricted to known mesh peer IPs only
8. `ssh c03rad0r@t470.fips` from T14Gen5 works
9. `ssh c08rad0r@t14gen5.fips` from T470 works
10. `ssh root@vps2.fips` from T470 works
11. All deployed machines ping6 each other (direct or via VPS2)
12. authorized_keys distributed for mesh SSH
13. Deployment reproducible via ansible-playbook
14. Documentation committed