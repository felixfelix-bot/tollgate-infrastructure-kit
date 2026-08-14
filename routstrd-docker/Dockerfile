# Production Dockerfile for routstrd
# Multi-stage build for minimal runtime image

# Stage 1: Builder
FROM oven/bun:1-slim AS builder

WORKDIR /app

# Copy dependency files first for better layer caching
COPY package.json bun.lock ./
RUN bun install

# Copy source and build
COPY . .
RUN bun run build

# Stage 2: Runtime
FROM oven/bun:1-slim AS runtime

# Install curl for health checks
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user with home directory
RUN groupadd -r routstrd && useradd -r -g routstrd -m -d /home/routstrd routstrd

# Copy built application from builder
COPY --from=builder /app/dist /app/dist
COPY --from=builder /app/package.json /app/package.json
COPY --from=builder /app/node_modules /app/node_modules

# Create data directory for persistent storage
RUN mkdir -p /data/.routstrd /data/.cocod && \
    chown -R routstrd:routstrd /data /app /home/routstrd

# Install cocod as root to system location, then fix permissions
RUN bun install -g @routstr/cocod && \
    mkdir -p /usr/local/lib/node_modules && \
    cp -r /root/.bun/install/global/node_modules/@routstr /usr/local/lib/node_modules/ && \
    ln -sf /usr/local/lib/node_modules/@routstr/cocod/src/index.ts /usr/local/bin/cocod && \
    chown -R routstrd:routstrd /usr/local/lib/node_modules/@routstr /usr/local/bin/cocod

WORKDIR /app

# Set environment variables
ENV ROUTSTRD_DIR=/data/.routstrd
ENV COCOD_DIR=/data/.cocod
ENV NODE_ENV=production
ENV PATH="/usr/local/bin:${PATH}"

# Switch to non-root user
USER routstrd

# Expose daemon port
EXPOSE 8008

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8008/health || exit 1

# Production command: run daemon directly in foreground (not via 'start' which backgrounds)
CMD ["bun", "run", "dist/daemon/index.js"]
