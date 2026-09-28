# Dual-Machine Architecture + VPS Stats + DNS Fix

## Phase 0: Finish VPS Stats UI

- [x] 0a Add `fetchVpsStats()` + `renderVpsStats()` JS to `static/services/index.html`
- [x] 0b Test VPS stats rendering — confirmed working at services.orangesync.tech

## Phase 1: Deploy Current Changes to VPS 226 (m1)

- [x] 1a VPS 226 came back online during deploy
- [x] 1b Deployed Caddy with new conditional template
- [x] 1c VPS stats timer running (every 10 seconds)
- [x] 1d Backup status timer running (every 60 seconds)
- [x] 1e Services dashboard with VPS stats rendering deployed
- [ ] 1f Full m1 deploy (setup-m1.yml) — only caddy deployed so far, other roles pending

## Phase 2: Dual-Machine Inventory + Config

- [x] 2a Add `machine_id` host var (m1/m2) to `ansible/inventory/hosts.yml`
- [x] 2b Create `ansible/inventory/group_vars/m1.yml` — machine 1 specific vars
- [x] 2c Create `ansible/inventory/group_vars/m2.yml` — machine 2 specific vars
- [x] 2d Add `machine_domain` variable (`m1.orangesync.tech` / `m2.orangesync.tech`)
- [x] 2e Add `machine_ip` per machine (env lookup)
- [x] 2f Define service split via `machine_roles` list in group_vars

## Phase 3: Caddy + DNS for Dual-Machine

- [x] 3a Update Caddyfile template with `{% if role in machine_roles %}` conditionals
- [x] 3b DNS role supports `*.{{ machine_domain }}` wildcard per machine
- [x] 3c DNS role supports machine root domain (`m1.orangesync.tech`)
- [ ] 3d Actually create `*.m1.orangesync.tech` DNS record → 226 (needs deploy)
- [ ] 3e Actually create `*.m2.orangesync.tech` DNS record → 51 (needs deploy)
- [ ] 3f Keep bare subdomains pointing to m1
- [ ] 3g Add `m1.orangesync.tech` and `m2.orangesync.tech` landing pages

## Phase 4: Dual-Machine Playbooks

- [x] 4a Create `ansible/playbooks/setup-m1.yml` — deploys m1 services
- [x] 4b Create `ansible/playbooks/setup-m2.yml` — deploys m2 services
- [x] 4c Update `setup-all.yml` to import both machine playbooks
- [ ] 4d Ensure idempotent: re-running on already-deployed machine is safe (needs testing)

## Phase 5: Services Dashboard for Both Machines

- [x] 5a Server-side service health agent (gen-vps-stats.py probes localhost HTTP/TCP)
- [x] 5b Dashboard rewritten with m1/m2 tabs, fetches {machine_id}-status.json
- [x] 5c Peer cross-fetch: each VPS fetches other machine's status via HTTP
- [x] 5d No browser-side service probing needed
- [ ] 5e Deploy updated dashboard + agent to VPS 226 (m1) when back online
- [ ] 5f Verify cross-machine status visibility when both VPSs are up

## Phase 6: Deploy to Both Machines

- [x] 6a VPS 226 (m1) back online, Caddy + VPS stats deployed
- [ ] 6b Deploy m2 config to 23.182.128.51 (VPS 51)
- [ ] 6c Full m1 deploy (all roles) to VPS 226
- [ ] 6d Verify both Caddy instances serve their subdomains
- [ ] 6e Verify DNS resolves correctly for m1.* and m2.* subdomains
- [ ] 6f Verify cross-machine Syncthing backup sync

## Service Split

| Service | m1 (226) | m2 (51) |
|---------|----------|---------|
| Caddy | yes | yes |
| strfry | yes | yes |
| GRASP | primary | mirror |
| Cashu mints | yes | - |
| Routstr | yes | - |
| Relatr | yes | - |
| Micro VPN | - | yes |
| ngit relay | yes | yes |
| Syncthing | yes | yes |
| Backup | yes | yes |
| Watchdog | yes | yes |
| Act Runner | yes | - |
| Blossom | yes | - |
| Obelisk | yes | - |
| Nsite Gateway | yes | - |

## Key Decisions

- Bare subdomains (relay.orangesync.tech) point to m1
- m1 = 23.182.128.226, m2 = 23.182.128.51
- Both machines run Caddy + Syncthing for cross-backup
- VPS stats update every 10 seconds
- Backup status updates every 60 seconds
- GRASP archive_all: false on both machines
- Caddyfile uses `{% if 'role_name' in machine_roles %}` for conditional routes
- DNS uses `in` operator for dict key checks (not `.get() is defined`)
- Env vars must be exported (`set -a && source .env`) for Ansible lookups
- Committed: `9f0326a` on `act-runner-tollgate-module-ci` branch

## Watchdog Dual-Machine

- [x] watchdog.json: each service has `"machine"` field (m1/m2)
- [x] watchdog.json: `"machines"` block with SSH config per machine
- [x] watchdog.py: checks SSH for both machines, probes HTTP per service
- [x] watchdog.py: redeploys with `--limit <ansible_host>` for correct target
- [x] watchdog.py: loads .env vars for both VPS_IP and OLD_VPS_IP
- [x] watchdog.json.j2 template updated with machine field per service
- [ ] Deploy watchdog config to both machines when online
