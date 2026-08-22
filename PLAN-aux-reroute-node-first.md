# PLAN: Aux-Model Rerouting — Corrected Cost Economics

Date: 2026-08-22 · Status: **PREMISE INVALIDATED — corrected plan below**
Related: `PLAN-ewma-outlier-aux-audit.md` (found the $81.83/24h aux bleed)

## What happened

Started implementing a "node-first failover" fix based on the premise
that the routstr node serves glm-5.2 at ~$0.0004/M. **Live measurement
disproved this:**

| Provider | Published rate | MEASURED rate (2026-08-22) | $/M @ BTC $77k |
|---|---|---|---|
| routstrd | 1 sat/M (sats_pricing) | ~0.8 sat/M (61,489 sats / 76M tok) | **$0.0006/M** |
| routstr node | 0.38 sat/M (pricing) | **~250 sat/M** (177 sats / 562 tok) | **$0.19/M** |
| OpenRouter | $0.97/M | $0.97/M | $0.97/M |

The node's published `pricing.prompt=3.81e-7` is sats/token on paper but
the node charges ~250 sat/M in practice (per-request caps, margins, or
rounding). The node is **300× more expensive than routstrd**, not cheaper.

## Corrected root cause of the $7.14 OpenRouter aux waste

- routstrd is the cheapest path ($0.0006/M) and already wins the failover
  sort (its missing `pricing` field parses as $0.00/M).
- 607 aux calls went to OpenRouter ($7.14) because **routstrd timed out
  1,899 times today** (flaky third-party upstream nodes: DigitalOcean,
  Baidu). When routstrd times out, the proxy falls through to OpenRouter.
- The fix is NOT "node-first" — it's **routstrd reliability** (its
  upstream node selection / retry behavior), which is the parallel
  session's active work (`fix/routstrd-balance-race-condition` branch).

## Actions taken this session

- [x] Discovered the node's loopback-bind probe failure (1,589 skips) —
      fixed by ROUTSTR_BASE env (playbook 48) + zai-proxy restart.
- [x] Implemented sats→USD conversion in `_fetch_openrouter_style_rates`
      — **REVERTED**: would have mispriced the node at $0.0004/M and
      stolen traffic from the genuinely cheaper routstrd.
- [x] Measured real per-token costs via live balance deltas — the
      foundational data that corrected the plan.

## What remains (corrected)

- [ ] D4. Fix playbook 48 (routstr_node_access role): add `notify: restart
      zai proxy` to the ROUTSTR_BASE env task so future env changes
      propagate (still valid — the stale-process bug is real).
- [ ] E1. routstrd reliability (1,899 timeouts/24h → OR fallback): this is
      the **parallel session's** active branch
      (`fix/routstrd-balance-race-condition`). Do NOT duplicate — coordinate.
- [ ] E2. Consider adding the node as a failover tier BETWEEN routstrd and
      OpenRouter (node $0.19/M << OR $0.97/M) — would catch the 607 aux
      calls that escape routstrd timeouts, saving ~$4.56/24h of the $7.14.
      Requires: correct node cost in the sort (~$0.19/M, not $0.0004/M).
- [ ] D7. Commit + push corrected plan doc + playbook 48 fix.

## Out of scope

- The node's published pricing vs actual charge discrepancy (routstr
  project's metering logic — their codebase, not ours).
- zai_proxy.py sats→USD conversion (reverted; would need the node's REAL
  measured rate hard-coded, not its published rate, to be safe).