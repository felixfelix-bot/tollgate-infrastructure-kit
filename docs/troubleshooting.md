# Troubleshooting

## Common Issues

### Deployment fails at "Wait for Caddy"
- **Cause**: Caddy can't obtain TLS certificates
- **Fix**: Verify Cloudflare API token and zone ID are correct
- **Fix**: Check that DNS records were created: `dig relay.yourdomain.com A`
- **Fix**: Check Caddy logs: `docker logs tollgate-caddy`

### Docker containers not starting
- **Cause**: Port conflicts or missing Docker
- **Fix**: Check if ports are in use: `ss -tlnp | grep <port>`
- **Fix**: Restart Docker: `systemctl restart docker`
- **Fix**: Check container logs: `docker logs <container_name>`

### DNS records not created
- **Cause**: Invalid Cloudflare API token
- **Fix**: Test your token: `curl -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" -H "Authorization: Bearer YOUR_TOKEN"`
- **Fix**: Verify zone ID matches your domain

### Shadowsocks not starting
- **Cause**: Invalid config or missing MPTCP kernel support
- **Fix**: Check journal: `journalctl -u shadowsocks-libev -n 50`
- **Fix**: Verify MPTCP: `sysctl net.mptcp.enabled`
- **Fix**: Check config: `cat /etc/shadowsocks-libev/config.json`

### FIPS daemon not starting
- **Cause**: Missing TUN device support
- **Fix**: Check logs: `journalctl -u fips -n 50`
- **Fix**: Verify TUN: `ip link show fips0`
- **Fix**: Check config: `cat /etc/fips/fips.yaml`

### Blossom server build fails
- **Cause**: Deno build issues or network problems
- **Fix**: Pull the image manually: `docker pull ghcr.io/hzrd149/blossom-server`
- **Fix**: Check disk space: `df -h`
- **Fix**: Rebuild: `docker compose -f /opt/tollgate/blossom/docker-compose.yml build --no-cache`

### strfry relay not responding
- **Fix**: Check if container is running: `docker ps | grep strfry`
- **Fix**: Check logs: `docker logs tollgate-strfry`
- **Fix**: Test locally: `curl http://localhost:7777`

### Hermes gateway not listening on port 8080
- **Cause**: The `command: ["sleep", "infinity"]` in docker-compose.yml overrides the image's s6 entrypoint, preventing the gateway service from starting
- **Fix**: Remove the `command` line from docker-compose.yml and restart the container:
  ```bash
  # Edit the compose file
  sed -i '/command: \["sleep", "infinity"\]/d' /opt/tollgate/hermes/<tenant>/docker-compose.yml
  
  # Restart the container
  cd /opt/tollgate/hermes/<tenant> && docker compose down && docker compose up -d
  ```
- **Fix**: For running containers without restart, remove the s6 'down' file:
  ```bash
  docker exec hermes-<tenant> rm -f /run/service/gateway-default/down
  ```
- **Verify**: Check gateway responds: `curl http://localhost:<port>/health`

### Locale warnings on Debian
- **Fix**: Run the system playbook to configure locale
- **Fix**: `dpkg-reconfigure locales` and select `en_US.UTF-8`

## Useful Commands

```bash
# Check all Docker containers
docker ps -a

# Check all services
systemctl status shadowsocks-libev fips

# Check Caddy config
docker exec tollgate-caddy caddy validate --config /etc/caddy/Caddyfile

# Reload Caddy (after manual config changes)
docker exec tollgate-caddy caddy reload --config /etc/caddy/Caddyfile

# View Caddy logs
docker logs -f tollgate-caddy

# Check disk usage
df -h

# Check Docker disk usage
docker system df

# Clean up Docker
docker system prune -af
```

## Getting Help

- Open an issue: [GitHub Issues](https://github.com/OpenTollGate/tollgate-infrastructure-kit/issues)
- Check the [services documentation](services.md) for service-specific details
