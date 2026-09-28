# PLAN: routstr Upstreams (z.ai + OpenRouter) + LNURL Profit Drain

**Date:** 2026-08-22
**Machine:** testserver2 (23.182.128.51, inventory `vps2`)
**Nodes:** `routstr-proxy` (:8009, friends/private, orangesync testnut mint) ·
`routstr-public` (:8010, `ai.orangesync.tech`, real mints)

## Goal

1. Put the new **z.ai coding key** (`abfc7a98…`, pro level, big window ~10.3k
   remaining until ~Aug 27, 5h window currently 100%-used → resets ~19:03 IST)
   into BOTH routstr nodes.
2. Add **OpenRouter** as a reserve upstream on the friends node (new key
   `sk-or-v1-9545…`, $0 usage, expires 2026-11-20; fee 1.27 → direct-OR via
   OXALPHA stays the proxy's primary overflow per user decision).
3. Public node z.ai models priced with **provider_fee 1.27 (27% ≥ 21% floor)**.
4. Operator profits drain via LNURL to
   `npub1gxelz640z3lxc7fcah32erv5wgsstp9009vztvt58zhss6r8efasxg0hdk@npubx.cash`
   (verified: LNURL-pay resolves, 1–100,000 sats range, Cashu lightning address).
   First sweep pays out the **13,972 sats** of accumulated operator fees.
5. **Anti-wipe invariant**: ansible deployments must never overwrite the
   node's `receive_ln_address` with an empty value; repo default for others =
   `tollgate@coinos.io`; our override lives in gitignored kit `.env`.

## Current state (verified)

- Friends node: z.ai provider id=2 with DEAD key (401); Ollama provider id=1
  (paywalled, same account as proxy's Ollama external — resets Monday);
  wallet `sk-hermes…` holds 24,892 testnut sats; admin password unknown
  (kit `ROUTSTR_ADMIN_PASSWORD` rejected).
- Public node: single PPQ provider (dead key); models table empty (catalog
  from refresh); `receive_ln_address` EMPTY (payout loop skips → 13,972 sats
  idle in `routstr_fees`); `min_payout_sat=210`, `payout_interval=900s`.
- Proxy-side: routstr is a failover candidate (tunnel + balance collector
  fixed earlier today) but the node serves nothing.

## Checklist

### Phase 1 — Friends node (:8009)
- [x] 1.1: Admin access recovered — password reset via the app's
      `set_admin_password` (docker exec `/.venv/bin/python`), stored in kit
      `.env` (`ROUTSTR_ADMIN_PASSWORD_FRIENDS`), login → 200
- [x] 1.2: z.ai key swapped on provider id=2 via
      `PATCH /admin/api/upstream-providers/2` (live-reload, no restart);
      Docker secret file `/home/debian/routstr/secrets/zai_api_key.txt`
      updated too (backup kept)
- [x] 1.3: OpenRouter provider added (id=3, generic,
      `https://openrouter.ai/api/v1`, fee 1.27, slug `openrouter`)
- [x] 1.4: Catalog: 7 → 394 models (OR sync + z.ai rows). glm-5.2 completion
      → 200 via node: z.ai candidate first (DB-row priority 4), 429-quota →
      node-internal failover to OR's `z-ai/glm-5.2` — charged 30 sats
      (wallet 24,892 → 24,862). Node glm-5.2 ≈ 5.08 sat/M ≈ $0.0039/M.
      Post-window-reset z.ai verification: Phase 3.

### Phase 2 — Public node (:8010)
- [x] 2.1: Admin password recovered → kit `.env`
      (`ROUTSTR_ADMIN_PASSWORD_PUBLIC`)
- [x] 2.2: z.ai provider added (id=2, fee 1.27 ≥ 21% margin floor)
- [x] 2.3: `receive_ln_address` = npubx address set via admin PATCH
      (min_payout_sat=210, payout_interval=900s unchanged).
      **Drain findings:** the 13,972 figure was MSATS (13.972 sats) — the
      routstr *platform* fee (2.1%), hardcoded to drain to the routstr
      project's npub.cash address (their revenue, not ours to redirect).
      Real owner balance showed 663 sats, but spendable-filtered proofs =
      5 sats vs 5 sats liability → nothing to drain yet (phantom proofs).
      Pipeline verified end-to-end: LNURL resolves, exact payout code path
      executes, periodic loop correctly no-ops on 0 available owner funds.
      Future profits drain automatically. NOTE: node's `send_to_lnurl`
      helper is buggy (never passes `amount` → AssertionError); the payout
      path calls `raw_send_to_lnurl` directly and is unaffected.
- [x] 2.4: Catalog republished: 337 models incl. glm-class from z.ai

### Phase 2.5 — Ansible anti-wipe + coinos default (kit role `routstr`)
- [x] 2.5.1: lookup default `''` → `tollgate@coinos.io` (empty-but-set
      falls back too)
- [x] 2.5.2: settings PATCH body via `combine()` — receive_ln_address
      included ONLY when non-empty (logic proven with ad-hoc playbook:
      empty case omits the key entirely)
- [x] 2.5.3: `RECEIVE_LN_ADDRESS` removed from compose template (with
      explanatory comment); `routstr_ln_address` fact removed
- [x] 2.5.4: Kit `.env`: npubx override set, `ROUTSTR_LN_ADDRESS` line
      replaced with removal note, `.env.example` documents default + override
- [x] 2.5.5: playbook syntax-check passes (`18-routstr.yml`); full
      idempotency proof deferred to the multi-instance role refactor plan

### Phase 3 — Proxy savings unlock (routstr-preference plan resumes)
- [x] 3.1: z.ai 5h window reset verified (12% used, 10,558 remaining);
      glm-5.2 through the node now serves via the **z.ai provider**
      (`provider: generic`, content OK) on free coding-plan quota, paid in
      testnut sats. Published glm-5.2 price after fix: 0.381 sat/M ≈
      $0.0003/M — 3,300× cheaper than OpenRouter → proxy cost-sort puts the
      node FIRST for glm-class. **Bonus bug fixed**: the z.ai model rows'
      pricing JSON had `max_*_cost: null` → Pricing validation failed →
      router silently skipped the z.ai candidates (glm-class always fell to
      OR). Fixed nulls → 0.0; routing now resolves to z.ai first.
- [x] 3.2: Model-ID mapping resolves natively (node serves `glm-5.2`,
      no namespacing)
- [x] 3.3: MRE plan updated (`PLAN-routstr-preference-cost-optimization.md`
      Phase 4 complete, a6b773e)

### Phase 4 — Docs + reproducibility
- [x] 4.1: Kit `.env`: new z.ai key as `ROUTSTR_UPSTREAM_API_KEY` (replaces
      dead `038e51…`), `ROUTSTR_OPENROUTER_UPSTREAM_KEY` added, both admin
      passwords stored
- [x] 4.2: Gap doc `docs/GAP-ROUTSTR-STACK.md` (kit): machine/container map,
      provider state, LN-address invariant
- [x] 4.3: Kit committed + pushed (af5c663); MRE docs committed + pushed
      (a6b773e)

## Follow-ups (not blocking)

- Watch the friends-node `sk-hermes` testnut wallet (24.7k sats; ~40-100
  sats/request at current pricing). No auto-topup exists for the NODE key
  (the routstrd funding guard watches the daemon's real-sats wallet).
  If drained: B1 gate fail-closes → proxy falls back to direct OpenRouter
  (graceful). Top-up = D3 approval flow re-issue, or lower the z.ai rows'
  USD pricing to stretch the wallet.
- Proxy-level blacklist nuance: a single node 402 (e.g. large request the
  wallet can't cover) marks routstr unfunded for 5 min for ALL models —
  existing coarse behavior, self-heals.
- Savings verification after 24h: OpenRouter glm-class spend should trend
  to ~$0 while z.ai 5h windows absorb bursts (big window ~8.9k remaining,
  resets ~Aug 27).

## Safety notes

- Friends-node payout stays DISABLED (testnut melts denied by D4 lockdown;
  drain would error-loop — no real profit lost, testnut fees are worthless
  by design).
- Restart of either node is near-zero impact (neither completes requests today).
- z.ai quota is window-bounded (~10.3k on the big window) — savings real but
  quota-capped; public exposure of a coding-plan key carries ToS risk,
  mitigated by the 27% margin + monitoring (user decision stands).
- Rollback: disable/delete provider rows via admin API; nodes return to
  today's state. Proxy changes inert while node models absent.
