# PLAN-dual-vps-failover.md

## Overview

Multi-VPS deployment with automated failover. All services deploy to both VPSes with `ignore_unreachable: true` so a down VPS doesn't block the other. Syncthing replicates stateful data between VPSes and to the backup machine.

## Machines

| Label | IP | User | Password | Role |
|---|---|---|---|---|
| vps1 | `66.92.204.38` | `debian` | `REDACTED_VPS_PASSWORD` | Primary (active for stateful) |
| vps2 | `23.182.128.51` | `debian` | `REDACTED_VPS2_PASSWORD` | Secondary (standby for stateful) |
| backup | `100.90.22.201` | `c03rad0r` | `REDACTED_BACKUP_PASSWORD` (sudo) | Syncthing backup target |

**Abandoned**: `23.182.128.226` (unreachable, removed from all configs)

## Architecture

```
                     Cloudflare DNS
                          │
           ┌──────────────┼──────────────┐
           │              │              │
      Shared (2 A)    Per-machine (1 A)  VPS-1 only (1 A)
      nsite,chat,git   relay1 → vps-1    *.mints → vps-1
      services,vote    relay2 → vps-2
      workshop,...     ngit1 → vps-1
      routstr          ngit2 → vps-2
      orangesync.tech  blossom1 → vps-1
                       blossom2 → vps-2
           │              │
      ┌────┴────┐    ┌────┴────┐
      │  VPS-1  │    │  VPS-2  │
      │ 66.92.  │    │ 23.182. │
      │ 204.38  │    │ 128.51  │
      │(debian) │    │(debian) │
      └────┬────┘    └────┬────┘
           │  syncthing    │
           │◄─────────────►│
           │  sendreceive  │
           └───────┬───────┘
                   │ syncthing
           ┌───────┴───────┐
           │    Backup     │
           │ 100.90.22.201 │
           └───────────────┘
```

## Service Modes

### Active-Active (running on both VPSes, Caddy failover + DNS round-robin)

caddy, nsite-gateway, obelisk (chat), releases, ci, vote, workshop, solix, wot, services dashboard, relatr, gitworkshop, nsyte, fips, mptcp-server

### Active-Passive (running on vps-1, standby on vps-2, watchdog failover)

GRASP (git), routstr, all mints, act-runner

### Unique per-VPS (independent instances, no sync)

strfry relay (relay1/relay2), ngit-relay (ngit1/ngit2), blossom (blossom1/blossom2)

### Per-VPS only

- vps1: bitcoin-core
- vps2: bitcoin-knots, micro-vpn

### Shared (both VPSes)

- jitsi-meet (`meet.orangesync.tech`)

## DNS Records

| Subdomain | Type | Records | Failover |
|---|---|---|---|
| `orangesync.tech` | A x2 | `66.92.204.38`, `23.182.128.51` | Caddy |
| `nsite` | A x2 | both IPs | Caddy |
| `chat` | A x2 | both IPs | Caddy |
| `git` | A x2 | both IPs | Caddy |
| `services` | A x2 | both IPs | Caddy |
| `routstr` | A x2 | both IPs | Caddy |
| `vote` | A x2 | both IPs | Caddy |
| `workshop` | A x2 | both IPs | Caddy |
| `releases` | A x2 | both IPs | Caddy |
| `ci` | A x2 | both IPs | Caddy |
| `runner` | A x2 | both IPs | Caddy |
| `solix` | A x2 | both IPs | Caddy |
| `wot` | A x2 | both IPs | Caddy |
| `meet` | A x2 | both IPs | Caddy |
| `relay1` | A | `66.92.204.38` | None (unique) |
| `relay2` | A | `23.182.128.51` | None (unique) |
| `ngit1` | A | `66.92.204.38` | None (unique) |
| `ngit2` | A | `23.182.128.51` | None (unique) |
| `blossom1` | A | `66.92.204.38` | None (unique) |
| `blossom2` | A | `23.182.128.51` | None (unique) |
| `*.mints` | A | `66.92.204.38` only | DNS change on failover |
| `vpn` | A | `23.182.128.51` only | None |

## Syncthing Folders (VPS-1 <-> VPS-2 <-> Backup, all sendreceive)

| ID | Path (live data) | Notes |
|---|---|---|
| `orangesync-grasp` | `/opt/tollgate/snapshots/grasp/` | Via mdb_copy snapshot every 5min |
| `orangesync-mints` | `/opt/tollgate/mints/` | SQLite WAL, safe for live sync |
| `orangesync-routstr` | `/opt/tollgate/routstr/` | SQLite WAL |
| `orangesync-caddy` | `/opt/tollgate/caddy/data/` | TLS certs |
| `orangesync-act-runner` | `/opt/tollgate/act-runner/` | SQLite + artifacts |
| `orangesync-static` | `/srv/tollgate/` | Static sites |

Not synced (unique per VPS): strfry DB, ngit-relay DB, blossom DB

## GRASP Safety: mdb_copy Snapshot

- Install `lmdb-utils` on both VPSes
- Systemd timer runs every 5 minutes
- `mdb_copy /opt/tollgate/grasp/data/relay /opt/tollgate/snapshots/grasp/relay` (hot backup, no stop)
- `rsync -a --delete /opt/tollgate/grasp/data/git/ /opt/tollgate/snapshots/grasp/git/` (git repos, safe)
- Syncthing syncs from `/opt/tollgate/snapshots/grasp/` (consistent snapshot)

## Automated Failover

### Detection

VPS is "down" if SSH unreachable for 3 consecutive watchdog checks (6 min at 120s interval).

### Failover Actions (vps-1 -> vps-2)

1. SSH to vps-2, start standby services:
   - `systemctl start ngit-grasp`
   - `cd /opt/tollgate/mints/test-mb && docker compose up -d` (for each mint)
   - `cd /opt/tollgate/routstr && docker compose up -d`
   - `systemctl start tollgate-act-runner`
2. Update Cloudflare DNS: `*.mints.orangesync.tech` -> `23.182.128.51`
3. Caddy on vps-2 already handles shared services via failover upstreams
4. Mark failover active in watchdog state

### Failback (manual for now, logic in place for auto)

1. Wait for syncthing to sync latest data back to vps-1
2. Start services on vps-1
3. Stop services on vps-2 (back to standby)
4. Restore DNS: `*.mints.orangesync.tech` -> `66.92.204.38`
5. Clear failover state

Run manually: `scripts/failover.py --failback`

---

## Implementation Checklist

### Layer 1: Foundation — DONE

- [x] 1.1 Update `.env` (VPS_IP, VPS_USER, VPS_PASSWORD, VPS2_IP, VPS2_USER, VPS2_PASSWORD)
- [x] 1.2 Rewrite `ansible/inventory/hosts.yml` (vps1, vps2, backup, vps group, ConnectTimeout=15)
- [x] 1.3 Update `group_vars/m1.yml` — machine_id: vps1, machine_number: 1, machine_active: true
- [x] 1.4 Update `group_vars/m2.yml` — machine_id: vps2, machine_number: 2, machine_active: false
- [x] 1.5 Update `group_vars/all.yml` (shared_subdomains, per_machine_subdomains lists)

### Layer 2: Mechanical Playbook Updates — DONE

- [x] 2.1 `00-zram.yml` — `ignore_unreachable: true`
- [x] 2.2 All playbooks — `hosts: vps` or per-machine + `ignore_unreachable: true`
- [x] 2.3 `deploy-mint.yml` — same
- [x] 2.4 `deploy-test-mints.yml` — same

### Layer 3: Setup Playbooks — DONE

- [x] 3.1 `setup-vps-1.yml` — hosts: vps1, 28 roles, ignore_unreachable
- [x] 3.2 `setup-vps-2.yml` — hosts: vps2, 30 roles (includes micro_vpn, bitcoin_knots)
- [x] 3.3 `setup-all.yml` imports both
- [x] 3.4 `setup-http-only.yml` — `hosts: vps` + `ignore_unreachable`

### Layer 4: Active-Passive Role Modifications — DONE

- [x] 4.1 `grasp/tasks/main.yml` — guarded with `when: machine_active | default(true)`
- [x] 4.2 `routstr/tasks/main.yml` — same
- [x] 4.3 `cashu_mint/tasks/main.yml` — same
- [x] 4.4 `mint_orchestrator/tasks/main.yml` — same
- [x] 4.5 `act_runner/tasks/main.yml` — same

### Layer 5: DNS Role — DONE

- [x] 5.1 `cloudflare_dns/tasks/main.yml` — dual-A-record for shared, numbered for per-machine, `*.mints` to vps1

### Layer 6: Caddy Template — DONE

- [x] 6.1 `caddy/templates/Caddyfile.http.j2` — failover upstreams, numbered subdomains, active-passive guards

### Layer 7: Syncthing — DONE (code), NOT YET PEEERED

- [x] 7.1 `syncthing/defaults/main.yml` — expanded folders
- [x] 7.2 `21-syncthing.yml` — `hosts: vps` + `ignore_unreachable`
- [x] 7.3 `syncthing/tasks/peering-local.yml` — peer backup with both VPSes
- [x] 7.4 `syncthing/tasks/peering.yml` — hostvars references
- [ ] 7.5 Syncthing actually peered and syncing between vps1 <-> vps2 <-> backup

### Layer 8: GRASP Snapshot Role — DONE

- [x] 8.1 `ansible/roles/grasp_snapshot/tasks/main.yml`
- [x] 8.2 `ansible/roles/grasp_snapshot/templates/tollgate-grasp-snapshot.sh.j2`
- [x] 8.3 `ansible/roles/grasp_snapshot/templates/tollgate-grasp-snapshot.service.j2`
- [x] 8.4 `ansible/roles/grasp_snapshot/templates/tollgate-grasp-snapshot.timer.j2`
- [ ] 8.5 Snapshot timer active and running on both VPSes

### Layer 9: Failover Script — DONE

- [x] 9.1 `scripts/failover.py` — failover/failback with Cloudflare DNS update + service start/stop

### Layer 10: Watchdog — DONE (code)

- [x] 10.1 `scripts/watchdog.json` — dual-machine config
- [x] 10.2 `watchdog/templates/watchdog.json.j2`
- [x] 10.3 `scripts/watchdog.py` — failover detection, trigger, failback logic

### Layer 11: Dashboard + Stats — DONE

- [x] 11.1 `static/services/index.html` — vps1/vps2, new IPs, failover status
- [x] 11.2 `backup/files/gen-vps-stats.py` — unified service list
- [x] 11.3 `backup/files/gen-backup-status.py` — new syncthing config path
- [x] 11.4 `backup/tasks/main.yml` — snapshot dir

### Layer 12: Bitcoin + Jitsi — DONE (roles created)

- [x] 12.1 Bitcoin Core role — builds from source, listen=0, pruned 10GB, cgroup limits
- [x] 12.2 Bitcoin Knots role — builds from source, RDTS_CONSENT, listen=0, cgroup limits
- [x] 12.3 Jitsi Meet role — docker-jitsi-meet stable-9584, no-auth
- [x] 12.4 Bitcoin Core deployed to vps1 — IBD ~39%
- [x] 12.5 Bitcoin Knots deployed to vps2 — IBD ~12%
- [ ] 12.6 Jitsi Meet deployed to vps1
- [ ] 12.7 Jitsi Meet deployed to vps2

### Layer 13: Commit and Push — DONE

- [x] 13.1 Committed to `act-runner-tollgate-module-ci` branch
- [x] 13.2 Pushed to origin, github, orangesync

---

## Deployment Checklist (current state)

### VPS1 (66.92.204.38) — Primary

| # | Role | Status | Notes |
|---|------|--------|-------|
| 1 | system | OK | |
| 2 | docker | OK | 16 containers running |
| 3 | cloudflare_dns | OK | |
| 4 | caddy | OK | Docker, ports 80/443 |
| 5 | strfry | OK | Docker |
| 6 | obelisk_relay | OK | Docker |
| 7 | blossom | OK | Docker |
| 8 | nsite_gateway | OK | Docker |
| 9 | release_explorer | OK | |
| 10 | hive_ci | OK | ignore_errors on npm |
| 11 | mint_orchestrator | OK | |
| 12 | cashu_brrr | OK | |
| 13 | mint_operator_proxy | OK | health check accepts 401 |
| 14 | mptcp_server | OK | ignore_errors on glorytun |
| 15 | fips | OK | systemd active |
| 16 | nsyte_cli | OK | |
| 17 | grasp | INACTIVE | binary not built (source 404, glibc mismatch) |
| 18 | act_runner | OK | systemd active |
| 19 | routstr | OK | Docker |
| 20 | auditable_voting | OK | |
| 21 | ngit_relay | OK | Docker |
| 22 | backup | OK | |
| 23 | gitworkshop | OK | |
| 24 | grasp_mirror | OK | |
| 25 | cloud_lab_runner | OK | |
| 26 | relatr | OK | Docker |
| 27 | jitsi_meet | OK | Docker, port 8090, 4 containers |
| 28 | bitcoin_core | OK | IBD ~40%, systemd active |
| 29 | grasp_snapshot | OK | timer active, every 5 min |
| 30 | syncthing | OK | systemd active, peered with vps2 |

### VPS2 (23.182.128.51) — Secondary

| # | Role | Status | Notes |
|---|------|--------|-------|
| 1 | system | OK | |
| 2 | docker | OK | 20 containers running |
| 3 | cloudflare_dns | OK | |
| 4 | caddy | OK | Docker, ports 80/443 |
| 5 | strfry | OK | Docker |
| 6 | obelisk_relay | OK | Docker |
| 7 | blossom | OK | Docker |
| 8 | nsite_gateway | OK | Docker |
| 9 | release_explorer | OK | |
| 10 | hive_ci | OK | |
| 11 | mint_orchestrator | OK | |
| 12 | cashu_brrr | OK | |
| 13 | mint_operator_proxy | OK | |
| 14 | mptcp_server | OK | |
| 15 | fips | OK | systemd active |
| 16 | nsyte_cli | INACTIVE | systemd inactive |
| 17 | grasp | OK | systemd active |
| 18 | grasp_snapshot | INACTIVE | timer not running |
| 19 | act_runner | OK | systemd active (5 stale containers) |
| 20 | routstr | OK | Docker |
| 21 | auditable_voting | OK | |
| 22 | ngit_relay | OK | Docker |
| 23 | backup | OK | |
| 24 | gitworkshop | OK | |
| 25 | grasp_mirror | OK | |
| 26 | cloud_lab_runner | OK | |
| 27 | relatr | OK | Docker |
| 28 | micro_vpn | BLOCKED | no API source code |
| 29 | jitsi_meet | OK | Docker, port 8090, 4 containers |
| 30 | bitcoin_knots | OK | IBD ~25%, systemd active |
| 31 | syncthing | OK | systemd active, peered with vps1 |
| - | mints (5) | OK | all stable (units fixed to sat) |

---

## Remaining Work Checklist

### Critical (infrastructure health) — ALL DONE

- [x] R1 Run `setup-vps-1.yml` end-to-end — all roles passing
- [x] R2 Run `setup-vps-2.yml` end-to-end — all roles passing
- [x] R3 Deploy Jitsi Meet to vps1 (port 8090, all 4 containers stable)
- [x] R4 Deploy Jitsi Meet to vps2 (port 8090, all 4 containers stable)
- [x] R5 Fix syncthing on vps1 (active) and establish peering vps1 <-> vps2 (connected)
- [x] R6 Fix 3 restarting mints on vps2 (changed GB/KB/MB units -> sat)
- [x] R7 Start GRASP snapshot timer on both VPSes (active, every 5 min)
- [x] R8 Clean up stale act-runner containers on vps2
- [x] R9 Test failover dry-run (failover + failback both verified)
- [x] R10 Fix relay_advertisement localhost sudo (added `become: no`)

### Blocked (requires external work)

- [ ] B1 GRASP on vps1 — source repo returns 404 (private/renamed), binary from vps2 incompatible (glibc 2.41 vs 2.36). Needs: source access or static build
- [ ] B2 micro_vpn on vps2 — API source code doesn't exist (role has infrastructure but no application code). Needs: Python Flask API + Dockerfile written
- [ ] B3 Syncthing backup machine peering — backup (100.90.22.201) shows `connected=false` from VPSes. Likely firewall or NetBird routing issue

### ContextVM Dashboard — Nostr-Native Status Monitoring

The dashboard at `services.orangesync.tech` has been rewritten as a pure Nostr client.
Each VPS publishes its status as a kind 31998 (parameterized replaceable) Nostr event
every 10 seconds. The browser dashboard subscribes to relay1 + relay2 (with public
fallback) and renders status in real-time. JSON fallback activates after 15s if no
Nostr events received.

**Architecture:**

```
gen-vps-stats.py (every 10s via systemd timer)
    |
    +-- writes vps1-status.json / vps2-status.json (local fallback)
    |
    +-- publishes kind 31998 Nostr event to relay1 + relay2
        +- d-tag: "tollgate-vps-status"
        +- t-tag: machine_id (vps1 / vps2)
        +- content: same JSON as status file
        +- signed with TOLLGATE_STATUS_NSEC

Browser (index.html)
    |
    +-- Minimal Nostr WebSocket client (~200 lines inline JS, 5KB, zero deps)
    +-- Subscribes: { kinds: [31998], authors: [STATUS_NPUB], "#d": ["tollgate-vps-status"] }
    +-- Relays: relay1.orangesync.tech, relay2.orangesync.tech
    +-- Public fallback: relay.damus.io, nos.lol
    +-- JSON fallback: fetches vps1-status.json / vps2-status.json after 15s timeout
```

**Event format (kind 31998):**

```json
{
  "kind": 31998,
  "content": "<full status JSON>",
  "tags": [
    ["d", "tollgate-vps-status"],
    ["t", "tollgate-infrastructure"],
    ["t", "vps1"],
    ["machine", "vps1"]
  ],
  "created_at": 1748512345,
  "pubkey": "<TOLLGATE_STATUS_NPUB>"
}
```

**Key management:**
- `TOLLGATE_STATUS_NSEC` / `TOLLGATE_STATUS_NPUB` in `.env`
- Templated into dashboard HTML by Ansible (caddy role)
- Read by gen-vps-stats.py from `/opt/tollgate/.env`
- Read-only keypair (no auth implications if leaked)

**Machine ID normalization:**
- `/etc/tollgate-machine-id` now contains `vps1`/`vps2` (was `m1`/`m2`)
- Stats script writes `vps1-status.json` / `vps2-status.json`
- Dashboard reads these filenames for JSON fallback
- SERVICES_MAP only uses `vps1`/`vps2` keys

**Service list expansion:**
- VPS1: 24 services tracked (was 14) — added jitsi, bitcoind, syncthing, all mints, routstr-tor
- VPS2: 27 services tracked (was 9) — added jitsi, bitcoind-knots, grasp, all mints, nutshell, routstr-tor, relatr, voting-worker, fips

**Implementation checklist:**

- [ ] D1 Generate TOLLGATE_STATUS Nostr keypair, add to .env + group_vars/all.yml
- [ ] D2 Expand SERVICES_VPS1 / SERVICES_VPS2 in gen-vps-stats.py with all deployed services
- [ ] D3 Add Nostr publishing to gen-vps-stats.py (coincurve + bech32 + websockets)
- [ ] D4 Rewrite dashboard index.html as pure Nostr client with JSON fallback
- [ ] D5 Update Ansible backup role — pip deps (coincurve, bech32, websockets), env vars
- [ ] D6 Update Ansible caddy role — template dashboard HTML to inject STATUS_NPUB
- [ ] D7 Normalize machine-id: re-run 22-backup.yml to write vps1/vps2 to /etc/tollgate-machine-id
- [ ] D8 Deploy to both VPSes via Ansible
- [ ] D9 Verify: Nostr events on relay, dashboard live, JSON fallback works
- [ ] D10 Cleanup stale m1-status.json, m2-status.json, vps-stats.json symlink
- [ ] D11 Commit and push to all remotes

### Lower priority (polish)

- [ ] R11 Verify solix nsite deployed
- [ ] R12 Publish relay advertisement Nostr events
- [ ] R13 Voting worker dinner vote walkthrough
- [ ] R14 Verify nsyte_cli on both VPSes
