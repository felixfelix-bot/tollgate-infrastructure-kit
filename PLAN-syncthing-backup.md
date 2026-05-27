# PLAN: Offsite Syncthing Backup to `100.90.22.201` + Dashboard Integration

## Goal
Set up bidirectional Syncthing backup between the VPS (`23.182.128.51`) and the backup machine (`100.90.22.201` via NetBird), with backup status displayed on `services.orangesync.tech`.

## Architecture

```
VPS (23.182.128.51)                          Backup Machine (100.90.22.201)
┌──────────────────────────┐                 ┌────────────────────────────┐
│ /opt/tollgate/backups/   │  Syncthing      │ ~/backups/orangesync/      │
│   strfry/  (sendreceive) │◄───────────────►│   strfry/  (sendreceive)   │
│   grasp/   (sendreceive) │  bidirectional  │   grasp/   (sendreceive)   │
│   ngit-relay/            │  over NetBird   │   ngit-relay/              │
│   mints/                 │                 │   mints/                   │
│   routstr/               │                 │   routstr/                 │
│   caddy/                 │                 │   caddy/                   │
└──────────────────────────┘                 └────────────────────────────┘
         │
         │ backup timer runs
         ▼
   /srv/tollgate/services/backup-status.json
         │
         ▼
   services.orangesync.tech (dashboard)
```

## Pre-work (one-time manual)
- [ ] `ssh-copy-id -i ~/.ssh/id_ed25519 c03rad0r@100.90.22.201`

## Implementation Checklist

### Ansible inventory + env
- [ ] Add `BACKUP_MACHINE_HOST`, `BACKUP_MACHINE_USER` to `.env`
- [ ] Add `tollgate-backup` host to `ansible/inventory/hosts.yml`

### Syncthing role
- [ ] Create `ansible/roles/syncthing/tasks/backup-machine.yml` — configure syncthing on backup machine
- [ ] Update `ansible/roles/syncthing/defaults/main.yml` — add backup machine vars
- [ ] Update `ansible/roles/syncthing/tasks/peering.yml` — bidirectional VPS ↔ backup machine
- [ ] Update `ansible/playbooks/21-syncthing.yml` — target backup machine instead of localhost

### Backup status
- [ ] Update `ansible/roles/backup/templates/tollgate-backup.sh.j2` — write `backup-status.json` after each backup
- [ ] Update `static/services/index.html` — add backup status section to dashboard

### Deployment & Verification
- [ ] Run `21-syncthing.yml` playbook against backup machine
- [ ] Verify syncthing sync starts on backup machine
- [ ] Trigger manual backup run to generate initial `backup-status.json`
- [ ] Verify dashboard shows backup status at `services.orangesync.tech`

### Commit & Push
- [ ] Commit and push to both repos

## Restore Flow (future VPS deployment)
1. Provision new VPS, run `setup-all.yml`
2. Ansible deploys all services + syncthing
3. Syncthing connects to backup machine over NetBird
4. All folders sync from backup machine → new VPS (bidirectional `sendreceive`)
5. Backup timer picks up and continues normal schedule

## Key Decisions
- **Bidirectional `sendreceive`** on both sides: enables automatic restore on new VPS
- **Static JSON** for dashboard status: no new service, backup script writes `/srv/tollgate/services/backup-status.json`
- **NetBird** for connectivity: backup machine is on `100.90.22.201` (NetBird IP)
- **Backup machine**: 321GB free, Ubuntu 25.10, syncthing already installed (device ID `F3ZBNGX-QKRVC6U-6RUCUBS-CCTYPEY-T6TVQ6J-OGLGMJ5-3P5BP6M-ZYNJ3Q3`)
