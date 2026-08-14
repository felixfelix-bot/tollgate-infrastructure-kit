# Hermes Slim Docker Image

A trimmed-down Docker image for Hermes Agent, optimized for friend containers. Reduces image size from ~3.8GB to ~813MB (78% reduction) by removing browser automation and media processing dependencies.

## Size Comparison

| Image | Size | Reduction |
|-------|------|-----------|
| hermes-agent:nostr | ~3.8GB | baseline |
| hermes-agent:nostr-slim | ~813MB | 78% smaller |

## What's Removed

- **Playwright** - Browser automation framework
- **Node.js/npm** - JavaScript runtime (downloaded on-demand if needed)
- **ffmpeg** - Media processing
- **build-essential** - C/C++ compilers
- **Rust/Cargo toolchain** - Build dependencies
- **Web UI/TUI components** - Terminal UI libraries

## What's Preserved

- **coincurve** - Cryptographic library for Nostr
- **s6-overlay** - Process supervisor and init system
- **Python 3.13** - Core runtime
- **All Python dependencies** from pyproject.toml
- **Hermes CLI** - Full functionality

## Usage

### Build the image

```bash
cd ~/.hermes/hermes-agent
docker build -f ~/tollgate-infrastructure-kit/hermes-docker/Dockerfile.slim \
  -t hermes-agent:nostr-slim .
```

### Run a container

```bash
docker run -d --name hermes-slim \
  -p 8080:8080 \
  -e HERMES_GATEWAY_PORT=8080 \
  hermes-agent:nostr-slim
```

### Verify the image

```bash
~/tollgate-infrastructure-kit/tests/test-hermes-slim-image.sh
```

## Technical Details

### Multi-stage Build

The Dockerfile uses a multi-stage build:

1. **Builder stage** (`ghcr.io/astral-sh/uv:python3.13`)
   - Installs build dependencies (gcc, cmake, libffi-dev, etc.)
   - Creates Python virtual environment with all dependencies
   - Installs Hermes in editable mode

2. **Runtime stage** (`debian:13.4-slim`)
   - Copies only runtime dependencies
   - Copies Python packages from builder
   - Copies full Hermes source tree to `/opt/hermes`
   - Sets up s6-overlay for process management
   - Creates fake venv structure for compatibility

### Key Design Decisions

- **Full source copy**: The entire Hermes source is copied to `/opt/hermes` because hermes_cli modules use relative imports (e.g., `from utils import ...`, `from agent.secret_sources import ...`)
- **Fake venv**: A minimal venv structure is created at `/opt/hermes/.venv` pointing to system Python for compatibility with scripts expecting venv paths
- **s6-overlay preserved**: The init system is kept for proper process supervision

## Testing

The test script verifies:
1. Image size is under 2GB
2. `hermes --version` works
3. Container starts successfully
4. Gateway port is accessible

## Notes

- First container startup may download Node.js and Chrome if browser tools are used
- The image is optimized for gateway/agent use, not for development
- For development with full browser automation, use the original `hermes-agent:nostr` image
