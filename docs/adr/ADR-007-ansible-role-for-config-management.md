# ADR-007: Ansible role for reproducible config management

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

DQ05's FIPS config was manually edited, causing drift from the intended state. With 4 machines to manage — each with different interfaces, peer configs, but the same base structure — manual editing is error-prone and not reproducible.

## Decision

Use an Ansible role (`ansible/roles/fips/`) with templates for `fips.yaml`, `/etc/fips/hosts`, and firewall rules. Inventory groups: `fips_laptops`, `fips_vps`, `fips_all`. Tags: `install`, `config`, `verify`, `dns`, `firewall`.

## Consequences

- All config changes go through Ansible — manual edits create drift (detected by `--check`)
- Idempotency is required (second run with `--check` shows no changes)
- Group vars must not override role defaults (past issue with tollgate.local relay URLs)
- Templates: `fips.yaml.j2` (main config), `fips-hosts.j2` (host aliases), `ssh.nft.j2` (firewall)
- Role defaults in `ansible/roles/fips/defaults/main.yml` define the base configuration
- Per-host overrides via inventory host vars (e.g., `fips_ethernet_interface`)