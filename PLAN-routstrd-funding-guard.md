# PLAN: routstrd Real-Ecash Funding Guard

**Date:** 2026-08-20
**Objective:** Make routstrd (local Cashu LLM market daemon, `localhost:8008`) a genuine
quota-exhaustion fallback for the LLM proxy by holding **real ecash** (minibits +
cubabitcoin) in its cocod wallet, and keep it funded automatically:

- Floor: **>= 5000 network-spendable sats** at all times
- On breach: surface a fixed **10k-sat Lightning top-up invoice** to the user
  (notify-send persistent popup + `lightning:` URI + espeak voice alert)
- Everything deployed via **Ansible** (this kit) so the setup is reproducible

**Context (verified 2026-08-20):**
- routstrd daemon: user systemd unit, bun, `:8008` (this machine, T14Gen5)
- Wallet: cocod daemon at `~/.cocod/cocod.sock`; holds 56,998 sats **orangesync
  testnut ecash** (not accepted by network nodes) + minibits configured at 0
- Proxy wiring already correct: `zai_proxy.py` fetches routstrd `/v1/models`
  (auth-free, OpenRouter-format per-token USD pricing), blends 3:1, 10-min cache;
  failover candidates cost-sorted per model (zai_proxy.py:3590, 4566). z.ai flat
  plan stays first (marginal cost ~0); routstrd = last-resort network pool.
- Nostr network nodes settle only in ecash from real mints they trust — hence
  minibits + cubabitcoin (same mints our public routstr node uses).

**Decisions (user-confirmed):**
- D1: Initial funding by pasted cashu token (user already holds minibits ecash);
  Lightning invoice path is the automated fallback
- D2: Fixed 10k-sat invoice when floor breached
- D3: Second real mint cubabitcoin added alongside minibits
- D4: orangesync sats never count toward the floor (testnut, not network-spendable)

## Checklist

### A. Wallet (manual, one-time) — DONE with caveats
- [x] A1: `routstrd wallet mints add https://mint.cubabitcoin.org` (correct URL is .org not .com)
- [x] A2: Received user's 21-sat minibits test token via `routstrd wallet receive cashu <token>`
- [x] A3: Verified per-mint balances via cocod socket (minibits=21, cubabitcoin=0)
- [x] A4: **Quarantined orangesync ecash** — removed orangesync from cocod mint list + deleted
  546 orangesync proofs (27 ready @ 56,998 sats + 519 spent) from coco.db. Reason: routstrd's
  `selectMintWithBalance()` picks the first mint with sufficient balance → orangesync (56,998)
  always won over minibits (21) → all payment tokens were orangesync (rejected by network nodes).
  Proofs backed up to `~/.cocod/orangesync_proofs_backup.json` + full DB backup.
- [x] A5: **Cleared 11 stale per-provider API keys** from `~/.routstrd/routstr.db` (sdk_storage
  table, key='api_keys'). These were pre-funded orangesync tokens cached from the fakewallet era.
  Without clearing, the daemon reused them instead of creating fresh minibits tokens.
- [x] A6: **Cleared 1,787 stuck receive operations** from coco.db (state 'executing' → 'rolled_back').
  These were fakewallet-era refund replays that caused cocod to loop on boot (514+ recovery events
  per startup, socket never came up).

### B. Live settlement test — WIRING PROVEN, settlement blocked by funding amount
- [x] B1: Cheapest network model: gpt-5.6-luna @ blazelight (1 sat/request max cost)
- [x] B2: Fired completion request — daemon correctly created a **minibits** token (not orangesync)
  and sent it to blazelight. Token preview decodes to `https://mint.minibits.cash/Bitcoin`. ✓
- [x] B3: **Settlement COMPLETED 2026-08-22** — see PLAN-cashu-ts-v4-token-fix.md. Root causes
      fixed: (1) cashu-ts v3.6.2 CBOR decoder rejected proofs with amounts > 23 (fixed by
      ansible-managed symlink to global cashu-ts 4.8.0); (2) funding: 512-sat minibits token
      received after fix. gpt-5.6-luna call returned OK, 512 -> 505 sats paid through a network
      node. routstrd is now a WORKING quota-exhaustion fallback with real ecash.

### C. Ansible role `routstrd_funding_guard` (this kit)
- [x] C1: Role `roles/routstrd_funding_guard` — files: guard script; tasks: routstrd CLI
      present, cubabitcoin mint present (idempotent), script deployed to
      `~/merchant-routing-engine/scripts/routstrd_funding_guard.py`, cron `*/5`
      (ansible `cron` module, named), state dir `~/.hermes/bot/`
- [x] C2: Playbook `playbooks/46-routstrd-funding-guard.yml` — hosts localhost
      (t14gen5 pattern: `connection: local`, `become: false`)
- [x] C3: Run playbook; verified idempotent on second run (0 changed)
- [x] C4: Guard logic verified live (21 sats < 5k floor → fires 10k invoice at cubabitcoin,
      notify-send, `~/.hermes/bot/routstrd_topup_invoice.txt`, espeak once)
- [x] C5: Anti-spam verified: second run within 2h does NOT create a new invoice (silent,
      same invoice reused)

### D. Observability (hermes side, manual edit)
- [x] D1: Guard writes `routstrd_network` row into `api_burn.db provider_balances`
      (network_sats in raw_json) every 5 min
- [x] D2: `efficiency-monitor.py` gains `check_routstrd_funds` (WARN < 5000 network sats)
- [x] D3: Next monitor run shows the new check: `[WARN] routstrd network ecash low`

### E. Version control
- [x] E1: Commit + push kit (plan, role, playbook, daemon.py, issue_to_friend.py)
      → pushed to felixfelix remote (commit e7cf77a)
- [x] E2: mint-auth-processor git init + commit (payment_processor_server.py + proto + pb2 stubs)
- [ ] E3: Create remote repo for mint-auth-processor + push (needs user to create GitHub repo)

### F. Follow-ups (out of scope here)
- [ ] F1: User pays 10k invoice when convenient (floor maintained thereafter)
- [ ] F2: Consider same guard pattern for VPS2 proxy migration (Phase 2 of hermes plan)

## Guard design (reference)

```
every 5 min (cron):
  bal = cocod /balance                      # {mint_url: {sats: N}}
  network_sats = sum(sats where mint != mint.orangesync.tech)
  write provider_balances row ('routstrd_network', raw_json={network_sats, btc_usd})
  if network_sats >= 5000: clear transition flag; exit
  state = load ~/.hermes/bot/.routstrd_funding_guard_state.json
  if fresh invoice (< 2h) in state: exit    # anti-spam
  mint = lower of (minibits, cubabitcoin) by balance
  invoice = `routstrd wallet receive bolt11 10000 --mint-url $mint`
  save state {invoice, mint, ts}
  write ~/.hermes/bot/routstrd_topup_invoice.txt
  notify-send (persistent, includes lightning: URI)  + espeak once per transition
```
