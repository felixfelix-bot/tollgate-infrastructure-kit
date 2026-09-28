# ADR-010: SSH-over-FIPS uses standard sshd on [::]:22

- **Date:** 2026-08-12
- **Status:** Accepted

## Context

SSH over FIPS is just SSH over the `fips0` TUN interface — no special FIPS SSH client is needed. The existing `sshd` already listens on `[::]:22` (all interfaces, including `fips0`). The question is whether to run a separate sshd instance for the FIPS interface or use the existing one.

## Decision

No sshd config changes. Use `ssh user@<shortname>.fips` for mesh SSH. The `fips.nft` firewall must allow inbound TCP:22 on `fips0` (drop-in rule). `ConnectTimeout=30` is recommended for high-latency mesh links.

## Consequences

- SSH access on `fips0` is governed by `fips.nft` firewall (default-deny, need drop-in for port 22)
- UFW on the host is separate from the FIPS interface firewall
- Three-layer firewall stack: `ufw` + `fips.nft` + `fips-firewall.service`
- No additional sshd processes or config files to manage
- `ssh.nft.j2` template deploys the nftables rule for fips0 SSH access