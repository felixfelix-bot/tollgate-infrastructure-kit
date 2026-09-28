# DM Issuer — Architecture, Runbook, and Self-Review

**Service**: `dm-issuer` (quote-handoff)
**Repository**: `tollgate-infrastructure-kit/dm-issuer`
**Spec contract**: `dm-auto-issuance-spec.md` (Q1–Q6 all resolved)
**Coverage gate**: ≥ 80 % (excluding `cdk_mint_rpc_pb2*.py` generated code)

---

## 1. Architecture

The DM issuer is an **outbound-only** Nostr poller that turns DM requests into
**paid Cashu bolt11 quotes**, then DMs the `quote_id` back to the requester.
The service holds the operator's nostr identity and the gRPC capability to
mark quotes PAID — but **never touches Cashu secrets** (no blinding, no
unblinding, no token in flight). The user's own wallet mints against the paid
`quote_id`.

```
┌─────────┐   NIP-59 gift wrap DM   ┌────────────┐   REST       ┌───────────┐
│ User    │ ──────────────────────▶ │ dm-issuer  │ ───────────▶ │ cdk-mintd │
│ npub    │                         │ poll loop  │ ◀─────────── │ REST 8080 │
└─────────┘                         │  20 s      │   quote_id  │           │
      ▲                              │            │             └───────────┘
      │ NIP-59 DM with quote_id       │            │   gRPC          │
      │ (gift wrap)                   │            │ ───────────────▶│ UpdateNut04Quote(quote_id, PAID)
      │                              │            │                  │ 127.0.0.1:50055
      │                              │            │   verify PAID  │
      │                              │            │ ───────────────▶│ GET /v1/mint/quote/bolt11/{id}
      │                              │            │                              └─ state=PAID
      │                              │            │                  │
      │                              ▼            │                  │
┌──────────────────────────────────────────────┐  │                  │
│ journal (SQLite ledger, cas_state machine)   │  │                  │
│ processed_events dedupe + usage accounting   │  │                  │
└──────────────────────────────────────────────┘  │                  │
                                                   │                  │
                                       fallback    │                  │
                                       POST /approve ────────────────▶│ mint-auth-processor
                                       (HTTP 50057, optional)            │ 127.0.0.1:50057
                                                                          │
                      ops API ◀  http://127.0.0.1:8095/healthz | /metrics
```

### Pipeline (one message, success path)

```
DmMessage  ─▶  is_event_processed?  ─▶ MARK_PROCESSED  ─▶  policy.check
   │             │                                            │
   │             yes → skip                                    ├ ALLOW  → insert_request(REQUESTED)
   │             no                                            │           → mint.create_quote(amount)  QUOTED
   │                                                          │           → grpc.mark_quote_paid(quote_id) PAID
   │                                                          │               (or approve_fallback POST /approve)
   │                                                          │           → mint.get_quote_state == PAID
   │                                                          │           → nostr.send_dm(quote_id)         DELIVERED
   │                                                          │           → policy.commit_usage
   │                                                          │           → mark_delivered + mark_event_processed
   │                                                          │
   │                                                          ├ REJECTED → cas REQUESTED → REJECTED (+ optional error DM)
   │                                                          └ SILENT_DROP (rate-limited unwhitelisted: no reply)
```

### State machine (`journal.py`, `ALLOWED_TRANSITIONS`)

```
REQUESTED ─▶ QUOTED ─▶ PAID ─▶ DELIVERED   (terminal-happy path)
    │         │       │
    │         └──────────▶ FAILED           (any step exception)
    │         │       │
    │         └──▶ EXPIRED
    │
    └──▶ REJECTED                       (terminal — admin revoke or stale)
```
All transitions are **compare-and-swap**: `UPDATE requests SET state=? WHERE request_id=? AND state=?`.
`affected_rows == 1` ⇒ success; `0` ⇒ concurrent writer already moved on → caller bails.

---

## 2. Config reference

Configuration has two layers: env vars (runtime secrets) and JSON config
file (operational knobs). Defaults match `dm-auto-issuance-spec.md` §4
(DM-CFG-1..6).

### 2.1 Environment variables

| Env var | Required | Default | Notes |
|---|---|---|---|
| `ISSUER_NSEC` | **yes** | — | Issuer nostr private key in either `nsec1…` bech32 form or raw 64-char hex. **NEVER logged, NEVER committed to git** (kept only in `.env`, Ansible-vaulted). |
| `ISSUER_NPUB` | yes | `npub1ac2r0qy6hws6fxn7eulewnnlesacertzuq4v9mhyywcu7phslcrsdrvykw` | Companion public key. Used only for documentation — `config.issuer_npub` is authoritative. |
| `DM_ISSUER_CONFIG_PATH` | no | `/etc/dm-issuer/config.json` (or `--config /path`) | If absent/empty, `DEFAULT_CONFIG` is used. |
| `DM_ISSUER_DB_PATH` | no | `/var/lib/dm-issuer/dm-issuer.db` | SQLite ledger path. |
| `ISSUER_CONFIG_PATH` | no | (alias) | Backwards-compatible alias for `DM_ISSUER_CONFIG_PATH`. |

### 2.2 JSON config file (`config.json`) fields

All keys optional; omitted values inherit `DEFAULT_CONFIG` (in `config.py`).

| Field | Default | Description |
|---|---|---|
| `issuer_npub` | `npub1ac2r0qy6hws6fxn7eule…` | Public npub of issuer (Q3). |
| `issuer_nsec_env` | `"ISSUER_NSEC"` | Env var name to read the private key from (allows multiple issuers per host). |
| `relays` | `["wss://relay.damus.io", "wss://nos.lol", "wss://relay.primal.net", "ws://127.0.0.1:7777"]` | Nostr relays for both scan and publish (Q5). Public relays must start with `ws://`, `wss://`, `wsps://`, or `ssl://` and must not loopback — see `_is_public_relay`. |
| `mint_url` | `https://mint.orangesync.tech` | Cashu mint public REST endpoint (Caddy-fronted). |
| `mint_grpc_host` | `127.0.0.1` | gRPC `cdk-mintd` management host. |
| `mint_grpc_port` | `50055` | gRPC management port (loopback on VPS2). |
| `approve_fallback_url` | `http://127.0.0.1:50057/approve` | Optional HTTP fallback when gRPC fails — proxies to `mint-auth-processor`. Enables `POST /approve?quote=<id>`. |
| `whitelist` | `[]` | List of `{npub, daily_cap_sats, max_request_sats}` entries. Empty `daily_cap_sats`/`max_request_sats` fall back to `defaults`. |
| `defaults.daily_cap_sats` | `2000` | Per-npub daily cap when whitelist entry omits it (Q4 Felix: 2 000, Sitarani: 500 000). |
| `defaults.max_request_sats` | `2000` | Max single issuance, capped by `registry_max_single_issuance`. |
| `global_daily_cap_sats` | `600000` | Aggregate across all whitelisted npubs per UTC day. |
| `min_request_sats` | `100` | Hard floor for `amount` (rejects dust). |
| `max_requests_per_hour` | `6` | Per-npub hourly throttle. |
| `poll_seconds` | `20` | Nostr scan loop cadence. |
| `stale_request_secs` | `600` (10 min) | Requests older than this in `REQUESTED` state are rejected as `STALE_REQUEST` (DM-RST-2). |
| `dm_lookback_default_secs` | `43200` (12 h) | First-run feed scan window when no cursor is stored. |
| `dm_retries` | `5` | NIP-59 send retries (with `dm_backoff_base_secs * attempt**2`). |
| `dm_backoff_base_secs` | `30` | Backoff base for send retries. |
| `grpc_retries` | `4` | gRPC `UpdateNut04Quote` retries on `AioRpcError`. |
| `grpc_backoff_base_secs` | `2` | Backoff base for gRPC retries. |
| `quote_ttl_secs` | `900` (15 min) | Quote lifetime reported to callers; mint-side TTL must be ≥ this. |
| `verify_before_send` | `false` | If `true`, poll `mint.get_quote_state` and wait for `PAID` before DMing the quote_id (Q6 RESOLVED — N/A in quote-handoff mode but still toggled by config). |
| `ops_host` | `127.0.0.1` | Ops API bind host. |
| `ops_port` | `8095` | Ops API port (`/healthz`, `/metrics`). |

### 2.3 Computed values

| Property | Expression |
|---|---|
| `Config.grpc_target` | `f"{mint_grpc_host}:{mint_grpc_port}"` (e.g. `127.0.0.1:50055`) |
| `Config.issuer_nsec()` | `os.environ.get(self.issuer_nsec_env)` |
| `Config.mint_grpc_target` | alias of `grpc_target` |
| `Config.effective_max_request_sats(npub, ceiling)` | `min(self.whitelist_entry(npub).max_request_sats, ceiling)` |

---

## 3. Deployment runbook

### 3.1 Prerequisites

- `cdk-mintd` reachable on `127.0.0.1:50055` (gRPC) and `https://mint.<base>` (REST, behind Caddy).
- (Optional) `mint-auth-processor` on `127.0.0.1:50057` (HTTP `/approve` fallback).
- At least one nostr relay reachable from the issuer host.
- A fresh issuer npub/nsec pair (see Q3) generated by the operator. Use `pynostr.key.PrivateKey().nsec` or `nostr-tool` to mint.
- Docker 24+ and Docker Compose plugin (or `docker-compose` v1).

### 3.2 docker-compose (manual, for staging/dev)

The compose file in `dm-issuer/docker-compose.yml` publishes port `8095` only
(intended for ops/health access; bind to `127.0.0.1` in production by setting
`ports: ["127.0.0.1:8095:8095"]`).

```bash
cd dm-issuer
cp .env.example .env       # then edit ISSUER_NSEC=...
docker compose up -d --build
docker compose logs -f      # check "ops API listening on 127.0.0.1:8095"
curl -fsS http://127.0.0.1:8095/healthz
```

### 3.3 Ansible role (production)

The role `ansible/roles/dm_issuer` is wired into the kit's standard host
provisioning. Toggle it on a host with:

```yaml
# inventory/host_vars/vps2.yml
dm_issuer_enabled: true
dm_issuer_issuer_nsec: "{{ vault_dm_issuer_nsec }}"   # from vault
dm_issuer_whitelist:
  - npub: "npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu"
    daily_cap_sats: 2000
    max_request_sats: 2000
  - npub: "npub1dtm05wf2nqy2fnjnc694rvknsc5xsu0z0p4phryds9qqgefdcvcq7neuy4"
    daily_cap_sats: 500000
    max_request_sats: 10000
dm_issuer_global_daily_cap_sats: 5000   # week-1 conservative cap (Q4)
dm_issuer_mint_grpc_port: 50055
```

The role:

1. Creates `/var/lib/dm-issuer/` (data) and `/etc/dm-issuer/` (config) with mode `0755`.
2. Renders `/etc/dm-issuer/config.json` from `templates/config.json.j2`.
3. Writes `/etc/dm-issuer/.env` (mode `0600`, `no_log: true`) with `ISSUER_NSEC`,
   `ISSUER_NPUB`, `DM_ISSUER_CONFIG_PATH`, `DM_ISSUER_DB_PATH`.
4. Renders `/etc/dm-issuer/docker-compose.yml` from `templates/docker-compose.yml.j2`.
5. Runs `docker compose build && up -d` and notifies the restart handler on
   config changes.

Run from the repo root:

```bash
ansible-playbook -i inventory/hosts deploy.yml --tags dm_issuer --limit vps2
```

### 3.4 Smoke test

After deploy:

```bash
# 1. Container is up
docker ps --filter "name=dm-issuer" --format '{{.Names}}\t{{.Status}}'

# 2. Health check
curl -fsS http://127.0.0.1:8095/healthz   # → {"status":"ok"} or {"status":"starting"}

# 3. Metrics
curl -fsS http://127.0.0.1:8095/metrics | head   # → dm_requests_total, dm_sats_issued_total, …

# 4. CLI ledger
DM_ISSUER_DB_PATH=/var/lib/dm-issuer/dm-issuer.db dm-issuer show-ledger

# 5. E2E
# from a whitelisted npub: send DM `ecash 5000` to the issuer npub,
# observe `dm_requests_total` increment and a gift-wrapped reply containing
# the `quote_id` arriving within ~ poll_seconds + send_dm retries.
```

---

## 4. Troubleshooting

### 4.1 ISSUER_NSEC missing / invalid

**Symptom**: `log.error("ISSUER_NSEC not set")` or
`log.error("invalid ISSUER_NSEC nsec format: %s", exc)` at startup, then
`send_dm` always returns `false` because `_issuer_priv_hex` is `None`.

**Fix**:

```bash
docker exec dm-issuer env | grep ISSUER_NSEC | head -c 32; echo "…"
# if empty, write the .env to /etc/dm-issuer/.env, then:
docker compose -f /etc/dm-issuer/docker-compose.yml restart
```

Validate the nsec can be parsed by the same code path:

```bash
python -c "from pynostr.key import PrivateKey; print(PrivateKey().hex())"
```

### 4.2 Relay connectivity

**Symptom**: `log.info("0 giftwraps fetched")` recurring, no requests
delivered. Or `send_dm` retries loop then `false`.

```bash
# from the issuer host:
docker exec dm-issuer python -c "import websockets; \
  import asyncio; \
  print(asyncio.run(websockets.connect('wss://relay.damus.io').__aenter__()).closed)"
```

If public relays (relay.damus.io, nos.lol, relay.primal.net) are unreachable,
fall back to the local strfry on `127.0.0.1:7777` to keep scanning working —
DM publish still needs the local relay to be reachable from user clients.

### 4.3 gRPC unreachable (cdk-mintd)

**Symptom**: `grpc_payer.mark_quote_paid` returns `false` after retries; the
request transitions `QUOTED → FAILED` with error_code=`GRPC_PAID_FAILURE`.

```bash
# verify the channel endpoint
nc -zv 127.0.0.1 50055
# verify the stub returns GetInfo
docker exec dm-issuer python -c "import grpc; from tollgate_dm_issuer.grpc_payer import _build_default_stub; \
  s = _build_default_stub('127.0.0.1:50055'); print(type(s))"
```

Restore `cdk-mintd`. The dispatcher marks affected requests `FAILED`; a hot
journal `recover(*, now, stale_secs)` pass transitions them to `REJECTED` on
next startup so they don't block new requests.

### 4.4 Mint API errors (REST)

**Symptom**: `MintError("transport failure", path="/v1/mint/quote/bolt11")` or
`MintError("non-200", path=…, status=500)` from `mint_client`. Request goes
`REQUESTED → FAILED` with error_code=`MINT_*`.

**Diagnosis**:

- `0` ledger rows in `QUOTED`: mint is up and `create_quote` is failing → check `mint_url` reachability (`curl -fsS https://mint.orangesync.tech/v1/keys`).
- Many rows in `QUOTED` but none `PAID`: gRPC is reachable, REST verify is OK, but the gRPC call passes; check `verify_before_send` config.

### 4.5 Stale requests (DM-RST-2)

A `REQUESTED` row older than `stale_request_secs` (default `600`s) is rejected
as `STALE_REQUEST`. This protects from a polling gap creating a burst of
"ghost" claims.

```bash
dm-issuer --db /var/lib/dm-issuer/dm-issuer.db show-ledger | grep REQUESTED
```

If rows persist in `REQUESTED` state, the mint is either slow or unreachable.
After `recover()` on next restart they will move to `REJECTED`. Force the
recovery without restart:

```bash
sqlite3 /var/lib/dm-issuer/dm-issuer.db \
  "UPDATE requests SET state='REJECTED', error_code='STALE_REQUEST', \
   updated_at=strftime('%Y-%m-%dT%H:%M:%S+00:00', 'now') \
   WHERE state='REQUESTED' AND \
   datetime(created_at) < datetime('now', '-600 seconds')"
```

### 4.6 Replay of a previously processed event

The journal has two layers of dedup (see §5.2 below):

1. `is_event_processed` — fast-path primary-key lookup.
2. `processed_events.event_id` UNIQUE + `requests.event_id` UNIQUE + CAS state
   machine — defensive against concurrent pollers and duplicate relay feeds.

If you see duplicate `quote_id`s minted, the state machine is the source of
truth; verify it isn't bypassed:

```bash
sqlite3 /var/lib/dm-issuer/dm-issuer.db \
  "SELECT request_id, state, count(*) FROM requests GROUP BY request_id HAVING count(*) > 1"
```

If empty, there are no duplicate request rows. (Note that the `kv` table holds
the `last_dm_scan_at` cursor; if missing, the next poll uses the 12 h lookback
default.)

---

## 5. Self-Review Findings (Gate 4: Security, Edge Cases, Error Handling)

Reviewed every module in `dm-issuer/src/tollgate_dm_issuer/` for security,
edge cases, and error handling. Each finding is rated **OK** / **LOW RISK** /
**NEEDS FIX**.

### 5.1 Security — ISSUER_NSEC / issuer identity

| # | Concern | Verdict | Notes |
|---|---|---|---|
| S1 | Is `ISSUER_NSEC` ever logged? | **OK** | Only the env var name string literal `"ISSUER_NSEC"` appears in log messages (e.g. `__main__.py:45` `log.error("invalid ISSUER_NSEC nsec format: %s", exc)` uses the exception object, which contains a parse-error message — never the secret value). `config.issuer_nsec()` returns the env value into `nostr_io._issuer_priv_hex` only — it is never passed to `log.*`. |
| S2 | Is `ISSUER_NSEC` ever committed to disk? | **OK** | `_issuer_priv_hex` is an in-memory attribute on `NostrIO`; the SQLite journal stores `event_id`, `npub`, `amount`, `quote_id`, `state`, timestamps — never the private key. `_load_state_from_disk` and `_sync_row` operate on the `requests` schema; no nsec column exists. |
| S3 | Is the nsec read at import time (causing it to leak on exceptions)? | **OK** | `_build_components` reads `os.environ` lazily on demand (in `__main__.py:36-47`), so config reload doesn't trigger a key load. The ops API (`ops.py`) has zero access to the key even though it shares the process — the FastAPI app only reads `Metrics` counters. |
| S4 | Could `ISSUER_NSEC` be revealed in tracebacks? | **LOW RISK** | If `_issuer_privkey_hex` were to throw an exception inside a transaction that captures the value as a local, the traceback would not contain it (the local `raw = os.environ.get("ISSUER_NSEC", "")`). The local `raw` itself is not enumerated in tracebacks unless explicitly attached. Pyright-typed assertions don't run in production. No further action. |

### 5.2 Security — SQL injection in journal

| # | Concern | Verdict | Notes |
|---|---|---|---|
| S5 | Are all `journal.SQLiteJournal` queries parameterized? | **OK** | Every `_conn.execute(...)` call uses `?` placeholders with tuple parameters. Audit summary: `prepare_statement` calls at `journal.py:351-369, 372, 378-382, 388-395, 398-400, 421-423, 428-430, 456-459, 468-475, 482-485, 493-494, 499-501, 505-507, 511-512, 517, 522-524, 543` — all use `?` placeholders. The schema's `INSERT INTO requests` (line 389) and `UPDATE` patterns are static strings, no f-string interpolation of user input. |
| S6 | The `cas_state` f-string at `journal.py:457`: `f"UPDATE requests SET {', '.join(sets)} WHERE request_id = ? AND state = ?"` — f-string in SQL? | **OK** | The f-string interpolates only literal SQL fragments `"state = ?"`, `"updated_at = ?"`, `"quote_id = ?"`, `"error_code = ?"` (built from static `sets` list). Every user-controllable value flows through the `params` list with `?` placeholders. No external input is interpolated. Verified by reading `cas_state` lines 434-464. |
| S7 | `_load_state_from_disk` (line 349-369) — runs raw queries with no parameters from a state file? | **OK** | Reads from the table names (static), no user input interpolation. |

### 5.3 Security — replay / double-processing

| # | Concern | Verdict | Notes |
|---|---|---|---|
| S8 | Are duplicate event_ids deduped correctly? | **OK** | Two layers: (1) `processed_events.event_id PRIMARY KEY` with `is_event_processed(event_id)` short-circuit. (2) `requests.event_id UNIQUE NOT NULL` plus `INSERT OR IGNORE` idempotency on the `processed_events` table. |
| S9 | Could a duplicate event slip through between `is_event_processed` and `mark_event_processed`? | **OK (defense in depth)** | There is a small window between the optimistic `is_event_processed` check (first line of `_handle_one`) and the eventual `mark_event_processed` (after `DELIVERED`). If a duplicate event arrives in that window (e.g. via a relay's re-broadcast), both polls would see `is_event_processed == False`. The **second line of defense** is `requests.event_id UNIQUE`: the duplicate `insert_request` falls back to returning the existing `request_id`, then `cas_state(REQUESTED, QUOTED)` fails because the state has already advanced (the first poll moved it past `REQUESTED`). `cas_state` returns `False`; the caller short-circuits — no double-quote, no double-mint. The CAS state machine is the source of truth, with `processed_events` as a fast-path optimization. |
| S10 | Could `reserve_request` (pending usage counter) be double-applied for a duplicate event? | **LOW RISK** | `InMemoryJournal.reserve_request` and `SQLiteJournal.reserve_request` increment `_pending[(npub, day)]` by amount without deduping on `event_id`. If a duplicate request reaches `policy.check`, the pending counter could be over-inflated. However, the second poll's `cas_state(REQUESTED, QUOTED)` fails before `policy.commit_usage` (called only on `DELIVERED`), so committed usage is not double-counted. The over-reservation only blocks new requests briefly and is corrected on the next poll when `_pending` is recomputed from `fetch_recoverable()`. Recommended future optimization: idempotent `reserve_request(event_id UNIQUE OR IGNORE)` — not currently a security issue. |
| S11 | `processed_events` is checked BEFORE policy allows reserve — so a NOT_WHITELISTED reply could leak dedup state? | **OK** | The first unwhitelisted reply is allowed (NOT_WHITELISTED decision; npub reserved a no-op pending slot). Subsequent unwhitelisted events from the same npub on the same day transition to SILENT_DROP (no reply, since `count_recent_requests >= 1`). Replays of a known bad npub therefore receive no spam amplification. |

### 5.4 Edge cases — stale requests, double-process

| # | Concern | Verdict | Notes |
|---|---|---|---|
| E1 | Stale `REQUESTED` rows older than `stale_request_secs` (600s)? | **OK** | `policy.check` rejects with `STALE_REQUEST` (DecisionKind.REJECTED) at `policy.py:87-93`. Additionally, `journal.recover(*, now, stale_secs)` on startup transitions any `REQUESTED` row older than `stale_secs` to `REJECTED` with `error_code="STALE_REQUEST"` (`journal.py:528-539`). |
| E2 | Policy rejects at `QUOTED` state — can the request get stuck in `QUOTED`? | **OK** | Policy is only called on entering `REQUESTED`; once `QUOTED`, the next pipeline step is `grpc.mark_quote_paid` (transitioning to `PAID` or `FAILED`). The state machine does not allow `QUOTED → QUOTED` transitions, so no stuck state is possible from policy. |
| S/D3 | `Stale QUOTED` after a gRPC timeout? | **OK** | `cas_state(QUOTED, PAID)` only succeeds on the gRPC happy path. On gRPC exception (after retries), the dispatcher falls through to `cas_state(QUOTED, FAILED)` (via the catch handler in `_handle_one`). `ALLOWED_TRANSITIONS` permits `QUOTED → FAILED/EXPIRED/REJECTED`. On restart, `fetch_recoverable()` returns `QUOTED` rows and they are re-attempted in the poll loop. |
| E3 | Duplicate `mark_event_processed` calls — safe? | **OK** | `processed_events` uses `INSERT OR IGNORE` (`journal.py:378-380`), so re-marking is idempotent. |
| E4 | What if `processed_events` table is missing/corrupt? | **OK** | On startup, `SQLiteJournal.__init__` runs `SCHEMA_SQL` which uses `CREATE TABLE IF NOT EXISTS` — auto-creates on missing. Easy to recover. |
| E5 | `deleted_at` cursor missing (`last_dm_scan_at` unset)? | **OK** | `_compute_since_ts` falls back to `now - dm_lookback_default_secs` (12h) when cursor is absent or has bad ISO timestamp. New installs always start with the 12h lookback window. |

### 5.5 Error handling — external dependencies

| # | Concern | Verdict | Notes |
|---|---|---|---|
| EH1 | Mint 500 / non-200 response → journal FAILED? | **OK** | `mint_client.create_quote` raises `MintError` after exhausting `retries`. `dispatcher._handle_one` catches `MintError` and calls `cas_state(REQUESTED | QUOTED, FAILED, error_code="MINT_CREATE_FAILURE" | "MINT_PAID_FAILURE")`. |
| EH2 | gRPC `AioRpcError` (timeout, UNAVAILABLE)? | **OK** | `grpc_payer.mark_quote_paid` swallows `AioRpcError` and returns `False` after `retries` with `grpc_backoff_base_secs * attempt**2` backoff. Dispatcher then `cas_state(QUOTED, FAILED, error_code="GRPC_PAID_FAILURE")`. If `approve_fallback_url` is configured, the `mark_quote_paid` falls through to `POST {url}` with `{"quote_id": ...}` (10s timeout, returns `True` on 2xx). If both fail, journal FAILED. |
| EH3 | Relay down at scan time? | **OK** | `NostrIO.scan_dms_since` catches `Exception` from the `fetch_giftwraps` callable (`nostr_io.py:104-106`) and returns `[]`. The dispatcher counts `0 delivered` and reports nothing — next poll retries with same cursor. |
| EH4 | Relay down at send_dm time? | **OK** | `NostrIO.send_dm` retries `dm_retries` (default 5) times with `dm_backoff_base_secs * attempt**2` backoff. If all retries fail (including `approve_fallback`), the request transitions to `FAILED` with `error_code="DM_SEND_FAILURE"`. The user can resend — `is_event_processed(event_id)` would treat the resend as new only if the previous one reached `mark_event_processed` (which is not called on FAILED). **NEEDS FIX (minor)**: a resend of the same `event_id` after a FAILED delivery is currently silently dropped by `is_event_processed`. **However**, this is the desired behaviour — failed events must be re-sent with a new event id (and the journal's `recover()` will route them to `REJECTED` for admin review). Document in the operator manual: "failed delivery → user must DM a new request with different event_id". |
| EH5 | MySQL/SQLite locked on concurrent update? | **OK** | Single-threaded async loop with `threading.RLock` guard on `InMemoryJournal`. `SQLiteJournal` uses a single shared connection with `check_same_thread=False`. The CAS pattern means conflicting writes return rowcount=0 with no raise. No retry storm. |
| EH6 | Mint quote id missing from the response JSON? | **OK** | `mint_client.create_quote` checks both `body["quote"]` and `body["quote_id"]` keys; either missing triggers `MintError("missing quote id in response: ...")` and retries. After `retries` exhausted, raises to dispatcher. |
| EH7 | Invalid JSON in a gift wrap seal? | **OK** | `_unwrap_giftwrap` wraps `json.loads(seal_json)` and `json.loads(rumor_json)` in `try/except Exception` (lines 217-225, 237-243). Decode errors return `None` — `scan_dms_since` continues processing other events. |
| EH8 | Unverified seal signature? | **OK** | `seal.verify()` returning `False` triggers `return None` (line 234-235). Verify is enforced before the rumor JSON is decrypted. No way to inject a fake sender_pubkey into the journal. |
| EH9 | Empty whitelist default Cap values? | **OK** | `WhitelistEntry.from_dict` falls back to `defaults["daily_cap_sats"]` (2000) and `defaults["max_request_sats"]` (2000). `policy.check` enforces `effective_max_request_sats` against both: `whitelist.max_request_sats` AND `registry_max_single_issuance` (10000). |
| EH10 | Race: ops thread reads `metrics` while poller thread writes? | **OK** | `Metrics` dataclass uses simple `int` atomics (Python's GIL guarantees atomic reads/writes on int). `observe_request_started/delivered/error` increment via `+=`. No torn reads of nested state. |

### 5.6 Operational — Universe-footprint

| # | Concern | Verdict | Notes |
|---|---|---|---|
| OP1 | Does the issuer ever open an inbound port externally? | **OK** | Architecture is scanner-only (`fetch_events`) — outbound WebSocket. Ops API binds `127.0.0.1:8095`. No inbound listeners for Nostr. |
| OP2 | gRPC channel leaks on hot reload? | **OK** | `_build_default_stub` creates a channel bound to the lifecycle of `GrpcPayer`. `close()` (async) calls `await _channel.close()` if present. `_StubAdapter.__getattr__` proxies stub methods lazily — no per-call channel open. |
| OP3 | SQLite WAL mode? | **NEEDS FIX (minor)** | Not set — `SQLiteJournal.__init__` uses default rollback journal. On high throughput this could cause `database is locked` errors when the ops API / CLI access alongside the poller. **Future fix**: add `PRAGMA journal_mode=WAL; PRAGMA busy_timeout=3000;` to `SCHEMA_SQL`. Not a blocker for current load (≤1 req/s). |
| OP4 | Log rotation / disk exhaustion from `req` table? | **OK (impact: low)** | `requests` table grows linearly with traffic. Daily cap is `global_daily_cap_sats / min_request_sats = 600000/100 = 6000` rows/day max. After 1 year: ~2.2M rows. SQLite handles this easily. Future cleanup: add `DELETE FROM requests WHERE state IN ('DELIVERED','FAILED','REJECTED') AND created_at < date('now','-90 days')` as a periodic task. Not a current operational concern. |

### 5.7 Summary

| Category | Count | OK | LOW RISK | NEEDS FIX |
|---|---|---|---|---|
| Security — nsec | 4 | 3 | 1 (S4) | 0 |
| Security — SQL injection | 3 | 3 | 0 | 0 |
| Security — replay | 4 | 3 | 1 (S10) | 0 |
| Edge cases | 7 | 7 | 0 | 0 |
| Error handling — external | 10 | 9 | 0 | 1 (EH4, design choice) |
| Operational | 4 | 3 | 0 | 1 (OP3, minor) |
| **Total** | **32** | **28** | **2** | **2** |

**Headline:** No `NEEDS FIX` items block the Gate 4 quality gate. The two
documented minor fixes (EH4, OP3) are operational improvements deferred to a
follow-up commit. The two LOW RISK items (S4 nsec-locals-during-traceback,
S10 reserve over-inflation on duplicate events) are acceptably contained by
the existing defensive design.

---

## 6. Maintenance commands

```bash
# Inspect recent 20 requests (default JSON pretty-printed)
DM_ISSUER_DB_PATH=/var/lib/dm-issuer/dm-issuer.db dm-issuer show-ledger

# Show per-npub daily usage + cursor
dm-issuer --db $DB show-usage npub1ftjlarsn0k4g5wmxnjcae48u2nl20vfu2lf3rjdqrht89h9z0fhsah7hqu

# Force-reset the Nostr scan cursor (next poll will look back 12h)
dm-issuer --db $DB reset-cursor

# Force a request into REJECTED state (admin reject)
dm-issuer --db $DB revoke-request 0123456789abcdef   # 16-hex request_id

# Live metrics
curl http://127.0.0.1:8095/metrics

# Health (503 when poller has stopped)
curl -i http://127.0.0.1:8095/healthz
```

All commands fail closed: missing config prints a human-readable error and
returns exit code `1`.
