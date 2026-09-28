# PLAN: Buzz ↔ Signal Bridge for Sitarani's Protein-RNA Groups

**Date:** 2026-08-22
**Goal:** Sitarani starts working with hermes **right away** via Buzz
(desktop client, her existing npub) in her two groups, while her dedicated
`hermes-sitarani` container is still being finished. The local manager
hermes keeps answering in the existing Signal groups (full session context,
dedicated system prompts) — the bridge mirrors both directions.

## Verified facts (2026-08-22)

- Signal groups live on the laptop's signal-cli daemon (0.14.5, JSON-RPC
  `127.0.0.1:8080`, account `+18102940908`):
  - `Protein-RNA interactome analysis` — gid `BZ3dOhXodEKJ1xKm/l0qlM/hzgVHAv9CSNf06nswq8Q=`
  - `Protein-RNA go analysis` — gid `+HBokV06uG2WMZZLqdSrow7OLhTJAJv+IB51hUMg9SU=`
  - Members: Felix (admin, uuid `cc5bdaa4…`), unknown member (uuid
    `35a17b31…`), the hermes-linked account (`+18102940908` / `346ebe24…`)
- Local manager hermes serves both groups with live sessions + dedicated
  system prompts (`~/.hermes/profiles/manager/config.yaml:901,959`).
  `SIGNAL_GROUP_ALLOWED_USERS=*`, account in `SIGNAL_GROUP_ADMIN_SENDERS`.
- Gateway promotes sync-with-groupInfo envelopes into processable
  dataMessages (gateway/platforms/signal.py:590-608) → messages the bridge
  sends via the same signal-cli daemon **are processed by hermes**.
- Buzz stack live on VPS2: `wss://relay.orangesync.tech` (buzz-relay), NIP-29
  group mechanics proven by `tests/e2e-buzz-hermes.sh` (kind 9 create,
  put-user, chat send, nak req --auth).
- Sitarani's existing npub: `npub1a3um269aaf3u5cy37kuykrrrnsg2pyv7za06pxjduv25lq5sdujs2qmdj6`
- `hermes-sitarani` container stays OUT of the bridge groups (no
  double-answering; it takes over when finished).

## Architecture

```
[Sitarani's Buzz desktop] ⇄ wss://relay.orangesync.tech (NIP-29 groups)
                                   ⇅ (nak req / nak event)
[buzz_signal_bridge.py — laptop, systemd user unit]
   - Signal→Buzz: signal-cli SSE (/api/v1/events) → nak event -k 9
   - Buzz→Signal: nak req -k 9 --tag h=<gid> → JSON-RPC send (groupId)
   - Loop prevention: content-hash dedup (pre-registered before send),
     sent-timestamp set, skip own npub on buzz side
        ⇅ (127.0.0.1:8080)
[signal-cli] → [hermes-gateway (manager)] → existing Protein-RNA sessions
```

Labels: Signal→Buzz `[signal] Felix: …` (sourceName / known-uuid map;
account-sourced syncs = hermes replies → `[signal] hermes: …`).
Buzz→Signal `[buzz] Sitarani: …` (her npub) / `[buzz] <npub8>: …` (others).

## Checklist

### Phase 0 — Pivot discoveries (2026-08-22, during implementation)
- [x] 0.1: An earlier session today already created the two buzz channels
      with deterministic UUIDs (namespace = community a3312780):
      `e6616f1a-e0f5-5e3a-bd5d-76a2d8921922` (interactome),
      `b5f8f21d-07cb-58a8-a33c-7c9c1d4f08f7` (go analysis) — created by the
      relay owner key. Reference:
      `~/.hermes/profiles/manager/skills/buzz-cli/references/manager-gateway-buzz-groups.md`
      (its design = manager gateway answers IN buzz; superseded by this
      plan's user-approved "hermes answers on Signal" decision).
- [x] 0.2: My nak-created "groups" (bridge30bd…, bridge9692…) were never
      real channels — the relay restricts channel creation to the owner
      key. Phantom artifacts only; nothing to clean server-side.
- [x] 0.3: **Owner key found**: `BUZZ_RELAY_PRIVATE_KEY` in the buzz-relay
      container env = nsec of bae18cf1 (channel owner) → full admin control
      over channel membership.
- [x] 0.4: Key map: `1a31189f`=Felix, `6af6fa39`=hermes-sitarani container
      nsec (the reference doc mislabels it "Sitarani"; her personal key per
      friends-v2 plan = npub1a3um269…, hex ec79b568), `c446470b`=unknown
      third member, `4ae5fe8e`=manager nostr key (=nostr_nsec.txt=
      BUZZ_PRIVATE_KEY, shared with the plebeian buzz identity).
- [x] 0.5: Manager gateway nostr adapter is ERROR-LOOPING: config.yaml
      `nsec_path: ~/...` (tilde) is never expanduser'd by nostr.py:189 →
      "nsec file not found". Also the adapter's groups list includes the
      two protein channels (would double-answer with the bridge).
      Fix: absolute path + remove protein channels from groups
      (config.yaml both blocks + manager .env NOSTR_GROUPS).

### Phase A — Channel membership (existing channels, owner key)
- [x] A1: Bridge nsec generated →
      `~/.hermes/profiles/manager/keys/buzz_bridge_nsec.txt` (npub
      4906b9d5…)
- [x] A2: Use EXISTING channels e6616f1a (interactome) + b5f8f21d (go)
- [x] A3: put-user bridge npub + Sitarani npub1a3um269 (member) in both
      channels, signed as owner (BUZZ_RELAY_PRIVATE_KEY). NOTE: `nak group
      put-user` fails the relay's NIP-42 auth wall — raw `nak event -k 9000
      -t h=<chan> -t p=<pubkey> --auth --sec <owner>` works (the reference
      doc's method).
- [x] A4: Verified in DB: 5 members per channel (owner, Felix, c446470b,
      bridge, Sitarani)

### Phase B — Gateway nostr config fix + bridge daemon (laptop)
- [x] B0: Precheck PASSED — config.yaml fixed (absolute nsec path —
      nostr.py never expanduser's the tilde; protein channels removed from
      groups lists so the manager nostr adapter doesn't double-answer),
      gateway restarted, JSON-RPC `send` into the go-analysis group →
      hermes processed + replied under the EXISTING session
      (20260822_223622_4452bdc4).
- [x] B1: `~/.hermes/bot/buzz_signal_bridge.py` deployed (config:
      `~/.hermes/bot/buzz_signal_bridge.json`; state:
      `~/.hermes/bot/.buzz_signal_bridge_state.json`)
- [x] B2: `~/.config/systemd/user/buzz-signal-bridge.service` (enabled)
- [x] B3: Smoke-run OK — both buzz streams + signal SSE connected.
      Pitfall found: the account `+` MUST be URL-encoded in the SSE URL
      (`quote(account, safe='')`) or signal-cli returns 400.

### Phase C — Sitarani handoff (user relays)
- [ ] C1: Give her: relay URL `wss://relay.orangesync.tech`, the two group
      ids, onboarding guide §3 (Buzz desktop, import existing key
      npub1a3um269…)

### Phase D — E2E verification
- [x] D1: Buzz→Signal: owner-key message in the interactome channel →
      bridge forwarded → hermes replied in the Signal group under the
      existing session (reply-quoted, context intact)
- [x] D2: Signal→Buzz: hermes/Felix replies mirrored into the buzz
      channels ("[signal] Felix: 4" observed live)
- [x] D3: Loop check OK across the E2E round trips (echo suppression via
      timestamp + content-hash registration); no storms observed

### Phase E — Docs + reproducibility
- [x] E1: This checklist updated; quirks: nsec tilde bug, SSE URL encoding,
      put-user auth wall, phantom nak groups (relay restricts channel
      creation to the owner key), reference-doc key mislabel
      (manager-gateway-buzz-groups.md calls 6af6fa39 "Sitarani" — it is
      actually the hermes-sitarani CONTAINER key; Sitarani's personal key
      is ec79b568 / npub1a3um269…)
- [x] E2: Ansible role `buzz_signal_bridge` + playbook
      `47-buzz-signal-bridge.yml` (local-machine, same pattern as 46-);
      script in role files/, unit + pair-config templates, nsec generated
      ONCE and kept (npub = channel membership identity). ALSO automates
      the gateway nostr config normalization (absolute nsec path,
      bridged channels excluded from the adapter's groups, one-time
      backup, gateway-restart handler only on change). Syntax-check +
      live run + idempotent rerun (changed=0) verified.
      Related automation: `48-routstr-node-access.yml` (SSH tunnel to the
      VPS2 node + ROUTSTR_BASE env + fixed balance_collectors.py deploy)
      and `49-routstr-node-config.yml` (node providers + payout LNURL via
      admin API, secrets from kit .env, idempotent — changed=0 verified).

## Known limitations (v1)

- Live-only Signal ingestion (no backfill while bridge is down — the
  gateway already consumes the same SSE stream, so nothing is lost to
  hermes; only buzz misses the mirror for that window).
- Text-only (attachments placeholder).
- The unknown Signal member (35a17b31…) forwards with a generic label;
  their messages are NOT processed by hermes (not in
  SIGNAL_GROUP_ADMIN_SENDERS) — only mirrored to buzz.
- If Felix writes from the +18102940908 device (not via gateway/bridge),
  such syncs forward labeled `hermes` — acceptable mislabel in v1.

## Rollback

- `systemctl --user stop buzz-signal-bridge.service` — bridge gone, Signal
  side untouched. Buzz groups remain (harmless; reusable later).
