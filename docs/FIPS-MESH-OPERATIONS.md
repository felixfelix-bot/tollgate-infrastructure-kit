# FIPS Mesh Operations Guide

> **Status:** Active operations document
> **Created:** 2026-08-12
> **Owner:** Felix (c03rad0r)
> **Repo:** `tollgate-infrastructure-kit` (main branch)
> **Ansible Role:** `ansible/roles/fips/`
> **Playbook:** `ansible/playbooks/13-fips.yml`
> **Related docs:** [FIPS Mesh Setup Plan](../PLAN-FIPS-MESH-SETUP.md), [FIPS Mesh Deployment Plan](FIPS-MESH-DEPLOYMENT-PLAN.md), [FIPS Ingress Gate](FIPS-INGRESS-GATE.md), [FIPS Hosting Plan](fips-hosting-plan.md)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Ansible Role Reference](#2-ansible-role-reference)
3. [Config Structure](#3-config-structure)
4. [Peer Management](#4-peer-management)
5. [Troubleshooting](#5-troubleshooting)
6. [Reboot Procedures](#6-reboot-procedures)
7. [ESP32 Status](#7-esp32-status)
8. [Daily Operations Cheat Sheet](#8-daily-operations-cheat-sheet)

---

## 1. Architecture Overview

### 1.1 Private Mesh — Hub-and-Spoke via VPS2

The mesh uses a **private** FIPS overlay with only Felix's devices. No public
test mesh nodes are used — the public mesh's bloom filters are saturated at
the scale of hundreds of nodes, causing false positives, unnecessary
connection attempts, and degraded discovery. FIPS v2 (dynamic bloom filter
sizing) is not yet released, so a small private mesh avoids the problem.

```
                         PRIVATE FIPS MESH
                              ┌──────────────────────────┐
                              │          VPS2 (HUB)      │
                              │       23.182.128.51      │
                              │   UDP:2121  TCP:8443     │
                              │   Public IP — inbound    │
                              │       eth0  Debian       │
                              └───┬──────────┬──────────┬┘
                                  │          │          │
                     ┌────────────┘          │          └────────────┐
                     │                       │                       │
                     ▼                       ▼                       ▼
              ┌──────────┐           ┌──────────┐           ┌──────────┐
              │   DQ05   │◄─ LAN ──►│  T14Gen5 │           │   T470   │
              │ (laptop) │  discovery│ (laptop) │           │ (backup) │
              │  x86_64  │           │  x86_64  │           │  x86_64  │
              │ wlp58s0  │           │wlp0s20f3 │           │ wlp58s0  │
              └────┬─────┘           └────┬─────┘           └────┬─────┘
                   │                      │                      │
                   └──────────┬───────────┴──────────────────────┘
                              │
                         ┌────┴─────┐
                         │ fips0    │
                         │ TUN IF   │
                         │ MTU 1280 │
                         │ IPv6 LL  │
                         └──────────┘
```

### 1.2 Fleet Inventory

| Machine   | Role     | Interface    | Reachable via          | npub                                                              | FIPS version |
|-----------|----------|--------------|------------------------|-------------------------------------------------------------------|--------------|
| VPS2      | Hub      | eth0         | 23.182.128.51 (public) | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82` | 0.4.1       |
| DQ05      | Spoke    | wlp58s0      | Netbird 100.90.22.201   | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72` | 0.4.1       |
| T14Gen5   | Spoke    | wlp0s20f3    | localhost (local)      | `npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh` | 0.4.1       |
| T470      | Spoke    | wlp58s0      | Netbird 100.90.101.9    | TBD (discover after install via `fipsctl show status`)            | 0.4.1       |
| Andre     | External peer | —      | 194.191.252.108:2121   | `npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n` | 0.4.1       |

> VPS1 (66.92.204.38) is offline since Jul 20 — excluded from the mesh.

### 1.3 Nostr Discovery

FIPS nodes use Nostr as a discovery layer with `policy: configured_only`.
Each node advertises its npub + transport addresses to the configured relay
set with app tag `fips-overlay-v1`. Nodes only connect to peers whose npubs
appear in their local config — no random public mesh peerings.

Relays used:
- `wss://relay.damus.io`
- `wss://nos.lol`
- `wss://offchain.pub`
- `wss://relay.orangesync.tech`
- `wss://ngit.orangesync.tech`

STUN servers for NAT traversal:
- `stun:stun.l.google.com:19302`
- `stun:stun.cloudflare.com:3478`
- `stun:global.stun.twilio.com:3478`

### 1.4 .fips DNS Resolution

1. `fips-dns` service listens on `[::1]:5354` (DNS-over-UDP)
2. `fips-dns-setup` integrates with `systemd-resolved` to route `*.fips` queries
3. `fips-dns` reads `/etc/fips/hosts` for name → npub mappings
4. Query for `dq05.fips` resolves the npub to the peer's mesh IPv6 on fips0
5. Applications connect to `<hostname>.fips` and traffic flows over fips0

Host aliases configured in `/etc/fips/hosts`:

| Alias     | npub                                                                 |
|-----------|----------------------------------------------------------------------|
| vps2      | `npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82`  |
| dq05      | `npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72`  |
| t14gen5   | `npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh`  |
| andre     | `npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n`  |

### 1.5 SSH User Reference

| Machine   | SSH user   | SSH key                | Connection method          |
|-----------|------------|------------------------|----------------------------|
| DQ05      | c03rad0r   | ~/.ssh/id_ed25519      | Netbird IP or localhost     |
| T14Gen5   | c03rad0r   | ~/.ssh/id_ed25519      | localhost (local)           |
| VPS2      | debian     | ~/.ssh/id_ed25519      | VPS2_IP (public)            |
| T470      | c03rad0r   | ~/.ssh/id_ed25519      | Netbird IP or localhost     |

---

## 2. Ansible Role Reference

### 2.1 Role Layout

```
ansible/roles/fips/
├── defaults/main.yml       # Default variables (version, peers, relays, STUN)
├── tasks/main.yml           # Task flow: install → configure → verify
├── handlers/main.yml        # Service reload/restart handlers
└── templates/
    ├── fips.yaml.j2         # Main FIPS config template
    ├── fips-hosts.j2        # /etc/fips/hosts — name → npub mappings
    └── ssh.nft.j2           # nftables rule for SSH over fips0
```

### 2.2 Playbook

`ansible/playbooks/13-fips.yml`:

```yaml
---
- name: Deploy fips
  hosts: all
  ignore_unreachable: true
  serial: 1
  become: yes
  gather_facts: yes
  roles:
    - fips
```

The playbook targets `all` hosts with `serial: 1` (one host at a time to
avoid mesh disruption). `ignore_unreachable: true` prevents a down machine
from aborting the entire run.

### 2.3 Key Variables (defaults/main.yml)

| Variable                  | Default                              | Description                         |
|---------------------------|--------------------------------------|-------------------------------------|
| `fips_version`             | `"0.4.1"`                            | FIPS package version                |
| `fips_ethernet_interface`  | `""` (auto-detect)                   | WiFi/ethernet interface for LAN     |
| `fips_ethernet_auto_detect`| `true`                               | Auto-detect active interface        |
| `fips_lan_discovery`       | `true`                               | Enable LAN/ethernet discovery       |
| `fips_mesh_ssh_port`       | `22`                                 | SSH port over fips0                 |
| `fips_advertise_relays`    | 5 Nostr relays                       | Relays for advertisement            |
| `fips_dm_relays`           | 5 Nostr relays                       | Relays for DMs                      |
| `fips_stun_servers`        | 3 STUN servers                       | NAT traversal                       |
| `fips_peers`               | Andre (194.191.252.108:2121)        | List of peer configs                |
| `fips_mesh_hosts`          | dq05, t14gen5, andre                 | Shortname → npub mapping dict        |
| `fips_extra_hosts`         | `{}`                                 | Per-host extra host aliases         |
| `fips_external_addr`       | `""`                                 | External TCP address for advertise  |

### 2.4 Inventory Groups

The Ansible inventory (`ansible/inventory/hosts.yml`) contains:

- **vps** — `vps1`, `vps2`
- **nip29_relays** — `dq05`, `t470`
- **t14gen5** — localhost (local connection)
- **t470_local** — localhost (local connection)

> **Note:** A `fips_all` / `fips_laptops` / `fips_vps` group structure is
> planned (see PLAN-FIPS-MESH-SETUP.md §6.2) but not yet in the inventory.

### 2.5 Task Tags (Planned)

| Tag       | Tasks                                                        | Use case                           |
|-----------|--------------------------------------------------------------|------------------------------------|
| `install` | Download .deb, install package, ensure fips group, add user  | Install or upgrade FIPS            |
| `config`  | Deploy fips.yaml, deploy /etc/fips/hosts, deploy ssh.nft     | Apply config changes only          |
| `verify`  | Wait for socket, check peers, check status, check DNS       | Verify mesh health without changes |
| `dns`     | Enable fips-dns, run fips-dns-setup, restart resolved        | DNS-specific operations            |
| `firewall`| Deploy ssh.nft, reload nftables                              | Firewall-specific operations       |

### 2.6 Common Ansible Commands

```bash
# Full deploy (all hosts, serial)
ansible-playbook 13-fips.yml

# Single machine
ansible-playbook 13-fips.yml -l dq05

# Check mode (dry run)
ansible-playbook 13-fips.yml --check

# Verify only (planned tag)
ansible-playbook 13-fips.yml --tags verify

# Limit to VPS2
ansible-playbook 13-fips.yml -l vps2
```

---

## 3. Config Structure

### 3.1 /etc/fips/fips.yaml

The main config file, templated from `fips.yaml.j2`:

```yaml
node:
  identity:
    persistent: true
  discovery:
    nostr:
      enabled: true
      policy: configured_only
      app: "fips-overlay-v1"
      advertise: true
      advert_relays:
        - "wss://relay.damus.io"
        - "wss://nos.lol"
        - "wss://offchain.pub"
        - "wss://relay.orangesync.tech"
        - "wss://ngit.orangesync.tech"
      dm_relays:
        - "wss://relay.damus.io"
        - "wss://nos.lol"
        - "wss://offchain.pub"
        - "wss://relay.orangesync.tech"
        - "wss://ngit.orangesync.tech"
      stun_servers:
        - "stun:stun.l.google.com:19302"
        - "stun:stun.cloudflare.com:3478"
        - "stun:global.stun.twilio.com:3478"
    lan:
      enabled: true

tun:
  enabled: true
  name: fips0
  mtu: 1280

dns:
  enabled: true
  bind_addr: "[::1]"
  port: 5354

transports:
  udp:
    bind_addr: "0.0.0.0:2121"
    advertise_on_nostr: true
  tcp:
    bind_addr: "0.0.0.0:8443"
    advertise_on_nostr: true
  ethernet:
    interface: "wlp58s0"
    discovery: true
    announce: true
    auto_connect: true
    accept_connections: true

peers:
  - npub: "npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n"
    alias: "Andre"
    addresses:
      - transport: udp
        addr: "194.191.252.108:2121"
    connect_policy: auto_connect
```

### 3.2 Config File Locations

| Path                    | Purpose                              | Mode  | Source            |
|-------------------------|--------------------------------------|-------|-------------------|
| `/etc/fips/fips.yaml`   | Main FIPS daemon config              | 0600  | `fips.yaml.j2`    |
| `/etc/fips/hosts`       | Shortname → npub mappings for DNS    | 0644  | `fips-hosts.j2`   |
| `/etc/fips/fips.d/`     | Drop-in directory for nftables rules | 0755  | tasks/main.yml    |
| `/etc/fips/fips.d/ssh.nft` | nftables rule for SSH over fips0  | 0644  | `ssh.nft.j2`      |

### 3.3 /etc/fips/hosts Format

One line per host: `<shortname> <npub>`

```
# /etc/fips/hosts — managed by Ansible
vps2 npub1sqg8fd4ea25gev2ppvra68lrg8qyhx3fup0awp7gsxwchph8634sewhu82
dq05 npub1eak909yyj7w94p6ct5yzqh3cn2ysq5w2u70cdat90uqxezcdkyus9kac72
t14gen5 npub1srsllgfuxrmv7cwewu3yzak0gmth5ats989zv35t6sc9ctf4fr6syqufhh
andre npub1k3aerhf3f4ed9mrlu2zcusx3yruvzqyeut0kz5we5xd023jfgl0s8wcl6n
```

### 3.4 ssh.nft Firewall Rule

```
table inet fips-ssh {
    chain input {
        type filter hook input priority 0; policy accept;
        iifname "fips0" tcp dport 22 accept
    }
}
```

This allows SSH traffic inbound on the fips0 TUN interface. The rule is
loaded via `nft -f /etc/fips/fips.d/ssh.nft`.

### 3.5 Systemd Services

FIPS installs three systemd services:

| Service          | Purpose                                    | Auto-start? |
|------------------|--------------------------------------------|-------------|
| `fips`           | Main FIPS daemon (TUN, peers, transports)  | yes (enabled)|
| `fips-dns`       | DNS resolver for *.fips on [::1]:5354     | yes (enabled)|
| `fips-firewall`  | nftables firewall management for fips0    | yes (enabled)|

The control socket is at `/run/fips/control.sock`.

---

## 4. Peer Management

### 4.1 Adding a New Peer

To add a new machine to the mesh:

1. **Install FIPS on the new machine** (if not already installed):
   ```bash
   # Via Ansible (preferred)
   ansible-playbook 13-fips.yml -l <new_host>

   # Manual install
   wget https://github.com/jmcorgan/fips/releases/download/v0.4.1/fips_0.4.1_amd64.deb
   sudo apt install ./fips_0.4.1_amd64.deb
   sudo systemctl enable --now fips fips-dns fips-firewall
   ```

2. **Discover the new machine's npub** (generated on first run with persistent identity):
   ```bash
   sudo fipsctl show status
   # Record the npub from the output
   ```

3. **Add the npub to Ansible defaults** (`ansible/roles/fips/defaults/main.yml`):
   ```yaml
   fips_mesh_hosts:
     ...
     <new_alias>: "<new_npub>"
   ```

4. **Add the peer config** (if the new machine should peer with a specific node):
   ```yaml
   fips_peers:
     - npub: "<new_npub>"
       alias: "<new_alias>"
       addresses:
         - transport: udp
           addr: "<ip>:2121"
       connect_policy: auto_connect
   ```

5. **Redeploy to all machines** to propagate the new host alias:
   ```bash
   ansible-playbook 13-fips.yml
   ```

6. **Verify**:
   ```bash
   # On the new machine
   sudo fipsctl show peers
   # Should show connected peers

   # From another machine
   dig @::1 -p 5354 <new_alias>.fips AAAA +short
   # Should return a mesh IPv6 address

   ssh <user>@<new_alias>.fips
   # Should connect over fips0
   ```

### 4.2 Removing a Peer

1. **Remove the peer** from `fips_peers` in `ansible/roles/fips/defaults/main.yml`
2. **Remove the host alias** from `fips_mesh_hosts` in the same file
3. **Redeploy**:
   ```bash
   ansible-playbook 13-fips.yml
   ```
4. **Verify** the peer is gone:
   ```bash
   sudo fipsctl show peers
   ```

### 4.3 Switching a Peer's Transport

To change a peer's transport (e.g., from UDP to TCP):

1. Edit the peer's `addresses` block in `fips_peers`:
   ```yaml
   fips_peers:
     - npub: "<peer_npub>"
       alias: "<peer_alias>"
       addresses:
         - transport: tcp
           addr: "<ip>:8443"
       connect_policy: auto_connect
   ```

2. Redeploy:
   ```bash
   ansible-playbook 13-fips.yml -l <target_host>
   ```

3. Verify:
   ```bash
   sudo fipsctl show peers
   ```

### 4.4 Peer Connectivity Verification

```bash
# Show all peers and their connection state
sudo fipsctl show peers

# Show node status (npub, version, peer count)
sudo fipsctl show status

# Show transports
sudo fipsctl show transports

# DNS resolution check
dig @::1 -p 5354 vps2.fips AAAA +short

# Ping over FIPS
ping vps2.fips

# SSH over FIPS
ssh debian@vps2.fips
```

### 4.5 Peer States

| State        | Meaning                                                   |
|--------------|-----------------------------------------------------------|
| `connected`  | Peer is reachable and the FMP session is active          |
| `connecting` | FIPS is attempting to establish a connection              |
| `disconnected` | Peer is known but not currently reachable              |
| `discovering` | FIPS is using Nostr/LAN discovery to find the peer      |

---

## 5. Troubleshooting

### 5.1 FIPS Daemon Not Starting

**Symptoms:** `systemctl status fips` shows failed/inactive

**Diagnostics:**
```bash
# Check journal
journalctl -u fips -n 50 --no-pager

# Verify TUN device
ip link show fips0

# Check config syntax
cat /etc/fips/fips.yaml

# Verify the .deb is installed
dpkg -l | grep fips

# Check for missing dependencies
dpkg --verify fips
```

**Common causes:**
- Missing TUN device support (kernel module not loaded): `sudo modprobe tun`
- Config file has YAML syntax errors
- Old version (v0.4.0-dev) has a known crash bug — upgrade to v0.4.1
- Permissions: ensure `/etc/fips/fips.yaml` is mode 0600

**Fix:**
```bash
# Reload and restart
sudo systemctl daemon-reload
sudo systemctl restart fips

# If still failing, re-run Ansible
ansible-playbook 13-fips.yml -l <host>
```

### 5.2 No Peers Connected

**Symptoms:** `fipsctl show peers` shows 0 connected peers

**Diagnostics:**
```bash
# Check if the peer's npub is in config
grep npub /etc/fips/fips.yaml

# Check if the peer is in /etc/fips/hosts
cat /etc/fips/hosts

# Check network connectivity to peer's IP
ping <peer_ip>

# Check if UDP 2121 / TCP 8443 is reachable
nc -zv <peer_ip> 2121
nc -zv <peer_ip> 8443

# Check Nostr relay connectivity
curl -s -o /dev/null -w "%{http_code}" https://relay.damus.io

# Check if STUN resolution works (NAT traversal)
# FIPS logs STUN results on startup
journalctl -u fips --no-pager | grep -i stun
```

**Common causes:**
- Peer is behind NAT and STUN failed — ensure STUN servers are reachable
- Nostr relay is down — discovery can't find the peer's advertised endpoint
- Peer's IP changed — update the peer address in config
- Firewall blocking UDP 2121 / TCP 8443 — check UFW/iptables/nftables
- Config drift — manually edited config doesn't match Ansible-managed state

**Fix:**
```bash
# Redeploy config via Ansible
ansible-playbook 13-fips.yml -l <host>

# Or manually restart FIPS after fixing config
sudo systemctl restart fips

# Wait for discovery + connection (can take 30-60s)
sleep 30 && sudo fipsctl show peers
```

### 5.3 .fips DNS Not Resolving

**Symptoms:** `dig @::1 -p 5354 vps2.fips AAAA +short` returns empty

**Diagnostics:**
```bash
# Check fips-dns service
systemctl status fips-dns

# Check if fips-dns is listening
ss -lunp | grep 5354

# Check /etc/fips/hosts has entries
cat /etc/fips/hosts

# Check systemd-resolved integration
resolvectl status | grep fips

# Check if fips-dns-setup was run
ls -la /usr/lib/fips/fips-dns-setup
```

**Common causes:**
- `fips-dns` service not started or not enabled
- `fips-dns-setup` not run (systemd-resolved doesn't route .fips queries)
- `/etc/fips/hosts` is empty or missing the target hostname
- Peer is not connected (DNS can't resolve a npub with no mesh IPv6)

**Fix:**
```bash
# Enable and start fips-dns
sudo systemctl enable --now fips-dns

# Run fips-dns-setup to integrate with systemd-resolved
sudo /usr/lib/fips/fips-dns-setup
sudo systemctl restart systemd-resolved

# Redeploy via Ansible
ansible-playbook 13-fips.yml -l <host>
```

### 5.4 SSH Over FIPS Fails

**Symptoms:** `ssh user@host.fips` times out or connection refused

**Diagnostics:**
```bash
# Verify DNS resolves
dig @::1 -p 5354 <host>.fips AAAA +short

# Verify peer is connected
sudo fipsctl show peers

# Verify fips0 interface is up
ip link show fips0

# Check nftables SSH rule is loaded
sudo nft list table inet fips-ssh

# Check SSH daemon is running on target
# (SSH from another method like Netbird or direct IP)
ssh <user>@<target_ip> systemctl status sshd
```

**Common causes:**
- DNS not resolving (see §5.3)
- Peer not connected (see §5.2)
- `ssh.nft` rule not loaded — reload nftables
- SSH daemon not listening on fips0 interface
- SSH keys not authorized on target machine

**Fix:**
```bash
# Reload nftables rule
sudo nft -f /etc/fips/fips.d/ssh.nft

# Redeploy via Ansible
ansible-playbook 13-fips.yml -l <host>

# Distribute SSH keys if needed
ssh-copy-id -i ~/.ssh/id_ed25519.pub <user>@<target_ip>
```

### 5.5 Config Drift (Manual Edits)

**Symptoms:** Ansible `--check` mode reports changes on a machine that was
supposedly already configured.

**Cause:** Someone manually edited `/etc/fips/fips.yaml` instead of using
Ansible. DQ05 had this problem — the config was hand-edited to use the old
test-us03 peer.

**Fix:**
```bash
# Back up the manual config
sudo cp /etc/fips/fips.yaml /etc/fips/fips.yaml.bak.$(date +%Y%m%d-%H%M%S)

# Let Ansible overwrite with the managed config
ansible-playbook 13-fips.yml -l <host>

# Verify
ansible-playbook 13-fips.yml -l <host> --check
# Should report no changes
```

### 5.6 Bloom Filter Saturation (Public Mesh)

**Symptoms:** Excessive connection attempts, high CPU/memory usage, slow
discovery on a node connected to the public test mesh.

**Cause:** FIPS v0.4.1 uses static bloom filter sizes. The public mesh has
hundreds of nodes, saturating the filters with false positives.

**Fix:** Switch to a private mesh (already done in this deployment). Ensure
no public test mesh nodes (test-usXX) remain in any config or hosts file:

```bash
grep -r "test-us" /etc/fips/
# Should return nothing
```

### 5.7 FIPS Version Mismatch

**Symptoms:** Peers fail to connect, protocol errors in logs.

**Diagnostics:**
```bash
# Check version on each machine
sudo fipsctl show status | grep -i version

# Or check the installed package
dpkg -l | grep fips
```

**Fix:** Ensure all machines are on the same version (0.4.1):

```bash
ansible-playbook 13-fips.yml -l <host>
# This will download and install the correct version
```

### 5.8 Useful Log Commands

```bash
# FIPS daemon logs
journalctl -u fips -n 100 --no-pager

# fips-dns logs
journalctl -u fips-dns -n 50 --no-pager

# fips-firewall logs
journalctl -u fips-firewall -n 50 --no-pager

# All FIPS-related logs
journalctl -u fips -u fips-dns -u fips-firewall --since "1 hour ago"

# Follow logs in real-time
journalctl -u fips -f
```

---

## 6. Reboot Procedures

### 6.1 Rebooting a Spoke Node (Laptop: DQ05, T14Gen5, T470)

Spoke nodes are laptops that peer to VPS2 (hub). Rebooting a spoke only
affects that machine's mesh connectivity — other nodes are unaffected.

**Steps:**
```bash
# 1. Verify mesh is healthy before reboot
sudo fipsctl show peers
# Record peer count for post-reboot comparison

# 2. Reboot
sudo reboot

# 3. After reboot, verify FIPS services auto-started
systemctl is-active fips fips-dns fips-firewall
# All three should report "active"

# 4. Wait for peer reconnection (30-60 seconds)
sleep 30
sudo fipsctl show peers
# Should show the same peers as before reboot

# 5. Verify DNS
dig @::1 -p 5354 vps2.fips AAAA +short

# 6. Verify SSH from another machine
ssh <user>@<rebooted_host>.fips
```

**If FIPS doesn't auto-start after reboot:**
```bash
# Check if services are enabled
systemctl is-enabled fips fips-dns fips-firewall
# All should report "enabled"

# If not, enable them
sudo systemctl enable fips fips-dns fips-firewall
sudo systemctl start fips fips-dns fips-firewall

# Or redeploy via Ansible
ansible-playbook 13-fips.yml -l <host>
```

### 6.2 Rebooting the Hub (VPS2)

**WARNING:** Rebooting VPS2 disconnects ALL spokes. No mesh traffic flows
while VPS2 is down. Plan reboots during low-usage windows.

**Steps:**
```bash
# 1. Notify all mesh users (if any active sessions)
# 2. Verify all spokes are connected
sudo fipsctl show peers

# 3. Reboot
sudo reboot

# 4. After VPS2 comes back (wait 1-2 minutes):
#    From a spoke machine:
ssh debian@vps2.fips
# Or via public IP:
ssh debian@23.182.128.51

# 5. Verify VPS2 FIPS is running
sudo fipsctl show status
sudo fipsctl show peers

# 6. Verify spokes reconnect (from each spoke):
sudo fipsctl show peers
# Should show vps2 connected

# 7. Verify exit node functionality (if VPS2 is an exit node)
curl --socks5 [vps2_fips_ipv6]:1080 https://example.com
```

**If VPS2 doesn't come back:**
- All spokes lose mesh connectivity
- Spokes can still reach each other via LAN discovery (if on same WiFi)
- Use Netbird or direct IP as fallback for SSH
- See §5.1 for FIPS startup troubleshooting on VPS2

### 6.3 Rebooting All Nodes (Full Mesh Restart)

Use this for FIPS upgrades or major config changes affecting all nodes.

**Steps:**
```bash
# 1. Reboot VPS2 first (hub)
ssh debian@23.182.128.51 sudo reboot

# 2. Wait for VPS2 to come back
sleep 120
ssh debian@23.182.128.51 systemctl is-active fips

# 3. Reboot each spoke (can be done in parallel)
ssh c03rad0r@100.90.22.201 sudo reboot  # DQ05
ssh c03rad0r@100.90.101.9 sudo reboot   # T470
# T14Gen5 is local:
sudo reboot

# 4. Wait for all nodes to come back
sleep 120

# 5. Verify all nodes from Ansible control machine
ansible-playbook 13-fips.yml --tags verify
```

### 6.4 Post-Reboot Verification Checklist

For any reboot, verify:

- [ ] `systemctl is-active fips fips-dns fips-firewall` → all active
- [ ] `fipsctl show status` → shows correct npub and version 0.4.1
- [ ] `fipsctl show peers` → shows expected peer count
- [ ] `dig @::1 -p 5354 vps2.fips AAAA +short` → returns mesh IPv6
- [ ] `ssh <user>@<host>.fips` → connects successfully
- [ ] `ip link show fips0` → interface is UP
- [ ] No errors in `journalctl -u fips -n 20`

---

## 7. ESP32 Status

### 7.1 Overview

ESP32 FIPS mesh support is developed in the **microFIPS** project
(`~/microfips/`), separate from the main FIPS daemon. The goal is to run
FIPS mesh on ESP32-C3 microcontrollers using ESP-NOW (peer-to-peer, no WiFi
AP hierarchy required).

**Current status:** Phase 0 (ESP-NOW transport) ~85% complete. Not yet
production-ready. No ESP32 nodes are part of the live private mesh.

### 7.2 What Works (as of 2026-07-09)

| Component                    | Status      | Notes                                          |
|------------------------------|-------------|------------------------------------------------|
| WiFi transport                | Done        | Noise handshake passes, 89 TX/RX on VPS1 interop|
| UART transport                | Done        | Compiles and flashes                            |
| USB transport                 | Done        | Compiles and flashes                            |
| ESP-NOW transport code       | ~85%        | 396 lines FFI, compiles clean, LED blink works  |
| MAC-to-node-address mapping   | On branch   | `feat/mac-mapping` — not merged into main      |
| Noise IK handshake            | Done        | Working with VPS1 interop                       |
| Noise XX migration            | In progress | PR #132                                         |
| FMP message handling          | Done        | Msg3 variant fixed                              |
| Monitoring crons              | Active      | Interop test, VPS1 health, auto-heal            |

### 7.3 What's Blocked

| Blocker                       | Impact      | Next step                                     |
|-------------------------------|-------------|-----------------------------------------------|
| ESP-NOW binary doesn't link   | Critical    | Use espflash as build tool; fix ESP-IDF FFI   |
| No erasure coding / pipeline  | High        | Port erasure.c from balloon-fresh (325 lines)  |
| No routing layer (STP/bloom)  | High        | Implement FIPS STP + bloom filters on MCU     |
| No firmware on physical ESP32 | High        | No firmware running since July 7th             |
| ESP-NOW MTU = 244 bytes       | Design      | FIPS frames up to 2048 bytes need fragmentation|
| Broken crons                   | Low         | fips-exit-smoke-daily needs conda path fix     |

### 7.4 ESP32 Hardware Constraints

- **RAM:** 48KB heap available for DRAM2
- **Flash:** 4MB (partitioned for LittleFS relay storage)
- **WiFi MAC blacklist:** Wrong WiFi password causes ESP32 to DDoS router
- **Log crate:** riscv32 lacks atomic ptr — must use `_racy` log variants
- **MTU:** ESP-NOW max payload 244 bytes (6-byte header) vs FIPS 2048-byte frames

### 7.5 Implementation Plan Phases

| Phase | Description                    | Est. Time  | Status    |
|-------|--------------------------------|------------|-----------|
| 0     | ESP-NOW transport              | 2-3 days   | ~85%      |
| 1     | Pipeline (fragmentation + erasure) | 3-4 days | 0%        |
| 2     | Routing (STP + bloom filters)   | 3-4 days   | ~10%      |
| 3     | Hardening (MTU, reliability)    | 2-3 days   | 0%        |
| 4     | Integration (multi-hop, 24h test) | 2-3 days | 0%       |

### 7.6 ESP32 Mesh vs Private Mesh Relationship

The ESP32 mesh (microFIPS) is a **separate effort** from the private FIPS
mesh (VPS2 hub + laptops). The private mesh uses the main FIPS daemon on
x86_64 Linux. The ESP32 mesh targets microcontrollers running a leaner
Rust implementation with ESP-NOW transport.

**Future integration:** Once microFIPS reaches Phase 4 (integration), ESP32
nodes could join the private mesh as additional peers. This requires:
- Erasure coding for frame size adaptation (244 bytes → 2048 bytes)
- Routing layer (STP + bloom filters) for multi-hop
- Noise handshake completion over ESP-NOW
- npub registration in `/etc/fips/hosts` on all mesh nodes

### 7.7 ESP32 Tollgate Firmware (Separate Project)

The `esp32-tollgate` project (`~/esp32-tollgate/`) is a separate ESP32-S3
firmware for the Tollgate captive portal hotspot (WiFi payments via Cashu).
It does NOT participate in the FIPS mesh — it's a standalone WiFi access
point with local Nostr relay and Cashu wallet. Three boards are in use:

| Board | MAC               | SSID               | AP IP          |
|-------|-------------------|--------------------|----------------|
| A     | 94:a9:90:2e:37:7c | TollGate-B96D80    | 10.185.47.1    |
| B     | fc:01:2c:c5:50:50 | TollGate-C0E9CA    | 10.192.45.1    |
| C     | 20:6e:f1:98:d7:08 | (TBD)              | (TBD)          |

### 7.8 FIPS Exit Gate (Related Project)

The `fips-exit-gate` project (`~/fips-exit-gate/`) provides **outbound**
internet exit service for FIPS mesh clients — SOCKS5 egress with prepaid
data packages, captive portal for unauthorized users, and per-client
metering via nftables. This is complementary to the FIPS ingress gate
(public internet → VPS2 → FIPS mesh for inbound hosting).

---

## 8. Daily Operations Cheat Sheet

### 8.1 Health Check (All Nodes)

```bash
# From Ansible control machine
ansible all -m shell -a "fipsctl show status" 2>/dev/null
ansible all -m shell -a "fipsctl show peers" 2>/dev/null
ansible all -m shell -a "systemctl is-active fips fips-dns fips-firewall" 2>/dev/null
```

### 8.2 Quick SSH Over FIPS

```bash
# Add to ~/.ssh/config for convenience:
# Host *.fips
#     User c03rad0r
#     StrictHostKeyChecking no
#     UserKnownHostsFile /dev/null

ssh dq05.fips
ssh t14gen5.fips
ssh debian@vps2.fips
ssh t470.fips
```

### 8.3 Redeploy Config to All Nodes

```bash
cd ~/tollgate-infrastructure-kit
ansible-playbook ansible/playbooks/13-fips.yml
```

### 8.4 Redeploy to Single Node

```bash
# DQ05
ansible-playbook ansible/playbooks/13-fips.yml -l dq05

# VPS2
ansible-playbook ansible/playbooks/13-fips.yml -l vps2

# T14Gen5 (local)
ansible-playbook ansible/playbooks/13-fips.yml -l t14gen5

# T470
ansible-playbook ansible/playbooks/13-fips.yml -l t470
```

### 8.5 Check for Config Drift

```bash
# Check mode — reports what would change without making changes
ansible-playbook ansible/playbooks/13-fips.yml --check
```

### 8.6 Verify Mesh DNS

```bash
# From any mesh node
dig @::1 -p 5354 vps2.fips AAAA +short
dig @::1 -p 5354 dq05.fips AAAA +short
dig @::1 -p 5354 t14gen5.fips AAAA +short
dig @::1 -p 5354 t470.fips AAAA +short
dig @::1 -p 5354 andre.fips AAAA +short
```

### 8.7 Emergency: Mesh Down (VPS2 Unreachable)

If VPS2 is down and all spokes lose connectivity:

1. **Don't panic** — spokes can still reach each other via LAN discovery
   (if on same WiFi) or Netbird (if configured)
2. **Check VPS2 via public IP:**
   ```bash
   ssh debian@23.182.128.51
   # If unreachable, VPS2 is down — contact VPS provider
   ```
3. **If VPS2 is up but FIPS is down:**
   ```bash
   ssh debian@23.182.128.51
   sudo systemctl restart fips fips-dns fips-firewall
   sudo fipsctl show status
   ```
4. **If VPS2 needs redeployment:**
   ```bash
   ansible-playbook ansible/playbooks/13-fips.yml -l vps2
   ```

### 8.8 References

- **FIPS releases:** https://github.com/jmcorgan/fips/releases
- **FIPS source:** `~/fips/` (jmcorgan/fips)
- **microFIPS (ESP32):** `~/microfips/`
- **FIPS exit gate:** `~/fips-exit-gate/`
- **Ansible role:** `ansible/roles/fips/`
- **Playbook:** `ansible/playbooks/13-fips.yml`
- **Inventory:** `ansible/inventory/hosts.yml`
- **Setup plan:** `PLAN-FIPS-MESH-SETUP.md`
- **Deployment plan:** `docs/FIPS-MESH-DEPLOYMENT-PLAN.md`
- **Ingress gate:** `docs/FIPS-INGRESS-GATE.md`
- **Hosting plan:** `docs/fips-hosting-plan.md`
- **General troubleshooting:** `docs/troubleshooting.md`