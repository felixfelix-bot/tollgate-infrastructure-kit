# Infrastructure Fixes: Backup, GRASP Storage, Relatr WoT, Services Dashboard

## Part 1: Backup Status — Per-Minute Updates + Fine-Grained View

- [x] 1a Create `tollgate-backup-status.service.j2` — systemd oneshot running `gen-backup-status.py`
- [x] 1b Create `tollgate-backup-status.timer.j2` — `OnCalendar=minutely`
- [x] 1c Add tasks to deploy + enable new timer in `backup/tasks/main.yml`
- [x] 1d Add error fallback to `gen-backup-status.py` — write error state instead of stale JSON
- [x] 1e Add per-folder disk usage to `gen-backup-status.py`
- [x] 1f Auto-expand backup detail section in `static/services/index.html`

## Part 2: GRASP Storage Fix

- [x] 2a Set `grasp_archive_all: false` in `group_vars/all.yml`
- [x] 2b Set `grasp_archive_read_only: false` in `group_vars/all.yml`
- [x] 2c Replace `cp -a` with `rsync --link-dest` in `tollgate-backup.sh.j2`
- [x] 2d Add error isolation per backup section in `tollgate-backup.sh.j2`
- [x] 2e Move status gen call to beginning of backup script

## Part 3: Deploy Relatr (WoT Trust Score Service)

- [x] 3a Create `ansible/roles/relatr/defaults/main.yml`
- [x] 3b Create `ansible/roles/relatr/tasks/main.yml`
- [x] 3c Create `ansible/roles/relatr/templates/docker-compose.relatr.yml.j2`
- [x] 3d Create `ansible/playbooks/32-relatr.yml`
- [x] 3e Add `relatr` to `setup-all.yml`
- [x] 3f Add `wot` subdomain Caddy route
- [x] 3g Add `wot` to `cloudflare_subdomains` in `group_vars/all.yml`
- [x] 3h Add relatr config vars to `group_vars/all.yml`
- [x] 3i Create `scripts/strfry-wot-policy.sh`
- [x] 3j Create `scripts/grasp-trust-filter.py`
- [ ] 3k Configure strfry ngit relay write-policy (requires testing on VPS)
- [x] 3l Add Relatr to watchdog

## Part 4: Services Dashboard

- [x] 4a Add Micro VPN to SERVICES array
- [x] 4b Add Plebeian Market E2E to SERVICES array
- [x] 4c Add Relatr (WoT) to SERVICES array
- [x] 4d Add `vpn` + `wot` to `cloudflare_subdomains`
- [x] 4e Add `"51820"` to `firewall_allowed_ports`

## Remaining

- [ ] 3k Configure strfry ngit relay write-policy (requires VPS deployment + testing)
- [ ] Deploy via `ansible-playbook setup-all.yml`
- [ ] Set RELATR_SERVER_SECRET_KEY in .env on VPS
- [ ] Verify backup-status.json updates every minute after deploy

## Key Config

| Variable | Value |
|----------|-------|
| Relatr root of trust | `npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw` |
| Number of hops | 2 |
| Trust threshold | 0.1 |
| Relatr port | 3000 |
| Relatr domain | `wot.orangesync.tech` |
| Micro VPN domain | `vpn.orangesync.tech` |
| Status timer interval | Every 60 seconds |
| GRASP archive | false (only push-accepted repos) |
