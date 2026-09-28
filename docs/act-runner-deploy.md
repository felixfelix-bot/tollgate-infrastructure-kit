# ACT Runner Deployment Checklist

## Pre-deployment

- [x] Verify VPS SSH connectivity
- [x] Verify Docker is running on VPS
- [x] Generate Nostr keypair for act-runner signing
- [x] Add ACT_RUNNER_NSEC / ACT_RUNNER_NPUB to .env on local machine
- [x] Configure repo allowlist in group_vars/all.yml (or override at deploy time)

## Deployment

- [x] Run Cloudflare DNS role (adds `runner` A record)
- [x] Run Caddy role (adds `runner.orangesync.tech` route + TLS cert)
- [x] Run act-runner playbook (`27-act-runner.yml`)
  - [x] Installs nektos/act binary (v0.2.77)
  - [x] Creates Python venv + installs package
  - [x] Deploys config, systemd unit, static dashboard
  - [x] Starts tollgate-act-runner service
- [x] Verify systemd service is active
- [x] Verify REST API at `http://localhost:8095/api/health`
- [x] Verify Caddy proxy at `https://runner.orangesync.tech/api/health`
- [x] Verify dashboard at `https://runner.orangesync.tech`

## Post-deployment

- [x] Run integration test: `tests/integration/test_act_runner.sh` (9/9 passed)
- [x] Checked GRASP for repos with `.github/workflows/` — none found yet (31 tollgate repos, 2048 total npubs)
- [x] Update PROGRESS.md
- [ ] Add repos to allowlist when repos with `.github/workflows/` are pushed to GRASP
- [ ] Verify Nostr events published after first build

## Rollback

If deployment fails:
1. `ssh debian@VPS_IP sudo systemctl stop tollgate-act-runner`
2. Remove Caddy route for `runner.{{ base_domain }}`
3. Remove Cloudflare DNS `runner` A record
