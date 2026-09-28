# Auditable Voting Family Test — Implementation Plan

## Goal

Onboard a 75-year-old family member to create a poll as coordinator, invite 5 participants via unique private invite links, participate as a voter, and help others vote.

## Context

- **Repo**: `https://github.com/tidley/auditable-voting.git` (main branch, commit `272fb95`)
- **Deployment**: `https://vote.orangesync.tech` on VPS2 `23.182.128.51` (Hetzner, hostname `testserver2`)
- **Source on VPS2**: `/opt/tollgate/src/auditable-voting/` — cloned from `tidley/auditable-voting.git`
- **Static files on VPS2**: `/srv/tollgate/auditable-voting/` — served by Caddy
- **VPS1 (66.92.204.38) is DOWN** — unreachable since ~Jun 2026. VPS2 is the active server.
- **23.182.128.226 also DOWN** — old IP, removed from DNS.
- **Caddy on VPS2**: `vote.orangesync.tech` → `root * /srv/tollgate/auditable-voting`, file_server, try_files fallback
- **Cloudflare DNS**: `vote.orangesync.tech` single A record → `23.182.128.51`
- **Coordinator npub**: `npub159dan6t2v84xa4ert70w6fvtp8s5v05jfdztp0w8h3dgyxcv0ywq53vu8h` (we are the coordinators)
- **75-year-old family member**: will be a voter (not coordinator) to simplify the flow
- **Audit proxy**: runs on each VPS with its own nsec, delegated by coordinator, handles blind signing
- **Other LLM session**: `npub1vc8y8836f2sjsamt8tsms74gygf7ff9z7k7m75hv7yl8uysajweqs5u87k`
- **My npub**: `npub12m5exm2uk3xa674cc5r0hlyvccs5xxn7qv83ezuteefv5972nquq4j4szl`

## Architecture (tidley's Code)

### Question Types
- `yes_no` — binary yes/no
- `multiple_choice` — single or multi-select
- `rank` — ranked choice
- `free_text` — open text

### Invite Flow
1. Coordinator creates questionnaire via `simple-coordinator.html`
2. Coordinator generates bearer invite codes (one per voter)
3. Each voter gets a unique URL: `https://vote.orangesync.tech/simple.html?q=<electionId>&coordinator=<coordNpub>&invited=<voterNpub>&invite_code=<privateCode>&login=1&role=voter`
4. Voter opens link → auto-logged in with browser-generated identity → sees ballot → votes → done
5. First vote per identity wins (duplicate nullifier rejection)

### Blind Signature Credentials
- Voters get blind-signed tokens (no coordinator knows who voted what)
- Nullifiers prevent double-voting
- Coordinator only sees: accepted/rejected vote counts

## Checklist

### Phase 0: VPS Migration to VPS2 (Jun 2026)
- [x] Diagnosed: VPS1 (66.92.204.38) unreachable, DNS round-robin causes ~2/3 of requests to fail
- [x] Confirmed VPS2 (23.182.128.51) has correct code + Caddy config + all assets
- [x] Confirmed VPS2 has `tidley/auditable-voting.git` origin, commit `3ab3079`
- [x] Identified 3 Cloudflare DNS A records: 2 dead (66.92.204.38, 23.182.128.226), 1 alive (23.182.128.51)
- [x] Updated VPS2 to latest `tidley/auditable-voting` main (`3ab3079` → `272fb95`)
- [x] Removed dead DNS A records from Cloudflare (keep only 23.182.128.51)
- [x] Verified `vote.orangesync.tech` loads reliably (single IP, no round-robin failures)
- [ ] Browser test: open `simple-coordinator.html`, confirm page renders and is interactive

### Phase 1: Deployment (Original — completed on VPS1, now on VPS2)
- [x] Check Vite config on VPS includes `simple.html` and `simple-coordinator.html` in build
- [x] Rebuild frontend on VPS with latest source
- [x] Deploy static files to Caddy (`/srv/tollgate/auditable-voting/`)
- [x] Verify all 5 HTML pages return HTTP 200 (`index.html`, `vote.html`, `dashboard.html`, `simple.html`, `simple-coordinator.html`)

### Phase 2: Audit Proxy Deployment
- [x] Updated coordinator npub in `.env` to `npub159dan6t2v84xa4ert70w6fvtp8s5v05jfdztp0w8h3dgyxcv0ywq53vu8h`
- [x] Updated `voting_worker` Ansible role relay list (public relays only, VPS-agnostic)
- [x] Updated playbook `28-voting-worker.yml` to target `vps2` host
- [x] Built worker binary from source on VPS2 (v0.1.16)
- [x] Auto-generated VPS2 worker keypair (nsec `nsec1dwj0vg...`, npub `npub1crzlqjp...`)
- [x] Deployed systemd service `tollgate-voting-worker.service` on VPS2
- [x] Worker running — connected to 7 relays, heartbeating, polling for delegation
- [ ] Verify worker announces in coordinator browser UI (requires coordinator session)
- [ ] Deploy audit proxy worker on VPS1 when it comes back online (separate nsec)

### Phase 2b: CSS Fix PR (c03rad0r → tidley/auditable-voting)
- [x] Diagnosed: `.simple-delegate-command` block has long unbroken strings (nsec, npub) that push layout wider than 960px container on desktop
- [x] Root cause: no `overflow-x` or `word-break` on `.simple-delegate-command` (line ~2020 in `styles.css`)
- [x] Fix identified: add `overflow-x: auto; word-break: break-all;` to `.simple-delegate-command`
- [x] Fork `tidley/auditable-voting` to `c03rad0r/auditable-voting`, synced main to upstream (`b62502e`)
- [x] Created branch `fix/delegate-command-overflow` from `main`
- [x] Applied CSS fix in `web/src/styles.css`
- [x] Built locally (`npm run build`) and verified fix in built CSS
- [x] Pushed branch and opened PR: https://github.com/tidley/auditable-voting/pull/2
- [x] Hot-fix deployed on VPS2 (rebuilt from fix branch, new CSS live at `vote.orangesync.tech`)

### Phase 3: Test Election (requires browser)
- [ ] Open coordinator app at `https://vote.orangesync.tech/simple-coordinator.html`
- [ ] Create a test questionnaire (add yes/no, choice, ranked, text questions)
- [ ] Generate 5 bearer invite codes
- [ ] Test one invite link end-to-end as a voter (open in another browser/incognito)
- [ ] Verify vote appears in coordinator dashboard

### Phase 4: Onboarding Guide
- [x] Write step-by-step guide for 75-year-old (coordinator + voter) → `docs/auditable-voting-onboarding-guide.md`
- [x] Include: how to create poll, how to share invite links, how to vote, how to help others
- [x] Keep language simple, avoid jargon

### Phase 5: Send Context to Other LLM Session
- [x] Draft Nostr DM with full context
- [x] Send via `nak` NIP-04 encrypted DM → event `c6db83ac...`

### Phase 6: E2E Test (requires browser + participants)
- [ ] Walk through complete flow with 5 simulated voters (5 incognito windows)
- [ ] Verify results tally correctly on coordinator dashboard
- [ ] Verify ranked choice aggregation works

## Notes

### Roles
- **Coordinators**: us (using npub `npub159dan6t2v84xa4ert70w6fvtp8s5v05jfdztp0w8h3dgyxcv0ywq53vu8h`)
- **Voters**: 75-year-old family member + other participants
- **Audit proxy workers**: one per VPS (own nsec), delegated by coordinator, handles blind signing

### Audit Proxy Architecture
- Worker binary: Rust, built from `tidley/auditable-voting/worker/`
- Each VPS gets its own `VOTING_WORKER_NSEC`/`VOTING_WORKER_NPUB` (auto-generated by Ansible)
- Worker connects to public relays (no VPS-specific relays in config, works regardless of which VPS is up)
- Systemd service: `tollgate-voting-worker.service`
- State dir: `/opt/tollgate/auditable-voting/worker-state/`
- Env vars: `WORKER_NSEC`, `COORDINATOR_NPUB`, `WORKER_RELAYS`, `RUST_LOG=info`

### VPS Layout
- **VPS1** (66.92.204.38, Sovereign Hybrid Compute) — DOWN, worker not yet deployed
- **VPS2** (23.182.128.51, Hetzner, hostname `testserver2`) — ACTIVE, serves `vote.orangesync.tech`
- VPS2 runs: Caddy, strfry, CDK mints, blossom, nsite-gateway, ngit, routstr, jitsi, and more (21 containers)
- Caddy env: `CF_API_TOKEN` for Cloudflare DNS-01 TLS

### Relay Setup
- VPS2 has strfry relay at `relay2.orangesync.tech`
- Worker uses public relays only (relay.nostr.net, nos.lol, relay.damus.io, etc.)
- Coordinator and voter apps communicate via Nostr DMs through these relays
