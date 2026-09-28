# Auditable Voting v0.1.63 Deployment Plan

## Goal

Redeploy `vote.orangesync.tech` from latest main (v0.1.63), deploy Rust audit proxy
worker, create E2E test suite, then walk through creating a dinner vote with
5 voters using private invite links.

## Current State

- Deployed version: v0.1.52 (May 4)
- Latest main: v0.1.63 (May 25) — 6 private invite bug fixes, redesigned observer, relay hints
- Build tools on VPS: Node.js v20, cargo 1.95, wasm-pack 0.15
- Voting keypair: `nsec1s6y8ud4t...` / `npub1kvcdvk9k...`

## Checklist

### Phase 1: Redeploy from latest main

- [ ] Run `ansible-playbook playbooks/17-auditable-voting.yml`
  - Git pulls latest main (v0.1.63)
  - Rebuilds WASM core + coordinator core
  - Rebuilds Vite static site
  - Deploys to `/srv/tollgate/auditable-voting/`
  - Deploys to nsite
- [ ] Verify `vote.orangesync.tech` serves new version
- [ ] Verify nsite updated

### Phase 2: Create E2E test repo

- [ ] Create `/home/c03rad0r/auditable-voting-tests/`
- [ ] `package.json` with `@playwright/test` dependency
- [ ] `playwright.config.ts` — desktop + mobile, baseURL from env
- [ ] `fixtures/index.ts` — Nostr auth mock for voter context
- [ ] `helpers/relay.ts` — relay connectivity checks
- [ ] `tests/smoke.spec.ts` — page load, all HTML routes, static assets
- [ ] `tests/observer.spec.ts` — landing page, questionnaire list
- [ ] `tests/coordinator.spec.ts` — role selection, questionnaire build, publish
- [ ] `tests/voter.spec.ts` — private invite link flow, vote submission
- [ ] Run tests locally against `vote.orangesync.tech`, verify passing
- [ ] Initialize git repo, push to ngit remotes

### Phase 3: Create voting_worker Ansible role

- [ ] `ansible/roles/voting_worker/defaults/main.yml`
- [ ] `ansible/roles/voting_worker/tasks/main.yml`
  - Build worker from source in auditable-voting repo
  - Generate worker keypair if not exists
  - Create systemd service template
  - Store keypair in `/opt/tollgate/.env`
- [ ] `ansible/roles/voting_worker/templates/tollgate-voting-worker.service.j2`
- [ ] `ansible/roles/voting_worker/handlers/main.yml`
- [ ] `ansible/playbooks/28-voting-worker.yml`
- [ ] Add to `setup-all.yml` after `auditable_voting`

### Phase 4: Create auditable_voting_tests Ansible role

- [ ] `ansible/roles/auditable_voting_tests/defaults/main.yml`
  - Repo URL: `http://localhost:7334/npub12m5exm2uk3xa674cc5r0hlyvccs5xxn7qv83ezuteefv5972nquq4j4szl/auditable-voting-tests.git`
- [ ] `ansible/roles/auditable_voting_tests/tasks/main.yml`
  - Clone from ngit
  - npm install
  - Install Playwright chromium
  - Run E2E tests
- [ ] `ansible/playbooks/29-auditable-voting-tests.yml`
- [ ] Add to `setup-all.yml` after `voting_worker`

### Phase 5: Deploy and verify

- [ ] Redeploy auditable-voting (Phase 1)
- [ ] Deploy voting-worker (Phase 3)
- [ ] Push test repo to ngit (Phase 2)
- [ ] Run auditable-voting-tests playbook (Phase 4)
- [ ] All E2E tests pass

### Phase 6: Interactive walkthrough — Dinner Vote (5 voters)

You do these steps in your browser while I guide you:

1. [ ] Open `https://vote.orangesync.tech/simple.html`
2. [ ] Select **Coordinator** role → Continue
3. [ ] In **Setup** tab:
   - Title: "Family Dinner Vote"
   - Q1 (single choice): "What time should we have dinner?" — 18:00, 19:00, 20:00
   - Q2 (single choice): "What's for dinner?" — Pizza, Pasta, Salad, Surprise me
   - Expected voters: 5
   - Configure relay hints: `wss://relay.orangesync.tech`, `wss://ngit.orangesync.tech`
4. [ ] Publish questionnaire — note the questionnaire ID
5. [ ] Configure the delegate worker:
   - Copy the COORDINATOR_NPUB from Settings tab
   - Set in `/opt/tollgate/.env` as `VOTING_WORKER_COORDINATOR_NPUB`
   - Start worker: `sudo systemctl restart tollgate-voting-worker`
6. [ ] In **Voters** tab — generate 5 private invite links
7. [ ] Distribute links via WhatsApp/email/SMS
8. [ ] Each voter: click link → auto-whitelisted → answer 2 questions → submit
9. [ ] Worker auto-issues blind credentials, verifies submissions
10. [ ] After 5/5 votes: worker auto-closes questionnaire, publishes results
11. [ ] Check results in coordinator Voters tab or observer landing page

### Phase 7: Update docs and commit

- [ ] Update PROGRESS.md
- [ ] Update PLAN.md
- [ ] Update setup-all.yml
- [ ] Commit and push

## Relays

For the worker and questionnaire relay hints:

| Relay | Purpose |
|-------|---------|
| `wss://relay.orangesync.tech` | Primary (our relay, fastest) |
| `wss://ngit.orangesync.tech` | Secondary (our relay) |
| `wss://relay.nostr.net` | Public (author's default) |
| `wss://nos.lol` | Public (author's default) |
| `wss://relay.damus.io` | Public (large, reliable) |

## Files Changed

| File | Change |
|------|--------|
| `ansible/roles/voting_worker/*` | New role — build + deploy audit proxy worker |
| `ansible/roles/auditable_voting_tests/*` | New role — clone + run E2E tests |
| `ansible/playbooks/28-voting-worker.yml` | New playbook |
| `ansible/playbooks/29-auditable-voting-tests.yml` | New playbook |
| `ansible/playbooks/setup-all.yml` | Add both new roles |
| `ansible/inventory/group_vars/all.yml` | Worker + test vars |
| `/home/c03rad0r/auditable-voting-tests/` | New standalone test repo |

## Worker Configuration

Environment variables for the systemd service:

```
WORKER_NSEC=<generated by Ansible>
COORDINATOR_NPUB=<set at vote creation time>
WORKER_RELAYS=wss://relay.orangesync.tech,wss://ngit.orangesync.tech,wss://relay.nostr.net,wss://nos.lol,wss://relay.damus.io
WORKER_STATE_DIR=/opt/tollgate/auditable-voting/worker-state
```
