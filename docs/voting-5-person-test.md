# Voting Client 5-Person Test Plan

## Goal

Fix the worker's NIP-59 gift-wrap failure, then test auditable voting end-to-end with 5 real people using private invite links.

## Current State

- App live at `https://vote.orangesync.tech` (v0.1.62)
- Worker running, connected to 5 relays, but heartbeat fails: `worker status gift-wrap construction failed`
- Worker state: empty elections, ready to receive delegation
- COORDINATOR_NPUB set to match voting keypair (`npub1kvcdvk9kvmk2x0kdvrl9zzx5ug7lcgj0zv49gllpcqyxfnakyzdqlf29fn`)
- 54/54 E2E tests passing (smoke, observer, coordinator, voter — desktop + mobile)

## Root Cause Analysis

The worker calls `EventBuilder::private_msg(&signer, recipient, content, tags).await` which internally:
1. Creates a rumor (unsigned event)
2. Calls `signer.nip44_encrypt()` to encrypt the rumor
3. Wraps in a seal event
4. Wraps in a gift-wrap event

The error "gift-wrap construction failed" is a generic `.with_context()` wrapper that swallows the actual nostr-sdk error. Need to surface the real error to diagnose.

## Checklist

### Phase 1: Diagnose Gift-Wrap Failure

- [x] Edit worker `main.rs` — change heartbeat error handling to log the actual `{:?}` error
- [x] Rebuild worker binary on VPS (`cargo build --release`)
- [x] Restart worker, capture the actual nostr-sdk error
- [x] Identify root cause: **`NIP59(Signer(SignerError("malformed public key")))`** — Ansible keygen used `hashlib.sha256(sk)` instead of Ed25519 key derivation to generate npub from nsec. Keypair was invalid.

### Phase 2: Fix and Rebuild

- [x] Fix: correct npub derived from existing nsec using `nacl.signing.SigningKey`
- [x] Update VOTING_NPUB and VOTING_WORKER_COORDINATOR_NPUB in `.env` on VPS
- [x] Update worker systemd service with corrected COORDINATOR_NPUB
- [x] Restart worker, verify zero errors (heartbeat succeeding, no gift-wrap failures)
- [x] Fix Ansible keygen in both `auditable_voting` and `voting_worker` roles (use NaCl instead of hashlib.sha256)
- [ ] Commit fix to tollgate-infrastructure-kit

### Phase 3: 5-Person Dinner Vote Test

- [ ] Coordinator opens `https://vote.orangesync.tech/simple.html`
- [ ] Select **Coordinator** role
- [ ] Build questionnaire:
  - Title: "Family Dinner Vote"
  - Q1 (single choice): "What time should we have dinner?" — 18:00, 19:00, 20:00
  - Q2 (single choice): "What's for dinner?" — Pizza, Pasta, Salad, Surprise me
  - Expected voters: 5
  - Relay hints: `wss://relay.orangesync.tech`, `wss://ngit.orangesync.tech`
- [ ] Publish questionnaire — note the questionnaire ID
- [ ] Verify worker picks up delegation config (check worker logs)
- [ ] In **Voters** tab — generate 5 private invite links
- [ ] Distribute links to 5 people
- [ ] Each voter: click link → auto-whitelisted → answer 2 questions → submit
- [ ] Worker verifies submissions (check worker logs for "accepted" entries)
- [ ] After 5/5 votes: worker auto-closes questionnaire, publishes results
- [ ] Check results in coordinator Voters tab
- [ ] Check results visible to observer on landing page

### Phase 4: Update Docs and Commit

- [ ] Update PROGRESS.md with test results
- [ ] Update PLAN.md if needed
- [ ] Commit and push all changes

## Worker Key Facts

- Worker nsec: `nsec1_REDACTED_worker_key`
- Worker npub: `npub17dhf0fsn43d7x7h93q7m8w4pzwkmyf93pnfkdmm87jx8sk55k5pqjnvgjs`
- Coordinator npub: `npub1kvcdvk9kvmk2x0kdvrl9zzx5ug7lcgj0zv49gllpcqyxfnakyzdqlf29fn`
- nostr-sdk: 0.44.1 (with nip59 feature)
- nostr crate: 0.44.2
- Relays: `wss://relay.orangesync.tech`, `wss://ngit.orangesync.tech`, `wss://relay.nostr.net`, `wss://nos.lol`, `wss://relay.damus.io`
- Worker binary: `/opt/tollgate/auditable-voting/worker/auditable-voting-worker`
- Worker source: `/opt/tollgate/src/auditable-voting/worker/`
- Worker state: `/opt/tollgate/auditable-voting/worker-state/state.json`

## Relays

| Relay | Purpose |
|-------|---------|
| `wss://relay.orangesync.tech` | Primary (our relay, fastest) |
| `wss://ngit.orangesync.tech` | Secondary (our relay) |
| `wss://relay.nostr.net` | Public (author's default) |
| `wss://nos.lol` | Public (author's default) |
| `wss://relay.damus.io` | Public (large, reliable) |

## Architecture

```
Coordinator (browser)                    Worker (VPS systemd)                Voters (5 browsers)
┌─────────────────────┐                 ┌──────────────────┐              ┌──────────────────┐
│ 1. Create election  │                 │ Polling relays   │              │ Click invite link │
│ 2. Build questions  │                 │ every 15s        │              │ Join as voter     │
│ 3. Delegate worker  │──public event──▶│ Apply delegation │              │ Submit blind req  │
│ 4. Generate invites │                 │ Wait for blind   │◀──DM (gift)──│ (NIP-59 DM)       │
│ 5. Share links      │                 │ Sign blind token │──DM (gift)──▶│ Receive token     │
│ 6. View results     │                 │ Verify vote      │◀──public────│ Submit ballot     │
└─────────────────────┘                 │ Close after 5/5  │              └──────────────────┘
                                        │ Publish results  │
                                        └──────────────────┘
```

The gift-wrap failure blocks step 4 (worker can't send signed blind token back to voter via DM).
