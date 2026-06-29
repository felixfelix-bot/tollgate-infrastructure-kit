# FIPS Exit Node — Known Limitations and Security Notes

## Status: Functional for testing / dogfooding. NOT production-hardened.

## Limitations

### 1. Open Exit / Abuse Risk (HIGH)
Anyone with a WireGuard peer entry can route all internet traffic through the VPS.
Illegal activity traces back to the VPS IP.
- No bandwidth limiting
- No traffic logging
- No per-peer isolation
- **Mitigation**: Only allow trusted peers. Add rate limiting (nft `limit` rules) before production.

### 2. Forward Chain Default-Accept (MEDIUM)
The forward chain uses `policy accept` (line 8 of exit-nat.nft.j2).
If no rule matches, the packet is ALLOWED, not dropped.
- **Fix**: Change to `policy drop` with explicit allow rules for the tunnel subnet only.

### 3. No IPv6 NAT (MEDIUM)
Rules are IPv4-only (`ip saddr`, not `ip6 saddr`).
FIPS uses IPv6 natively. IPv6 tunnel traffic will not be NAT'd — it will leak or fail silently.
- **Fix**: Add a parallel `ip6` postrouting masquerade rule and ip6 forward rules.

### 4. Persistent ip_forward sysctl (LOW)
`net.ipv4.ip_forward=1` is set persistently. Required for forwarding but increases blast radius
if other firewall rules are misconfigured elsewhere on the VPS.

### 5. On-Box Key Generation (LOW)
WireGuard private keys AND Nostr identity are generated on the VPS itself via `wg genkey`.
Files are mode 0600 (good), but if the VPS is compromised the attacker gets the private keys.
- **Consideration**: For production, generate keys offline and inject via Ansible vault.

## Reviewed
- nftables template: `templates/exit-nat.nft.j2`
- WireGuard config: `templates/wg-exit.conf.j2`
- Ansible tasks: `tasks/main.yml`
- Reviewed: 2026-06-30
