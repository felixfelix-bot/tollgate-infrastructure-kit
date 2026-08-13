# ADR-005: Nostr discovery with configured_only policy

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

FIPS supports Nostr discovery for peer endpoint advertisement. Policy options:
- **open** — connect to any discovered node
- **configured_only** — only connect to peers whose npubs are in local config or `/etc/fips/hosts`

Using `open` policy on a private mesh risks connecting to random public mesh nodes that advertise on the same relays, re-introducing the bloom filter saturation problem (see ADR-002).

## Decision

Use `configured_only` policy. Machines advertise their npub and transport addresses on Nostr relays (damus, nos.lol, offchain, orangesync, ngit) but only connect to peers whose npubs are in their local config or `/etc/fips/hosts`.

## Consequences

- No random peering with public mesh nodes
- Discovery uses Nostr relays as a convenience layer, not authority
- Relay downtime delays discovery but doesn't break mesh (static peers in config still work)
- Adding a new machine requires updating `/etc/fips/hosts` on all existing machines
- The `fips-overlay-v1` app tag is used for advertisement events