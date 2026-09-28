# Services Overview

## Caddy (Reverse Proxy)
- **Subdomain**: Gateway (handles all subdomains)
- **Ports**: 80 (HTTP→HTTPS redirect), 443 (HTTPS)
- **Purpose**: TLS termination, reverse proxy, static file server
- **Tech**: Caddy 2 with `caddy-dns/cloudflare` plugin
- **Config**: `/opt/tollgate/caddy/Caddyfile`

## strfry (Nostr Relay)
- **Subdomain**: `relay.<domain>`
- **Port**: 7777
- **Purpose**: General-purpose Nostr relay for event storage and relay
- **Tech**: C++ high-performance relay
- **Config**: `/opt/tollgate/strfry/strfry.conf`

## obelisk-relay (NIP-29 Group Chat)
- **Subdomain**: `chat.<domain>`
- **Port**: 8080
- **Purpose**: Relay-based group chat with NIP-29 support
- **Tech**: Rust (Tokio + Axum), prebuilt Docker image
- **Features**: Group management, roles, invite codes, admin UI

## buzz-relay (Buzz relay, patched)
- **Subdomain**: `relay.<domain>` (wss://relay.orangesync.tech)
- **Port**: 127.0.0.1:3007 → container 3000
- **Purpose**: Buzz relay with membership auth (NIP-42), media/file storage, group chat backend
- **Tech**: Rust (Tokio + Axum), Docker; fork image `tollgate/buzz:audio` (= ghcr.io/felixfelix-bot/buzz:tollgate-audio)
- **Stack**: `/opt/buzz-relay/docker-compose.yml` (postgres 17-alpine, redis 7-alpine, minio + one-shot mc init, buzz-relay)
- **Local deviation**: audio upload support (tollgate:audio-validate) — magic-byte sniffed audio allowlist on the generic file path, `BUZZ_MAX_AUDIO_BYTES` cap (25 MiB), M4A carved out of the ISO-BMFF video pipeline. See `PATCHES.md`.
- **Media storage**: internal MinIO `buzz-relay-minio` (no host ports; NOT Sitarani on :9000), bucket `buzz-media` (private), served auth-gated at `https://relay.<domain>/media/<sha256>.<ext>`

## blossom-server (Blob Storage)
- **Subdomain**: `blossom.<domain>`
- **Port**: 3001
- **Purpose**: Content-addressed blob storage for Nostr (BUD-01 to BUD-11)
- **Tech**: Deno 2 + TypeScript + Hono
- **Features**: Upload, download, mirror, media optimization, admin dashboard
- **Config**: `/opt/tollgate/blossom/config.yml`

## nsite-gateway (Static Site Gateway)
- **Subdomain**: `nsite.<domain>`
- **Port**: 3002
- **Purpose**: Serves Nostr-hosted static websites via HTTP
- **Tech**: Deno 2 + TypeScript + Hono
- **Features**: Hostname resolution, caching, homepage, status dashboard

## Tollgate Release Explorer
- **Subdomain**: `releases.<domain>`
- **Purpose**: Browse and download Tollgate firmware releases from Nostr
- **Tech**: React 18 static site
- **Source**: `https://github.com/OpenTollGate/tollgate-release-explorer-site`

## Hive CI Site
- **Subdomain**: `ci.<domain>`
- **Purpose**: Frontend for Hive CI decentralized CI/CD system
- **Tech**: Vue.js static site
- **Source**: `https://github.com/Origami74/hive-ci-site-mirror`

## Cashu Mint Orchestrator
- **Subdomain**: `*.mints.<domain>`
- **Ports**: 3338+ REST, 50051+ gRPC (one per mint), 8090 API
- **Purpose**: Per-operator Cashu ecash mints with Nostr-based approval gating
- **Tech**: CDK mintd (`cashubtc/mintd` Docker image) + Python orchestrator daemon
- **Approval**: Mint owners sign kind 38010 Nostr events → orchestrator validates → gRPC sets quote PAID
- **Units**: sat, usd, eur, B, KB, MB, GB, sec, min, hr, day, wk, mo
- **Config**: `/opt/tollgate/mints/registry.json`
- **Usage**: `./scripts/deploy-mint.sh <npub>`

## GRASP Server (ngit-grasp)
- **Subdomain**: `git.<domain>`
- **Port**: 7334
- **Purpose**: Decentralized Git hosting via Nostr authorization (GRASP protocol)
- **Tech**: Rust (ngit-grasp), built from source
- **Features**: GRASP-01/02/05, NIP-34/77, archive-all mode, proactive sync
- **Config**: systemd unit with environment variables

## MPTCP Server
- **No subdomain** (TCP/UDP service)
- **Ports**: 65101 (Shadowsocks TCP), 65001 (Glorytun UDP)
- **Purpose**: Multi-path TCP aggregation for Tollgate routers
- **Tech**: shadowsocks-libev + glorytun
- **Config**: `/opt/tollgate/mptcp/server-config.txt`

## FIPS (Mesh Network)
- **No subdomain** (TUN interface)
- **Purpose**: Self-organizing encrypted mesh network using Nostr identities
- **Tech**: Rust, Noise Protocol, TUN/nftables
- **Config**: `/etc/fips/fips.yaml`

## nsyte CLI
- **No subdomain** (CLI tool)
- **Purpose**: Deploy and manage nsites from the VPS
- **Tech**: Deno 2 + TypeScript
- **Usage**: `nsyte deploy ./dist`

## GRASP Mirror Daemon
- **No subdomain** (systemd service)
- **Purpose**: Mirrors git data and Nostr events across all known GRASP servers for redundancy
- **Tech**: Rust (nostr-sdk 0.39, git2, sqlx/SQLite, tokio)
- **Source**: `nostr://npub12m5exm2uk3xa674cc5r0hlyvccs5xxn7qv83ezuteefv5972nquq4j4szl/git.orangesync.tech/grasp-mirror`
- **Config**: `/opt/tollgate/grasp-mirror/config.toml`
- **State**: `/opt/tollgate/grasp-mirror/repos/` (bare git mirrors), `mirror.db` (SQLite sync state)
- **Health**: Tracked on `services.orangesync.tech` (mirroring health inferred from GRASP server reachability)
- **Monitors**: 9 GRASP servers, watches npub12m5exm2uk3xa674cc5r0hlyvccs5xxn7qv83ezuteefv5972nquq4j4szl
