# ADR-004: Pin FIPS version to v0.4.1

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

FIPS master branch is mid-sans-io rewrite (v0.5.0-dev) and may break features. The ble-v2 branch is for Android/BLE. FIPS v0.4.1 is the latest stable release (2026-07-19) and is wire-compatible with v0.4.0.

VPS2 currently runs v0.4.0-dev, which needs upgrading. DQ05 and T14Gen5 already run v0.4.1.

## Decision

Pin all machines to FIPS v0.4.1. Use prebuilt .deb packages (amd64). Do NOT follow master branch.

## Consequences

- Stable, reproducible deployments across all machines
- Missing v2 features (dynamic bloom filters, Nym mixnet)
- Will need a coordinated upgrade when v2 is released and stable
- .deb packages provide clean install/upgrade path with systemd integration
- Wire compatibility with v0.4.0 means VPS2 upgrade from v0.4.0-dev is safe