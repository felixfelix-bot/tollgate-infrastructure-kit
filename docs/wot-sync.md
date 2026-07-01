# WoT Sync — kind-3 follow list → Blossom + grasp-mirror

The root npub's kind-3 (contact list) is the single source of truth for the
Web of Trust. `strfry-agg-reconcile` (role `strfry_agg`) fetches it every
15 min and writes `/opt/tollgate/strfry-agg/state/allowed.npubs` — a sorted
list of lowercase hex pubkeys. The `wot_sync` role deploys two consumers of
that allowlist so storage and mirroring track the follow list automatically.

## What it deploys

### 1. blossom-wot-enforce  (tag: `blossom_wot`)

A Python oneshot (`/usr/local/bin/blossom-wot-enforce`) that:

1. Reads `allowed.npubs` (the already-reconciled allowlist — it does **not**
   re-fetch kind-3).
2. Queries the Blossom SQLite DB (`owners` + `blobs` tables).
3. Deletes blobs whose owners are **all** outside the allowlist. A blob
   shared between a non-WoT and a WoT npub is **kept** (multi-owner safe).
4. Cleans orphaned rows in `accessed`, `media_derivatives`, `reports`, then
   unlinks the physical blob files.
5. Refuses to run on an empty allowlist (would delete everything).

Timer: `blossom-wot-enforce.timer` fires at `*:7/15` (07, 22, 37, 52 min
past) — offset 7 min after the reconcile timer (`*:0/15`) so the allowlist
is freshly written.

### 2. grasp-mirror-sync  (tag: `grasp_wot`)

A Python oneshot (`/usr/local/bin/grasp-mirror-sync`) that:

1. Reads the local `allowed.npubs` if present (fast path — zero network).
   Falls back to fetching the root npub's kind-3 from the bootstrap relays
   and extracting `p` tags (used when the allowlist is on another host).
2. Converts hex pubkeys → bech32 npubs.
3. Rewrites `MIRROR_NPUBS=...` in the grasp-mirror env file, preserving
   other lines.
4. Restarts `grasp-mirror.service` **only** when the set changed.

Timer: `grasp-mirror-sync.timer` fires every 30 min at `*:12/30`.

## Architecture

```
                 kind-3 (root npub)
                        │
          strfry-agg-reconcile  (every 15 min, role: strfry_agg)
                        │
                        ▼
              allowed.npubs  (hex, ~1300 pubkeys)
                  ┌─────────┴──────────┐
                  ▼                    ▼
        blossom-wot-enforce     grasp-mirror-sync
         (every 15 min,         (every 30 min,
          :07 offset)            :12 offset)
                  │                    │
                  ▼                    ▼
        purges Blossom blobs    rewrites MIRROR_NPUBS
        from non-WoT npubs      + restarts daemon
```

## Deploy

The role is included in `setup-vps-1.yml` (both blossom and grasp-mirror
live on vps1), so a standard deploy picks it up:

```bash
ansible-playbook ansible/playbooks/setup-vps-1.yml
```

Targeted redeploy of one mechanism:

```bash
# Blossom only
ansible-playbook ansible/playbooks/40-wot-sync.yml -l vps1 --tags blossom_wot
# grasp-mirror only
ansible-playbook ansible/playbooks/40-wot-sync.yml -l vps1 --tags grasp_wot
```

## Verify

```bash
# Dry-run blossom enforcement (no writes)
sudo /usr/local/bin/blossom-wot-enforce --dry-run -v

# Dry-run grasp-mirror sync (no writes / no restart)
sudo /usr/local/bin/grasp-mirror-sync --dry-run -v

# Timer status
systemctl list-timers blossom-wot-enforce.timer grasp-mirror-sync.timer
systemctl status blossom-wot-enforce.service   # last run output in journal
journalctl -u blossom-wot-enforce.service -n 20 --no-pager
```

## Configuration (role defaults)

| Variable | Default | Purpose |
|---|---|---|
| `wot_sync_allowed_path` | `/opt/tollgate/strfry-agg/state/allowed.npubs` | allowlist (single source of truth) |
| `wot_sync_blossom_db` | `…/blossom_blossom-data/_data/blossom.db` | Blossom SQLite DB |
| `wot_sync_blossom_blobs` | `…/blossom_blossom-data/_data/blobs` | blob file dir |
| `wot_sync_blossom_offset_min` | `7` | minutes after reconcile |
| `wot_sync_grasp_env_file` | `/opt/tollgate/grasp-mirror/grasp-mirror.env` | daemon env to rewrite |
| `wot_sync_grasp_service` | `grasp-mirror` | systemd unit to restart |
| `wot_sync_root_npub` | `npub1c03rad0r…` | root npub for kind-3 fetch fallback |
| `wot_sync_relays` | `damus.io`, `nos.lol` | bootstrap relays for kind-3 fallback |
| `wot_sync_install_websockets` | `true` | install `python3-websockets` for the fetch fallback |

## Relationship to the manager-side cleanup

`~/.hermes/…/blossom_wot_cleanup.py` (manager profile cron) does similar
work but runs **remotely** over SSH from the dev box. `blossom-wot-enforce`
replaces it with a **local** VPS systemd timer — lower latency, no SSH
overhead, no password in env. Once `wot_sync` is deployed, the manager-side
cron becomes redundant and can be disabled.
