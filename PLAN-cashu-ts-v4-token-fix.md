# PLAN: cashu-ts v4 Token Fix (routstrd wallet)

**Date:** 2026-08-21
**Problem:** routstrd's cocod wallet cannot receive Cashu tokens whose proofs carry
amounts > 23 sats ("Invalid token" / "Unsupported length: 28"). Small tokens
(21 sats: proofs 16+4+1) receive fine; a 512-sat token (proofs 256, 64, 64, 32, …) fails.

**Root cause (verified by CBOR byte-level analysis):**
- Cashu token proofs encode `a` (amount) as CBOR uint. Amounts ≤ 23 fit in the 5-bit
  info field; amounts ≥ 24 need extended CBOR (info 24/25 = 1/2-byte lengths).
- `coco-cashu-core` 1.1.2-rc.50 (bundled inside the global bun install used by cocod)
  depends on `@cashu/cashu-ts` `^3.5.0` → resolves 3.6.2. Its CBOR decoder chokes on
  the extended encodings → decode aborts → "Invalid token".
- No published coco-cashu-core release bundles cashu-ts v4 (latest npm release still
  pins ^2.7.2/^3.5.0), but `@cashu/cashu-ts` 4.8.0 is already installed globally
  (`~/.bun/install/global/node_modules/@cashu/cashu-ts`) and decodes these tokens.

**Fix:** symlink the global cashu-ts 4.8.0 over the bundled 3.6.2 inside
coco-cashu-core's node_modules, restart the wallet stack (cocod + routstrd),
re-enforce via Ansible so future routstrd updates that reinstall the old
dependency get auto-repaired.

## Checklist

### A. Ansible role update (tollgate-infrastructure-kit)
- [x] A1: Extend `roles/routstrd_funding_guard/tasks/main.yml` with a
      "cashu-ts v4 compatibility" block:
      ensure global `@cashu/cashu-ts` >= 4 installed (bun add -g),
      detect bundled version inside coco-cashu-core,
      symlink v4 over bundled < 4, notify restart handler
- [x] A2: Add handler `restart routstrd wallet stack` (kill cocod →
      `systemctl --user restart routstrd`, which supervises cocod)
- [x] A3: Playbook run green + idempotent on second run

### B. Apply the fix (via the playbook)
- [x] B1: Run playbook 46 → symlink created, wallet stack restarted
- [x] B2: Verify bundled version now reports 4.8.0 and cocod socket healthy

### C. Wallet recovery
- [x] C1: Receive the user's 512-sat minibits token via
      `routstrd wallet receive cashu <token>` (previously "Invalid token")
- [x] C2: Balance shows minibits ≈ 512 sats (+ any leftovers)

### D. Live settlement test (retry with adequate funds)
- [x] D1: Fire one cheap completion (gpt-5.6-luna @ blazelight ~1 sat, or
      deepseek-v4-flash ~32 sats) via `localhost:8008/v1/chat/completions`
- [x] D2: Confirm HTTP 200 + response text + minibits balance dropped
      (first completed real-ecash network settlement)

### E. Wrap-up
- [x] E1: Update PLAN-routstrd-funding-guard.md cross-reference
- [x] E2: Commit + push kit (plan + role)

## Risk / rollback
- cashu-ts v4 renames some APIs vs v3; if coco-cashu-core's receive/send paths
  break after the swap, rollback = remove symlink, `bun install` inside
  coco-cashu-core (or reinstall globally) to restore 3.6.2, restart stack.
- Test immediately after swap: /balance (send-path intact) + token receive
  (decode-path fixed). If send breaks, rollback and instead decode the token
  with a standalone script using global cashu-ts 4.8.0 and import proofs
  directly into coco.db (fallback documented, not implemented).

## Outcome (2026-08-22)
- Symlink live: coco-cashu-core/node_modules/@cashu/cashu-ts -> global 4.8.0
- Playbook idempotent (2nd run: 0 changed, 4 skipped)
- 512-sat minibits token received cleanly (was "Invalid token" before)
- FIRST completed real-ecash network settlement: gpt-5.6-luna via network node,
  response OK, 512 -> 505 sats (7 sats paid)
- cashu-ts v4 API-compatible with coco-cashu-core receive/send paths (no rollback needed)
