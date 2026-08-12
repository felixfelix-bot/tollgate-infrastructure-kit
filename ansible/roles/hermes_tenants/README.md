# hermes_tenants

Deploys multiple isolated Hermes Agent instances as Docker containers on a single VPS — one per tenant (friend). Each tenant gets its own Nostr keypair, Docker network, persistent volume, resource limits, log management, and healthcheck. No Docker socket is mounted in any tenant container (security).

## Requirements

- Docker and Docker Swarm initialized on the target host
- Hermes Agent Docker image (`hermes-agent:nostr`) built and available
- NIP-29 relay running (provides Nostr connectivity for tenants)
- `pynostr` Python package (auto-installed by the role)
- `community.docker` Ansible collection on the controller

## Role Variables

### Core

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_image` | `hermes-agent:nostr` | Docker image for Hermes Agent |
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
| `hermes_tenants_llm_proxy_url` | `http://routstr:8000` | LLM proxy URL (Routstr endpoint) |
| `hermes_tenants_gateway_port_base` | `9000` | Base host port for tenant gateways (incremented per tenant) |
| `hermes_tenants_health_port_base` | `9100` | Base host port for tenant health endpoints |

### Routstrd

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_routstrd_config.port` | `9000` | Internal routstrd port |
| `hermes_tenants_routstrd_config.health_endpoint` | `/health` | Health endpoint path |

### Resource Limits

| Variable | Default | Description |
|---|---|---|
| `hermes_tenants_resource_limits.memory` | `512m` | Max memory per tenant container |
| `hermes_tenants_resource_limits.cpus` | `1.0` | Max CPUs per tenant container |
| `hermes_tenants_resource_reservations.memory` | `256m` | Reserved memory per tenant container |

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
| `hermes_tenants_routstrd_config.port` | `9000` | Internal routstrd port to check |
| `hermes_tenants_routstrd_config.health_endpoint` | `/health` | Routstrd health endpoint path |

The healthcheck tests both the gateway (port 8080/health) and routstrd (port 9000/health).
If the gateway endpoint is unreachable, it falls back to `pgrep hermes` (process alive check).
If unhealthy after 3 retries, Docker auto-restarts the container (`restart: unless-stopped`).

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
2. **Creates Docker volume** — `hermes-<name>-data` for persistent state
3. **Writes docker-compose.yml** — per-tenant compose file with env vars (NOSTR_RELAYS, NOSTR_GROUPS, NOSTR_NSEC_PATH, LLM_PROXY_URL, routstrd config)
4. **Creates per-tenant Docker network** — `hermes-net-<name>` isolates each friend from the others
5. **Configures resource limits** — memory and CPU caps via Docker deploy.resources
6. **Configures log management** — json-file driver, max-size 10m, max-file 3
7. **Adds healthcheck** — checks routstrd health endpoint, auto-restarts on failure
8. **No Docker socket mount** — tenant containers cannot control the Docker daemon

## Example

```yaml
hermes_tenants_tenants:
  - name: "ours"
    npub: "npub1..."
    nsec: "nsec1..."
    zai_api_key: "sk-..."
  - name: "friend1"
    npub: "npub1..."
    nsec: "nsec1..."
    zai_api_key: "sk-..."
  - name: "friend2"
    zai_api_key: "sk-..."  # npub/nsec auto-generated
```

## Verification

After deployment, verify:

```bash
# 3 Hermes containers running
docker ps --filter name=hermes-

# 3 Docker networks
docker network ls --filter name=hermes-net-

# 3 Docker volumes
docker volume ls --filter name=hermes-

# Log config applied
docker inspect --format '{{.HostConfig.LogConfig}}' hermes-ours

# Health status
docker inspect --format '{{.State.Health.Status}}' hermes-ours

# Healthcheck test command
docker inspect --format '{{index .Config.Healthcheck.Test 1}}' hermes-ours

# Restart policy
docker inspect --format '{{.HostConfig.RestartPolicy.Name}}' hermes-ours

# No Docker socket mounted
docker inspect --format '{{.HostConfig.Binds}}' hermes-ours
```