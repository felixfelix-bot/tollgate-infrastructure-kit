#!/bin/bash
# V2-01 Rename Script: Rename Hermes containers on VPS2
# Maps: hermes-ours -> hermes-sitarani, hermes-friend1 -> hermes-chiefmonkey, hermes-friend2 -> hermes-bekka
# Preserves data volumes by copying from old to new

set -euo pipefail

echo "=== V2-01: Renaming Hermes Containers ==="
echo "Target: VPS2 (23.182.128.51)"
echo ""

# Define the rename mapping
# Format: old_dir:old_container:new_dir:new_container
RENAME_MAP=(
    "ours:hermes-ours:sitarani:hermes-sitarani"
    "friend1:hermes-friend1:chiefmonkey:hermes-chiefmonkey"
    "friend2:hermes-friend2:bekka:hermes-bekka"
)

BASE_DIR="/opt/tollgate/hermes"

cd "$BASE_DIR" || { echo "ERROR: Cannot cd to $BASE_DIR"; exit 1; }

# Step 1: Stop old containers
echo "[1/7] Stopping old containers..."
for mapping in "${RENAME_MAP[@]}"; do
    old_container=$(echo "$mapping" | cut -d: -f2)
    if docker ps -a --format '{{.Names}}' | grep -q "^${old_container}$"; then
        echo "  Stopping ${old_container}..."
        docker stop "$old_container" 2>/dev/null || true
    else
        echo "  ${old_container} not found (already stopped)"
    fi
done

# Step 2: Copy volumes to new names
echo ""
echo "[2/7] Copying volume data to new names..."
for mapping in "${RENAME_MAP[@]}"; do
    old_container=$(echo "$mapping" | cut -d: -f2)
    new_container=$(echo "$mapping" | cut -d: -f4)
    old_volume="${old_container}-data"
    new_volume="${new_container}-data"
    
    if docker volume ls --format '{{.Name}}' | grep -q "^${old_volume}$"; then
        if ! docker volume ls --format '{{.Name}}' | grep -q "^${new_volume}$"; then
            echo "  Creating ${new_volume} from ${old_volume}..."
            docker volume create "$new_volume"
            # Copy data from old volume to new volume
            docker run --rm \
                -v "${old_volume}:/old" \
                -v "${new_volume}:/new" \
                alpine:latest \
                sh -c 'cp -a /old/. /new/ 2>/dev/null || true'
            echo "    ✓ Data copied to ${new_volume}"
        else
            echo "  ${new_volume} already exists, skipping copy"
        fi
    else
        echo "  WARNING: ${old_volume} not found, creating empty ${new_volume}..."
        docker volume create "$new_volume" || true
    fi
done

# Step 3: Create new networks
echo ""
echo "[3/7] Creating new networks..."
for mapping in "${RENAME_MAP[@]}"; do
    new_dir=$(echo "$mapping" | cut -d: -f3)
    new_network="hermes-net-${new_dir}"
    
    if ! docker network ls --format '{{.Name}}' | grep -q "^${new_network}$"; then
        echo "  Creating network ${new_network}..."
        docker network create "$new_network" || true
    else
        echo "  Network ${new_network} already exists"
    fi
done

# Step 4: Create new tenant directories with updated compose files
echo ""
echo "[4/7] Creating new tenant directories..."
for mapping in "${RENAME_MAP[@]}"; do
    old_dir=$(echo "$mapping" | cut -d: -f1)
    old_container=$(echo "$mapping" | cut -d: -f2)
    new_dir=$(echo "$mapping" | cut -d: -f3)
    new_container=$(echo "$mapping" | cut -d: -f4)
    
    if [ -d "$old_dir" ]; then
        if [ ! -d "$new_dir" ]; then
            echo "  Creating ${new_dir} from ${old_dir}..."
            mkdir -p "$new_dir"
            
            # Copy config and nsec directories
            if [ -d "${old_dir}/config" ]; then
                cp -r "${old_dir}/config" "${new_dir}/"
            fi
            if [ -d "${old_dir}/nsec" ]; then
                cp -r "${old_dir}/nsec" "${new_dir}/"
            fi
            
            # Create new docker-compose.yml with updated names
            old_port_prefix=""
            case "$old_dir" in
                "ours") old_port_prefix="9000" ;;
                "friend1") old_port_prefix="9001" ;;
                "friend2") old_port_prefix="9002" ;;
            esac
            
            cat > "${new_dir}/docker-compose.yml" << EOF
services:
  ${new_container}:
    image: hermes-agent:nostr
    command: ["sleep", "infinity"]
    container_name: ${new_container}
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ${new_container}-data:/data
      - ./config:/config
      - ./nsec:/nsec:ro
    networks:
      - routstr_default
      - hermes-net-${new_dir}
    ports:
      - "${old_port_prefix}:8080"
      - "91${old_port_prefix#90}:9000"
    healthcheck:
      test: ["CMD-SHELL", "pgrep -f 'hermes gateway run' || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s
    deploy:
      replicas: 1
      restart_policy:
        condition: unless-stopped
      resources:
        limits:
          memory: 512m
          cpus: "1.0"
        reservations:
          memory: 256m
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"
    security_opt:
      - no-new-privileges:true

volumes:
  ${new_container}-data:
    external: true
    name: ${new_container}-data

networks:
  routstr_default:
    external: true
  hermes-net-${new_dir}:
    external: true
    name: hermes-net-${new_dir}
EOF
            
            # Copy .env file
            if [ -f "${old_dir}/.env" ]; then
                cp "${old_dir}/.env" "${new_dir}/.env"
            fi
            
            echo "    ✓ Created ${new_dir}/docker-compose.yml"
        else
            echo "  ${new_dir} already exists, skipping"
        fi
    else
        echo "  WARNING: ${old_dir} not found"
    fi
done

# Step 5: Remove old containers
echo ""
echo "[5/7] Removing old containers..."
for mapping in "${RENAME_MAP[@]}"; do
    old_container=$(echo "$mapping" | cut -d: -f2)
    if docker ps -a --format '{{.Names}}' | grep -q "^${old_container}$"; then
        echo "  Removing ${old_container}..."
        docker rm "$old_container" 2>/dev/null || true
    else
        echo "  ${old_container} already removed"
    fi
done

# Step 6: Start new containers
echo ""
echo "[6/7] Starting new containers..."
for mapping in "${RENAME_MAP[@]}"; do
    new_dir=$(echo "$mapping" | cut -d: -f3)
    new_container=$(echo "$mapping" | cut -d: -f4)
    
    if [ -d "$new_dir" ] && [ -f "${new_dir}/docker-compose.yml" ]; then
        echo "  Starting ${new_container}..."
        cd "$new_dir"
        docker compose up -d 2>/dev/null || docker-compose up -d 2>/dev/null || true
        cd "$BASE_DIR"
    else
        echo "  WARNING: ${new_dir}/docker-compose.yml not found"
    fi
done

# Step 7: Verification
echo ""
echo "[7/7] Verification..."
echo ""
echo "Running containers:"
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep hermes || echo "  No hermes containers found"

echo ""
echo "Volumes:"
docker volume ls | grep hermes || echo "  No hermes volumes found"

echo ""
echo "Networks:"
docker network ls | grep hermes || echo "  No hermes networks found"

echo ""
echo "Tenant directories:"
ls -la | grep -E '^(d|-).*\s(ours|friend1|friend2|sitarani|chiefmonkey|bekka)$' || true

echo ""
echo "=== Rename Complete ==="
echo "Run tests/verify-hermes-rename.sh to verify"
