# Plan: Plebeian Market Aggregator Relay + WoT Filter

## Context

The Plebeian Market auctions UI suffers from multi-second load times. Root cause
analysis (issue #1046) identified dead relays masked by 8s timeouts + sequential
query waterfalls as the primary bottlenecks. NDK is NOT the dominant median
bottleneck (both NDK and applesauce EOSE in ~180ms on healthy relays).

A dedicated WoT-gated strfry aggregator relay eliminates the dead-relay problem:
the market app queries ONE fast local relay instead of fanning out to 5+
potentially-dead relays. The relatr ContextVM provides multi-hop web-of-trust
filtering so the aggregator only caches events from trusted npubs.

## Architecture

```
[Market App]
     | queries (ONE relay, ~5ms local)
     v
[market-agg.orangesync.tech : strfry :7780]
     ^ write-policy checks      ^ scrapes upstream
     |                           |
[relatr-market :3001]       [nos.lol, damus, relay.orangesync.tech]
     | WoT allowlist
     v
  allowed.npubs (2-hop trust graph)
```

## Components

| Component | Domain | Port | Role |
|-----------|--------|------|------|
| strfry market agg | market-agg.{{ base_domain }} | 7780 | strfry_agg (overridden vars) |
| relatr market WoT | market-wot.{{ base_domain }} | 3001 | relatr (overridden vars) |

## Deployment

```bash
# Deploy market aggregator on vps2
ansible-playbook 39-plebeian-market-agg.yml -i inventory/ --extra-vars "target=vps2"

# Or as part of full setup (opt-in)
ansible-playbook setup-all.yml --extra-vars "deploy_market_agg=true"

# Required env vars:
export MARKET_AGG_ROOT_NPUB=npub1c03rad0r...  # root trust anchor
export CLOUDFLARE_API_TOKEN=...                # for DNS records
```

## Root npubs (trust anchors)

Add Plebeian team members to the relatr source config:
- c03rad0r (operator)
- Franchovy (market maintainer)
- maximotodev (developer)

## Market-specific event kinds (scraped)

| Kind | Description |
|------|-------------|
| 1023 | Auction root |
| 1024 | Auction bid |
| 1025 | Auction settlement |
| 1026 | Auction claim |
| 30408 | Auction path release |
| 30440 | Validator verdict |
| 30441 | Validator (variant) |
| 30442 | Validator (variant) |
| 30023 | Long-form (auction listings) |
| + standard kinds | 1, 3, 5, 6, 7, 10000, 10002 |

## Wiring the market app

After deployment, update `src/lib/stores/ndk.ts` in the market repo:

```typescript
const MARKET_AGG_RELAY = `wss://market-agg.${BASE_DOMAIN}`;
// Add as primary relay (first in the list, fastest path)
explicitRelayUrls: [MARKET_AGG_RELAY, 'wss://relay.damus.io', 'wss://nos.lol']
```

## Checklist

- [x] Playbook created: `39-plebeian-market-agg.yml`
- [x] Caddy routes added: `market-agg.*` + `market-wot.*` (+ general `agg.*` + `wot.*`)
- [x] Wired into `setup-all.yml` (opt-in via `deploy_market_agg=true`)
- [x] Uses existing `strfry_agg` + `relatr` roles (no new role needed)
- [ ] Deploy on VPS (requires SSH access + env vars)
- [ ] Wire market app's `ndk.ts` to use aggregator as primary relay
- [ ] Add Franchovy + maximotodev npubs as trust anchors
- [ ] Verify write-policy rejects untrusted npubs
- [ ] Load-test: compare auctions UI load time before/after
