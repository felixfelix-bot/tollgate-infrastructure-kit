# Getting Started

## Prerequisites

### 1. VPS Requirements
- **OS**: Debian 13 (trixie) x86_64
- **RAM**: Minimum 2GB (4GB recommended)
- **Storage**: Minimum 20GB (50GB recommended for blob storage)
- **Network**: Public IP address, ports 80/443 accessible

### 2. Local Machine Requirements
- **Python 3.8+** with pip
- **Ansible 2.14+**: `pip install ansible`
- **Docker collections**: `ansible-galaxy collection install community.docker community.general`
- **SSH client** with key-based access to the VPS
- **Node.js 18+** (for Playwright E2E tests)

### 3. Domain & Cloudflare
- A domain name (e.g., `tollgate.example.com`)
- Domain DNS managed by Cloudflare
- A Cloudflare API token with Zone:DNS:Edit and Zone:Zone:Read permissions

## Step-by-Step Setup

### Step 1: Prepare the VPS
Ensure you have SSH key access:
```bash
ssh debian@YOUR_VPS_IP
```

### Step 2: Clone and Configure
```bash
git clone https://github.com/OpenTollGate/tollgate-infrastructure-kit.git
cd tollgate-infrastructure-kit
cp .env.example .env
```

### Step 3: Edit .env
```bash
vim .env
```

Fill in all required values:
- `VPS_IP` — Your VPS public IP
- `BASE_DOMAIN` — Your domain (e.g., `tollgate.me`)
- `CLOUDFLARE_API_TOKEN` — See [Cloudflare Setup](cloudflare-setup.md)
- `CLOUDFLARE_ZONE_ID` — Your Cloudflare zone ID
- `SHADOWSOCKS_PASSWORD` — A strong password for the MPTCP server
- `OBELISK_ADMIN_NPUB` — Your Nostr npub for admin access

### Step 4: Install Ansible Dependencies
```bash
pip install ansible
ansible-galaxy collection install community.docker community.general
```

### Step 5: Deploy
```bash
make deploy
```

This will:
1. Install all system packages and configure the OS
2. Install Docker
3. Create DNS records in Cloudflare
4. Deploy Caddy reverse proxy with automatic HTTPS
5. Deploy all services
6. Run integration tests

### Step 6: Verify
```bash
make test
```

## Deploying Individual Services

You can deploy services individually:
```bash
# Deploy just the Nostr relay
ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/05-strfry.yml

# Deploy just the blossom server
ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/07-blossom.yml
```

## Deploying a Cashu Mint

```bash
./scripts/deploy-mint.sh npub1abc123...
# or
make deploy-mint NPUB=npub1abc123...
```

This will:
1. Create a new mint container
2. Generate mint credentials
3. Add the route to Caddy
4. Reload Caddy (zero downtime)

The mint will be available at `<subdomain>.mints.yourdomain.com`.
