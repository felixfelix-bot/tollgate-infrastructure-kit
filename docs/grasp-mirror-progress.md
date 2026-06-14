# GRASP Mirror Daemon — Progress Tracker

## Current Status: **Running, discovery working, push blocked**

The daemon is deployed and running on `23.182.128.226`. It discovers 75 repos across 3 npubs, clones them from source servers, but git push to `git.orangesync.tech` fails — likely needs authenticated `kind:30618` state event (requires NIP-46 pairing).

---

## Checklist

### Phase 1: Build & Deploy
- [x] Rust project structure created (`/tmp/grasp-mirror/`)
- [x] All source modules implemented (config, db, git_mirror, nostr_mirror, discovery, health, nip46, signing)
- [x] NIP-46 remote signing client (session management, NIP-04 encryption, relay listener)
- [x] Fix compile errors (nip04/nip46 features, API mismatches, borrow checker)
- [x] Fix `secret_key()` → `to_secret_hex()`, `EventBuilder::new` args, async map_err
- [x] Build succeeds on VPS with Rust 1.95.0 (warnings only, no errors)
- [x] Binary installed at `/usr/local/bin/grasp-mirror`
- [x] Systemd service configured and enabled (`grasp-mirror.service`)
- [x] Config at `/etc/grasp-mirror/config.toml`
- [x] Env file at `/etc/grasp-mirror/env` with `MIRROR_NPUBS`

### Phase 2: Discovery & Relay Connectivity
- [x] Service starts and connects to relays
- [x] NIP-46 sessions initialized (3 sessions, all unpaired)
- [x] Health endpoint live at `http://localhost:7335/health`
- [x] Fix: relay pool returns empty when most relays dead
  - Root cause: `relay.orangesync.tech` and `ngit.orangesync.tech` have no event data
  - Data lives on `git.orangesync.tech` (the GRASP server relay)
  - Fix: use dedicated discovery client with only `wss://git.orangesync.tech`
- [x] Fix: suppress noisy relay pool retry logs (`nostr_relay_pool=warn`)
- [x] **75 repos discovered** (33 + 29 + 13 across 3 npubs)
- [x] NIP-11 server verification: `git.orangesync.tech` verified (GRASP-01, GRASP-02, GRASP-05, v1.0.2)

### Phase 3: Git Mirror (In Progress)
- [x] Repos cloned from source URLs (some succeed, some fail — source URLs down)
- [ ] **Git push to `git.orangesync.tech` failing** — all pushes rejected
  - Likely cause: GRASP server requires authenticated push (kind:30618 state event)
  - State event signing requires NIP-46 pairing (Amber)
  - Error: `failed to push mirror to https://git.orangesync.tech/...`
- [ ] Investigate GRASP server push auth requirements
- [ ] Verify clone URL format matches what GRASP expects

### Phase 4: NIP-46 Pairing (Blocked — requires user action)
- [ ] Pair npub `c3e23eb5...` via Amber
  - URI: `nostrconnect://2839411006e06e1c83b9cbd29a63ae7f58444e2fe03fa04e720e4eaff6e28fd2?metadata={"name":"grasp-mirror"}&relay=wss://relay.orangesync.tech&relay=wss://ngit.orangesync.tech`
- [ ] Pair npub `2c8db3b4...` via Amber
  - URI: `nostrconnect://92d7842be1b30c4ea627447c30ec6fe555b6b0139136436233e2ee0aaa72990f?metadata={"name":"grasp-mirror"}&relay=wss://relay.orangesync.tech&relay=wss://ngit.orangesync.tech`
- [ ] Pair npub `56e9936d...` via Amber
  - URI: `nostrconnect://9c273012cd08569fe3e8081643243b58a863707dff90c06cf156cf65703f50a4?metadata={"name":"grasp-mirror"}&relay=wss://relay.orangesync.tech&relay=wss://ngit.orangesync.tech`
- [ ] Verify pairing in health endpoint (`connected: true`)
- [ ] End-to-end test: sign kind:30618, push succeeds

### Phase 5: Nostr Event Mirror
- [ ] Forward repo events (kind:30617, issues, PRs, comments) to target servers
- [ ] Sync all events for tracked npubs
- [ ] Verify event persistence in target server relays

### Phase 6: Production Hardening
- [ ] Fix NIP-46 relay config (use `wss://git.orangesync.tech` instead of `relay.orangesync.tech`)
- [ ] Add more GRASP servers when they come online
- [ ] Test retry/backoff on failed clones
- [ ] Add monitoring/alerting
- [ ] Switch to Ansible-based deployment for ongoing updates

---

## Key Findings

1. **Relay data location**: Event data for these npubs lives on `wss://git.orangesync.tech` (the GRASP server relay), NOT on `wss://relay.orangesync.tech` or `wss://ngit.orangesync.tech`. These relays appear to be different services (Tollgate Infrastructure Relay, ngit relay) that don't carry GRASP event data.

2. **nostr-sdk pool behavior**: `fetch_events()` returns empty when most relays in the pool are dead. Use a separate client with only working relays, or use `fetch_events_from()` with known-good URLs.

3. **Push auth**: GRASP servers likely require `kind:30618` state events for push authorization. Without NIP-46 pairing, the daemon can't sign state events, so all pushes fail.

---

## Architecture

```
VPS (23.182.128.226)
├── grasp-mirror binary (/usr/local/bin/)
├── config.toml (/etc/grasp-mirror/)
├── env file (/etc/grasp-mirror/env)
├── SQLite DB (/var/lib/grasp-mirror/mirror.db)
├── Bare repos (/var/lib/grasp-mirror/repos/)
└── systemd service (grasp-mirror.service)
    ├── Polls every 300s
    ├── Discovers repos via wss://git.orangesync.tech
    ├── Clones from source URLs (relay.ngit.dev, gitnostr.com, etc.)
    ├── Signs state events via NIP-46 (Amber on phone)
    └── Pushes to target GRASP servers
```
