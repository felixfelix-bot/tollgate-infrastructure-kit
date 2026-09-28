# ACT Runner for GRASP Repos — Implementation Plan

## Overview

A Python daemon on the VPS that watches the GRASP server (`git.orangesync.tech`) for new pushes to specific allowlisted repositories, clones the repo, runs `act` (nektos/act) on any `.github/workflows/*.yml` files, publishes results as Nostr Kind 1985 events, and serves a CI dashboard at `runner.orangesync.tech`.

## Architecture

```
GRASP (git.orangesync.tech:7334)
  │
  │  poll git ls-remote every 30s
  ▼
act-runner daemon (Python, systemd, port 8095)
  │
  ├── Reads allowlist from /opt/tollgate/act-runner/config.yaml
  │
  ├── On new commit detected:
  │     1. git clone --depth 1 <repo>
  │     2. Check for .github/workflows/*.yml
  │     3. Run: act --event push --bind
  │     4. Capture stdout/stderr + exit code
  │     5. Publish Kind 1985 event to ngit + relay
  │     6. Store results in SQLite
  │
  ├── REST API (port 8095):
  │     GET /api/repos           → allowlisted repos + last build status
  │     GET /api/builds          → recent builds (paginated)
  │     GET /api/builds/<id>     → build detail + logs
  │     GET /api/builds/<id>/log → raw log output
  │     GET /api/health          → health check
  │
  └── CI Dashboard (runner.orangesync.tech):
        Static HTML served by Caddy, fetches from REST API
        Shows: repo name, commit, branch, status, duration, timestamp
        Click to expand full log

Nostr Event (Kind 1985):
  tags: [["d", "<repo-url>:<branch>"], ["commit", "<sha>"], ["branch", "<ref>"],
         ["status", "success|failure"], ["duration_ms", "<ms>"],
         ["r", "wss://ngit.orangesync.tech"], ["r", "wss://relay.orangesync.tech"]]
  content: JSON { repo, commit, branch, status, duration_ms, log_url, timestamp }
```

## Checklist

### 1. Python Package (`act-runner/`)

- [x] `act-runner/pyproject.toml` — project metadata + dependencies
- [x] `act-runner/act_runner/__init__.py`
- [x] `act-runner/act_runner/__main__.py` — entrypoint (via daemon:main)
- [x] `act-runner/act_runner/config.py` — load YAML config + env vars
- [x] `act-runner/act_runner/daemon.py` — main asyncio loop
- [x] `act-runner/act_runner/watcher.py` — poll git ls-remote for allowlisted repos
- [x] `act-runner/act_runner/executor.py` — clone + run act subprocess
- [x] `act-runner/act_runner/nostr_publisher.py` — publish Kind 1985 events
- [x] `act-runner/act_runner/db.py` — SQLite build history
- [x] `act-runner/act_runner/api.py` — aiohttp REST API
- [x] `act-runner/act_runner/tests/test_config.py`
- [x] `act-runner/act_runner/tests/test_watcher.py`
- [x] `act-runner/act_runner/tests/test_executor.py`
- [x] `act-runner/act_runner/tests/test_nostr_publisher.py`
- [x] `act-runner/act_runner/tests/test_db.py`
- [x] `act-runner/act_runner/tests/test_api.py`

### 2. Static Dashboard (`static/runner/`)

- [x] `static/runner/index.html` — CI dashboard (dark theme, fetches from REST API)

### 3. Ansible Role (`ansible/roles/act_runner/`)

- [x] `ansible/roles/act_runner/defaults/main.yml`
- [x] `ansible/roles/act_runner/handlers/main.yml`
- [x] `ansible/roles/act_runner/tasks/main.yml`
- [x] `ansible/roles/act_runner/templates/act-runner.service.j2`
- [x] `ansible/roles/act_runner/templates/act-runner-config.yaml.j2`

### 4. Ansible Playbook

- [x] `ansible/playbooks/27-act-runner.yml`

### 5. Updates to Existing Files

- [x] `ansible/inventory/group_vars/all.yml` — add `act_runner_*` vars, `runner` to subdomains
- [x] `ansible/playbooks/setup-all.yml` — add `act_runner` role after `grasp`
- [x] `.env.example` — add `ACT_RUNNER_NSEC`, `ACT_RUNNER_NPUB`
- [x] Caddy config — add `runner.{{ base_domain }}` route (both templates)
- [x] `static/services/index.html` — add CI group with Act Runner + Dashboard
- [x] `PLAN.md` — add service #25
- [x] `PROGRESS.md` — add act runner section

### 6. Tests

- [x] Unit tests all passing (34/34)
- [x] `tests/integration/test_act_runner.sh` — health check, API, Caddy proxy

### 7. Commit

- [ ] All changes committed and pushed

## Key Decisions

- **Subdomain**: `runner.orangesync.tech` (new, does not replace Hive CI at `ci.orangesync.tech`)
- **Push detection**: Poll `git ls-remote` every 30s per allowlisted repo
- **Build mode**: Serial (one build at a time). Concurrent to be added later.
- **Config**: Ansible vars → rendered YAML config template on VPS
- **Nostr event kind**: 1985 (GitHub Actions result)
- **Nostr keypair**: Auto-generated on first deploy, stored in `/opt/tollgate/.env`
- **act execution**: Runs as subprocess using host Docker (not DinD)
- **Build isolation**: Each build in a fresh Docker container via `act`
- **Build artifacts**: Stored in `/opt/tollgate/act-runner/builds/`
- **Work dir**: `/opt/tollgate/act-runner/work/<repo-sanitized>/`
