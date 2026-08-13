# ADR-003: VPS2 as hub in hub-and-spoke topology

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

A node with a public IP is needed for NAT traversal — all laptops are behind NAT and cannot accept inbound connections. VPS2 (23.182.128.51) has a public IP, accepts inbound, and already runs FIPS as an exit node. Full-mesh peering between all laptops is impractical because NAT-to-NAT direct connections require STUN luck or relay assistance.

## Decision

Hub-and-spoke topology: VPS2 is the hub, all laptops (DQ05, T14Gen5, T470) peer directly to VPS2. LAN discovery is enabled for same-network machines. Nostr discovery (configured_only policy) provides relay-based peer finding as a secondary mechanism.

## Consequences

- VPS2 is a single point of failure — if it goes down, all cross-network mesh connectivity is lost
- Mitigated by LAN discovery between laptops on the same WiFi (DQ05 and T14Gen5 can find each other directly)
- VPS2 also serves as exit node for internet access
- Cross-network traffic between two laptops transits through VPS2
- VPS2 must maintain high uptime — all laptops depend on it