# FIPS Ingress Gate — Public Internet → FIPS Mesh

> **Status:** Design / Planning
> **Created:** 2026-08-12
> **Owner:** Felix (c03rad0r)
> **Repo:** `tollgate-infrastructure-kit`
> **VPS:** VPS2 (23.182.128.51, `orangesync.tech`)
> **Inspiration:** [fr34aky/fips-exit-gate](https://github.com/fr34aky/fips-exit-gate) (outbound exit service)

---

## 1. Purpose

The fips-exit-gate project handles **outbound** traffic: FIPS mesh → public
internet (SOCKS5 egress, paid packages, captive portal). This document covers
the reverse: **inbound** traffic from the public internet → VPS2 → FIPS mesh →
home machines hosting services.

**Goal:** Use a VPS with a public IP as a front door. Any FIPS mesh machine
at home can host content (web, API, SSH) accessible from the public internet,
routed through the VPS into the FIPS mesh. Think Tailscale/Netbird — but over
FIPS, with no additional VPN layer.

---

## 2. Architecture

```
   Public Internet
        │
        ▼ :443 (HTTPS)     :22 (SSH)       :XXXX (arbitrary TCP)
┌─ VPS2 (23.182.128.51) ──────────────────────────────────────┐
│                                                             │
│  Caddy (TLS, SNI routing)    SSH daemon    nftables/Caddy4  │
│  subdomain.domain →          ProxyJump     port forward      │
│  [fd00::fips-addr]:port      → fips0       → fips0           │
│                                                             │
│  fips0 interface (MTU 1280, IPv6 fd00::/8)                   │
│  FIPS mesh node — reaches all home machines via fd00::/8    │
│  VPS2 FIPS addr: fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149   │
│                                                             │
└──────────┬──────────────────────┬────────────────────────────┘
           │ fips0                 │ fips0
           ▼                       ▼
  ┌────────────────┐     ┌────────────────┐
  │ Home FIPS node  │     │ Home FIPS node  │
  │ fd00::machine1  │     │ fd00::machine2  │
  │ :443 (web)      │     │ :8080 (API)     │
  │ :22 (SSH)       │     │ :3000 (grafana) │
  └────────────────┘     └────────────────┘
```

**Key insight:** VPS2 runs FIPS as a mesh participant. It gets a `fd00::/8`
address and can route to any other FIPS machine. No WireGuard tunnel needed —
FIPS IS the overlay network. Caddy on VPS2 already terminates TLS for
`orangesync.tech` and can reverse-proxy to FIPS addresses directly.

---

## 3. Transport Modes

### 3.1 HTTP/HTTPS Services — Caddy Reverse Proxy

Caddy already runs on VPS2 with Cloudflare DNS TLS. Add routes pointing to
FIPS addresses instead of localhost:

```caddy
# Example: Grafana dashboard on a home FIPS machine
grafana.orangesync.tech {
    reverse_proxy [fd00::machine-addr]:3000
}

# Example: Web app on a home FIPS machine
app.orangesync.tech {
    reverse_proxy [fd00::machine-addr]:443
}
```

- TLS terminates at VPS2 (Cloudflare DNS challenge)
- Plaintext to FIPS address (FIPS mesh is encrypted at L3)
- Multiple services on different subdomains, all via :443
- No additional VPN, no WG, no SSH tunnels

### 3.2 SSH Access — ProxyJump

VPS2 already has SSH on :22 and can route to fips0. Use SSH ProxyJump:

```ssh-config
# ~/.ssh/config
Host dq05.fips
    ProxyJump root@23.182.128.51
    HostName fd00::dq05-addr
    User c03rad0r

Host t470.fips
    ProxyJump root@23.182.128.51
    HostName fd00::t470-addr
    User c03rad0r
```

Then: `ssh dq05.fips` — transparent SSH into any FIPS machine via VPS2.

Alternative: Caddy layer4 plugin for TCP stream proxy:
```caddy
:2222 {
    reverse_proxy fd00::machine:22
}
```

### 3.3 Arbitrary TCP — Caddy layer4 or nftables DNAT

For non-HTTP TCP services (gaming, MQTT, custom protocols):

**Option A — Caddy layer4 plugin (TCP stream):**
```caddy
:8080 {
    reverse_proxy [fd00::machine]:8080
}
```

**Option B — nftables port forward:**
```bash
nft add rule nat prerouting tcp dport 8080 dnat to [fd00::machine]:8080
```

---

## 4. FIPS Addressing

FIPS addresses are derived from npub via `SHA-256(pubkey)[0:15]` prefixed with
`fd00::/8`. The `*.fips` DNS domain resolves these automatically via fips-dns.

### 4.1 Known Mesh Nodes

| Alias | npub | FIPS Address | Machine |
|-------|------|-------------|---------|
| vps2 | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82` | `fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149` | VPS2 (public IP hub) |
| dq05 | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72` | (derived) | DQ05 laptop |
| t14gen5 | (derived) | (derived) | T14Gen5 laptop |
| t470 | (derived) | (derived) | T470 backup laptop |

### 4.2 FIPS URL Convention

FIPS supports `npub.fips` DNS resolution. Services can be addressed as:
- `http://npub1....fips:8080/dashboard`
- `http://npub1....fips:8081/proxy_clear.pac`

The fips-dns daemon (`[::1]:5354`) resolves `*.fips` names to FIPS IPv6 addresses.

---

## 5. Reference: fips-exit-gate Patterns

The [fips-exit-gate](https://github.com/fr34aky/fips-exit-gate) project provides
useful patterns we can adapt for the ingress direction:

| Pattern | Exit Gate (outbound) | Ingress Gate (inbound) |
|---------|----------------------|------------------------|
| **Auth** | Source IPv6 address (npub-derived) | Caddy TLS + optional client cert |
| **Gate** | nftables: authorized → service, else captive | nftables: rate limit + Caddy routing |
| **Egress** | Dante SOCKS5 → internet | Caddy reverse_proxy → fips0 |
| **Metering** | Per-client byte counters | Optional: Caddy access logs + Prometheus |
| **Payments** | BTCPay/Cashu prepaid packages | Not needed (operator's own services) |
| **Captive** | Unauthorized → 302 portal | 404 for unknown subdomains |
| **DNS** | unbound server-side | fips-dns on VPS2 for *.fips resolution |

### Key files from fips-exit-gate for reference:

- `pkg/fipsaddr/fipsaddr.go` — npub → fd00::/8 address derivation
- `deploy/render-nftables.sh` — nftables gate ruleset template
- `deploy/services.conf` — service catalog (port mapping)
- `dispatch/route.go` — destination-based routing (SOCKS5)
- `docs/threat-model.md` — security model (source-address trust, abuse prevention)

---

## 6. Example URLs (from operator's mesh)

These are live services on the FIPS mesh, accessible from any mesh participant:

- `http://npub1lx2m36mtzpvae7caw6tphqzhuyufg82y63p8lvd8n6nvkdkw0thq08hdpz.fips:8080/dashboard`
  - Dashboard service on a FIPS node (exit-gate management portal)

- `http://npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n.fips:8081/proxy_clear.pac`
  - PAC (Proxy Auto-Configuration) file for SOCKS5 egress via the exit gate

These demonstrate the FIPS URL convention: `npub.fips:port/path`. The ingress
gate will expose similar services to the public internet via subdomains on
`orangesync.tech`.

---

## 7. Security Considerations

### 7.1 Threat model (inbound differs from outbound)

- **Public attack surface:** VPS2:443 is internet-facing. Caddy TLS + SNI
  routing limits exposure. Only explicitly configured subdomains route to FIPS.
- **No source-address auth needed:** Unlike the exit gate (which trusts FIPS
  source addresses), inbound traffic from the internet is untrusted. Caddy
  handles TLS. Optional client certificate auth for sensitive services.
- **Rate limiting:** nftables on VPS2 for per-IP connection limits (inspired by
  exit-gate's `MAX_CONNS_PER_SRC` pattern).
- **FIPS mesh isolation:** VPS2 FIPS daemon only accepts connections from
  configured peers. Random internet traffic cannot enter the mesh directly.

### 7.2 Hardening checklist

- [ ] Caddy: TLS 1.2+ only, HSTS headers
- [ ] nftables: per-source connection limits on :443
- [ ] Caddy: default 404 for unknown subdomains (already configured)
- [ ] SSH: key-only auth, no password, fail2ban already deployed
- [ ] FIPS: `configured_only` discovery policy (no random peers)
- [ ] Optional: Caddy client-cert auth for admin/SSH-proxy routes

---

## 8. Implementation Plan

### Phase 1: VPS2 FIPS operational ✅

- [x] Fix duplicate `peers` field in `/etc/fips/fips.yaml`
- [x] Restart fips.service — now running, fips0 interface UP
- [x] VPS2 FIPS address: `fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149`
- [x] Peers connecting (Andre + 2 NAT-traversed peers)

### Phase 2: Caddy FIPS routing

- [ ] Add first test route: `test-fips.orangesync.tech → [fd00::machine]:port`
- [ ] Verify TLS + reverse_proxy works to FIPS address
- [ ] Document Caddy reload procedure

### Phase 3: SSH ProxyJump

- [ ] Configure `~/.ssh/config` with ProxyJump for FIPS machines
- [ ] Test SSH to each home machine via VPS2
- [ ] Document SSH access patterns

### Phase 4: Arbitrary TCP

- [ ] Evaluate Caddy layer4 plugin vs nftables DNAT for TCP services
- [ ] Add first non-HTTP TCP route
- [ ] Test end-to-end

### Phase 5: Documentation + Automation

- [ ] Ansible role for managing FIPS ingress Caddy routes
- [ ] Template for adding new exposed services
- [ ] Monitoring (Prometheus metrics on routes, access patterns)

---

## 9. Comparison: Why Not SSH Tunnel / WG / Reverse Proxy?

| Option | Verdict | Reason |
|--------|---------|--------|
| SSH reverse tunnel | ❌ Rejected | One tunnel per port, reconnect flakiness, no SNI multiplexing, home machine must maintain connection |
| WireGuard tunnel | ❌ Rejected | Unnecessary — VPS2 IS a FIPS mesh node, can reach all fd00::/8 natively. WG would add a second overlay for no benefit |
| nginx reverse proxy | ⚠️ Viable | Caddy already deployed on VPS2, does the same thing with better TLS automation (Cloudflare DNS challenge). No reason to switch |
| **Caddy + FIPS** | ✅ Selected | Already running, TLS automated, SNI routing, simple config, no extra tunnel needed |

**Bottom line:** VPS2 runs FIPS → it has fd00::/8 routing to all home
machines. Caddy already handles TLS + reverse proxy for ~15 services on
`orangesync.tech`. Adding routes to FIPS addresses is a one-line Caddyfile
change per service. This is the simplest, most maintainable approach.

---

## 10. Bidirectional Future

The ingress gate pairs naturally with a fips-exit-gate deployment on VPS2:

- **Inbound** (this doc): `internet → VPS2:Caddy → fips0 → home machines`
- **Outbound** (fips-exit-gate): `home machines → fips0 → VPS2:Dante → internet`

VPS2 becomes a full bidirectional FIPS gateway: public-facing front door for
hosting services, and paid SOCKS5 exit for outbound internet access. Both
share the same FIPS mesh membership and nftables infrastructure.