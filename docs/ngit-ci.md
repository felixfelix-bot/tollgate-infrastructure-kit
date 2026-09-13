# ngit-ci — coordinator + dashboard

Nostr-native CI (NIP-C1) in two roles:

| Role | Host | What it deploys | Playbook |
|------|------|-----------------|----------|
| `ngit_ci_dashboard` | vps2 (23.182.128.51) | static Vite SPA served by the **host systemd Caddy** at `ci.orangesync.tech` | `53-ngit-ci-dashboard.yml` |
| `ngit_ci` | dq05 (192.168.2.23 / tailnet 100.90.22.201) | coordinator container + `docker:dind` job-runner sidecar | `54-ngit-ci.yml` |

Both replace hand-deployed state: the dashboard had no automated path to
`ci.orangesync.tech`, and the coordinator was deployed by hand in
`~/ngit-ci-deploy` on DQ05 (docker compose + dind + `/data` volume + `.env`).
Everything live is now reproducible from this repository, and the parts of the
hand deployment that lived only in that `.env` are carried into the roles
rather than shadowed by them.

```
dq05                                   vps2
┌──────────────────────────────┐       ┌────────────────────────────────────┐
│ coordinator (ngit-ci 0.1.1)  │       │ systemd caddy                      │
│   ├ /data  (identity, cache) │       │   └ ci.orangesync.tech             │
│   └ tcp://dind:2375 ─────┐   │       │        root * /srv/tollgate/        │
│ dind sidecar (docker:dind)│  │       │        ngit-ci-dashboard/dist      │
│   └ job containers        │  │       └────────────────────────────────────┘
└───────────────────────────┼──┘                      ▲
                            └─ NIP-C1 events ──► relays (relay.ngit.dev, gitnostr.com)
```

## Deploying

```bash
cd ~/tollgate-infrastructure-kit
set -a; source .env; set +a            # CLOUDFLARE_API_TOKEN / ZONE_ID for the dashboard

# ansible.cfg is read only from the cwd, and it is what sets roles_path, so run
# from ansible/ — from the kit root the role lookup fails:
#   [ERROR]: The role 'ngit_ci_dashboard' was not found in: .../ansible/playbooks/roles
cd ansible

# A — dashboard (ci.orangesync.tech)
ansible-playbook playbooks/53-ngit-ci-dashboard.yml -l vps2

# B — coordinator (dq05)
ansible-playbook playbooks/54-ngit-ci.yml -l dq05
```

Both plays are idempotent: a second run against unchanged hosts reports
`changed=0` (verified 2026-09-13, three consecutive runs each). A deploy is
"done" when the play's own assertions pass — neither role accepts a container
that is merely `Up` or an HTTP 200 alone.

## Deliverable A — `ngit_ci_dashboard`

* Source: the ngit-published repo
  `https://relay.ngit.dev/npub1xtzgnzzu88yfv9es3evykl3ympjz0gc3umy2e6rs3jazruhjyevqe63edh/ngit-ci-dashboard.git`,
  **pinned** to `ngit_ci_dashboard_repo_version`
  (`a018425abb920f367e3cbad20b7674f8e5c1ec0d`, the published `main`).
  The pin and the deployed bundle must stay equal: the Caddy site block embeds
  the revision as a comment and the build is pinned, so a stale pin would
  rewrite the block *and* ship an older bundle.
* Build: `npm ci` + `npm run build` (full install — Vite/tsc are
  devDependencies) in `/opt/tollgate/src/ngit-ci-dashboard`, run as
  `sudo -u debian` after a root clone (Debian 13 rejects `become_user` ACLs).
  The build is skipped when `dist/index.html` exists **and** the pinned
  revision did not move; `ngit_ci_dashboard_force_build=true` forces it.
* Served from `/srv/tollgate/ngit-ci-dashboard/dist`. `rsync --chmod=D755,F644`
  normalises the bundle (the build user's umask 002 would otherwise make the
  publish and the world-readable pass fight each other on every run), and the
  whole path chain is made `0755` so the unprivileged `caddy` user can traverse
  it.
* Caddy: VPS2 runs a **systemd** Caddy. The route is injected with
  `blockinfile` markers (`# BEGIN NGIT CI DASHBOARD ROUTES`) so it survives
  Caddyfile regeneration, `validate: caddy validate --adapter caddyfile --config
  %s` guards the write (without `--adapter caddyfile` the JSON parser always
  fails and aborts the play), and the handler is `systemctl reload caddy` —
  **never** `docker restart tollgate-caddy`, which does not exist here and
  would reload nothing (the failure mode is silent).
* Cloudflare: A record `ci` → `23.182.128.51` with `proxied: false` (Caddy does
  its own TLS; the proxy would break the ACME challenge). The record is read
  back from the API and the play **fails** on a mismatch; stale records for the
  name are deleted first, and the pre-deploy fan-out of three A records is
  asserted down to exactly one so ACME validation is deterministic.
* Health check: **fatal** — the play aborts unless
  `https://ci.orangesync.tech/` answers 200 with a valid certificate and the
  body is the dashboard shell (not a placeholder page).

### Render verification (Playwright)

HTTP 200 is not acceptance for a client-rendered SPA. Two paths:

* On a host with Chrome/Chromium the role runs
  `roles/ngit_ci_dashboard/files/verify_dashboard.mjs` and fails when the shell
  does not render. VPS2 has no Chrome (Debian ships none), so there it records
  the check as delegated (the `skip`s in the play recap).
* From a workstation with Chrome:
  ```bash
  scripts/verify-ngit-ci-dashboard.sh                  # report only
  REQUIRE_RUN_ROWS=1 scripts/verify-ngit-ci-dashboard.sh   # enforce rows
  ```
  Same script; `PLAYWRIGHT_DIR` selects the checkout whose `node_modules`
  provides Playwright.

The script always reports the **run-row count** and hard-fails on zero rows:
`require_run_rows` defaults to **true** (the card's acceptance is a rendered run
list and the coordinator has live history — 79 rows at 11:44Z, 82 by 12:00Z, 0
page errors — so zero rows means the dashboard is broken, not that CI is idle).
Set `-e ngit_ci_dashboard_require_run_rows=false` only while a coordinator
legitimately has no history yet.

On VPS2 the role delegates the render check (no Chrome there) but the same
script is what a workstation run uses, and the `REQUIRE_RUN_ROWS=1` invocation
is the authoritative gate.

## Deliverable B — `ngit_ci`

* Source staged by git at `ngit_ci_repo_version`
  (`0580b27382b4fc9b6b3937d549a1cb2d125954fb`, v0.1.1 — verified md5-identical
  to the tree the live coordinator image was built from) into
  `~/ngit-ci-src`, then handed to the deploy owner. The ownership pass checks
  and reports only real changes, and skips `.git` (the git module fetches as
  root, so its internals are root-owned by design and are excluded from the
  build context anyway). `rev-parse HEAD` is asserted against the pin before
  anything is built.
* `docker-compose.yml` is generated from `docker-compose.yml.j2`, derived from
  upstream's compose with deliberate deltas:
  * `name: ngit-ci-deploy` pins the compose project so
    `ngit-ci-deploy_coordinator-data` — which holds the signing identity — is
    **reused, never recreated**;
  * the build context points at the git-staged source instead of a hand copy;
  * explicit container names and image tag (no implicit naming).
* Environment: `templates/coordinator.env.j2` → `~/ngit-ci-deploy/.env` (0600).
  The template states every effective value, so the runtime config is explicit
  rather than inherited from compose defaults.
* **Watched repositories** (`ngit_ci_repos`) mirror the live deployment: all
  repos of the TollGate upstream key aliased `#TMBG` (the alias its per-repo CI
  secret is stored under), plus the second npub the coordinator already watched.
  Narrowing this list silently stops CI for the dropped repo.
* **Per-repo secrets** (`NGIT_CI_SECRET_<ALIAS>__<NAME>`, `NGIT_CI_OPERATOR_BUNKER`)
  live in `~/ngit-ci-deploy/ngit-ci-secrets.env` (0600, never overwritten,
  injected into the container by compose's `env_file`). The hand deployment kept
  them inside `.env`, which this role owns and rewrites — so before rewriting it
  harvests any secret line from the existing `.env` into the secrets file and
  **fails the play** if the count would drop. Values are never read back into
  the play, logged, or committed: only key names and counts are printed. The
  role also asserts, after the stack is up, that every preserved key actually
  reached the coordinator's environment — a secret that is stored but not
  injected is a silent CI failure.
* `NGIT_CI_ACT_CONTAINER_DAEMON_SOCKET` is carried through explicitly for the
  same reason: compose only passes `.env` values named in the service's
  environment block, and the live deployment set it.
* The coordinator's signing key lives at `/data/.coordinator.nsec` on the
  volume. The role asserts only that the file *exists* — the key is never read,
  printed, copied or committed, and a re-run cannot rotate it.
* Readiness is asserted from the container's own log stream (`docker logs`,
  not `--since`): a healthy coordinator that was not restarted still has its
  startup banner and advertisement in that stream, so an idempotent re-run does
  not fail the play. The play fails when the coordinator never opened its
  subscriptions, never published an advertisement, or runs with a repo list,
  daemon socket or out-of-range ceiling that differs from the role.

### Concurrency: `NGIT_CI_MAX_CONCURRENT_JOBS` 1 → 3 (a ceiling, not a fixed value)

DQ05 has 4 cores, 10.9 GB RAM, 180 GB free and idles around load 1.0. The role
raises the ceiling to 3 so independent runs can proceed in parallel; per-job
caps are unchanged (`--memory=4g --memory-swap=4g --cpus=2 --pids-limit=2048`),
so the theoretical host ceiling becomes 3 × 4 GB = 12 GB against 10.9 GB RAM.
The caps are *ceilings*, not reservations, and jobs are short-lived, but
sustained oversubscription would push the host into swap/throttling. If that is
ever observed, reduce to `3 × 3g` (or back to 2) before raising further — **do
not go above 3 without operator sign-off**.

**The role owns the ceiling, not the instantaneous value.** An existing
operator-owned controller — `kalman-ci-concurrency.timer` on the worker host
(every 5 min, `/home/c03rad0r/repos/gh-ngit-ci-bridge/ci_concurrency_controller.py`)
— drives `NGIT_CI_MAX_CONCURRENT_JOBS` on DQ05 from the dispatch
resource-pressure signal and recreates the coordinator on each change. So a live
`NGIT_CI_MAX_CONCURRENT_JOBS=1` is that controller's decision inside the ceiling,
**not** drift. The role's post-deploy assertion therefore checks
`1 <= effective <= ngit_ci_max_concurrent_jobs` and reports the effective value;
asserting equality would flag a legitimate, operator-owned decision as a failure
on every run after a controller tick.

## Verification (2026-09-13)

| Check | Evidence |
|-------|----------|
| Coordinator containers | `ngit-ci-deploy-coordinator-1` / `ngit-ci-deploy-dind-1` both `Up` in `docker compose ps` |
| Effective config | container env: `NGIT_CI_REPOS=<both watched repos>` (aliased `#TMBG`), `NGIT_CI_ACT_CONTAINER_DAEMON_SOCKET=unix:///var/run/docker.sock`, `NGIT_CI_EXECUTION_POLICY=request-required`; `NGIT_CI_MAX_CONCURRENT_JOBS` within the role ceiling of 3 (the Kalman controller had it at 1 at review time — legitimate, inside the ceiling) |
| Signing identity | `/data/.coordinator.nsec` present on `ngit-ci-deploy_coordinator-data` (existence only) |
| Secret preservation | `sha256` of the `NGIT_CI_SECRET_TMBG__NSEC_HEX` line identical before (`.env`) and after (`.env` + `ngit-ci-secrets.env`) the role run |
| Playbook 54 | first run `ok=31 changed=8 failed=0`; re-runs `ok=29 changed=0 failed=0` |
| Playbook 53 (vps2) | `ok=27 changed=0 failed=0` on three consecutive runs |
| Public URL | `curl -o /dev/null -w '%{http_code}' https://ci.orangesync.tech/` → `200`, TLS verify `0` (Let's Encrypt `CN=ci.orangesync.tech`, 2026-09-11 → 2026-12-10) |
| DNS | `dig +short ci.orangesync.tech` → `23.182.128.51` (single A record, `proxied: false`) |
| Render | Playwright `channel: 'chrome'`: title `ngit-ci · Nostr CI Dashboard`, shell rendered, **79 run rows**, 0 page errors |
| Repo test | `tests/test-ngit-ci-secret-harvest.sh` → 15/15 assertions pass (move, idempotent re-run, preserved value wins, no secret on stdout) |
| Syntax | `ansible-playbook --syntax-check` clean for playbooks 53 and 54 |

## Troubleshooting

* **`--check` does not work on these roles** — by design. Both plays verify what
  they did with read-only probes and hard assertions (`systemctl is-active`,
  `git rev-parse`, `docker exec env`, the HTTPS/render checks), and Ansible skips
  `shell`/`command` tasks in check mode — so the probes return empty strings and
  the assertions abort with a misleading message (`Caddy is running in '' mode`).
  Run the play for real instead: it is idempotent (`changed=0` on a second run),
  which is the stronger guarantee a dry run was approximating.
* **Route 404/502 but the Caddyfile looks right** — the reload never happened.
  Check `systemctl status caddy`, then `systemctl reload caddy` by hand and
  re-run `curl -I https://ci.orangesync.tech/`.
* **Caddy refuses the config with `ambiguous site definition`** — a second site
  block for the same host exists. `ngit_ci_dashboard_caddy_marker` and
  `ngit_ci_dashboard_dist_dir` must match the block already on the host so
  `blockinfile` updates it in place.
* **Certificate not issued** — DNS must resolve before ACME runs. Confirm the
  Cloudflare record is `proxied: false` and `dig +short ci.orangesync.tech`
  returns exactly the VPS2 address.
* **Dashboard renders an old revision** — `ngit_ci_dashboard_repo_version` is
  behind the published `main`; bump it (the build re-runs when the pin moves).
* **Coordinator up but not advertising** — check the index relay connection in
  `docker logs ngit-ci-deploy-coordinator-1`; the play fails without an
  advertisement.
* **Jobs missing a secret** — confirm the key is in
  `~/ngit-ci-deploy/ngit-ci-secrets.env` (not `.env`) and that the repo's
  `NGIT_CI_REPOS` entry carries the matching `#ALIAS`. The role asserts this
  after every run.
* **Identity missing** — `/data/.coordinator.nsec` is generated on first start.
  If the play reports it missing, the compose project name or volume name has
  changed: **stop** and restore the volume, do not let a new identity be minted
  (the dashboard renders events for the old pubkey).
