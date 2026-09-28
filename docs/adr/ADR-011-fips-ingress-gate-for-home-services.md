# ADR-011: FIPS ingress gate for hosting services from home machines

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

Felix wants to host services from home machines (DQ05, T14Gen5) accessible from the internet. VPS2 has Caddy, a public IP, and a domain (orangesync.tech). The FIPS mesh connects VPS2 to all home machines via the `fips0` TUN interface.

Options considered:
- WireGuard tunnel from VPS2 to home machines — redundant since FIPS mesh already provides connectivity
- Port forwarding on home router — not possible, machines are behind NAT
- FIPS ingress gate — reverse proxy on VPS2 forwarding to FIPS mesh IPv6 addresses

## Decision

Use Caddy `reverse_proxy` on VPS2 to forward internet traffic to FIPS mesh IPv6 addresses. SSH via `ProxyJump` through VPS2. TCP services via Caddy layer4 or nftables DNAT.

## Consequences

- Internet → VPS2:443 (Caddy) → `[fd00::home-machine]:port`
- No WireGuard tunnel needed (VPS2 is already on the FIPS mesh)
- High-latency hops need increased `proxy_timeout` in Caddy
- PoC verified 2026-08-12
- VPS2 is the single public entry point — if it goes down, all home-hosted services are unreachable
- FIPS mesh IPv6 addresses must be stable (persistent identity ensures this)