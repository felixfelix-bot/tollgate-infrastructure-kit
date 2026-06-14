# Tollgate Infrastructure Kit — Implementation Plan

## Overview

A single Ansible-based repository that deploys all Tollgate-related infrastructure services on a single VPS with one command. Designed for anyone to run Tollgate infrastructure without depending on a small set of operators.

## Target Environment

- **OS**: Debian 13 (trixie) x86_64
- **Access**: SSH key-based (`debian@<VPS_IP>`)
- **Domain**: User brings their own (`BASE_DOMAIN` variable)
- **Secrets**: `.env` file (not committed to git)

## Services (25 total)

| # | Service | Subdomain | Internal Port | Install Method |
|---|---------|-----------|---------------|----------------|
| 1 | Caddy (reverse proxy) | gateway | 80/443 | Docker + xcaddy (with cloudflare plugin) |
| 2 | strfry (general Nostr relay) | `relay.` | 7777 | Docker |
| 3 | obelisk-relay (NIP-29 group chat) | `chat.` | 8080 | Docker (GHCR prebuilt) |
| 4 | blossom-server (blob storage) | `blossom.` | 3001 | Docker (build from hzrd149/blossom-server) |
| 5 | nsite-gateway (Nostr site gateway) | `nsite.` | 3002 | Docker (build from hzrd149/nsite-gateway) |
| 6 | tollgate-release-explorer | `releases.` | — | Static build, Caddy file_server |
| 7 | hive-ci-site | `ci.` | — | Static build, Caddy file_server |
| 8 | Cashu mint infrastructure | `*.mints.` | 8085-8093 | CDK + Nutshell mint containers |
| 9 | cashu-brrr (money printer) | `print.mints.` | — | Static build, Caddy file_server |
| 10 | Mint operator proxy | `print.mints./api/` | 3000 | Node.js systemd (tsx) |
| 11 | MPTCP server | none | 65101/65001 | Systemd |
| 12 | FIPS (mesh network) | none | TUN | Systemd (Debian package) |
| 13 | nsyte CLI | N/A | N/A | Deno binary in PATH |
| 14 | GRASP server (ngit-grasp) | `git.` | 7334 | Systemd (built from source) |
| 15 | Routstr AI inference node | `routstr.` | 8000 | Docker (ghcr.io/routstr/proxy) |
| 16 | Routstr Tor hidden service | `.onion` | 80 | Docker (tor-hidden-service) |
| 17 | Auditable Voting (static) | `vote.` | — | Static build (React+Vite+WASM), Caddy file_server |
| 18 | Auditable Voting (nsite) | `<npub>.nsite./` | — | Nostr static site via blossom + nsyte |
| 19 | ngit Relay (git-optimized Nostr) | `ngit.` | 7778 | Docker (strfry, 10MB event limit) |
| 20 | VPS Watchdog | N/A (local) | N/A | Systemd user service (Python) |
| 21 | Syncthing (backup sync) | none | 22000/8384 | Systemd (send-only on VPS) |
| 22 | Daily backup (systemd timer) | none | N/A | Shell script + systemd timer |
| 23 | GitWorkshop | `workshop.` | — | Static build (React+Vite), Caddy file_server |
| 24 | Services status page | `services.` | — | Static HTML, Caddy file_server |
| 25 | ACT Runner (CI/CD) | `runner.` | 8095 | Python daemon + nektos/act binary |
| 26 | Voting Worker | none | — | Rust binary (audit proxy), systemd |
| 27 | Auditable Voting E2E Tests | none | — | Playwright tests, triggered via Ansible |

## Architecture

```
Internet → Cloudflare DNS (auto A records via API)
  → VPS (Debian 13)
    → Caddy (:80/:443, Docker host network, auto HTTPS via Cloudflare DNS-01)
      ├── relay.BASE_DOMAIN     → strfry (Docker :7777)
      ├── chat.BASE_DOMAIN      → obelisk-relay (Docker :8080)
      ├── blossom.BASE_DOMAIN   → blossom-server (Docker :3001)
      ├── nsite.BASE_DOMAIN     → nsite-gateway (Docker :3002)
      ├── releases.BASE_DOMAIN  → /srv/tollgate/releases/ (Caddy file_server)
      ├── ci.BASE_DOMAIN        → /srv/tollgate/hive-ci/ (Caddy file_server)
      ├── git.BASE_DOMAIN       → ngit-grasp (Systemd :7334)
      ├── routstr.BASE_DOMAIN   → Routstr Core (Docker :8000) ← AI inference proxy
        ├── *.mints.BASE_DOMAIN   → CDK + Nutshell mint containers
        │   ├── test-mb  (:8085, CDK)
        │   ├── test-kb  (:8086, CDK)
        │   ├── test-gb  (:8087, CDK)
        │   ├── test-min (:8088, CDK)
        │   ├── routstr-mint (:8089, CDK) ← dedicated mint for AI credits
        │   ├── testnut-cdk (:8091, CDK, sat, fakewallet)
        │   ├── testnut-nutshell (:8092, Nutshell 0.20.0, sat, FakeWallet)
        │   └── testnut-compat (:8093, Nutshell 0.18.2, sat, FakeWallet, old keyset format)
       └── print.mints.BASE_DOMAIN → cashu-brrr static + /api/* proxy → mint operator proxy (:3000)

    Auditable Voting:
      ├── vote.BASE_DOMAIN        → Static React+Vite+WASM build (Caddy file_server)
      └── nsite via blossom        → Same build published to Nostr (our relay + blossom + public)

     ngit Relay:
       └── ngit.BASE_DOMAIN         → strfry (Docker :7778, 10MB event limit, open access)
             Optimized for git (NIP-34) events — kind 30617/30618
             No rate limits, no write restrictions

     GitWorkshop:
       └── workshop.BASE_DOMAIN     → Static React SPA (Caddy file_server)
             Cloned from Nostr via ngit, built with pnpm+Vite

     Services Status Page:
       └── services.BASE_DOMAIN     → Static HTML (Caddy file_server)
             21 services monitored, dark theme, auto-refresh

     nsite Gateway (wildcard):
       └── *.nsite.BASE_DOMAIN      → nsite-gateway (Docker :3002)
             Serves static sites published on Nostr (kind 15128/35128)
             Hostname resolution: npub subdomain, snapshot, named site, CNAME
             Requires wildcard DNS + wildcard TLS for *.nsite.BASE_DOMAIN

     Testnut Mints (for Go router compatibility):
       ├── testnut-cdk     (:8091, CDK v0.16.0, new keyset format)
       ├── testnut-nutshell (:8092, Nutshell 0.20.0, new keyset format)
       └── testnut-compat  (:8093, Nutshell 0.18.2, old 16-char keyset format)
             testnut-compat emits keyset ID "00" + 14 hex chars
             Compatible with gonuts-tollgate Go library
             See docs/nutshell-test-mint-requirement.md

    Routstr AI Inference Node:
      ├── Routstr Core (Docker :8000)
      │     FastAPI reverse proxy for OpenAI-compatible APIs
      │     Accepts Cashu eCash payments from routstr-mint + minibits
      │     Proxies to Z.ai Coding Plan (GLM-5.1) upstream
      │     Admin dashboard at root /
      │     Lightning payouts to TollGate@coinos.io
      │     Nostr discovery (kind 38421) via local relay
      │     Fully configurable via Ansible (env vars + admin API)
      ├── Tor hidden service (Docker host network)
      │     Anonymous .onion access to Routstr API
      └── Dedicated CDK mint (routstr-mint, :8089, gRPC :50055)
            Node operator issues AI credits (sat/msat units)
            Fakewallet backend (testing); swap to real LN for production payouts

    Mint orchestrator:
      ├── tollgate-mint-orchestrator (Python daemon :8090)
      │     Subscribes to Nostr relay for kind:38010 approval events
      │     Validates Nostr signatures + npub ownership
      │     Calls CDK gRPC UpdateNut04Quote to approve issuance
      │     Publishes confirmation events to relay
      ├── mint-approve CLI (Python, for mint owners)
      └── mint-dashboard (static HTML, client-side nsec signing)

     ACT Runner (CI/CD for GRASP repos):
       ├── tollgate-act-runner (Python daemon :8095)
       │     Polls GRASP repos via git ls-remote for new commits
       │     Clones repo, runs nektos/act on .github/workflows/*.yml
       │     Publishes Kind 1985 CI result events to ngit + relay
       │     Serial build queue (one build at a time)
       │     REST API: /api/health, /api/repos, /api/builds, /api/builds/<id>/log
       ├── runner.{{ base_domain }} (Caddy proxy + static dashboard)
       │     Dark-themed CI dashboard, auto-refreshes every 15s
       └── Config: allowlisted repos in YAML, Nostr keypair for event signing

     System services (not HTTP):
      ├── shadowsocks-libev (TCP :65101, MPTCP enabled)
      ├── glorytun (UDP :65001)
      └── fips daemon (TUN interface + nftables)

    CLI tools:
      └── nsyte (global Deno binary)
```

## CDK Fakewallet Custom Unit Bug

CDK v0.16.0 has two bugs that prevent custom units (MB, KB, GB, min) with the fakewallet:

1. **Case mismatch**: `CurrencyUnit::Custom` serializes to lowercase (`Custom("MB")` → `"mb"`) but `FromStr` preserves case. The payment processor HashMap key `Custom("MB")` doesn't match the deserialized `Custom("mb")` from requests → "No payment processor set for pair mb, bolt11".

2. **No msat conversion**: Fakewallet calls `convert_currency_amount(custom_unit, Msat)` but only knows `Sat↔Msat` and `Usd/Eur→Msat`. No path for custom units → "Could not create invoice: Unknown invoice amount".

**Workaround**: All mints use `CDK_MINTD_FAKE_WALLET_SUPPORTED_UNITS=sat`. Display unit mapping is handled in the cashu-brrr frontend (mint URL → display unit). See `cashu-brrr/HANDOVER.md` Phase 5.

**Future fix options**: gRPC payment processor, CDK fork, or upstream fix.

## Mint Orchestrator Design

### Cashu Mint (CDK mintd)

- **Docker image**: `cashubtc/mintd:latest` (official, not a fork)
- **Lightning backend**: `fakewallet` — auto-fills quotes
- **gRPC management**: `cdk-mint-rpc` built into CDK — `UpdateNut04Quote` sets quote state
- **Per-mint containers**: each unit gets its own mintd instance with unique ports
- **Active mints**: `test-mb` (sat, displayed as MB), `test-kb` (sat, displayed as KB), `test-gb` (sat, displayed as GB), `test-min` (sat, displayed as min)
- **Database**: SQLite per mint
- **Key constraint**: All mints use `sat` internally due to CDK fakewallet bug. Custom unit display is a frontend concern.

### Approval Flow (Nostr-based)

1. User creates mint quote via Cashu wallet → `POST /v1/mint/quote/bolt11`
2. Quote starts UNPAID (fakewallet auto-fills after delay, but orchestrator can gate via gRPC)
3. Mint owner signs kind 38010 Nostr event approving the quote
4. Orchestrator validates signature, calls gRPC `UpdateNut04Quote` → PAID
5. User mints tokens → `POST /v1/mint/bolt11`

### CDK gRPC (cdk-mint-rpc)

Proto: `crates/cdk-mint-rpc/src/proto/cdk-mint-rpc.proto` from `cashubtc/cdk`
- Package: `cdk_mint_management_v1`
- Key RPC: `UpdateNut04Quote(UpdateNut04QuoteRequest) → UpdateNut04QuoteRequest`
- Env vars: `CDK_MINTD_MINT_MANAGEMENT_ENABLED`, `CDK_MINTD_MANAGEMENT_PORT`

### CDK mintd Key Environment Variables

| Variable | Purpose |
|----------|---------|
| `CDK_MINTD_URL` | Mint public URL |
| `CDK_MINTD_LN_BACKEND` | `fakewallet` for testing |
| `CDK_MINTD_LISTEN_HOST` | `0.0.0.0` in Docker |
| `CDK_MINTD_LISTEN_PORT` | REST API port |
| `CDK_MINTD_DATABASE` | `sqlite` |
| `CDK_MINTD_MNEMONIC` | Seed for key derivation |
| `CDK_MINTD_FAKE_WALLET_SUPPORTED_UNITS` | Comma-separated units |
| `CDK_MINTD_MINT_MANAGEMENT_ENABLED` | `true` to enable gRPC |
| `CDK_MINTD_MANAGEMENT_PORT` | gRPC port |
| `CDK_MINTD_LN_MIN_MINT` / `CDK_MINTD_LN_MAX_MINT` | Mint amount limits |

## Cloudflare DNS Automation

The `cloudflare_dns` Ansible role creates A records for: `relay`, `chat`, `blossom`, `nsite`, `releases`, `ci`, `git`, `routstr`, `vote`, `ngit`, `services`, `mints`, `workshop`, bare domain, `*.mints`, `*.nsite`

## Deployment Flow

```
make deploy  (or ./scripts/deploy.sh)
  01. System setup (packages, locale, sysctl)
  02. Docker + Compose V2 installation
  03. Cloudflare DNS record creation
  04. Caddy reverse proxy deployment
  05. strfry Nostr relay
  06. obelisk-relay NIP-29 group chat
  07. blossom-server blob storage
  08. nsite-gateway
  09. tollgate-release-explorer (static)
  10. hive-ci-site (static)
  11. Mint orchestrator + dashboard
  12. MPTCP server (Shadowsocks + Glorytun)
  13. FIPS mesh network
  14. nsyte CLI installation
  15. GRASP server (ngit-grasp)
  16. Routstr AI inference node + dedicated mint + Tor
  17. Auditable Voting (static + nsite)
  18. cashu-brrr frontend + operator proxy
  19. ngit Relay (git-optimized Nostr relay)
  20. VPS Watchdog (local health monitor + auto-redeploy)
   21. Syncthing (VPS send-only + laptop receive-only)
   22. Backup (daily strfry/ngit/grasp/mint/routstr/caddy exports)
   23. Relay Advertisement (NIP-10002 relay list + ngit repo metadata)
   24. GitWorkshop (static React SPA from Nostr)
     25. Testnut mints (CDK + Nutshell 0.20 + Nutshell 0.18 compat)
     26. ACT Runner (CI/CD for GRASP repos)
     27. Voting Worker (audit proxy, built from auditable-voting/worker/)
     28. Auditable Voting E2E Tests (Playwright, triggered via Ansible)
     → Integration tests
     → Playwright E2E tests
```

## Backup Architecture

```
VPS (send-only)                              Laptop (receive-only)
┌──────────────────────┐                     ┌───────────────────────────┐
│ Daily 02:00 backup:  │   Syncthing         │ ~/backups/orangesync/     │
│  strfry export       │───port 22000/TCP───▶│  ├── strfry/  (*.jsonl)   │
│  ngit-relay export   │   encrypted,        │  ├── ngit-relay/          │
│  GRASP git mirror    │   authenticated     │  ├── grasp/git/           │
│  Mint SQLite copy    │                     │  ├── mints/  (*.db)       │
│  Routstr data copy   │                     │  ├── routstr/             │
│  Caddy cert copy     │                     │  └── caddy/               │
│                      │                     │ 30-day staggered versioning│
│ Staging: /opt/tollgate/backups/            └───────────────────────────┘
│ Retention: 7 days    │
└──────────────────────┘
```

Security: VPS folders are send-only (laptop cannot push). No live LMDB syncing — only pre-exported snapshots. Syncthing API bound to 127.0.0.1 only.

## Relay Advertisement

- Kind 10002 Nostr event listing public relay URLs (`wss://relay.orangesync.tech`, `wss://ngit.orangesync.tech`)
- ngit repo metadata published for GRASP-hosted repositories
- Uses a dedicated Nostr keypair stored in `.env` as `RELAY_AD_NSEC`/`RELAY_AD_NPUB`
- Published to: local relays + public relays (damus, nos.lol, primal)

## nsite Gateway Wildcard TLS

The nsite gateway resolves hostnames to Nostr sites via subdomain encoding (e.g. `npub1abc....nsite.BASE_DOMAIN`). This requires:

1. **Wildcard DNS**: `*.nsite.BASE_DOMAIN` A record → VPS IP
2. **Wildcard Caddy block**: `*.nsite.BASE_DOMAIN` with Cloudflare DNS-01 TLS
3. **Gateway env**: `PUBLIC_DOMAIN=nsite.BASE_DOMAIN` (generates correct subdomain links)

The gateway uses hostname resolution strategies (in order):
- npub subdomain: `npub1abc....nsite.BASE_DOMAIN` → kind 15128 root site
- Snapshot: `v<50-char-base36>.nsite.BASE_DOMAIN` → kind 5128 snapshot
- Named site: `<base36-pubkey><identifier>.nsite.BASE_DOMAIN` → kind 35128
- CNAME: custom domain → nsite subdomain

## Testnut Mint Compatibility

See `docs/nutshell-test-mint-requirement.md` for full details.

The `gonuts-tollgate` Go library uses the old Cashu keyset ID derivation: `SHA-256(sorted_pubkeys)[:14]` prefixed with `"00"` → 16-char hex ID. CDK v0.16.0 and Nutshell v0.20.0 use a new 64-char hex format, which crashes `gonuts-tollgate`.

| Mint | Software | Keyset Format | Compatible with gonuts-tollgate |
|------|----------|---------------|-------------------------------|
| testnut-cdk | CDK v0.16.0 | 64-char hex (new) | No |
| testnut-nutshell | Nutshell v0.20.0 | 64-char hex (new) | No |
| testnut-compat | Nutshell v0.18.2 | 16-char hex "00"+14 (old) | Yes |

## Auditable Voting Observer UX Fixes

Two issues reported after family testing on mobile:

### Problem 1: No loading indicator on initial fetch
`SimpleAuditorApp.tsx` fetches questionnaire definitions from Nostr relays on mount. While loading, the UI shows a misleading empty state ("No public questionnaire rounds discovered yet.") instead of a loading indicator. On slow mobile connections, users see this and think nothing exists.

**Fix**: Show "Loading questionnaires from Nostr relays..." when `questionnaires.length === 0 && refreshInFlight` is true. Add a `initialLoadDone` ref to distinguish first load from subsequent refreshes.

### Problem 2: URL doesn't reflect selected questionnaire
The observer page reads `?q=` / `?questionnaire=` URL params on load (`readInitialQuestionnaireIdFromUrl()`), but never writes the selected questionnaire ID back to the URL when the user picks from the dropdown. Sharing the URL always shows the newest questionnaire to recipients.

**Fix**: Add a `useEffect` that calls `history.replaceState` when `selectedQuestionnaireId` changes, writing `?q=<id>` to the URL. This mirrors `writeRoleToUrl()` in `SimpleAppShell.tsx`. The existing `readInitialQuestionnaireIdFromUrl()` already handles reading `q` on load.

### Problem 3: No loading state for response panel
When a questionnaire is selected but responses haven't loaded yet, the panel shows "No submitted responses found for this round yet." which is misleading during the fetch.

**Fix**: Track response loading state and show a loading message while responses are being fetched.

All changes are in `web/src/SimpleAuditorApp.tsx` only.

## Testing Strategy

| Level | Tool | What it tests |
|-------|------|---------------|
| Unit | pytest | Registry, event validator, gRPC client, audit log, daemon |
| Integration | Bash + pytest | Package imports, full pytest suite, service health |
| E2E | Playwright (TypeScript) | API endpoints, dashboard UI, mint REST API, TLS |
