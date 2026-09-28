# VPS2 Load Alert Ladder + Sample History (T4.2)

Branch `hermes-v2/monitoring` · script `scripts/hermes-health-check.sh` · cron `*/5 * * * *`

## Why

On Aug 14 VPS2 (23.182.128.51, hostname `testserver2`) reached load 120 with
nobody noticing until SSH wedged (§1.4 of PLAN-v2-remediation.md). Root cause
analysis after the fact was impossible: **no sample history existed**. This
deploy fixes both gaps: an early-warning ladder that fires long before
catastrophe, and 5-minute persisted samples so the next post-mortem has data.

## Alert ladder

| Level | Load (15-min avg) | Disk (`/` used) | RAM (available) | Swap (free) | Pushes repeat |
|---|---|---|---|---|---|
| warn | > 8 | > 85% | < 10% | < 10% | every 6 h |
| page | > 15 | > 95% | < 5% | < 2% | every 30 min |
| meltdown | > 30 | — | — | — | every 10 min |

- Thresholds are strictly greater (load 8.0 is `ok`, 8.1 is `warn`).
- Escalation (warn→page→meltdown) pushes immediately regardless of window.
- The box has 2 cores: load 8 = 4× oversubscription, load 30 = 15×.
- Container/gateway failures (V2-10 checks) page; optional services (buzz
  relay, routstr) only warn.
- Exit codes: 0 = ok/warn, 1 = page, 2 = meltdown, 3 = delivery failure.
  All overrides via `/etc/default/hermes-health-check` (file wins over env):
  `LOAD_WARN LOAD_PAGE LOAD_MELTDOWN DISK_MOUNT DISK_WARN_PCT DISK_PAGE_PCT
  RAM_WARN_PCT RAM_PAGE_PCT SWAP_WARN_PCT SWAP_PAGE_PCT NTFY_URL
  REPEAT_WARN REPEAT_PAGE REPEAT_MELTDOWN`.

## Delivery channel

Alerts always land in `/var/log/hermes-health-check.alert` (post-mortem
trail). If `NTFY_URL` is set, each alert is also pushed to that ntfy topic
([ntfy.sh](https://ntfy.sh) or self-hosted) — this is the out-of-band pager
channel that works even when Docker/SSH are dying, as long as the network
stack is up. The topic URL acts as the credential and lives only in
`/etc/default/hermes-health-check` (mode 0600) on the box — never in git.

Subscribe on a phone/desktop: open `https://ntfy.sh/<topic>` or the ntfy app
and subscribe to the topic (get it from the box: `grep NTFY_URL
/etc/default/hermes-health-check`).

Fire a synthetic alert and confirm end-to-end delivery:

```bash
/opt/tollgate/scripts/hermes-health-check.sh --test-alert
curl -s "https://ntfy.sh/<topic>/json?poll=1"   # message must appear here
```

## Sample history (post-mortem fuel)

| Tool | Cadence | Data | Location | Retention |
|---|---|---|---|---|
| sysstat/sar | 5 min | system: load, cpu, mem, swap, disk | `/var/log/sysstat/saDD` | 28 days |
| atop | 5 min | **per-process** cpu/mem | `/var/log/atop/atop_YYYYMMDD` | 28 days |

Reading the history (what T4.3 will use):

```bash
sar -q -f /var/log/sysstat/sa14        # load/runq on the 14th
sar -r -f /var/log/sysstat/sa14        # memory pressure timeline
atop -r /var/log/atop/atop_20260814    # replay: t/G to step, P = per-process
```

Provisioned by `ansible/roles/hermes_tenants/tasks/monitoring.yml`:
`sysstat` (`ENABLED=true`, `HISTORY=28`, timer drop-in
`OnUnitActiveSec=5min`) and `atop` (`LOGINTERVAL=5`, `LOGGENERATIONS=28`).

## Deployment

Ansible (idempotent): role `hermes_tenants` include `monitoring.yml`,
override `hermes_health_ntfy_url` (e.g. `-e` or host_vars — not committed).
The role also removes the legacy `/opt/tollgate/hermes/monitor.sh` cron that
still watched pre-rename containers (`hermes-ours/friend1/friend2`) and
alerted into a dead log every 5 minutes.

## Live findings on VPS2 at deploy time (Aug 15, input for T4.3)

The first live run correctly paged on all of these — evidence the ladder
surfaces real conditions, not just load:

- **`/` at 99%** (1.2G free of 99G) — the pre-existing legacy monitor had
  been logging this into a dead file for days.
- **All three gateway `/health` checks fail**: containers report `healthy`,
  but the docker healthcheck is still the fake `pgrep -f 'hermes gateway
  run'` (the D3 anti-pattern). Inside the containers nothing listens on the
  mapped ports (8080→900x, 9000→910x); gateway-default died after a
  non-retryable z.ai **HTTP 401 "token expired"** abort at 15:55 Aug 14 and
  s6-supervise kept the flag green. The LLM leg is down for all tenants.
- **`sleep infinity` still runs** inside the containers (PID 103) — the
  V2-04 compose entrypoint fix never converged to the live box.
- Docker-proxy accepts TCP on 900x/910x then never answers (wedged-backend
  signature) — HTTP probes, not TCP connects, are the honest signal.

These are convergence work (V2-12 / T2.x), not monitoring work — recorded
here because the alert ladder is what surfaced them.

