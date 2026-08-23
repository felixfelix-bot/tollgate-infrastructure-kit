# PLAN: Cost History Rewrite + Measured Rates + Public Dataset

Date: 2026-08-23 · Status: DONE (all phases executed + verified)
Related: `PLAN-aux-reroute-node-first.md` (corrected economics),
`PLAN-ewma-outlier-aux-audit.md` (found the bleed)

## Goal

Fix the foundational unit-error in routstrd/routstr cost accounting (sats
misread as USD inflating recorded spend ~1.5×), establish a forward-looking
**measured-rate** probe so the failover sort uses ground truth instead of
unreliable catalog pricing, and publish a sanitized copy of the telemetry
dataset for the community.

## Corrected economics (live-measured 2026-08-22)

| Provider | Real rate (measured) | $/M @ BTC $77k |
|---|---|---|
| routstrd | ~0.8 sat/M | **$0.0006/M** |
| routstr node | ~250 sat/M | **$0.19/M** |
| OpenRouter glm-5.2 | $0.97/M | $0.97/M |

routstrd is the cheapest; recorded $75.87/24h was inflated by the
sats-as-USD bug in `routing_profit.effective_price`. Real burn ≈ $47/24h.

## Phase 1: Backup

- [x] PRAGMA wal_checkpoint(TRUNCATE) on zai_usage.db.
- [x] Timestamped copy to `~/.hermes/bot/zai_usage.db.bak-costrewrite-<ts>`.
- [x] JSON snapshot of the 3 daily_spend routstrd/routstr rows.

## Phase 2: Measured-rate probe

- [x] Write `scripts/routstr_probe.py` in kit (deployed to
      `~/.hermes/profiles/manager/scripts/`).
- [x] Create `measured_rates(provider, model, sats_per_M, usd_per_M,
      btc_usd, measured_at)` table in zai_usage.db.
- [x] Run probe once to populate seed values.
- [x] Wire daily crontab `0 3 * * *` (before escalation cron).

## Phase 3: Historical rewrite (with audit trail)

- [x] Fetch historical BTC/USD per day (2026-08-19 through 2026-08-23)
      from CoinGecko; cache in JSON.
- [x] Create shadow tables `daily_spend_inflated_pre_rewrite`,
      `routing_profit_inflated_pre_rewrite`,
      `api_calls_cost_inflated_pre_rewrite` populated with originals.
- [x] Rewrite daily_spend spend_usd for routstrd/routstr rows.
- [x] Rewrite routing_profit effective_price for 1,490 routstrd/routstr rows.
- [x] Backfill api_calls.cost_usd for 1,483 routstrd/routstr NULL rows.
- [x] Verification queries: Aug 22 routstrd should be ~$47 (was $75.87).

## Phase 4: Forward-looking fix (zai_proxy.py)

- [x] Add `_get_measured_rate(provider, model)` helper: reads
      measured_rates table, returns None if stale (>24h).
- [x] In `_get_provider_cost`, check measured rates FIRST for
      routstr/routstrd before catalog fallback.
- [x] Commit to `~/.hermes/bot` repo on branch
      `fix/routstrd-balance-race-condition` (survives parallel-session
      checkouts).
- [x] Mirror as patch file in `~/tollgate-infrastructure-kit/docs/patches/`.

## Phase 5: Sanitized export

- [x] Write `scripts/sanitize_db.py` in kit.
- [x] Drop key_suffix, session_id; categorize error_type to enum.
- [x] Drop anomaly_events.detail + key_health transients.
- [x] Keep real provider names (user-confirmed).
- [x] Run it to produce scrubbed.db.

## Phase 6: Key scrub (MRE worktree branch)

- [x] `docs/PLAN-oxalpha-acceleration-2026-08-22.md:249` — redact
      `sk-or-v1-08c…2af` → `sk-or-v1-[REDACTED]`.
- [x] `docs/PLAN-oxalpha-promo-2026-08-21.md:32` — redact
      `sk-or-v1-0e7…d92` → `sk-or-v1-[REDACTED]`.
- [x] Leave fixture/test display keys alone (already illustrative).
- [x] Commit on the worktree branch (don't push — parallel session owns it).

## Phase 7: Publish to MRE datasets/

- [x] `datasets/routing-telemetry/scrubbed.db.gz` (compressed).
- [x] `datasets/routing-telemetry/README.md` — schema doc + sample queries.
- [x] `datasets/routing-telemetry/SCHEMA.sql` — sqlite3 .schema dump.
- [x] Push MRE branch `datasets/routing-telemetry`.

## Phase 8: Plan doc + commits

- [x] Ansible playbook `51-routstr-cost-probe.yml` (deploys probe + cron).
- [x] Commit + push probe, sanitize script, patch, plan doc, playbook to
      `buzz-audio-bridge-docs`.

## Out of scope

- routstrd reliability (1,899 timeouts/24h) — parallel session's branch.
- node as middle-tier failover — automatically better once measured_rates
  drive the sort.
- Auto-rotation of MRE worktree keys (already truncated — pure cosmetic).
