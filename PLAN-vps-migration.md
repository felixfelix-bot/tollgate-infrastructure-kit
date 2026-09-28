# PLAN: Full VPS Migration (Old → New) + Fix Backup Sync

## Goal
Migrate all services from old VPS (`23.182.128.51`) to new VPS (`23.182.128.226`), fix backup sync, and ensure data is synced to both the backup machine (`100.90.22.201`) and the new VPS before decommissioning the old one.

## Infrastructure

| | Old VPS (`23.182.128.51`) | New VPS (`23.182.128.226`) | Backup (`100.90.22.201`) |
|---|---|---|---|
| OS | Debian 13 | Debian 13 | Ubuntu 25.10 |
| Disk | 99GB (100% full) | 504GB (1% used) | 468GB (28% used) |
| RAM | 8GB | 4GB | 10GB |
| KVM | Yes | No | N/A |
| Syncthing | Running (folders in error) | Not installed | Running (folders empty) |
| Docker | 18GB containers | Not installed | N/A |
| NetBird | Yes | Installed, inactive | Yes |
| Latency | Same subnet, <1ms | Same subnet, <1ms | Via WAN |

## Root Cause of Backup "Problem"
All 6 syncthing folders on old VPS: **"folder marker missing"** — `.stfolder` directory doesn't exist in `/opt/tollgate/backups/*/`. Syncthing refuses to sync without it. Plus disk is 100% full.

## Phase 1: Fix old VPS backup sync
- [ ] Free ~2GB disk space (delete old exports, rotate logs)
- [ ] Create `.stfolder` marker dirs in all 6 backup staging dirs
- [ ] Trigger syncthing rescan
- [ ] Verify data syncs to backup machine (`100.90.22.201`)
- [ ] Fix dashboard `backup-status.json` — all 6 folders green

## Phase 2: Deploy new VPS
- [ ] Copy SSH key to new VPS (`ssh-copy-id debian@23.182.128.226`)
- [ ] Update `.env` with new VPS credentials, keep old as `OLD_VPS_IP`
- [ ] Update `hosts.yml` — add `tollgate-vps-new`, keep old as `tollgate-vps-old`
- [ ] Run `setup-all.yml` against new VPS
- [ ] Configure syncthing peering: new VPS ↔ old VPS ↔ backup machine (3-way)
- [ ] Wait for data sync from old VPS to new VPS

## Phase 3: Validate and cutover
- [ ] Verify all services running on new VPS (check services.orangesync.tech)
- [ ] Verify backups synced to both backup machine and new VPS
- [ ] Verify dashboard shows all green
- [ ] Update Cloudflare DNS to point to new VPS IP
- [ ] Keep old VPS running as secondary until confident

## Credentials
- New VPS: `debian@23.182.128.226`, password `possible-tourist-material-busy-power-jeans`
- Old VPS: `debian@23.182.128.51`, SSH key
- Backup: `c03rad0r@100.90.22.201`, SSH key

## Notes
- New VPS has no KVM — QEMU will be software emulation (~10min boot). Acceptable for now.
- New VPS has 4GB RAM — tight with Docker + QEMU but functional.
- Old and new VPS are on same /24 subnet — direct SSH/syncthing, no NetBird needed between them.
- Don't delete GRASP data on old VPS.
