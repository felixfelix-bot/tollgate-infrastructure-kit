# Configuration Reference

All configuration is managed through the `.env` file in the project root.

## VPS Connection

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VPS_IP` | Yes | — | Public IP address of your VPS |
| `VPS_USER` | No | `debian` | SSH username for the VPS |
| `SSH_PRIVATE_KEY_FILE` | No | `~/.ssh/id_ed25519` | Path to SSH private key |

## Domain

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `BASE_DOMAIN` | Yes | — | Your domain name (e.g., `tollgate.me`) |
| `MINT_DOMAIN` | No | `mints.<BASE_DOMAIN>` | Base domain for Cashu mints |

## Cloudflare

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLOUDFLARE_API_TOKEN` | Yes | — | API token with Zone:DNS:Edit + Zone:Zone:Read |
| `CLOUDFLARE_ZONE_ID` | No | Auto-detected | Cloudflare zone ID |

## TLS / ACME

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ACME_EMAIL` | No | `admin@<BASE_DOMAIN>` | Email for Let's Encrypt notifications |

## Service Ports

| Variable | Default | Description |
|----------|---------|-------------|
| `strfry_port` | `7777` | Nostr relay port |
| `obelisk_port` | `8080` | NIP-29 chat relay port |
| `blossom_port` | `3001` | Blossom blob server port |
| `nsite_gateway_port` | `3002` | nsite gateway port |
| `mint_base_port` | `8085` | Starting port for mint containers |

## MPTCP Server

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SHADOWSOCKS_PASSWORD` | Yes | — | Password for Shadowsocks proxy |
| `SHADOWSOCKS_PORT` | No | `65101` | Shadowsocks TCP port |
| `SHADOWSOCKS_METHOD` | No | `chacha20-ietf-poly1305` | Encryption method |
| `GLORYTUN_PORT` | No | `65001` | Glorytun UDP port |
| `GLORYTUN_ENABLED` | No | `true` | Enable Glorytun tunnel |

## FIPS Mesh

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `FIPS_RELAY_URLS` | No | `wss://relay.damus.io,wss://nos.lol` | Nostr relays for mesh discovery |

## Obelisk Relay

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OBELISK_ADMIN_NPUB` | Yes | — | Admin Nostr npub for the group chat relay |

## nsyte CLI

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `NSYTE_PRIVATE_KEY` | No | — | Nostr private key for nsyte (for automated deployments) |

## Advanced (group_vars/all.yml)

For advanced configuration, edit `ansible/group_vars/all.yml` directly. This file contains all default values and can override any `.env` setting.

## Subdomains

The following subdomains are automatically created in Cloudflare:

| Subdomain | Service |
|-----------|---------|
| `relay` | strfry Nostr relay |
| `chat` | obelisk NIP-29 group chat |
| `blossom` | Blossom blob storage |
| `nsite` | nsite gateway |
| `releases` | Tollgate release explorer |
| `ci` | Hive CI frontend |
| `*.mints` | Cashu mint wildcard |
