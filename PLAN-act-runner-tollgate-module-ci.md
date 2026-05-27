# Plan: act-runner Full `act` Mode for tollgate-module-basic-go

## Context

The OpenTollGate GitHub organization is suspended, so GitHub Actions CI is down.
The act-runner on orangesync.tech already watches tollgate-module-basic-go via
GRASP (line 143 in all.yml) but runs in default `pipeline: act` mode without
secrets, artifact server, or correct branch config. This plan makes it work end-to-end.

## Generated Key Pair (for blossom upload)

- NSEC_HEX (hex): `ef61843bb1259a7928d13d5f55bff97b3e593b2b90e49a25455353b73241af28`
- npub (hex): `13756083586fdd552224e1a6a21f82e71f373e9e4e9a3be566946904de3f8785`

## Checklist

### Phase 1: Secrets and Config

- [x] Generate new NSEC_HEX key pair with `nak key generate`
- [x] Store `TOLLGATE_MODULE_NSEC_HEX` in `.env`
- [x] Fix branch `master` → `main` in `ansible/inventory/group_vars/all.yml` (line 144)
- [x] Add `tollgate_module_nsec_hex` var to `ansible/roles/act_runner/defaults/main.yml`
- [x] Update `ansible/roles/act_runner/templates/act-runner.service.j2` with Environment for secrets

### Phase 2: act-runner Python code

- [x] Update `act-runner/src/act_runner/config.py` — add `secrets: dict[str, str]` field + env parsing
- [x] Update `act-runner/src/act_runner/executor.py` — update `run_act()` with `--secret`, `--artifact-server-path`
- [x] Update `act-runner/src/act_runner/executor.py` — update `execute_build()` to pass secrets + artifact path
- [x] Update `act-runner/src/act_runner/daemon.py` — pass `_config.secrets` and artifact path to executor
- [x] All 39 existing tests pass (0.57s)

### Phase 3: Workflow adjustment (tollgate-module-basic-go)

- [x] Add `if: ${{ !env.ACT }}` to `trigger-build-os` job (skip during act-runner builds)

### Phase 4: Trigger API

- [x] Add `POST /api/trigger` endpoint to `api.py` (no auth, substring repo match)
- [x] Expose `_build_queue` from `daemon.py` via module-level accessor
- [x] Add test for trigger endpoint in `test_api.py`
- [x] All 44 tests pass

### Phase 5: VPS Deployment

- [x] Verify Docker is installed and accessible on VPS (Docker 29.4.3)
- [x] Pre-pull `openwrt/sdk:mediatek-filogic-25.12.0` on VPS
- [x] Pre-pull `ubuntu:latest` on VPS
- [x] Pre-pull `catthehacker/ubuntu:act-latest` on VPS (full runner image with git)
- [x] Upgrade `act` from v0.2.77 → v0.2.88 (node24 runtime support)
- [x] Create `/home/debian/.config/act/actrc` with runner image + architecture config
- [x] Run Ansible playbook to deploy updated act-runner
- [x] Verify act-runner health at `https://runner.orangesync.tech/api/health`

### Phase 6: Build PR #118

- [x] Push `94-mint-health-rebase-clean` branch to GRASP mirror (via SSH direct push)
- [x] Fix: `--event` flag → positional `push` arg for act CLI
- [x] Fix: `node:16-buster-slim` → `catthehacker/ubuntu:act-latest` (needs git in container)
- [x] Fix: `actions/upload-artifact@v7/@v8` → `@v4` (mime_type incompatibility with act artifact server)
- [x] Fix: RepoConfig import missing in daemon.py
- [x] Trigger build via `POST /api/trigger` — build running with commit `53c767d`
- [ ] Monitor build in dashboard at `https://runner.orangesync.tech`
- [ ] Verify build logs and artifact output

## Architecture

```
Push to ngit mirror (git.orangesync.tech)
  → GRASP announces new head
  → act-runner polls, detects new commit on main
  → Clones repo via localhost GRASP
  → Runs `act --event push --bind -s NSEC_HEX=... --artifact-server-path ...`
  → act executes .github/workflows/build-package.yml in Docker containers
  → Results published as NIP-94 event to ngit relay
```

## Files Changed

| File | Change |
|------|--------|
| `tollgate-infrastructure-kit/.env` | Add `TOLLGATE_MODULE_NSEC_HEX` |
| `act-runner/src/act_runner/config.py` | Add secrets field + env parsing |
| `act-runner/src/act_runner/executor.py` | Add --secret, --artifact-server-path to run_act() |
| `act-runner/src/act_runner/daemon.py` | Pass secrets through build pipeline |
| `ansible/roles/act_runner/defaults/main.yml` | Add tollgate_module_nsec_hex var |
| `ansible/roles/act_runner/templates/act-runner.service.j2` | Add Environment for secrets |
| `ansible/inventory/group_vars/all.yml` | Fix branch master→main |
| `tollgate-module-basic-go/.github/workflows/build-package.yml` | Skip trigger-build-os in act mode |
| `act-runner/src/act_runner/api.py` | Add POST /api/trigger endpoint |
| `act-runner/src/act_runner/daemon.py` | Expose build queue for trigger API |

## Risks

| Risk | Mitigation |
|------|-----------|
| `actions/upload-artifact@v7`/`@v8` not supported by act | Pinned to @v4 in workflow for act compatibility |
| OpenWrt SDK containers ~500MB each | Pre-pulled on VPS |
| VPS RAM/CPU for full matrix | act runs sequentially by default, 7.8GB RAM |
| `publish-metadata` needs blossom server | Blossom is on same VPS (localhost:3001) |
| `trigger-build-os` needs GitHub org | Skipped via `if: ${{ !env.ACT }}` |
| `act` interactive prompt for default image | Pre-created `/home/debian/.config/act/actrc` |
