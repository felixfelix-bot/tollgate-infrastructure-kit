# ADR-008: TCP fallback transport (UDP silently fails)

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

UDP peer connections can silently fail — the handshake starts but never completes, and no error is logged. This was observed on DQ05 when peering with test-us01 over UDP. TCP on port 443/8443 traverses most firewalls reliably.

## Decision

All peer configs include BOTH UDP and TCP transport addresses. VPS2 listens on UDP:2121 and TCP:8443. Laptops connect via either transport, with TCP as fallback.

## Consequences

- Two transport ports to open in firewalls (2121/udp, 8443/tcp) on VPS2
- UFW rules required on VPS2 for both ports
- `fips.nft` drop-in needed for the `fips0` interface
- More reliable connectivity in restrictive network environments
- Slightly more complex peer configuration (two addresses per peer)