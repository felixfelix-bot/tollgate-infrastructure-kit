# FIPS Hosting Plan — All Services Over the Mesh

## Goal

Make every Tollgate service accessible over the FIPS mesh at
`http://npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82.fips/`

Architecture: extend Caddy to also listen on the fips0 IPv6 address. All existing
routes apply to both clearnet and mesh — zero code duplication.

## Key Facts

- VPS FIPS npub: `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`
- fips0 IPv6: `fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149`
- FIPS version on VPS: 0.4.0-dev
- Current state: FIPS running, 0 peers, Nostr discovery commented out

## Checklist

### 1. Enable FIPS Nostr Discovery

- [ ] Update `ansible/roles/fips/templates/fips.yaml.j2`
  - Uncomment `discovery.nostr` section
  - Set `enabled: true`, `policy: configured_only`, `advertise: true`
  - Add relay list: `wss://relay.orangesync.tech`, `wss://ngit.orangesync.tech`, `wss://relay.damus.io`, `wss://nos.lol`
  - Set `advert_relays` and `dm_relays` to same set
  - Enable persistent identity (so npub stays stable across restarts)
  - Enable UDP advertise_on_nostr: true

### 2. Add Caddy fips0 Listener

- [ ] Update `ansible/roles/caddy/templates/Caddyfile.http.j2`
  - Add a global `bind` block or a top-level site block for fips0 IPv6 on port 80
  - All service blocks bind to both `:443` (clearnet) and `[fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149]:80` (mesh)
  - No TLS on fips0 (mesh traffic is already encrypted via Noise IK/XK)
  - Static file sites use same `root` directives
  - Reverse proxy sites use same `reverse_proxy` directives

### 3. FIPS Firewall Drop-in

- [ ] Add task to `ansible/roles/fips/tasks/main.yml`
  - Template `/etc/fips/fips.d/services.nft` with `tcp dport 80 accept`
  - Reload nft rules after writing

### 4. Ansible Variables

- [ ] Add to `group_vars/all.yml`:
  - `fips_advertise_relays` list
  - `fips_dm_relays` list
  - `fips_mesh_http_port: 80`

### 5. Deploy

- [ ] Run `13-fips.yml` playbook to redeploy fips.yaml + firewall
- [ ] Run Caddy playbook to redeploy Caddyfile
- [ ] Restart fips service
- [ ] Verify: `sudo fipsctl show status` shows peers connecting
- [ ] Verify: from another FIPS node, `curl http://npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82.fips/` returns page

### 6. Update PROGRESS.md

- [ ] Add FIPS hosting section

### 7. Commit and push

- [ ] Commit all changes
- [ ] Push to ngit remotes

## What Users Need

To access services over FIPS, a user needs:
1. FIPS daemon installed and running (Linux, macOS, Windows — no mobile yet)
2. `.fips` DNS resolver active (automatic with FIPS)
3. Navigate to `http://npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82.fips/`

## Services That Become Available

All services currently at `*.orangesync.tech`:

| Clearnet | FIPS |
|----------|------|
| `https://relay.orangesync.tech` | `http://<npub>.fips/` (via Caddy route) |
| `https://vote.orangesync.tech` | `http://<npub>.fips/` (via Caddy route) |
| `https://runner.orangesync.tech` | `http://<npub>.fips/` (via Caddy route) |
| `https://services.orangesync.tech` | `http://<npub>.fips/` (via Caddy route) |
| ... all others | Same — Caddy routes by Host header |

Note: Caddy route matching uses the Host header. On the mesh, browsers send
the full `npub...fips` domain. Caddy needs a catch-all or explicit match for
that domain. Alternatively, path-based routing on a single fips0 site block.

## Architecture Detail

```
Browser → http://<npub>.fips/
       → FIPS DNS resolves <npub>.fips → fdfd:c0e5:3717:6cb1:bb60:de97:987e:7149
       → HTTP request over FIPS mesh (Noise encrypted)
       → VPS fips0:80 → Caddy → routes to service (same as clearnet)
```
