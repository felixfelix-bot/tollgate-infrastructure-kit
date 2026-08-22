# VPS2 Security Audit — August 2026

## Root Cause

Docker Compose short port syntax (`PORT:PORT`) binds to `0.0.0.0`, which
bypasses UFW firewall rules entirely. Any service using bare port bindings
was reachable directly via the server's public IP, bypassing the Caddy
reverse proxy and its TLS/authentication layer.

## Affected Ports

| Port  | Service           | Template                                         |
|-------|-------------------|--------------------------------------------------|
| 8009  | routstr-proxy     | `roles/routstr/templates/docker-compose.routstr.yml.j2` |
| 8010  | routstr-public    | `roles/routstr/templates/docker-compose.routstr.yml.j2` |
| 9100  | hermes-sitarani   | `roles/hermes_tenants/templates/docker-compose.tenant.yml.j2` |

## Fix

All Docker Compose port bindings in ansible templates now use explicit
`127.0.0.1:PORT:PORT` syntax. This ensures services are only reachable
via the loopback interface, forcing all external access through Caddy
which terminates TLS and applies domain-based routing.

### Changes Made

1. **hermes_tenants** `docker-compose.tenant.yml.j2`:
   - Changed `"{{ tenant_gateway_port }}:8080"` to `"127.0.0.1:{{ tenant_gateway_port }}:8080"`

2. **routstr** `docker-compose.routstr.yml.j2`:
   - Uses `network_mode: host` — no compose-level port bindings exist.
   - Port exposure is controlled by the application's `PORT` env var and
     UFW rules. No compose template changes needed.

## Verification

After deploying the fix:

- Direct IP access (e.g. `curl http://<vps2-ip>:9100/health`) returns
  "connection refused" — the port is no longer bound on the public interface.
- Caddy domain access (e.g. `https://sitarani.<domain>/health`) still
  returns 200 OK — Caddy proxies to `127.0.0.1:<port>` internally.
- `ufw status` shows the ports are not listed as allowed, confirming UFW
  is not the primary control (loopback binding is).

## Date

2026-08-22
