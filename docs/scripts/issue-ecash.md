# issue_ecash.py — Operator eCash Issuance Runbook

## Overview

`scripts/issue_ecash.py` is a pure-Python Cashu minting client for operator-side
token issuance against the production CDK mint. It performs blinded token minting
using hand-rolled secp256k1 point arithmetic — no C crypto dependencies beyond
the standard library.

The `hash_to_curve` implementation matches the official Cashu SDK
(`cashu/core/crypto/b_dhke.py`) byte-for-byte, ensuring interoperability with
CDK mintd keysets.

## Prerequisites

- Python 3.8+ (stdlib only — no pip installs required)
- Network access to the mint REST API
- A funded quote (either fakewallet auto-pay or gRPC `UpdateNut04Quote` → PAID)

## Flow

```
┌─────────┐     ┌──────────────┐     ┌───────────┐     ┌──────────┐     ┌───────────┐
│  quote   │────▶│  gRPC PAID   │────▶│   mint    │────▶│   swap   │────▶│  routstr  │
│ (bolt11) │     │ (orchestrator)│     │ (blind)   │     │ (verify) │     │  redeem   │
└─────────┘     └──────────────┘     └───────────┘     └──────────┘     └───────────┘
```

### Step 1: Create a mint quote

```bash
python3 scripts/issue_ecash.py quote 5000
```

Creates a bolt11 mint quote for 5000 sats. Prints the quote ID.

### Step 2: Mark quote as PAID via gRPC

Use the mint orchestrator's gRPC interface (or `issue_to_friend.py`) to call
`UpdateNut04Quote` with the quote ID, setting its state to `PAID`.

```bash
# Via mint-orchestrator gRPC (port 50055 for routstr-mint)
cdk-mint-rpc update-quote --quote <QUOTE_ID> --state PAID
```

For fakewallet-backed mints, this step happens automatically within seconds.

### Step 3: Mint blinded tokens

```bash
python3 scripts/issue_ecash.py mint <QUOTE_ID> 5000
```

Generates blinded messages, sends them to the mint's `/v1/mint/bolt11` endpoint,
unblinds the returned signatures, and writes:

- `/tmp/sitarani_token.txt` — Cashu token string (`cashuA...`)
- `/tmp/proofs.json` — Raw proof array

### Step 4: Swap-verify (optional but recommended)

```bash
python3 scripts/issue_ecash.py swap
```

Submits the minted proofs to `/v1/swap` and re-receives fresh proofs. This
verifies the originals are spendable at the mint and produces clean, verified
tokens.

### Step 5: Redeem via Routstr

The resulting `cashuA...` token can be fed to the Routstr AI inference proxy
as payment for model API calls. Routstr consumes the token via its Cashu wallet
integration and credits the caller.

## Security Notes

- The script writes tokens to `/tmp/` — treat these as bearer instruments.
- No private keys are stored; blinding secrets are ephemeral per session.
- The mint URL is hardcoded to the production endpoint. For testing, edit the
  `MINT` constant.

## Implementation Details

- **secp256k1**: Pure Python point addition, scalar multiplication, modular
  inverse — no `coincurve` or `secp256k1` C library required.
- **hash_to_curve**: Uses the Cashu tag `Secp256k1_HashToCurve_Cashu_` with
  SHA-256 and try-and-increment (lift_x_even), matching the official SDK.
- **Blinding**: `B_ = Y + r·G` where `Y = hash_to_curve(secret)` and `r` is
  a random scalar. Unblinding: `C = C_ - r·K` where `K` is the mint's pubkey
  for the amount.
- **Token format**: `cashuA` + base64url(JSON) per NUT-00.
