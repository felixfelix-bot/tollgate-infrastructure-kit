# DM Issuer

Quote-handoff DM auto-issuance service. Receives NIP-59 gift-wrapped DMs of the
form `ecash <amount>` from whitelisted npubs, requests a Cashu mint bolt11
quote, marks it PAID via the cdk-mintd gRPC `UpdateNut04Quote` RPC, verifies
the quote state, and DMs the resulting `quote_id` back to the sender. The
service never touches Cashu secrets — handing off the paid quote_id is the
entire issuance surface.

## Layout

```
dm-issuer/
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── proto/cdk-mint-rpc.proto
├── src/tollgate_dm_issuer/
│   ├── __init__.py
│   ├── __main__.py
│   ├── config.py
│   ├── parse.py
│   ├── policy.py
│   ├── journal.py
│   ├── grpc_payer.py
│   ├── mint_client.py
│   ├── nostr_io.py
│   ├── ops.py
│   ├── cli.py
│   └── cdk_mint_rpc_pb2{,_grpc}.py
└── tests/
    ├── conftest.py
    ├── test_config.py
    ├── test_parse.py
    ├── test_policy.py
    ├── test_journal.py
    ├── test_grpc_payer.py
    ├── test_mint_client.py
    └── test_nostr_io.py
```

## Running tests

```
cd dm-issuer
PYTHONPATH=src python -m pytest tests/ -v --cov=tollgate_dm_issuer --cov-report=term-missing
```

## Environment

- `ISSUER_NSEC` (required) — the issuer's nostr nsec kept in `.env` (gitignored).
- `ISSUER_NPUB` — the companion npub (`npub1ac2r0qy6hws6fxn7eulewnnlesacertzuq4v9mhyywcu7phslcrsdrvykw`).
- `DM_ISSUER_CONFIG_PATH` — optional override for `/etc/dm-issuer/config.json`.

See `docs/dm-issuer.md` for the full runbook.
