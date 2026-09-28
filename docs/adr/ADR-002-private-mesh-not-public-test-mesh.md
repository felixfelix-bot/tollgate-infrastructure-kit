# ADR-002: Private mesh instead of public test mesh (bloom filter saturation)

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

The original plan connected all machines to the public FIPS test mesh (test-us01 through test-uk01). The public mesh bloom filters are saturated — too many nodes causing false positives, unreliable discovery, wasted bandwidth. FIPS v2 with dynamic bloom filter sizing is not yet released.

Symptoms on the public mesh:
- Bloom filter false-positive rates skyrocket, causing unnecessary connection attempts
- Discovery messages become unreliable — nodes miss or misinterpret peer advertisements
- Mesh becomes noisy with traffic from unrelated nodes, degrading performance
- Memory and CPU overhead from maintaining large filter state impacts laptops on WiFi

## Decision

Run a private mesh with only Felix's 4 devices (VPS2, DQ05, T14Gen5, T470). No public test mesh nodes. VPS2 serves as the hub.

## Consequences

- Small bloom filters (4 nodes), no noise from unrelated nodes
- Full control over topology and routing
- No connectivity to other FIPS users on the public mesh
- Can reconsider joining the public mesh when FIPS v2 ships dynamic bloom filter sizing
- All peering must be explicitly configured — no accidental discovery of outside nodes