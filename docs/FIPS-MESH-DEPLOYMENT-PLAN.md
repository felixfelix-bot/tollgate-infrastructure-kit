# FIPS Mesh Deployment Plan — All Machines Reachable

**Status:** DRAFT v2 — incorporates kimi-consultant review (CHANGES_REQUESTED resolved)  
**Date:** 2026-08-12  
**Author:** Manager (Felix)  
**Consultant review:** kimi-k2.7-code, 3 blockers + 8 major + 8 minor found

## Goal

Every machine in the fleet runs FIPS v0.4.1 with:
- Persistent identity (stable npub)
- Nostr discovery enabled + working (with correct relay URLs)
- Ethernet transport on the correct interface (WiFi or wired)
- Mesh firewall enabled with SSH open
- .fips DNS resolution working
- Multiple test mesh peers connected (redundancy)
- Fleet machines registered in /etc/fips/hosts for shortname resolution

Result: `ssh user@<machine>.fips` works from any machine to any machine.

## Current Fleet

| Machine | Hostname | Interface | Status | Role |
|---------|----------|-----------|--------|------|
| T470 | CobridorWave | wlp58s0 | FIPS 0.3.0-dev, 0 peers, broken | Local dev |
| T14Gen5 | T14Gen5 | wlp0s20f3 | FIPS 0.4.1, test-us03 connected, no DNS | Local dev |
| VPS1 | 66.92.204.38 | N/A (VPS) | DOWN since Jul 20, unreachable | Exit node (skipped) |
| VPS2 | 23.182.128.51 | N/A (VPS) | FIPS 0.4.0-dev, exit node running | Active exit node |
| DQ05 | 100.90.22.201 | auto-detect | Unknown FIPS state | Nostr relay host |
| Backup | env-configured | auto-detect | Unknown | Backup server |

## Task Graph (v2)

```
Phase 0: Ansible Role Fixes (worker-fips, sequential)
  T1: Fix group_vars relay conflict + role bugs
  T2: Add ansible-lint compliance + jmespath prereq
  T3: Add Molecule test scaffolding
         │
Phase 1: Deploy Pass 1 — Install + Connect (worker-fips, parallel)
  T4: Deploy FIPS to T470
  T5: Deploy FIPS to T14Gen5 (idempotent, already v0.4.1)
         │
Phase 1.5: Identity Collection (worker-fips)
  T6: Collect npubs from all deployed machines, populate /etc/fips/hosts
         │
Phase 2: Deploy Pass 2 — Fleet DNS + Remote Machines (worker-fips, parallel)
  T7: Redeploy T470 + T14Gen5 with fleet hosts entries
  T8: Deploy FIPS to VPS2 (preserve exit node config)
  T9: Deploy FIPS to DQ05 (check port conflicts)
  T10: Deploy FIPS to Backup (if reachable)
         │
Phase 3: Cross-Mesh Verification (worker-inspector)
  T11: Verify all-to-all reachability + SSH over FIPS
         │
Phase 4: Documentation (worker-admin)
  T12: Write deployment runbook + update PROGRESS.md + ssh config
```

## Blockers Resolved (from consultant review)

### Blocker 1: group_vars/all.yml relay URL conflict
**Problem:** `group_vars/all.yml` defines `fips_advertise_relays` with `tollgate.local` domains that override the role's defaults (public relays). This silently breaks Nostr discovery.
**Fix (T1):** Move FIPS relay defaults to the role's `defaults/main.yml` only. Remove `fips_advertise_relays` and `fips_dm_relays` from `group_vars/all.yml`. The role defaults already have the correct public relay URLs (damus, nos.lol, offchain, orangesync, ngit).

### Blocker 2: Missing identity collection pass
**Problem:** Each machine generates a random npub on first boot. No step collects these npubs to populate /etc/fips/hosts for fleet DNS resolution. `ssh user@t470.fips` won't work without fleet hosts entries.
**Fix (T6 + T7):** Two-pass deployment:
- Pass 1 (T4/T5): Install FIPS, persistent identity generates stable npub
- Identity collection (T6): Run `fipsctl show status` on each machine, extract npub, store in group_vars or a fleet-npubs.yml file
- Pass 2 (T7): Redeploy with `fips_extra_hosts` populated so /etc/fips/hosts has all fleet machines

### Blocker 3: Worker profile inconsistency
**Problem:** Task graph says `worker-fips` but profiles section proposes `worker-fips-mesh`.
**Fix:** Use `worker-fips` for all tasks. The existing worker-fips profile is fine — it currently does ESP32 firmware work on the `fips` board, but mesh deployment tasks will be on a separate `fips-mesh-deploy` board. No context contamination across boards.

## Major Issues Resolved

### Major 1: Unnecessary serial dependencies
**Problem:** T7 (DQ05) and T8 (Backup) depend on T6 (VPS2) but are independent.
**Fix:** T8, T9, T10 all run in parallel after Phase 1.5. No serial dependency on VPS2.

### Major 2: WiFi interfaces in ethernet transport
**Problem:** T470 (wlp58s0) and T14Gen5 (wlp0s20f3) use WiFi interfaces in the `ethernet` transport section.
**Fix:** FIPS ethernet transport works with WiFi interfaces — it's a layer-2 transport that uses raw frames. The `wlp*` prefix is correct. Auto-detect task already matches `^wl|^enp|^eth`. No change needed, but document this in the runbook.

### Major 3: json_query requires jmespath
**Problem:** `tasks/main.yml` uses `json_query` which requires the `jmespath` Python package.
**Fix (T2):** Replace `json_query` with direct Jinja2 attribute access: `fips_status.stdout | from_json | json_query('npub')` -> `(fips_status.stdout | from_json).npub`. No external dependency needed.

### Major 4: No handler for fips-firewall restart
**Problem:** Role deploys ssh.nft but doesn't restart fips-firewall service.
**Fix (T1):** Add handler `restart fips-firewall` that runs `systemctl restart fips-firewall` and notify it from the ssh.nft deploy task.

### Major 5: Backup excluded from verification matrix
**Fix:** T11 includes all deployed machines in the test matrix.

### Major 6: Incomplete acceptance criteria
**Fix:** Acceptance criteria now require all reachable machines to have mesh connectivity, not just T470<->T14Gen5.

### Major 7: Single peer SPOF
**Problem:** All machines peer only with test-us03.
**Fix (T1):** Change `fips_peers` default to include 3 peers: test-us01, test-us03, test-us04 (different geographic locations for redundancy).

### Major 8: Unused fips_identity_nsec
**Problem:** group_vars defines `fips_identity_nsec` but template doesn't use it.
**Fix (T1):** Template already has the nsec conditional from the original role. The variable should come from env or host_vars, not group_vars/all.yml. Remove from group_vars, document as optional host-level override.

## Minor Issues Resolved

- **nft table cleanup:** Add `flush table inet fips-ssh` at top of ssh.nft.j2
- **wait_for timeout:** Increase to 30 seconds, make configurable via `fips_init_timeout`
- **DNS check hardcoded:** Use configured peer name, not hardcoded test-us01
- **Cold review scope:** Apply Gate 2.5 to T1, T3, and T8 (VPS2 deployment touching exit node)
- **Netbird IP fragility:** Document that DQ05 IP must be verified before T9
- **Duplicate inventory entries:** Rename t470 under nip29_relays to avoid confusion
- **Persistent identity verification:** T11 includes reboot test on one machine

## Phase Details

### Phase 0: Ansible Role Fixes

**T1: Fix group_vars relay conflict + role bugs** (worker-fips, no deps)
- Remove `fips_advertise_relays`, `fips_dm_relays`, `fips_identity_nsec` from `group_vars/all.yml`
- Role defaults already have correct public relay URLs
- Add `restart fips-firewall` handler, notify from ssh.nft task
- Change `fips_peers` default to 3 peers (test-us01, test-us03, test-us04)
- Replace `json_query` with direct Jinja2 attribute access
- Add `flush table inet fips-ssh` to ssh.nft.j2
- Increase wait_for timeout to 30s, add `fips_init_timeout` variable
- Make DNS check use first configured peer, not hardcoded test-us01
- Fix assert task: warn instead of fail when no peer connected on fresh install
- Gate 2.5: kimi-consultant cold review on diff

**T2: ansible-lint compliance** (worker-fips, depends on T1)
- Run `ansible-lint` against the role
- Fix all warnings (FQCN module names, task names, etc.)
- Verify syntax check still passes
- Install jmespath as Ansible dependency (or remove all json_query usage in T1)

**T3: Molecule test scaffolding** (worker-fips, depends on T1)
- Create molecule scenario using docker driver
- Test: default role behavior (installs, starts, enables services)
- Test: with ethernet_interface set and unset
- Test: with custom peers and extra_hosts
- Gate 2.5: kimi-consultant cold review on test code

### Phase 1: Deploy Pass 1 — Install + Connect

**T4: Deploy FIPS to T470** (worker-fips, depends on T2,T3)
- Run: `ansible-playbook playbooks/13-fips.yml -i inventory/hosts.yml -l t470_local`
- T470 ethernet: wlp58s0 (WiFi, used as layer-2 ethernet transport)
- Verify: `fipsctl show status` — version 0.4.1, transports > 0
- Verify: `fipsctl show peers` — at least 1 peer connected
- Verify: `dig @::1 -p 5354 test-us01.fips AAAA +short` returns fd97 address
- Verify: `ping6 -c 3 test-us01.fips` works
- Record: npub from `fipsctl show status` output (for T6)

**T5: Deploy FIPS to T14Gen5** (worker-fips, depends on T2,T3, parallel with T4)
- Run: `ansible-playbook playbooks/13-fips.yml -i inventory/hosts.yml -l t14gen5`
- T14Gen5 ethernet: wlp0s20f3
- Already has v0.4.1 — role should be idempotent
- Verify same checks as T4
- Record: npub from `fipsctl show status` output (for T6)

### Phase 1.5: Identity Collection

**T6: Collect npubs + populate fleet hosts** (worker-fips, depends on T4,T5)
- Run `fipsctl show status` on T470 and T14Gen5
- Extract npub from each machine
- Create `ansible/inventory/group_vars/fips_mesh.yml` with:
  ```yaml
  fips_extra_hosts:
    t470: "<t470 npub>"
    t14gen5: "<t14gen5 npub>"
  ```
- This file is NOT committed to git (contains machine-specific identity mappings)
- Add to .gitignore if not already

### Phase 2: Deploy Pass 2 — Fleet DNS + Remote Machines

**T7: Redeploy local machines with fleet hosts** (worker-fips, depends on T6)
- Run playbook again on T470 and T14Gen5
- Now /etc/fips/hosts will include fleet shortnames
- Verify: `dig @::1 -p 5354 t470.fips AAAA +short` returns T470's fd97 address
- Verify: `dig @::1 -p 5354 t14gen5.fips AAAA +short` returns T14Gen5's fd97 address
- Verify: `ping6 -c 3 t14gen5.fips` works from T470 (and vice versa)

**T8: Deploy FIPS to VPS2** (worker-fips, depends on T6, parallel with T7,T9,T10)
- VPS2 already has FIPS 0.4.0-dev as exit node
- Role MUST be idempotent and preserve existing exit node config
- Back up existing /etc/fips/fips.yaml before deploying: `cp /etc/fips/fips.yaml /etc/fips/fips.yaml.bak`
- VPS2: no ethernet interface, fips_external_addr: "23.182.128.51"
- Verify: `fipsctl show status` — version 0.4.1
- Verify: `wg show wgexit0` — exit node still functional
- Verify: `nft list table inet fips-exit` — MASQUERADE still loaded
- Record: VPS2 npub for fleet hosts
- Gate 2.5: kimi-consultant cold review on deployment diff (exit node safety)

**T9: Deploy FIPS to DQ05** (worker-fips, depends on T6, parallel with T7,T8,T10)
- Verify DQ05 reachable: `ping -c 1 100.90.22.201`
- Check port conflicts: `ss -tulnp | grep -E ':2121|:8443|:5354'`
- Auto-detect ethernet interface
- Deploy playbook
- Record: DQ05 npub for fleet hosts

**T10: Deploy FIPS to Backup** (worker-fips, depends on T6, parallel with T7,T8,T9)
- Verify backup machine reachable
- Auto-detect ethernet interface
- Deploy playbook
- Record: Backup npub for fleet hosts

### Phase 3: Cross-Mesh Verification

**T11: Verify all-to-all reachability** (worker-inspector, depends on T7,T8,T9,T10)
- Update fleet hosts on all machines with all collected npubs
- Final redeploy to all machines with complete /etc/fips/hosts
- Test matrix (ping6 -c 3 for each pair):
  - T470 -> T14Gen5, VPS2, DQ05, Backup
  - T14Gen5 -> T470, VPS2, DQ05, Backup
  - VPS2 -> T470, T14Gen5, DQ05, Backup
  - DQ05 -> T470, T14Gen5, VPS2, Backup
- Test SSH: `ssh c03rad0r@t470.fips` from T14Gen5 (primary goal)
- Test SSH: `ssh c03rad0r@t14gen5.fips` from T470 (reverse)
- Reboot one machine, verify npub unchanged (persistent identity proof)
- Document: which pairs work directly vs through mesh forwarding

### Phase 4: Documentation

**T12: Write deployment runbook** (worker-admin, depends on T11)
- Document the full deployment process in ~/tollgate-infrastructure-kit/docs/
- Include: prerequisites, playbook commands, verification steps
- Include: how to add a new machine to the mesh
- Include: troubleshooting guide (DNS not resolving, peer not connecting)
- Update ~/tollgate-infrastructure-kit/PROGRESS.md
- Create ~/.ssh/config entries for .fips hostnames:
  ```
  Host t470.fips
    User c03rad0r
    AddressFamily inet6
  Host t14gen5.fips
    User c08rad0r
    AddressFamily inet6
  ```
- Commit + push

## Worker Profiles

### Existing Profiles Used (no new profile needed)

| Profile | Model | Role | Tasks |
|---------|-------|------|-------|
| worker-fips | glm-5.2 | FIPS implementation + deployment | T1-T10 |
| worker-inspector | glm-5.2 | Verification + testing | T11 |
| worker-admin | glm-5.2 | Documentation | T12 |
| kimi-consultant | kimi-k2.7-code | Cold review (Gate 2.5) | T1, T3, T8 |

**No new profile created.** worker-fips handles both ESP32 firmware (on `fips` board) and mesh deployment (on `fips-mesh-deploy` board). Context isolation is maintained by board separation, not profile separation.

## Quality Gates (per task)

Every task MUST pass:
1. **Gate 1 (TDD):** Ansible tasks use molecule/ansible-lint as tests. Write the test first.
2. **Gate 2 (tests pass):** ansible-lint clean, molecule passes, syntax-check passes.
3. **Gate 2.5 (cold review):** Cross-family review using kimi-consultant on T1, T3, T8.
4. **Gate 3 (docs updated):** Role changes update PROGRESS.md or docs/.
5. **Gate 4 (atomic commits):** One concern per commit, conventional messages.
6. **Gate 5 (pushed):** git push to ngit verified exit 0.
7. **Gate 6 (manager review):** Task status = review, not done.

## Kanban Board

Board: `fips-mesh-deploy` (new board, separate from `fips` board)

```bash
hermes kanban boards create fips-mesh-deploy \
  --name "FIPS Mesh Deployment" \
  --description "Deploy FIPS v0.4.1 to all machines, enable SSH over mesh" \
  --icon "🌐" --color "#0066cc" --switch
```

## Dependencies

- VPS1 is DOWN — skipped entirely (not a blocker)
- DQ05 must be reachable via Netbird for T9
- Backup machine must be reachable for T10
- T4/T5 (local machines) are prerequisites for identity collection (T6)
- T6 is prerequisite for all Phase 2 tasks
- Phase 2 tasks (T7-T10) run in parallel

## Risk Mitigation

- **VPS2 exit node:** T8 backs up existing config before deploying. Gate 2.5 cold review on VPS2 deployment.
- **DQ05 port conflicts:** T9 checks ports before deploying. FIPS uses 2121, 8443, 5354 — DQ05 runs relays on 7777, 8080, 3001, 3002 — no conflicts expected.
- **Group membership:** Adding user to `fips` group requires re-login. Playbook output includes a note. T11 reboots one machine for testing.
- **Stale identity:** T14Gen5 currently has ephemeral identity. Switching to persistent changes its npub. T6 collects the new npub after deployment.
- **Netbird IP fragility:** DQ05's Netbird IP (100.90.22.201) can change. Document in runbook. T9 verifies reachability first.
- **Single peer SPOF:** Default config includes 3 test mesh peers (test-us01, test-us03, test-us04) for redundancy.

## Acceptance Criteria

The plan is complete when:
1. All reachable machines (T470, T14Gen5, VPS2, DQ05, Backup) run FIPS v0.4.1
2. All machines have persistent identity (verified by reboot test on one machine)
3. All machines have at least 1 mesh peer connected (target: 3 peers)
4. .fips DNS resolution works on all machines
5. Mesh firewall enabled with SSH open on all machines
6. /etc/fips/hosts on all machines contains shortname entries for all fleet machines
7. `ssh c03rad0r@t470.fips` works from T14Gen5 (primary goal)
8. `ssh c08rad0r@t14gen5.fips` works from T470 (reverse direction)
9. ping6 works between all reachable machine pairs
10. Deployment is reproducible via `ansible-playbook playbooks/13-fips.yml`
11. Documentation committed to ~/tollgate-infrastructure-kit/docs/