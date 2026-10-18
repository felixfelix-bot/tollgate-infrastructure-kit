#!/usr/bin/env bash
# Install / upgrade the buzz-media-deleter sidecar on the relay host (VPS2).
#
# Idempotent. Detects the relay's compose network by inspecting the running
# minio container rather than assuming a name — the compose project prefix is
# not guaranteed across a re-provision, and a wrong guess here fails at runtime
# with a confusing "no such host: minio".
#
# Usage:
#   ./media-deleter/install.sh                 # install or upgrade
#   ./media-deleter/install.sh --verify-only   # just probe the live endpoint
#
# Requires: /opt/buzz-relay/.env (MinIO root creds), docker, root.
set -euo pipefail

INSTALL_DIR="${MD_INSTALL_DIR:-/opt/buzz-media-deleter}"
RELAY_DIR="${MD_RELAY_DIR:-/opt/buzz-relay}"
TENANT_NET="${MD_TENANT_NETWORK:-hermes-net-sitarani}"
TENANT_CONTAINER="${MD_TENANT_CONTAINER:-hermes-sitarani}"
MINIO_CONTAINER="${MD_MINIO_CONTAINER:-buzz-relay-minio}"
PORT="${MD_LISTEN_PORT:-8099}"
VERIFY_ONLY=0

for arg in "$@"; do
    case "$arg" in
        --verify-only) VERIFY_ONLY=1 ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

die() { echo "FATAL: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker not found"

detect_relay_network() {
    docker inspect "$MINIO_CONTAINER" \
        --format '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' 2>/dev/null \
        | grep -E '^(buzz|relay)' | head -1
}

verify() {
    if ! docker ps --format '{{.Names}}' | grep -qx 'buzz-media-deleter'; then
        die "container buzz-media-deleter is not running"
    fi
    if docker exec buzz-media-deleter \
        python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:${PORT}/healthz', timeout=5).status==200 else 1)"; then
        echo "OK  healthz 200 inside container"
    else
        die "healthz failed inside container"
    fi
    # Reachability from the tenant container is the actual contract; /healthz
    # needs no auth, so this proves DNS + network wiring without a token.
    if docker exec "$TENANT_CONTAINER" \
        python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://buzz-media-deleter:${PORT}/healthz', timeout=5).status==200 else 1)" 2>/dev/null; then
        echo "OK  healthz 200 from ${TENANT_CONTAINER} (the bridge's view)"
    else
        echo "WARN could not reach http://buzz-media-deleter:${PORT}/healthz from ${TENANT_CONTAINER}"
        echo "     check: docker inspect buzz-media-deleter --format '{{json .NetworkSettings.Networks}}'"
        echo "     and that the tenant is attached to ${TENANT_NET}"
    fi
}

if [ "$VERIFY_ONLY" -eq 1 ]; then
    verify
    exit 0
fi

[ -f "${RELAY_DIR}/.env" ] || die "${RELAY_DIR}/.env not found (MinIO creds live there)"

RELAY_NET=$(detect_relay_network) || true
[ -n "${RELAY_NET:-}" ] || RELAY_NET="buzz-relay-net"
echo "relay network: ${RELAY_NET}"
echo "tenant network: ${TENANT_NET}"
docker network inspect "$RELAY_NET" >/dev/null 2>&1 || die "network ${RELAY_NET} does not exist"
docker network inspect "$TENANT_NET" >/dev/null 2>&1 || die "network ${TENANT_NET} does not exist"

install -d -m 0755 "$INSTALL_DIR"
install -m 0755 "$(dirname "$0")/buzz_media_deleter.py" "${INSTALL_DIR}/buzz_media_deleter.py"
install -m 0644 "$(dirname "$0")/Dockerfile" "${INSTALL_DIR}/Dockerfile"
install -m 0644 "$(dirname "$0")/docker-compose.yml" "${INSTALL_DIR}/docker-compose.yml"

# Reuse the relay's MinIO root creds rather than minting a second identity the
# operator would have to rotate separately. See ADR-012 "Consequences".
if [ ! -f "${INSTALL_DIR}/.env" ]; then
    ACCESS=$(grep -E '^MINIO_ROOT_USER=' "${RELAY_DIR}/.env" | head -1 | cut -d= -f2-)
    SECRET=$(grep -E '^MINIO_ROOT_PASSWORD=' "${RELAY_DIR}/.env" | head -1 | cut -d= -f2-)
    if [ -z "$ACCESS" ] || [ -z "$SECRET" ]; then
        die "MINIO_ROOT_USER/PASSWORD not found in ${RELAY_DIR}/.env"
    fi
    TOKEN=$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')
    umask 077
    {
        echo "MD_MINIO_ACCESS_KEY=${ACCESS}"
        echo "MD_MINIO_SECRET_KEY=${SECRET}"
        echo "MD_AUTH_TOKEN=${TOKEN}"
        echo "MD_RELAY_NETWORK=${RELAY_NET}"
        echo "MD_TENANT_NETWORK=${TENANT_NET}"
    } > "${INSTALL_DIR}/.env"
    echo "wrote ${INSTALL_DIR}/.env (0600)"
    echo "NOTE: put MD_AUTH_TOKEN=${TOKEN} in the tenant .env to enable the bridge call"
else
    echo "reusing existing ${INSTALL_DIR}/.env"
    if ! grep -q '^MD_RELAY_NETWORK=' "${INSTALL_DIR}/.env"; then
        echo "MD_RELAY_NETWORK=${RELAY_NET}" >> "${INSTALL_DIR}/.env"
    fi
fi

cd "$INSTALL_DIR"
docker compose -p buzz-media-deleter build --pull
docker compose -p buzz-media-deleter up -d

for _ in $(seq 1 20); do
    if docker exec buzz-media-deleter \
        python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:${PORT}/healthz', timeout=3).status==200 else 1)" 2>/dev/null; then
        break
    fi
    sleep 1
done

verify
echo
echo "Install complete. Bridge contract:"
echo "  POST http://buzz-media-deleter:${PORT}/delete  {\"sha256\":\"<64-hex>\",\"ext\":\"<ext>\"}"
