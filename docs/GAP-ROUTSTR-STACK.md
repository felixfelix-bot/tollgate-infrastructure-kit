# GAP: Routstr Stack — Deployed State vs Kit (2026-08-22)

Live inventory of the routstr + mint stack on **testserver2** (23.182.128.51,
inventory `vps2`) and what the kit can / cannot reproduce today.

## Machines

| Machine | IP | State |
|---|---|---|
| testserver2 (`vps2`) | 23.182.128.51 | live — both routstr nodes, cdk-mintd, mint-auth-processor, mint-orchestrator, systemd caddy |
| hermes | 23.182.128.219 | bare (no docker; ssh + dnsd only) — canary candidate for reproducibility proof |
| hermes2 | 64.188.7.239 | unreachable (SSH timeout) despite Active billing |
| vps1 (old) | 66.92.204.38 | dead — still in inventory defaults, retire |

## Live containers (vps2)

| Container | Bind | Upstream(s) | Mint(s) | Kit role |
|---|---|---|---|---|
| `routstr-proxy` (friends/private) | 127.0.0.1:8009 | id=1 ollama.com (paywalled acct `elastic_heisenberg_340`); id=2 z.ai coding (key `abfc7a98…`, fee 1.27); id=3 openrouter (key `sk-or-v1-9545…`, fee 1.27, reserve) | orangesync testnut | `routstr` (single-instance design — gap) |
| `routstr-public` (ai.orangesync.tech) | 127.0.0.1:8010 | id=1 ppq (dead key); id=2 z.ai coding (fee 1.27) | minibits + cubabitcoin (real sats) | none (gap) |
| `cdk-mintd` | host :8085 | — | orangesync (mnemonic env; grpc-processor lockdown) | `cashu_mint` uses public image (gap: custom `cdk-mintd-grpc:0.17.3` built in `/opt/cdk-mintd-build`) |
| `mint-auth-processor` | :50056 gRPC / :50057 HTTP | approves mint quotes | — | none (gap; source git-init'd on laptop, no remote) |
| `mint-orchestrator` | — | Nostr kind-38010 → processor | — | `mint_orchestrator` |

Caddy (systemd): `ai.` + `routstr.` → :8010, `friends.` → :8009, `mint.` → :8085.
Kit's caddy role deploys docker-caddy with templates (drift; manage-live-systemd
decision pending from reproducibility plan).

## Access

- Friends node from the laptop: `routstr-tunnel.service` (systemd user unit,
  `ssh -N -L 127.0.0.1:8009:127.0.0.1:8009 root@23.182.128.51`).
  `ROUTSTR_BASE=http://localhost:8009` in `~/.hermes/.env` +
  `~/.hermes/profiles/manager/.env`.
- Admin passwords (both nodes): reset 2026-08-22 via the app's
  `set_admin_password` (docker exec `/.venv/bin/python`); stored in kit `.env`
  (`ROUTSTR_ADMIN_PASSWORD_FRIENDS` / `_PUBLIC`).

## LN-address invariant (2026-08-22)

- `receive_ln_address` (operator profit drain) on `routstr-public` =
  `npub1gxelz640z3lxc7fcah32erv5wgsstp9009vztvt58zhss6r8efasxg0hdk@npubx.cash`
  (set via admin API; kit `.env` `ROUTSTR_RECEIVE_LN_ADDRESS` carries it).
- Friends node payout: intentionally unset — testnut melts are denied by the
  D4 mint lockdown; payout would error-loop.
- **Anti-wipe**: the routstr role never PATCHes an empty `receive_ln_address`;
  repo default = `tollgate@coinos.io` (what public workflow users get);
  private deployments override via gitignored `.env`.
- Platform fee (2.1%) drains to the routstr project's hardcoded npub.cash
  address — their revenue model, not configurable.

## Known node quirks (verified 2026-08-22)

- `GET /v1/wallet/balance` (old) → 404; current endpoint is
  `GET /v1/balance/info` (same `balance` field). Balance collector fixed
  (MRE `src/balance_collectors.py`).
- Node's `wallet.send_to_lnurl` helper never passes `amount` →
  AssertionError; the payout path calls `raw_send_to_lnurl` directly and is
  unaffected.
- `routstr_fees.accumulated_msats` is MSATS (13,972 msat = 13.972 sats), not
  sats.
- Model routing: DB model rows (exact-ID match, priority 4) beat fetched
  catalog entries (base-ID match, priority 3); provider_map is a failover
  list — z.ai first, node-internal failover to OpenRouter on quota errors.

## Reproducibility gaps (from the approved plan, pending)

1. routstr role → multi-instance (friends + public, live names, loopback
   binds, entrypoint bind, tor/dedicated-mint optional-off)
2. `mint_auth_processor` role (fold source into kit, build on host)
3. cdk-mintd-grpc Dockerfile into kit + build-on-host task
4. Caddy sites (ai/friends/mint) via ansible-managed systemd snippets
5. Inventory: add hermes/hermes2, retire vps1
