# FIPS Ingress Gate — Public Internet → FIPS Mesh Reverse Proxy

## Status: Phase 1 COMPLETE — PoC verified
## Date: 2026-08-12

## Problem Statement

Home machines on the FIPS mesh (fd00::/8 IPv6) need to serve content to
the public internet. The VPS (23.182.128.51) has a public IP and is
already a FIPS mesh participant. We need a reverse proxy on the VPS that
accepts inbound traffic from the internet and forwards it to home
machines reachable via the FIPS mesh.

This is the INVERSE of fips-exit-gate (which does FIPS → internet).
Together they form a bidirectional gate.

## FIPS-Native Service Examples

FIPS supports `.fips` domain resolution — services are reachable via
`<npub>.fips:<port>` from within the mesh. Examples observed on the
live mesh:

- **Dashboard**: `http://npub1lx2m36mtzpvae7caw6tphqzhuyufg82y63p8lvd8n6nvkdkw0thq08hdpz.fips:8080/dashboard`
  - A web dashboard served by node npub1lx2m... on port 8080
  - Demonstrates: HTTP service over FIPS mesh, .fips DNS resolution
  - Ingress gate would expose this as e.g. `dashboard.orangesync.tech`

- **PAC file (proxy auto-config)**: `http://npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n.fips:8081/proxy_clear.pac`
  - Proxy auto-config served by andre's node on port 8081
  - Demonstrates: non-HTTP-standard path served over FIPS, PAC distribution
  - Ingress gate would expose this as e.g. `pac.orangesync.tech`

These confirm FIPS mesh carries HTTP traffic natively. The ingress gate
just needs to bridge public internet → these FIPS-native endpoints.

## Current Infrastructure (Verified)

### VPS2 (23.182.128.51)
- **FIPS daemon**: running, active, 3 connected peers
- **VPS2 FIPS address**: `fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149`
- **FIPS interface**: fips0 (MTU 1280)
- **Routing**: `fd00::/8 dev fips0` (all FIPS traffic via mesh)
- **Caddy**: v2.11.3, already running on :80/:443
- **Caddyfile**: `/etc/caddy/Caddyfile` — has on_demand_tls + many routes
- **On-demand TLS**: configured, asks `http://127.0.0.1:6798/` (nsite gateway)
- **Domains**: orangesync.tech (Cloudflare), sovereignengineering.io (Namecheap)

### FIPS Mesh Peers (reachable from VPS2)
| Name | FIPS IPv6 | Npub | Status |
|------|----------|------|--------|
| npub1ajkl...2k8a | fd1b:eb17:a8ae:e7a1:4094:1ac5:3f90:f6b9 | npub1ajkllfq8tewz4r27txg8sajlj2wvjealc5h76hnke3czue665wpqzu2k8a | connected |
| npub1jtn5...fp8k | fd0b:350e:c8ce:5d40:60fd:3bfe:a757:fdf0 | npub1jtn5fu7ear993zx6xxkg... | connected |
| andre | fd91:8fb5:5778:f352:7ee2:1fdb:d6ab:868f | npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n | connected |

### fips-exit-gate (reference, fr34aky's repo)
- Outbound: FIPS → internet via SOCKS5 (Dante) + nftables gate
- Auth by source IPv6 address (npub-derived, no credentials)
- nftables authorized set + per-client byte counters
- Captive portal for unauthorized users
- We borrow patterns from this for the ingress direction

## Requirements

1. **HTTP/HTTPS reverse proxy**: internet → VPS → FIPS home machine
2. **TCP proxy (non-HTTP)**: SSH access to any FIPS machine from internet
3. **Multi-machine**: route by hostname/SNI to different home machines
4. **TLS**: automatic cert management (Caddy on-demand or Let's Encrypt)
5. **Access control**: optional — restrict who can reach services
6. **Bidirectional**: VPS2 already does egress (fips-exit-gate), add ingress
7. **FIPS-native**: VPS reaches home machines via fips0 interface (already works)

## Architecture

```
                    Public Internet
                         │
                    ┌────▼────┐
                    │  VPS2   │  23.182.128.51
                    │ Caddy   │  :80  :443  (HTTP/HTTPS)
                    │ + socat │  :2222 (SSH proxy)
                    └────┬────┘
                         │ fips0 interface
                         │ fd00::/8 routing
                    ┌────▼────┐
                    │ FIPS Mesh│
                    └────┬────┘
              ┌──────────┼──────────┐
              │          │          │
         home-1      home-2      home-3
         fd1b:...    fd0b:...    fd91:...
         :80         :3000       :22
```

### HTTP/HTTPS Layer — Caddy

Caddy already runs on VPS2. Add routes that proxy to FIPS addresses
instead of localhost:

```
# Home machine 1 — blog
blog.orangesync.tech {
    reverse_proxy [fd1b:eb17:a8ae:e7a1:4094:1ac5:3f90:f6b9]:80
}

# Home machine 2 — web app
app.orangesync.tech {
    tls on_demand
    reverse_proxy [fd0b:350e:c8ce:5d40:60fd:3bfe:a757:fdf0]:3000
}
```

Caddy handles TLS automatically. For dynamic/on-demand TLS (wildcard
subdomains), the existing on_demand_tls config already works — just need
the ask endpoint to resolve FIPS addresses.

### TCP/SSH Layer — Caddy L4 or socat

Caddy v2.11 supports `reverse_proxy` for TCP via the L4 module, but it's
not in the standard build. Two options:

**Option A: socat (simplest, immediate)**
```bash
# SSH to home machine via VPS
socat TCP-LISTEN:2222,fork,reuseaddr TCP6:[fd1b:eb17:a8ae:e7a1:4094:1ac5:3f90:f6b9]:22
# Or with systemd service
```

User connects: `ssh -p 2222 user@23.182.128.51` → forwarded to home machine:22.

**Option B: Caddy L4 module (cleaner, single config)**
Custom Caddy build with layer4 module:
```
{
    layer4 {
        :2222 {
            proxy [fd1b:eb17:a8ae:e7a1:4094:1ac5:3f90:f6b9]:22
        }
    }
}
}
```

**Option C: nginx stream (if already have nginx)**
```nginx
stream {
    server {
        listen 2222;
        proxy_pass [fd1b:eb17:a8ae:e7a1:4094:1ac5:3f90:f6b9]:22;
    }
}
```

### Access Control (Phase 2 — borrowed from fips-exit-gate)

The fips-exit-gate uses nftables with an authorized set of IPv6 source
addresses. For ingress, we reverse the logic:

- **Public-facing**: nftables on VPS eth0 limits who can reach the proxy ports
- **FIPS-facing**: nftables on VPS fips0 controls which home machines can be proxied
- **Authorized set**: home machines that are allowed to be exposed (whitelist)
- **Rate limiting**: per-source connection limits on inbound

## Implementation Phases

### Phase 1: Proof of Concept — HTTP reverse proxy (1 home machine)

**Goal**: Serve a web page from a home machine on the public internet.

1. Pick a home machine with a web server running
2. Add a Caddy route on VPS2 pointing to its FIPS address
3. Add a DNS A record (or use on-demand TLS) for the subdomain
4. Reload Caddy
5. Test from external network: `curl https://subdomain.orangesync.tech`

**Verification**: Page loads from home machine via VPS.

### Phase 2: TCP/SSH proxy

**Goal**: SSH into a home machine via VPS.

1. Install socat on VPS2 (or build Caddy with L4 module)
2. Create systemd service for TCP forwarding
3. Test: `ssh -p 2222 user@23.182.128.51` → lands on home machine
4. Add Caddy route for SSH web terminal if desired (gotty/ttyd)

**Verification**: SSH session established through VPS to home machine.

### Phase 3: Dynamic routing — FIPS-aware on-demand proxy

**Goal**: Any home machine can register a service, VPS auto-configures.

1. Build a small API/service (Go or Python) that:
   - Accepts service registrations from FIPS machines
   - Maps hostname → FIPS IPv6 address + port
   - Serves as Caddy's on-demand TLS ask endpoint
2. Home machines announce services via FIPS (or simple HTTP API)
3. Caddy asks the API: "blog.orangesync.tech → ?"
   API responds: `fd1b:eb17:a8ae:e7a1:4094:1ac5:3f90:f6b9:80`
4. Caddy proxies dynamically — no manual config per service

**Verification**: New home machine registers service, immediately
accessible via public URL without VPS config changes.

### Phase 4: Access control + nftables integration

**Goal**: Borrow fips-exit-gate's nftables pattern for ingress.

1. nftables on VPS2 eth0: rate limit, connection limit per source IP
2. nftables authorized set for which home machines can be exposed
3. Optional: captive portal / auth for private services
4. Per-service byte counters for accounting

### Phase 5: Bidirectional gate — unified

**Goal**: VPS2 = both exit (outbound) and ingress (inbound) node.

1. Deploy fips-exit-gate (outbound) on VPS2
2. Deploy ingress gate (inbound) on VPS2
3. Unified nftables ruleset handling both directions
4. Single dashboard showing both egress and ingress traffic
5. Single agent syncing authorized sets for both directions

## Decision Points

### D1: Caddy vs Nginx for ingress proxy?

**Recommendation: Caddy.**
- Already running on VPS2, already has on-demand TLS
- Auto-HTTPS, HTTP/2, HTTP/3
- Simple config (3 lines per service)
- nginx would need separate process + cert management

### D2: socat vs Caddy L4 vs nginx stream for TCP/SSH?

**Recommendation: socat for Phase 1-2, Caddy L4 for Phase 3+.**
- socat: zero setup, just works, one command per port
- Caddy L4: unified config but needs custom build (module not standard)
- nginx stream: works but adds another process to manage

### D3: How to map subdomains → FIPS machines?

Three options:
- **A. Manual Caddyfile**: one block per service. Simple but manual.
- **B. On-demand TLS ask endpoint**: Caddy asks an API for the upstream.
  Dynamic, auto-configuring. Needs building the API.
- **C. Wildcard + SNI proxy**: single Caddy route, proxy by SNI hostname
  to a resolver. Like a FIPS-aware load balancer.

**Recommendation: B (on-demand ask endpoint).**
- Reuses existing Caddy on_demand_tls infrastructure
- API can query FIPS daemon for known machines
- New machines auto-discovered, zero config changes
- Can add auth: only registered services get proxied

### D4: Use orangesync.tech or sovereignengineering.io?

**Recommendation: orangesync.tech** (Cloudflare-managed, easier DNS API).

### D5: Which home machine for Phase 1 PoC?

Need: a home machine on FIPS mesh with a web server running.
Candidates (from peer list):
- npub1ajkl... (fd1b:...) — connected
- npub1jtn5... (fd0b:...) — connected
- andre (fd91:...) — connected

**Question for operator**: Which home machine has a web server we can
test with? Or should we start one on a machine we control?

## Security Considerations

1. **VPS becomes gateway**: all home services exposed through one IP
   → mitigate with per-service auth, rate limiting, nftables
2. **TLS termination on VPS**: VPS sees plaintext traffic
   → alternative: TLS pass-through (SNI proxy) so VPS doesn't decrypt
   → but pass-through loses HTTP features (host routing, caching)
   → compromise: TLS on VPS for public services, pass-through for private
3. **FIPS mesh firewall**: must prevent address spoofing (same as exit-gate)
   → already a prerequisite for fips-exit-gate, assume it's met
4. **Port exposure**: only expose intended ports, nftables whitelist
   → never proxy to FIPS internal services accidentally

## Comparison: Why Not SSH Tunnels / WireGuard / Nginx?

| Requirement | SSH Tunnel | WG + Nginx | Caddy on FIPS VPS |
|---|---|---|---|
| Multiple home machines | 1 tunnel each | 1 tunnel each | route by hostname ✅ |
| HTTP features (TLS, SNI) | No | Nginx adds it | Built-in ✅ |
| FIPS-native | No | No | Yes ✅ |
| TCP/SSH proxy | Yes | Manual | socat/L4 ✅ |
| Dynamic config | No | No | on-demand API ✅ |
| Setup complexity | Low | High | Low ✅ |
| Bidirectional | One-way | Manual | Both ✅ |
| Auto-TLS | No | Certbot | Built-in ✅ |

SSH tunnels: per-service setup, reconnect fragility, no HTTP features.
WireGuard: unnecessary since VPS already on FIPS mesh.
Nginx: would work but Caddy already running, adds nothing.

## Deliverables

1. Caddy config additions for FIPS ingress routes
2. socat/systemd service for SSH TCP proxy
3. On-demand TLS ask endpoint (Phase 3)
4. nftables rules for ingress access control (Phase 4)
5. Documentation: how to expose a new home service

## Next Action

Phase 1 PoC complete. Next phases can proceed:

- **Phase 2**: TCP/SSH proxy via socat
- **Phase 3**: Dynamic routing with on-demand TLS ask endpoint
- **Phase 4**: Access control + nftables integration
- **Phase 5**: Bidirectional gate (unified with fips-exit-gate)

## Phase 1 PoC Results (2026-08-12)

### What was done

1. **Test web server**: Wrote `scripts/fips-poc-server.py` — Python HTTP
   server bound to T470's FIPS IPv6 address (fd97:77d4:...:dee8) on port 8888.
   Serves a simple HTML page: "FIPS Ingress Gate PoC - served from T470".

2. **FIPS mesh peering fix**: VPS2 did not have T470 as a configured peer.
   Added T470 (npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72)
   to VPS2's `/etc/fips/fips.yaml` peers list. Updated Ansible defaults
   (`ansible/roles/fips/defaults/main.yml`) for persistence.

3. **Caddy reverse proxy route**: Added to VPS2 `/etc/caddy/Caddyfile`:
   ```
   poc.orangesync.tech {
       reverse_proxy [fd97:77d4:cd27:a6ae:1b29:e92e:fd96:dee8]:8888
   }
   ```

4. **DNS**: Wildcard `*.orangesync.tech` A record already points to
   23.182.128.51 — no new DNS record needed. Caddy on-demand TLS handles
   certificate provisioning automatically.

5. **Reloaded Caddy**: `caddy reload --config /etc/caddy/Caddyfile` —
   config validated successfully.

### Verification (Gate 2)

- **Local (T470)**: `curl -g "http://[fd97:...:dee8]:8888/"` → 200, "FIPS Ingress Gate PoC"
- **VPS2 → T470 via FIPS mesh**: `curl -g "http://[fd97:...:dee8]:8888/"` → 200, "FIPS Ingress Gate PoC"
- **External (public internet)**: `curl https://poc.orangesync.tech/` → 200, "FIPS Ingress Gate PoC"
- **VPS2 → public URL**: `curl https://poc.orangesync.tech/` → 200, "FIPS Ingress Gate PoC"

All tests returned HTTP 200 with the expected page content.

### Key Findings

- **FIPS mesh peering must be bidirectional**: VPS2 needed T470 in its peer
  config for the Noise handshake to authenticate. T470 had VPS2 configured
  but VPS2 did not reciprocate. The `configured_only` Nostr discovery policy
  means only listed peers get authenticated.

- **Wildcard DNS simplifies ingress**: The existing `*.orangesync.tech`
  wildcard A record means new FIPS ingress subdomains need no DNS changes —
  just add a Caddy route and reload.

- **Caddy on-demand TLS works seamlessly**: Certificate was automatically
  provisioned on first request to `poc.orangesync.tech`.

- **FIPS mesh carries HTTP traffic natively**: VPS2 reached T470's web
  server through the FIPS mesh (fips0 interface) with no additional routing
  configuration beyond the peer peering fix.

### Artifacts

- `scripts/fips-poc-server.py` — PoC web server script
- `ansible/roles/fips/defaults/main.yml` — Updated with T470 peer config
- `docs/FIPS-INGRESS-GATE-PLAN.md` — This document, updated with PoC results
- VPS2 `/etc/caddy/Caddyfile` — Added poc.orangesync.tech route (live)
- VPS2 `/etc/fips/fips.yaml` — Added T470 peer (live)