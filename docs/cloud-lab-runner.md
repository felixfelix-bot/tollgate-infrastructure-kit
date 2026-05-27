# Cloud Lab Runner

Ansible role that prepares a VPS for running TollGate API tests using QEMU/KVM nested virtualization.

## Related Repos

- **Test Automation** (test suite + cloud lab CLI): [ngit](nostr://npub12m5exm2uk3xa674cc5r0hlyvccs5xxn7qv83ezuteefv5972nquq4j4szl/ngit.orangesync.tech/physical-router-test-automation) | [GitHub](https://github.com/OpenTollGate/physical-router-test-automation)

## Overview

This role installs everything needed to run the TollGate cloud lab test suite on your VPS. The cloud lab boots QEMU virtual machines (OpenWrt router + Debian client), deploys TollGate, runs the API test suite, and publishes results to gh-pages.

## Requirements

- A VPS with KVM/nested virtualization support
- Debian 12 (bookworm) or Debian 13 (trixie)
- Minimum 4GB RAM, 20GB disk
- The `cloud_lab_runner_enabled` variable must be `true`

## Enabling

Add to your `.env`:

```bash
echo "cloud_lab_runner_enabled=true" >> .env
```

Then deploy:

```bash
make deploy
```

Or run only the cloud lab role:

```bash
ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/setup-all.yml \
  --tags cloud_lab_runner
```

## What It Installs

### Packages

- `qemu-system-x86` — QEMU/KVM hypervisor
- `qemu-utils` — `qemu-img` for disk image management
- `iproute2`, `bridge-utils`, `iptables` — networking for virtual lab bridge
- `python3-venv`, `python3-pip` — Python environment
- `sshpass` — automated SSH for test provisioning
- `git`, `curl`, `jq` — general utilities

### Directory Structure

```
~/tollgate-virtual-lab/
├── images/
│   ├── openwrt-base.qcow2          # OpenWrt x86_64 base image
│   └── debian-12-nocloud-amd64.qcow2  # Debian nocloud base image
├── overlays/                        # Per-run copy-on-write disks (auto-managed)
├── run/                             # QEMU PID files, serial/monitor sockets
```

### Test Suite Checkout

```
/opt/tollgate-test/                  # Cloned from GitHub (read by worker)
/opt/tollgate-venv/                  # Python venv with pytest + test deps
```

## Configuration Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `cloud_lab_runner_enabled` | `false` | Must be `true` to install anything |
| `cloud_lab_workdir` | `~/tollgate-virtual-lab` | Base directory for VM images |
| `cloud_lab_openwrt_version` | `24.10.1` | OpenWrt version to download |
| `cloud_lab_debian_disk_size` | `10G` | Debian overlay disk size |
| `cloud_lab_bake_playwright` | `false` | Pre-install Playwright in Debian overlay |

## Running Tests

See the [physical-router-test-automation docs](https://github.com/OpenTollGate/physical-router-test-automation/blob/main/docs/vps-cloud-lab.md) for full usage instructions.

Quick start:

```bash
export TOLLGATE_VPS_HOST=your.vps.ip
cd physical-router-test-automation
./scripts/cloud-lab.py --provider vps submit --pr 42 --publish
```

## Updating Images

To re-download base images (e.g., when a new OpenWrt version is released):

```bash
ssh root@$VPS_IP "rm ~/tollgate-virtual-lab/images/openwrt-base.qcow2"
# Re-run the Ansible role
make deploy
```

The Debian overlay is NOT reset between test runs (Playwright cache is preserved). OpenWrt overlays are recreated fresh each run.

## Checking KVM Support

```bash
ssh root@$VPS_IP "egrep -c '(vmx|svm)' /proc/cpuinfo"
```

- `0`: No KVM. QEMU will use software emulation (very slow, ~10x slower)
- `1+`: KVM available. Tests run at near-native speed
