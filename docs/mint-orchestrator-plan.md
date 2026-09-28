# Cashu Mint Orchestrator — Implementation Plan

## Overview

A system for deploying per-operator Cashu mints on a shared VPS, where mint issuance is gated
by Nostr event-based approval. Each mint is tied to a Nostr npub (the mint owner), and only
that npub can approve ecash issuance from their mint.

## Architecture

```
┌──────────────┐     ┌──────────────────────────────────────────────────────┐
│ Mint Owner   │     │                    VPS                               │
│ (has nsec)   │     │                                                      │
│              │     │  ┌─────────────────────────────────────────────┐     │
│  1. Signs &  │────►│  │  tollgate-mint-orchestrator (Python)        │     │
│     publishes│     │  │                                             │     │
│     kind 38010│    │  │  Subscribes to relay for kind:38010         │     │
│     approval │     │  │  Validates signature + npub ownership       │     │
│     event    │     │  │  Calls gRPC UpdateNut04Quote → PAID         │     │
│              │     │  │  Publishes confirmation events              │     │
└──────────────┘     │  │  Exposes REST API on :8090                  │     │
                     │  └──────────────┬──────────────────────────────┘     │
                     │                 │ gRPC (localhost:50051+)             │
                     │        ┌────────┴────────┐                           │
                     │   ┌────┴─────┐     ┌──────┴─────┐                    │
                     │   │ mint-abc │     │ mint-def   │                    │
                     │   │ Nutshell │     │ Nutshell   │                    │
                     │   │ :3338    │     │ :3339      │                    │
                     │   │ gRPC     │     │ gRPC       │                    │
                     │   │ :50051   │     │ :50052     │                    │
                     │   └──────────┘     └────────────┘                    │
                     │        ▲                  ▲                          │
                     │   ┌────┴──────────────────┴──┐                       │
                     │   │  Caddy *.mints.domain     │                       │
                     │   │  abc.mints → :3338        │                       │
                     │   │  def.mints → :3339        │                       │
                     │   └───────────────────────────┘                       │
                     └──────────────────────────────────────────────────────┘
```

## Components

### 1. Nutshell Mint Containers (per-npub)

Each mint owner gets their own Nutshell (cashubtc/nutshell) Docker container:

- **FakeWallet** backend with `FAKEWALLET_BRR=False` — invoices are NOT auto-approved
- **gRPC management API** enabled — orchestrator can force quote states via `UpdateNut04Quote`
- **SQLite** database per mint
- **Multi-unit support**: sat, usd, eur, MB, GB, B, KB, seconds, minutes, hours, days, weeks, months
- **Unique ports**: REST API (3338+) and gRPC (50051+) per mint

### 2. Nostr Approval Event (kind 38010)

```json
{
  "kind": 38010,
  "pubkey": "<mint-owner-hex-pubkey>",
  "content": "Mint approval for quote <quote-id>",
  "tags": [
    ["t", "mint-approval"],
    ["mint", "https://abc.mints.domain"],
    ["quote", "<quote-id>"],
    ["amount", "1000"],
    ["unit", "sat"],
    ["p", "<orchestrator-hex-pubkey>"]
  ]
}
```

Validation rules:
1. Kind must be 38010
2. Signature cryptographically valid
3. `pubkey` matches mint owner npub from registry
4. Has `["t", "mint-approval"]` tag
5. Has `["mint", "<url>"]` matching a known mint
6. Has `["quote", "<id>"]` with valid quote ID
7. Quote is in UNPAID state
8. Event age < 5 minutes (replay protection)

### 3. Orchestrator Daemon (Python)

Long-running service that:
- Subscribes to relay for `kind:38010, #t:mint-approval`
- Validates events against registry
- Calls gRPC `UpdateNut04Quote` to approve quotes
- Publishes confirmation/status events to relay
- Exposes REST API on port 8090
- Logs all approvals to JSONL audit log

### 4. CLI Approval Tool (mint-approve)

```bash
tollgate-mint-approve --nsec <nsec> --mint <url> --quote <id> --amount 1000 --unit sat
```

Signs and publishes a kind 38010 approval event.

### 5. Web Dashboard

Single HTML page with nostr-tools for client-side signing:
- Login with nsec (never sent to server)
- View pending quotes
- Click to approve
- View audit log

### 6. Ansible Roles

- `cashu_mint`: Deploy per-mint Nutshell containers
- `mint_orchestrator`: Deploy orchestrator daemon + dashboard

## Supported Units

| Unit | Backend | Description |
|------|---------|-------------|
| sat | FakeWallet | Satoshis (Bitcoin) |
| usd | FakeWallet | US Dollars (cents) |
| eur | FakeWallet | Euros (cents) |
| B | FakeWallet | Bytes |
| KB | FakeWallet | Kilobytes |
| MB | FakeWallet | Megabytes |
| GB | FakeWallet | Gigabytes |
| sec | FakeWallet | Seconds |
| min | FakeWallet | Minutes |
| hr | FakeWallet | Hours |
| day | FakeWallet | Days |
| wk | FakeWallet | Weeks |
| mo | FakeWallet | Months |

Each unit requires its own `MINT_BACKEND_BOLT11_<UNIT>` env var set to `FakeWallet`.

## End-to-End Flow

### Mint Creation
```
./scripts/deploy-mint.sh npub1abc123...
→ Ansible creates Nutshell container, Caddy route, registry entry
→ Output: mint URL
```

### Token Issuance
```
1. User creates quote: POST /v1/mint/quote/bolt11 {"amount": 100, "unit": "sat"}
2. Quote stays UNPAID (FakeWallet brr=False)
3. Mint owner approves: tollgate-mint-approve --quote <id> --amount 100
4. Orchestrator validates event, calls gRPC → quote = PAID
5. User mints tokens: POST /v1/mint/bolt11 {"quote": "<id>", "outputs": [...]}
6. User has ecash!
```

### Token Spending
Swap, melt, and other operations work without approval.

## Security Model

- **nsec never leaves client** — all signing is client-side (browser or CLI)
- **gRPC is localhost-only** — not exposed via Caddy
- **Nostr event signature = cryptographic proof** — cannot be forged
- **5-minute TTL** on approval events prevents replay
- **Per-mint isolation** — separate containers, DBs, private keys
- **Audit log** — all approvals logged with timestamp, npub, quote, amount
- **No auto-issuance** — `FAKEWALLET_BRR=FALSE`

## File Structure

```
mint-orchestrator/          # Python package
├── pyproject.toml
├── Dockerfile
├── protos/management.proto
├── src/tollgate_mint_orchestrator/
│   ├── daemon.py
│   ├── nostr_subscriber.py
│   ├── event_validator.py
│   ├── grpc_client.py
│   ├── mint_registry.py
│   ├── audit_log.py
│   └── api.py
└── tests/
    ├── test_event_validator.py
    ├── test_grpc_client.py
    ├── test_mint_registry.py
    ├── test_audit_log.py
    └── test_daemon.py

mint-approve/               # CLI tool
├── pyproject.toml
└── src/tollgate_mint_approve/cli.py

mint-dashboard/              # Web UI
├── index.html
├── style.css
└── app.js
```

## Implementation Phases

1. Package skeleton + protos
2. Core modules (registry, validator, gRPC client)
3. Daemon + subscriber
4. CLI tool
5. Web dashboard
6. Ansible roles
7. Tests (unit, integration, E2E, Playwright)
