# routstrd Production Docker Image

Production-ready Docker image for routstrd - the Routstr daemon for LLM proxy routing with Cashu payments.

## Features

- Multi-stage build for minimal image size (~671MB)
- Runs as non-root user (`routstrd`)
- Health check endpoint at `/health`
- Persistent wallet storage via `/data` volume
- Includes `cocod` wallet daemon dependency
- Exposes port 8008 for API access

## Building

```bash
cd ~/repos/routstrd
docker build -f Dockerfile.production -t routstrd:latest .
```

## Running

### Basic usage

```bash
docker run -d \
  --name routstrd \
  -p 8008:8008 \
  -v routstrd-data:/data \
  routstrd:latest
```

### With custom configuration

```bash
docker run -d \
  --name routstrd \
  -p 8008:8008 \
  -v routstrd-data:/data \
  -e ROUTSTRD_DIR=/data/.routstrd \
  -e COCOD_DIR=/data/.cocod \
  routstrd:latest
```

## API Endpoints

- `GET /health` - Health check (returns `{"ok":true}`)
- `GET /ping` - Ping test (returns `{"output":"pong"}`)
- `GET /status` - Daemon status including wallet state
- `GET /wallet/status` - Wallet details
- `POST /` - Route LLM requests

## Testing

Run the verification script:

```bash
./test-routstrd-docker.sh
```

This tests:
1. Image exists and is valid
2. Container starts and passes health checks
3. Health endpoint responds correctly
4. Status endpoint returns daemon info
5. Ping endpoint works
6. Container runs as non-root user
7. Cocod binary is available
8. Port 8008 is exposed
9. Image size is acceptable
10. Wallet persistence across container restart

## Integration with Hermes

The routstrd container is designed to run as a sidecar alongside Hermes containers:

```yaml
services:
  hermes:
    image: hermes-agent:nostr-slim
    environment:
      LLM_PROXY_URL: http://routstrd:8008/v1
    depends_on:
      - routstrd
  
  routstrd:
    image: routstrd:latest
    volumes:
      - routstrd-data:/data
```

## Wallet Persistence

The `/data` volume persists:
- `~/.routstrd/` - routstrd configuration and state
- `~/.cocod/` - cocod wallet data

To backup wallet data:

```bash
docker run --rm -v routstrd-data:/data alpine tar czf /backup/routstrd-backup.tar.gz /data
```

## Nostr Discovery

routstrd discovers Routstr providers via Nostr events (kinds 38421/38423/38425). Ensure the container has network access to Nostr relays.

## Security

- Runs as non-root user (`routstrd`)
- Minimal runtime image (no build tools)
- Health check prevents routing to unhealthy instances
- Wallet data isolated in named volume
