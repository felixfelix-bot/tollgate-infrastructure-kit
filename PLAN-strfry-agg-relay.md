# Plan: Strfry Aggregation Relay + Disk Stabilization + Status Fix

## Context

Three problems identified on the tollgate infrastructure:

1. **Disk pressure** — both VPS near full (vps-1: 90%, vps-2: 95-100%, 880M free).
2. **JSON fallback** on `services.orangesync.tech` — Nostr status path dead, relying on JSON.
3. **Need** — a gated aggregation relay that mirrors only followed npubs' events.

## Root Causes (confirmed via live inspection)

### Disk — mostly NOT justified
| Consumer | vps-1 | vps-2 | Justified? |
|---|---|---|---|
| strfry JSONL backups | 17G | 20G | No — full daily dumps x7 of unbounded open relay |
| Docker build cache | 7.4G | 4.4G | No — reclaimable |
| Container write layers (logs) | ~2.2G | ~2.3G | No — unbounded json-logs |
| Bitcoin node | 21G | 13G | Yes (blockchain), prune-able separately |
| Stale market clones | — | ~4G | No |
| /var/log | — | 2.9G | Partially |

Root: `tollgate-backup.sh.j2:31` does full `strfry export` daily x 7 copies.

### JSON fallback
- Signing key CORRECT (npub1u37txk... matches derived key).
- `relay1.orangesync.tech` -> SSL TLSV1_ALERT_INTERNAL_ERROR
- `relay2.orangesync.tech` -> HTTP 502
- `relay.orangesync.tech` -> SSL error
- `gen-vps-stats.py:371-395` swallows all publish errors (`except Exception: pass`).
- Net: events never land on a queryable relay -> browser 15s timeout -> JSON fallback.

## Implementation

### Phase 1 — Stabilize disk + status (immediate relief)

- [x] 1.1 Disk cleanup playbook `38-disk-cleanup.yml`: `docker builder prune -af`, delete strfry JSONL >2 days, remove stale `/home/debian/market*` clones on vps2, `journalctl --vacuum-size=200M`
- [x] 1.2 Docker log rotation: `/etc/docker/daemon.json` with `json-file` `max-size=20m max-file=3` (+ restart docker) — in cleanup playbook, applies on next deploy/recreate
- [x] 1.3 restic incremental backups: install restic; rewrite strfry/ngit backup section to `restic backup` + `restic forget --keep-last 7 --prune`; init restic repo `/opt/tollgate/backups/restic/` — dedup proven (50MB file + 99%-identical = only 658KB delta)
- [ ] 1.4 Flip relay1/relay2 Cloudflare records to DNS-only (gray-cloud); ensure Caddy relay1./relay2. blocks -> localhost:7777
- [x] 1.5 Fix `gen-vps-stats.py` to log (not swallow) Nostr publish errors; verify kind 31998 queryable

### Phase 2 — Aggregation relay (new dedicated gated strfry)

- [x] 2.1 Create `strfry_agg` Ansible role (defaults, tasks, templates: strfry.conf.j2 w/ writePolicy, docker-compose.yml.j2, write-policy.sh.j2, agg-reconcile.py.j2, agg-scrape.py.j2, reconcile + scrape service/timer templates)
- [x] 2.2 Playbook `37-strfry-agg.yml`; wire into `setup-all.yml` after ngit_relay
- [x] 2.3 Install `nak` binary; Cloudflare `agg` record + Caddy block (per-machine -> correct VPS); watchdog health check; services status page entry
- [x] 2.4 `.env` / `.env.example`: add `STRFRY_AGG_ROOT_NPUB` (= npub1c03rad0r...) + auto-managed `STRFRY_AGG_SERVED_NPUBS`

#### Aggregation relay design
- Port 7779, domain `agg.{{ base_domain }}`, Docker strfry, db maxSize 5G.
- **Write-policy plugin**: gates inbound writes to pubkey allowlist (`state/allowed.npubs`).
- **Reconcile timer (15 min)**: fetch root npub kind-3 -> diff vs allowlist -> `strfry delete --filter='{"authors":[unfollowed hex]}'` (SHRINKS on unfollow) -> rewrite allowlist -> mirror `STRFRY_AGG_SERVED_NPUBS` into .env.
- **Scrape timer (30 min)**: per served npub resolve kind-10002 relay list (fallback big relays) -> `strfry sync <relay> --dir=down --filter='{"authors":[hex],"kinds":[...]}'`.

### Phase 3 — Tests

- [x] 3.1 Unit (pytest): reconcile diff (added/removed/unchanged), npub<->hex, allowlist atomic write, plugin decisions
- [x] 3.2 Integration (bash): followed-npub event accepted, non-followed rejected; simulate unfollow -> strfry info count drops

## Key Config

| Variable | Value |
|----------|-------|
| Root npub | npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw |
| Status signing npub | npub1u37txkvf3cskntkfzwvh54aqqfsau998acg0uwa6lrxwy48e6fws7gfnyr |
| agg domain | agg.orangesync.tech |
| agg port | 7779 |
| reconcile interval | 15 min |
| scrape interval | 30 min |

## Verification

- `restic snapshots` shows incremental sizes; `df -h` under threshold.
- WS REQ to relay2.orangesync.tech returns kind 31998; services page shows "Live via Nostr".
- agg.orangesync.tech accepts followed-npub events, rejects others; strfry info stays bounded.
