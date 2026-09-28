# Nutshell-Format Test Mint Requirement

## Context

The `tollgate-module-basic-go` router daemon and its CLI tools use the [`gonuts-tollgate`](https://github.com/Origami74/gonuts-tollgate) Go library for Cashu wallet operations (receiving tokens, swapping proofs, checking balances). This library implements the **original Cashu keyset ID derivation**:

```
SHA-256(all_pubkeys_sorted) → first 14 hex chars → prefix "00" → 16-char hex ID
Example: "00b4cd27d8861a44"
```

## The Problem

CDK mintd v0.16.0 and Nutshell v0.20.0 both use the **new keyset ID format** — a 64-char hex string derived from the full compressed public key:

```
Example: "01884a74bb2fc5ee6e5f958f89f9e4e6cf79241fbc9fd1012d6811b054a78beffe"
```

When `gonuts-tollgate` encounters a mint with these keyset IDs, it crashes:

```
error adding new mint: Got invalid keyset.
Derived id: '009a1f293253e41e'
but got '01884a74bb2fc5ee6e5f958f89f9e4e6cf79241fbc9fd1012d6811b054a78beffe' from mint
```

This crash is fatal — the tollgate-wrt daemon exits on startup if the configured mint uses the new format.

## What We Need

Deploy a **Nutshell v0.18.x** test mint on orangesync.tech, in addition to the existing mints.

Nutshell 0.18.x uses the old 16-char keyset ID format that `gonuts-tollgate` expects. The public `nofee.testnut.cashu.space` (Nutshell 0.18.2) is the only known mint that works, but it's shared infrastructure that experiences DB lock contention under load.

### Recommended Configuration

| Field | Value |
|-------|-------|
| Subdomain | `testnut-compat.mints.orangesync.tech` |
| Software | Nutshell 0.18.x (Python, not CDK) |
| Unit | `sat` |
| Fees | **0_ppk (critical)** — must match nofee.testnut.cashu.space behavior |
| Auto-pay | fakewallet or equivalent — quotes should auto-resolve |
| Docker image | `cashubtc/nutshell` or similar |

### Why Not Just Update gonuts-tollgate?

That's the long-term fix, but it requires upstream changes to the keyset ID derivation in the `gonuts-tollgate` `crypto/keyset.go` module. The `DeriveKeysetId()` function hardcodes the `"00" + 14_hex_chars` format. Supporting both formats requires:

1. Accepting the server's keyset ID as-is instead of re-deriving it
2. Handling both ID formats in proof serialization/deserialization
3. Updating all keyset lookups to work with both lengths

This is a non-trivial change that affects the entire wallet/minting pipeline.

## Existing Mints — Keep As-Is

The existing CDK mints are valuable and should stay:

| Mint | URL | Notes |
|------|-----|-------|
| test-mb | `test-mb.mints.orangesync.tech` | CDK, sat unit (MB display mapping in cashu-brrr) |
| test-kb | `test-kb.mints.orangesync.tech` | CDK, sat unit |
| test-gb | `test-gb.mints.orangesync.tech` | CDK, sat unit |
| test-min | `test-min.mints.orangesync.tech` | CDK, sat unit |
| routstr-mint | `routstr-mint.mints.orangesync.tech` | CDK, for AI inference payments |
| testnut-cdk | `testnut-cdk.mints.orangesync.tech` | CDK, general testing |
| testnut-nutshell | `testnut-nutshell.mints.orangesync.tech` | Nutshell 0.20.0 — **not compatible** with gonuts-tollgate |

The CDK mints work fine with `cashu-ts` (JavaScript), the cashu-brrr frontend, and any client that supports the new keyset format. They're needed for the broader ecosystem. The ask is to add one more mint running the older Nutshell version specifically for Go-based router compatibility.

## Compatibility Matrix

| Client | Old keyset (16-char) | New keyset (64-char) |
|--------|---------------------|---------------------|
| gonuts-tollgate (Go) | OK | CRASH |
| cashu-ts v2.9+ (JS) | OK | OK |
| cashu Python lib | OK | Partial |
| CDK mintd | emits new | emits new |
| Nutshell 0.18.x | emits old | N/A |
| Nutshell 0.20.x | N/A | emits new |

## Affected Systems

- `tollgate-module-basic-go` — the router daemon, uses gonuts-tollgate for all Cashu operations
- `physical-router-test-automation/scripts/mint-token/` — test helper that mints tokens for Playwright e2e tests
- Any Go-based tool that uses gonuts-tollgate for token operations

## File Reference

The keyset ID derivation is in `gonuts-tollgate` at `crypto/keyset.go`, function `DeriveKeysetId()`:

```go
func DeriveKeysetId(keyset PublicKeys) string {
    // ... sort and concatenate pubkeys ...
    hash := sha256.New()
    hash.Write(keys)
    return "00" + hex.EncodeToString(hash.Sum(nil))[:14]
}
```

The validation check is called during wallet initialization when it fetches the mint's keysets and compares the server's keyset ID against the locally-derived one.
