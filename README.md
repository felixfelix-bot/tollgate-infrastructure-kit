# Tollgate Infrastructure Kit

A single-command Ansible-based toolkit that deploys all Tollgate-related infrastructure services on a single VPS. Designed so anyone can run Tollgate infrastructure without depending on a small set of operators.

## Quick Start

```bash
# 1. Clone this repo
git clone https://github.com/OpenTollGate/tollgate-infrastructure-kit.git
cd tollgate-infrastructure-kit

# 2. Configure your environment
cp .env.example .env
# Edit .env with your VPS IP, domain, Cloudflare token, etc.

# 3. Deploy everything
make deploy
```

## Services Deployed

### Web Services (HTTPS via Caddy + Cloudflare DNS-01)

| Service | URL | Description |
|---------|-----|-------------|
| Routstr AI Node | `https://routstr.<BASE_DOMAIN>` | Decentralized AI inference proxy (GLM-5.1 via Z.ai) |
| Routstr Admin | `https://routstr.<BASE_DOMAIN>/admin` | Routstr node management dashboard |
| Nostr Relay | `https://relay.<BASE_DOMAIN>` | strfry — general-purpose Nostr relay |
| NIP-29 Chat | `https://chat.<BASE_DOMAIN>` | obelisk-relay — group chat relay |
| Blob Storage | `https://blossom.<BASE_DOMAIN>` | blossom-server — Nostr blob storage (BUD-01 to BUD-11) |
| nsite Gateway | `https://nsite.<BASE_DOMAIN>` | Gateway for Nostr-hosted static sites |
| Release Explorer | `https://releases.<BASE_DOMAIN>` | Tollgate firmware release browser |
| Hive CI | `https://ci.<BASE_DOMAIN>` | Decentralized CI frontend |
| GRASP Git Server | `https://git.<BASE_DOMAIN>` | ngit-grasp — Nostr-based git hosting |

### Cashu Mint Infrastructure

| Service | URL | Description |
|---------|-----|-------------|
| Mint (MB) | `https://test-mb.mints.<BASE_DOMAIN>` | CDK mintd — megabyte-denominated test mint |
| Mint (KB) | `https://test-kb.mints.<BASE_DOMAIN>` | CDK mintd — kilobyte-denominated test mint |
| Mint (GB) | `https://test-gb.mints.<BASE_DOMAIN>` | CDK mintd — gigabyte-denominated test mint |
| Mint (min) | `https://test-min.mints.<BASE_DOMAIN>` | CDK mintd — minute-denominated test mint |
| Routstr Mint | `https://routstr-mint.mints.<BASE_DOMAIN>` | CDK mintd — sat/msat mint for AI credit issuance |
| Money Printer | `https://print.mints.<BASE_DOMAIN>` | cashu-brrr — mint token minting UI |
| Mint API Proxy | `https://print.mints.<BASE_DOMAIN>/api/` | REST API proxy for mint operations |
| Mint Dashboard | `https://dashboard.mints.<BASE_DOMAIN>` | Mint orchestrator dashboard with nsec signing |

### Internal Services (no public URL)

| Service | Port | Description |
|---------|------|-------------|
| Mint Orchestrator | `:8090` | Python daemon — Nostr-based mint approval flow |
| Mint Operator Proxy | `:3000` | Node.js REST API for mint management |
| Routstr Core API | `:8000` | FastAPI reverse proxy for AI inference |

### Non-HTTP Services

| Service | Port | Description |
|---------|------|-------------|
| MPTCP / Shadowsocks | `:65101` | Multi-path TCP aggregation (TCP) |
| Glorytun | `:65001` | UDP tunnel transport |
| FIPS Mesh | (TUN) | Mesh network daemon |
| Tor Hidden Service | `.onion` | Anonymous access to Routstr API |

### CLI Tools

| Tool | Description |
|------|-------------|
| nsyte | nsite deployment CLI (global Deno binary) |
| mint-approve | Signs and publishes Nostr kind 38010 approval events |

## Prerequisites

- A VPS running Debian 13 (trixie) with a public IP
- SSH key access to the VPS
- A domain name managed by Cloudflare
- A Cloudflare API token with DNS edit permissions
- Ansible 2.14+ installed locally

## Configuration

All configuration is managed through the `.env` file. See `.env.example` for all available options.

Key variables:
- `VPS_IP` — Your VPS IP address
- `BASE_DOMAIN` — Your domain name
- `CLOUDFLARE_API_TOKEN` — Cloudflare API token
- `SHADOWSOCKS_PASSWORD` — Password for MPTCP server

## Available Commands

```bash
make deploy          # Deploy all services
make test            # Run integration and E2E tests
make teardown        # Remove all services
make deploy-mint     # Deploy a new Cashu mint (NPUB=<npub>)
make remove-mint     # Remove a Cashu mint (MINT_ID=<id>)
make lint            # Lint Ansible playbooks
make check           # Syntax check playbooks
```

## Documentation

- [Getting Started](docs/getting-started.md)
- [Configuration Reference](docs/configuration.md)
- [Services Overview](docs/services.md)
- [Adding New Services](docs/adding-services.md)
- [Cloudflare Setup](docs/cloudflare-setup.md)
- [Troubleshooting](docs/troubleshooting.md)

## License

MIT
