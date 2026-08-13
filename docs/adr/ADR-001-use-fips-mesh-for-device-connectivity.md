# ADR-001: Use FIPS mesh for device-to-device connectivity

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

Felix needs to SSH between 4 machines (VPS2, DQ05, T14Gen5, T470) across different networks. Some are behind NAT, one is a VPS with a public IP. Options considered:

- **Tailscale** — commercial VPN overlay, third-party coordination server
- **Netbird** — already used for DQ05/T470 connectivity but not installed on T14Gen5
- **FIPS mesh** — IPv6 overlay with Nostr-based discovery, encrypted mesh, no central coordinator
- **Plain SSH with port forwarding** — manual, fragile, doesn't scale

Felix is already invested in the FIPS ecosystem (exit nodes, TollGate, Android client). Netbird works for DQ05/T470 but T14Gen5 is not on Netbird and adding it would require additional setup. Tailscale introduces a third-party dependency. Plain SSH port forwarding is too manual for 4 machines.

## Decision

Use FIPS mesh overlay for device-to-device connectivity across all 4 machines.

## Consequences

- All machines run the FIPS daemon
- `.fips` DNS for name resolution (via fips-dns service)
- SSH over the `fips0` TUN interface using `<shortname>.fips` hostnames
- No dependency on third-party VPN services (Tailscale, Netbird)
- FIPS must be installed, configured, and maintained on every machine
- Mesh connectivity depends on FIPS daemon health on each node