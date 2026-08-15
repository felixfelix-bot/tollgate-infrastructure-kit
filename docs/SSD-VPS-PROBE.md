# T5.1 SSD VPS Dual-Vantage Probe

Probe cron for 64.188.7.38 + 66.92.204.38 (down since Aug 14): ICMP + TCP:22 every 1min from >=2 vantages (this box + VPS2). On first success: auto-notify manager + set V2-11 ready.

## Overview

This component implements the T5.1 task from PLAN-v2-remediation.md:
- Continuously probes both SSD VPS IPs from multiple vantage points
- Detects when both ICMP ping and TCP port 22 respond
- Requires confirmation from >=2 vantages before triggering notification
- Auto-notifies manager and sets V2-11 task to ready on first success

## Architecture

```
┌─────────────────┐     ┌─────────────────┐
│   This Box      │     │     VPS2        │
│ (CobradorWave)  │     │  (23.182.128.51)│
│                 │     │                 │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │ Probe Cron│  │     │  │ Probe Cron│  │
│  │ (1/min)   │  │     │  │ (1/min)   │  │
│  └─────┬─────┘  │     │  └─────┬─────┘  │
│        │        │     │        │        │
│        ▼        │     │        ▼        │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │ 64.188.   │  │     │  │ 64.188.   │  │
│  │ 7.38      │  │     │  │ 7.38      │  │
│  │ (ICMP+22) │  │     │  │ (ICMP+22) │  │
│  └───────────┘  │     │  └───────────┘  │
│        │        │     │        │        │
│        ▼        │     │        ▼        │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │ 66.92.    │  │     │  │ 66.92.    │  │
│  │ 204.38    │  │     │  │ 204.38    │  │
│  │ (ICMP+22) │  │     │  │ (ICMP+22) │  │
│  └───────────┘  │     │  └───────────┘  │
│        │        │     │        │        │
│        ▼        │     │        ▼        │
│  ┌───────────┐  │     │  ┌───────────┐  │
│  │ State Log │◄─┼─────┼──┤ State Log │  │
│  │ (shared)  │  │     │  │ (shared)  │  │
│  └─────┬─────┘  │     │  └───────────┘  │
│        │        │     └─────────────────┘
│        ▼        │
│  ┌───────────┐  │
│  │ Dual-Vant │  │
│  │ Detect    │  │
│  └─────┬─────┘  │
│        │        │
│        ▼        │
│  ┌───────────┐  │
│  │ Notify    │  │
│  │ Manager   │  │
│  └───────────┘  │
└─────────────────┘
```

## Files

### Scripts
- `scripts/ssd-vps-probe.sh` - Main probe script with simulate mode
- `scripts/ssd-vps-probe.service` - systemd service unit
- `scripts/ssd-vps-probe.timer` - systemd timer (1/min)

### Ansible Role
- `ansible/roles/ssd_vps_probe/` - Full Ansible role for deployment
  - `tasks/main.yml` - Installation tasks
  - `defaults/main.yml` - Default variables
  - `handlers/main.yml` - Service reload handlers
  - `templates/*.j2` - Jinja2 templates

### Playbook
- `ansible/playbooks/50-ssd-vps-probe.yml` - Deployment playbook

### Tests
- `tests/test-ssd-vps-probe.sh` - Test suite with simulate mode

## Usage

### Manual Testing (Simulate Mode)

Test the dual-vantage detection logic without waiting for real IPs:

```bash
# Run simulate mode (uses 127.0.0.1 as test target)
./scripts/ssd-vps-probe.sh simulate

# Check status
./scripts/ssd-vps-probe.sh status

# Clean up test state
./scripts/ssd-vps-probe.sh cleanup
```

### Deployment

Deploy to this box (CobradorWave):

```bash
cd ansible
ansible-playbook -i localhost, -c local playbooks/50-ssd-vps-probe.yml
```

Deploy to VPS2:

```bash
cd ansible
ansible-playbook -i vps2, playbooks/50-ssd-vps-probe.yml
```

### Verification

```bash
# Check timer status
systemctl status ssd-vps-probe.timer

# View logs
journalctl -u ssd-vps-probe -f
tail -f /var/log/ssd-vps-probe.log

# Check probe state
cat /var/lib/ssd-vps-probe/64_188_7_38.log
cat /var/lib/ssd-vps-probe/66_92_204_38.log
```

## State Files

- `/var/lib/ssd-vps-probe/64_188_7_38.log` - Probe history for 64.188.7.38
- `/var/lib/ssd-vps-probe/66_92_204_38.log` - Probe history for 66.92.204.38
- `/var/lib/ssd-vps-probe/64_188_7_38.notified` - Notification flag (created after first dual-vantage success)
- `/var/lib/ssd-vps-probe/66_92_204_38.notified` - Notification flag
- `/var/lib/ssd-vps-probe/notifications.log` - Notification history

## Probe Logic

1. Every minute, probe both target IPs
2. For each IP: send ICMP ping + TCP connect to port 22
3. Record result with timestamp and vantage ID
4. Check if >=2 vantages reported success in last 2 minutes
5. If dual-vantage success and not yet notified:
   - Log notification
   - Attempt to notify via hermes kanban comment
   - Attempt to unblock V2-11 task
   - Create .notified flag to prevent duplicate notifications

## Integration with Kanban

When dual-vantage success is detected:
1. Logs to `/var/log/ssd-vps-probe.log`
2. Attempts `hermes kanban comment <task_id>` if available
3. Attempts `hermes kanban unblock <task_id>` if available
4. Persists notification state to prevent duplicates

## Security

- Runs as root (required for ICMP ping)
- systemd service uses security hardening:
  - `NoNewPrivileges=true`
  - `ProtectSystem=strict`
  - `ProtectHome=true`
  - Read-only paths for scripts
  - Read-write only for state/log directories

## Notes

- IPs 64.188.7.38 and 66.92.204.38 have been down since Aug 14
- Provider escalation ticket filed separately
- Operator checks provider console Aug 16 lunch
- Do not lease anything without manager approval
