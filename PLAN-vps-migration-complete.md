# VPS Migration Plan: Complete Cutover to New VPS (23.182.128.226)

## Current State

### Old VPS (23.182.128.51) — `testserver2`
- 99GB disk (79% full), 8GB RAM, KVM enabled
- All services running: Caddy, strfry, obelisk, blossom, nsite-gateway, ngit, GRASP (21GB), routstr, relatr, 7 mints, act-runner, syncthing
- DNS partially points here (blossom, git, vote, ngit, most mints)

### New VPS (23.182.128.226) — Debian 13
- 504GB disk (4% used), 4GB RAM, NO KVM
- Running: Caddy, strfry, obelisk, blossom, nsite-gateway, ngit, mint-test-mb, mint-routstr-mint, test-market, test-relay
- Missing: GRASP, routstr, relatr, 5 mints, act-runner, syncthing, cashu-brrr, fips, nsyte
- DNS partially points here (relay, chat, nsite, releases, ci, workshop, runner, solix, services)

### DNS Split (needs unification)
| Points to old (51) | Points to new (226) | Points to neither (64) |
|---|---|---|
| blossom, git, vote, ngit, test-mb/kb/gb/min.mints, testnut-cdk/nutshell.mints, routstr-mint.mints | relay, chat, nsite, releases, ci, workshop, runner, solix, services, testnut-compat.mints | dashboard.mints, print.mints |

---

## Phase 0: Create zram Ansible Role (NEW)

### 0.1 Create `ansible/roles/zram/`
- `defaults/main.yml`: zram_size (default: 50% of RAM), zram_algorithm (zstd), zram_swappiness (180)
- `tasks/main.yml`:
  1. Install `zram-config` via apt
  2. Set `vm.swappiness=180` via sysctl
  3. Verify zram devices exist (`/proc/swaps`, `zramctl`)
  4. Start/enable `zram-config` service

### 0.2 Add to `setup-all.yml` as playbook `00-zram.yml` (before 01-system)
- Runs on all hosts (VPS, backup machine, future machines)
- Should be idempotent (safe to run on machines that already have zram)

---

## Phase 1: Data Migration (Old VPS → New VPS)

The critical irreplaceable data:

| Data | Path | Size | How to Transfer |
|---|---|---|---|
| GRASP git repos + LMDB | `/opt/tollgate/grasp/data/` | 21GB | rsync over SSH |
| GRASP relay owner nsec | `/opt/tollgate/grasp/.relay-owner.nsec` | 63B | rsync |
| Routstr SQLite DB | `/opt/tollgate/routstr/data/` | 156K | rsync |
| Routstr nsec + conf | `/opt/tollgate/routstr/routstr.conf` | 184B | rsync |
| Routstr Tor onion key | `/opt/tollgate/routstr/tor-data/` | 59MB | rsync |
| Mint keys (7 mints) | `/opt/tollgate/mints/*/mint_key` | ~600B | rsync |
| Mint databases | `/opt/tollgate/mints/*/data/` | small | rsync |
| Mint registry | `/opt/tollgate/mints/registry.json` | ~1K | rsync |
| Act-runner build DB | `/opt/tollgate/act-runner/builds.db` | varies | rsync |
| Caddy TLS certs | `/opt/tollgate/caddy/data/` | 8K | rsync (optional, re-issuable) |

**Total: ~21.1GB (dominated by GRASP)**

### 1.1 rsync all irreplaceable data from old → new
```bash
# From a machine with SSH access to both
rsync -avz --progress debian@23.182.128.51:/opt/tollgate/grasp/ debian@23.182.128.226:/opt/tollgate/grasp/
rsync -avz --progress debian@23.182.128.51:/opt/tollgate/routstr/ debian@23.182.128.226:/opt/tollgate/routstr/
rsync -avz --progress debian@23.182.128.51:/opt/tollgate/mints/ debian@23.182.128.226:/opt/tollgate/mints/
rsync -avz --progress debian@23.182.128.51:/opt/tollgate/act-runner/ debian@23.182.128.226:/opt/tollgate/act-runner/
rsync -avz --progress debian@23.182.128.51:/opt/tollgate/caddy/data/ debian@23.182.128.226:/opt/tollgate/caddy/data/
rsync -avz --progress debian@23.182.128.51:/var/log/tollgate/ debian@23.182.128.226:/var/log/tollgate/
```

### 1.2 Verify data integrity on new VPS
- Compare mint_key files (md5sum)
- Verify GRASP dir count matches (2196 repos)
- Verify routstr.conf nsec matches

---

## Phase 2: Deploy Missing Ansible Playbooks on New VPS

Run these playbooks in order. Each is already in the repo:

### 2.1 zram (NEW - Phase 0)
```bash
ansible-playbook -i inventory/hosts.yml playbooks/00-zram.yml
```

### 2.2 GRASP (builds Rust binary, needs 21GB data from Phase 1)
```bash
ansible-playbook -i inventory/hosts.yml playbooks/15-grasp.yml
```
- Builds ngit-grasp from source (~10min Rust compile on 4GB RAM)
- Data already present from rsync
- Needs `.relay-owner.nsec` in place

### 2.3 Deploy all test mints
```bash
ansible-playbook -i inventory/hosts.yml playbooks/deploy-test-mints.yml
```
- Deploys test-mb, test-kb, test-gb, test-min, testnut
- Mint keys already present from rsync (Ansible detects existing keys)
- Note: test-mb and routstr-mint already running, won't conflict

### 2.4 Routstr (needs data from Phase 1)
```bash
ansible-playbook -i inventory/hosts.yml playbooks/18-routstr.yml
```
- Deploys tollgate-routstr + tollgate-routstr-tor containers
- Config already present from rsync (nsec, domain)
- Includes dedicated routstr-mint (already running, idempotent)

### 2.5 cashu-brrr (frontend build, no data)
```bash
ansible-playbook -i inventory/hosts.yml playbooks/16-cashu-brrr.yml
```

### 2.6 mint-operator-proxy
```bash
ansible-playbook -i inventory/hosts.yml playbooks/17-mint-operator-proxy.yml
```

### 2.7 Act runner (needs builds.db from Phase 1)
```bash
ansible-playbook -i inventory/hosts.yml playbooks/27-act-runner.yml
```

### 2.8 GRASP mirror daemon
```bash
ansible-playbook -i inventory/hosts.yml playbooks/30-grasp-mirror.yml
```

### 2.9 Remaining playbooks that previously failed or were skipped
```bash
ansible-playbook -i inventory/hosts.yml playbooks/12-mptcp-server.yml   # timeout, retry
ansible-playbook -i inventory/hosts.yml playbooks/13-fips.yml            # needs FIPS_IDENTITY_NSEC
ansible-playbook -i inventory/hosts.yml playbooks/14-nsyte.yml           # CLI tool, should work
ansible-playbook -i inventory/hosts.yml playbooks/24-gitworkshop.yml     # previously failed
ansible-playbook -i inventory/hosts.yml playbooks/26-plebeian-market-test.yml
ansible-playbook -i inventory/hosts.yml playbooks/28-voting-worker.yml
ansible-playbook -i inventory/hosts.yml playbooks/29-auditable-voting-tests.yml
```

### 2.10 Static dashboard files
```bash
# Copy the enhanced dashboard
scp static/services/index.html debian@23.182.128.226:/srv/tollgate/services/
scp roles/backup/files/gen-backup-status.py debian@23.182.128.226:/usr/local/bin/
```

---

## Phase 3: Configure Syncthing on New VPS

### 3.1 Run syncthing playbook against new VPS
```bash
ansible-playbook -i inventory/hosts.yml playbooks/21-syncthing.yml
```
This playbook:
1. Installs + starts syncthing on new VPS
2. Configures backup machine peering
3. Creates all 6 sync folders

### 3.2 Update syncthing folder paths
The current `orangesync-grasp` folder on old VPS points to `/opt/tollgate/grasp/data/git` (live data).
On new VPS, it should point to the same path (data already rsynced).

### 3.3 Wait for initial sync
Syncthing will verify all files match between old VPS, new VPS, and backup machine.
This is fast since data is already present — just hash verification.

---

## Phase 4: DNS Cutover

### 4.1 Fix Cloudflare DNS playbook to UPDATE existing records
Current playbook only POSTs (creates). Need to add PATCH logic:
- GET existing records
- For each subdomain, PATCH the record to point to new IP
- This avoids duplicate records

### 4.2 Run DNS playbook with new VPS IP
```bash
VPS_IP=23.182.128.226 ansible-playbook -i inventory/hosts.yml playbooks/03-cloudflare-dns.yml
```
This updates all subdomains + wildcard `*.mints.orangesync.tech` → 23.182.128.226

### 4.3 Verify DNS propagation
```bash
for sub in relay chat blossom nsite git dashboard print releases ci vote ngit workshop runner solix services; do
  echo "$sub -> $(dig +short ${sub}.orangesync.tech A)"
done
echo "*.mints -> $(dig +short test-mb.mints.orangesync.tech A)"
```

---

## Phase 5: Verify All Services on New VPS

### 5.1 Check all Docker containers
```bash
ssh debian@23.182.128.226 "docker ps --format '{{.Names}}\t{{.Status}}' | sort"
```
Expected: ~20 containers running

### 5.2 Check all systemd services
```bash
ssh debian@23.182.128.226 "systemctl is-active ngit-grasp tollgate-act-runner syncthing@syncthing tollgate-backup.timer"
```

### 5.3 Test all service URLs via dashboard
Visit `https://services.orangesync.tech` — all dots should be green

### 5.4 Test backup status
```bash
ssh debian@23.182.128.226 "sudo python3 /usr/local/bin/gen-backup-status.py"
```

---

## Phase 6: Cleanup

### 6.1 Stop services on old VPS (NOT destroy)
```bash
ssh debian@23.182.128.51 "docker stop \$(docker ps -q)"
ssh debian@23.182.128.51 "sudo systemctl stop ngit-grasp tollgate-act-runner syncthing@syncthing"
```

### 6.2 Keep old VPS for 1 week as fallback
- Don't delete any data
- DNS TTL is 300s (5 min) so rollback is fast
- If new VPS has issues, just re-run DNS playbook with old IP

### 6.3 After 1 week, decommission old VPS
- Verify all data is on backup machine via syncthing
- Shut down old VPS

---

## Playbooks That Need Fixes Before Running

| Playbook | Issue | Fix |
|---|---|---|
| `03-cloudflare-dns` | Only creates records, can't update | Add PATCH for existing records |
| `12-mptcp-server` | Timeout waiting for port 65101 | May need longer timeout or skip (MPTCP may not be supported on new kernel) |
| `13-fips` | Needs `FIPS_IDENTITY_NSEC` env var | Check .env, may need to be added |
| `24-gitworkshop` | Failed on new VPS | Investigate and fix |
| `27-act-runner` | Times out (~20min for cargo build + venv) | Increase timeout |
| `relatr` | No playbook/role exists yet | Skip for now (planned future service) |

---

## Services NOT Migrating

| Service | Reason |
|---|---|
| `cloud_lab_runner` | No KVM on new VPS, software emulation too slow |
| `relatr` | Not yet implemented as Ansible role |
| `25-solix-nsite` | Previously failed, non-critical |

---

## Checklist

### Phase 0: zram Ansible Role
- [x] Create `ansible/roles/zram/defaults/main.yml`
- [x] Create `ansible/roles/zram/tasks/main.yml` (install zram-tools, sysctl swappiness, verify)
- [x] Create `ansible/playbooks/00-zram.yml`
- [x] Run `00-zram.yml` on new VPS — 1.9GB swap active
- [x] Run `00-zram.yml` on old VPS — 3.9GB swap active
- [ ] Run `00-zram.yml` on backup machine (blocked: needs passwordless sudo)
- [x] Verify zram active on VPS machines

### Phase 1: Data Migration
- [x] rsync GRASP 21GB + relay-owner nsec from old → new (via direct VPS-to-VPS rsync)
- [x] rsync routstr data (conf, tor-data, DB) from old → new
- [x] rsync mint keys (7 mints) from old → new (piped via sudo)
- [x] rsync act-runner data (273MB) from old → new
- [x] rsync Caddy certs from old → new
- [x] Fix routstr.conf nsec (Ansible generated new one, overwrote with correct one from old VPS)
- [x] Fix mint_key for test-mb and routstr-mint (Ansible generated new ones, overwrote)
- [x] Verify mint_key md5sums match (all 6 OK)
- [x] Verify GRASP repo count matches (2196)
- [x] Verify routstr.conf nsec matches

### Phase 2: Deploy Missing Playbooks
- [x] GRASP: copied binary from old VPS (v1.0.2), deployed systemd unit manually
- [x] Test mints: test-mb, test-kb, test-gb, test-min, testnut — all running
- [x] Routstr + Tor containers running
- [x] Mint routstr-mint running
- [ ] cashu-brrr (blocked: Node.js not in Debian 13 repos)
- [ ] Mint operator proxy
- [ ] Act runner (needs `27-act-runner.yml`, long build time)
- [ ] GRASP mirror daemon
- [ ] fips (needs env vars)
- [ ] nsyte CLI
- [ ] gitworkshop
- [ ] plebeian-market-test
- [ ] voting-worker
- [ ] auditable-voting-tests
- [ ] nutshell mints (nutshell-mint, nutshell-compat)

### Phase 3: Syncthing
- [x] Run `21-syncthing.yml` on new VPS — installed, peered with backup machine
- [x] 6 sync folders created
- [x] Peering with backup machine active
- [ ] Wait for initial scan/hash verification (GRASP 21GB will take time)
- [ ] Regenerate backup-status.json on new VPS

### Phase 4: DNS Cutover
- [x] Fix `03-cloudflare-dns` playbook — rewrote to upsert (PUT existing, POST new)
- [x] Run DNS playbook with `VPS_IP=23.182.128.226`
- [x] Delete 25 duplicate records pointing to old IP (23.182.128.51)
- [x] Update wildcard `*.orangesync.tech` from 64 to 226
- [x] Verify all subdomains resolve to 23.182.128.226 via Cloudflare DNS

### Phase 5: Verification
- [x] Core services: relay, chat, blossom, nsite, git (GRASP), ngit, routstr — all 200 OK
- [x] Dashboard at services.orangesync.tech — 200 OK
- [x] 5 test mints accessible (test-mb, test-kb, test-gb, test-min, routstr-mint)
- [ ] testnut mint — 404 (TLS cert still provisioning)
- [ ] Static sites (vote, workshop, runner, solix, ci, releases) — 404 (content not deployed yet)
- [ ] Dashboard backup status shows new VPS as source
- [ ] Act runner connected and processing jobs

### Phase 6: Cleanup
- [ ] Stop services on old VPS (keep data intact)
- [ ] Monitor new VPS for 1 week
- [ ] Decommission old VPS after verification period
