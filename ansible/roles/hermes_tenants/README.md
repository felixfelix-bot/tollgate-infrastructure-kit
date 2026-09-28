# hermes_tenants

Deploys multiple isolated Hermes Agent instances as Docker containers on a single VPS — one per tenant (friend). Each tenant gets:
- Its own Nostr keypair
- Its own Docker network (isolated from other tenants)
- Its own persistent volumes (Hermes data + routstrd wallet)
- Resource limits (memory, CPU)
- Log management with rotation
- Healthchecks for both Hermes and routstrd
- A routstrd sidecar for LLM proxy with Cashu payments

No Docker socket is mounted in any tenant container (security).

## Architecture

Each tenant runs two containers:

1. **hermes-<tenant>** — The Hermes Agent gateway (listens on port 8080)
2. **routstrd-<tenant>** — The routstrd sidecar (port 8008) for LLM proxy with Cashu payments

Hermes routes all LLM calls through the routstrd sidecar:
```
Hermes → routstrd → Routstr node → z.ai
```

Each tenant has its own Cashu wallet (persisted in `routstrd-<tenant>-data` volume).

## Requirements

- Docker and Docker Compose v2 on the target host
- Hermes Agent Docker image (`hermes-agent:nostr-slim`) built and available
- routstrd Docker image (`routstrd:latest`) built and available
- NIP-29 relay running (provides Nostr connectivity for tenants)
- `pynostr` Python package (auto-installed by the role)
- `community.docker` Ansible collection on the controller

## Role Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_image` | `hermes-agent:nostr-slim` | Docker image for Hermes Agent |
| `hermes_tenants_routstrd_image` | `routstrd:latest` | Docker image for routstrd sidecar |
| `hermes_tenants_base_dir` | `/opt/tollgate/hermes` | Base directory for tenant data |
| `hermes_tenants_relay_url` | `ws://nip29-relay:7780` | NIP-29 relay URL for tenants |
| `hermes_tenants_deployment_admin_nsec` | `""` | Deployment admin Nostr secret key |
| `hermes_tenants_tenants` | `[]` | List of tenant dicts (see below) |
| `hermes_tenants_container_restart` | `unless-stopped` | Docker restart policy |

### Networking

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_nostr_relays` | `ws://nip29-relay:7780,...` | Comma-separated Nostr relay URLs |
| `hermes_tenants_nostr_groups` | `""` | Comma-separated NIP-29 group IDs |
| `hermes_tenants_llm_proxy_url` | `http://routstrd:8008/v1` | LLM proxy URL (routstrd sidecar) |
| `hermes_tenants_gateway_port_base` | `9000` | Base host port for tenant gateways (incremented per tenant) |
| `hermes_tenants_health_port_base` | `9100` | Base host port for tenant health endpoints |

### Routstrd Sidecar

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_routstrd_config.port` | `8008` | Internal routstrd port |
| `hermes_tenants_routstrd_config.health_endpoint` | `/health` | Health endpoint path |
| `hermes_tenants_routstrd_resource_limits.memory` | `256m` | Max memory for routstrd container |
| `hermes_tenants_routstrd_resource_limits.cpus` | `0.5` | Max CPUs for routstrd container |

### Resource Limits

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_resource_limits.memory` | `512m` | Max memory per Hermes container |
| `hermes_tenants_resource_limits.cpus` | `1.0` | Max CPUs per Hermes container |
| `hermes_tenants_resource_reservations.memory` | `256m` | Reserved memory per Hermes container |

### Log Management

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_log_driver` | `json-file` | Docker logging driver |
| `hermes_tenants_log_max_size` | `10m` | Max log file size before rotation |
| `hermes_tenants_log_max_file` | `3` | Max number of rotated log files |

### Healthcheck

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_healthcheck_interval` | `30s` | Healthcheck interval |
| `hermes_tenants_healthcheck_timeout` | `10s` | Healthcheck timeout |
| `hermes_tenants_healthcheck_retries` | `3` | Healthcheck retries before unhealthy |
| `hermes_tenants_healthcheck_start_period` | `60s` | Grace period before healthchecks count |
| `hermes_tenants_gateway_config.port` | `8080` | Internal gateway port to check |
| `hermes_tenants_gateway_config.health_endpoint` | `/health` | Gateway health endpoint path |

The healthcheck tests the gateway (port 8080/health). If unhealthy after 3 retries, Docker auto-restarts the container (`restart: unless-stopped`).

### Security

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_no_docker_socket` | `true` | If true, Docker socket is NOT mounted in tenant containers |

## Tenant Configuration

Each tenant is a dict with:

- `name`: unique identifier (used for container name, network, volume, directory)
- `npub`: Nostr public key (npub1...) — auto-generated if omitted
- `nsec`: Nostr secret key (nsec1...) — auto-generated if omitted
- `zai_api_key`: ZAI API key for LLM inference

## What the Role Does

For each tenant:

1. **Generates nsec/npub keypair** — if `nsec` is not provided, generates a fresh Nostr keypair using `pynostr` and writes the nsec to `nsec/nsec.txt`
2. **Creates Docker volumes**:
   - `hermes-<name>-data` for Hermes persistent state
   - `routstrd-<name>-data` for routstrd wallet and config
3. **Writes docker-compose.yml** — per-tenant compose file with:
   - Hermes service with `LLM_PROXY_URL` pointing to routstrd sidecar
   - routstrd sidecar service with healthcheck and resource limits
   - Both services on shared `hermes-net-<name>` network
4. **Creates per-tenant Docker network** — `hermes-net-<name>` isolates each friend from the others
5. **Configures resource limits** — memory and CPU caps via Docker deploy.resources
6. **Configures log management** — json-file driver, max-size 10m, max-file 3
7. **Adds healthchecks** — for both Hermes gateway and routstrd sidecar
8. **No Docker socket mount** — tenant containers cannot control the Docker daemon

## Example

```yaml
hermes_tenants_tenants:
  - name: "sitarani"
    npub: "npub1..."
    nsec: "nsec1..."
    zai_api_key: "sk-..."
  - name: "chiefmonkey"
    npub: "npub1..."
    nsec: "nsec1..."
    zai_api_key: "sk-..."
  - name: "bekka"
    zai_api_key: "sk-..."  # npub/nsec auto-generated
```

## Verification

After deployment, verify:

```bash
# 3 Hermes containers + 3 routstrd sidecars running
docker ps --filter name=hermes-
docker ps --filter name=routstrd-

# 3 Docker networks
docker network ls --filter name=hermes-net-

# 6 Docker volumes (3 Hermes + 3 routstrd)
docker volume ls --filter name=hermes-
docker volume ls --filter name=routstrd-

# Hermes health status
docker inspect --format '{{.State.Health.Status}}' hermes-sitarani

# routstrd health status
docker inspect --format '{{.State.Health.Status}}' routstrd-sitarani

# Check routstrd is responding
docker exec routstrd-sitarani curl -s http://localhost:8008/health

# Verify LLM proxy routing
docker exec hermes-sitarani env | grep LLM_PROXY_URL

# Restart policy
docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' hermes-sitarani

# No Docker socket mounted
docker inspect --format '{{.HostConfig.Binds}}' hermes-sitarani
```