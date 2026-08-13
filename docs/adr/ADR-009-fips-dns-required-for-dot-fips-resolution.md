# ADR-009: fips-dns required for .fips DNS resolution

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

The FIPS daemon has a DNS responder on port 5354, but the system resolver doesn't forward `.fips` queries there without the `fips-dns` service. Symptom: peers are connected but `ssh user@dq05.fips` fails with "Name or service not known" because the system resolver doesn't know about the `.fips` TLD.

## Decision

Enable the `fips-dns` service on all machines. Use the `fips-dns-setup` script to create a systemd-resolved drop-in that routes `.fips` queries to `[::1]:5354`.

## Consequences

- `fips-dns.service` must be enabled and started on every mesh node
- `fips-dns-setup` creates the systemd-resolved integration
- Without it, `.fips` names are invisible to the system resolver
- The Ansible role includes a `dns` tag for managing this service
- DNS resolution is a hard dependency for SSH-over-FIPS to work with hostnames