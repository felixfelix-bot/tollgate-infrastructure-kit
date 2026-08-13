# ADR-006: Two-pass deployment for persistent identity npub discovery

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

FIPS persistent identity mode generates a random npub on first run. Host aliases in `/etc/fips/hosts` and the Ansible `fips_mesh_hosts` variable require npubs to be known in advance. T14Gen5 and T470 npubs are not known until FIPS has been installed and started on those machines.

## Decision

Two-pass deployment:
1. **Pass 1:** Install FIPS on all machines, collect npubs via `fipsctl show status`
2. **Pass 2:** Redeploy with all npubs populated in `fips_mesh_hosts` and `/etc/fips/hosts` for fleet-wide DNS resolution

## Consequences

- First deploy only has known npubs (VPS2, DQ05)
- T14Gen5 and T470 npubs discovered in Pass 1, added for Pass 2
- Ansible role handles this via the `fips_extra_hosts` variable for incremental additions
- Two Ansible runs required to achieve full mesh connectivity
- Machines have partial DNS resolution after Pass 1 (only vps2 and dq05 aliases)