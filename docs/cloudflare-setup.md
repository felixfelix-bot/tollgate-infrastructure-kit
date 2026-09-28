# Cloudflare Setup

## Creating a Cloudflare API Token

### Step 1: Log in to Cloudflare
Go to [https://dash.cloudflare.com](https://dash.cloudflare.com) and log in.

### Step 2: Create API Token
1. Go to **My Profile** → **API Tokens**
2. Click **Create Token**
3. Use the **Custom token** template

### Step 3: Set Permissions
Configure the token with these permissions:

| Permission | Scope | Details |
|------------|-------|---------|
| Zone:DNS:Edit | Specific zone | Your domain (e.g., `tollgate.me`) |
| Zone:Zone:Read | Specific zone | Your domain |

### Step 4: Get Your Zone ID
1. Go to your domain's overview page in Cloudflare
2. Scroll down to the **API** section
3. Copy the **Zone ID**

### Step 5: Configure .env
```
CLOUDFLARE_API_TOKEN=your_token_here
CLOUDFLARE_ZONE_ID=your_zone_id_here
```

## DNS Records Created

The deployment automatically creates these DNS records:

| Record | Type | Value |
|--------|------|-------|
| `relay.yourdomain.com` | A | Your VPS IP |
| `chat.yourdomain.com` | A | Your VPS IP |
| `blossom.yourdomain.com` | A | Your VPS IP |
| `nsite.yourdomain.com` | A | Your VPS IP |
| `releases.yourdomain.com` | A | Your VPS IP |
| `ci.yourdomain.com` | A | Your VPS IP |
| `*.mints.yourdomain.com` | A | Your VPS IP |

## TLS Certificates

Caddy automatically obtains wildcard TLS certificates from Let's Encrypt using DNS-01 challenge via the Cloudflare API. No manual certificate management is needed.

## Troubleshooting

### "Invalid API Token"
- Verify the token has the correct permissions
- Check that the token is for the correct zone
- Ensure the token hasn't expired

### "Zone not found"
- Verify the `CLOUDFLARE_ZONE_ID` matches your domain
- Ensure the domain is active in Cloudflare

### "DNS record already exists"
- This is handled automatically — existing records are skipped
- If you need to update an IP, delete the old record in the Cloudflare dashboard and re-run deployment
