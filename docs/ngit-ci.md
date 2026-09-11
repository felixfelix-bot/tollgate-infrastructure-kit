# ngit-ci — coordinator + dashboard

Two roles run the Nostr-native CI stack:

| Role | Host | What it deploys | Playbook |
|------|------|-----------------|----------|
| `ngit_ci` | dq05 (192.168.2.23 / tailnet 100.90.22.201) | ngit-ci coordinator container + `docker:dind` job-runner sidecar | `54-ngit-ci.yml` |
| `ngit_ci_dashboard` | vps2 (23.182.128.51) | static Vite SPA served by the **host systemd Caddy** at `ci.orangesync.tech` | `53-ngit-ci-dashboard.yml` |

Both replace hand-deployed state: the coordinator was originally deployed by
hand in `~/ngit-ci-deploy` on DQ05 (docker compose + dind + `/data` volume +
`.env`), and the dashboard had no automated path to `ci.orangesync.tech` at all.
Everything live is now reproducible from this repository.

```
dq05                                   vps2
┌──────────────────────────────┐       ┌────────────────────────────────────┐
│ coordinator (ngit-ci 0.1.1)  │       │ systemd caddy                      │
│   ├ /data  (identity, cache) │       │   └ ci.orangesync.tech             │
│   └ tcp://dind:2375 ─────┐   │       │        root * /srv/tollgate/ci     │
│ dind sidecar (docker:dind)│  │       └────────────────────────────────────┘
│   └ job containers        │  │                      ▲
└───────────────────────────┼──┘                      │ static bundle
                            └─ NIP-C1 events ──► relays (relay.ngit.dev, gitnostr.com)
```

## Deploying

```bash
cd ~/tollgate-infrastructure-kit
set -a; source .env; set +a            # CLOUDFLARE_API_TOKEN / ZONE_ID for the dashboard

# A — dashboard (ci.orangesync.tech)
ansible-playbook ansible/playbooks/53-ngit-ci-dashboard.yml -l vps2

# B — coordinator (dq05)
ansible-playbook ansible/playbooks/54-ngit-ci.yml -l dq05
```

## Deliverable A — `ngit_ci_dashboard`

* Source: the ngit-published repo
  `https://relay.ngit.dev/npub1xtzgnzzu88yfv9es3evykl3ympjz0gc3umy2e6rs3jazruhjyevqe63edh/ngit-ci-dashboard.git`,
  **pinned** to `ngit_ci_dashboard_repo_version` (currently
  `22bcb25cf9fb4a9857bdab5d33ea1f06b7e9b7ae`, the published `main`). The brief
  cited `2f3976d`; the published repo has since advanced to `22bcb25`.
* Build: `npm ci` + `npm run build` (full install — Vite/tsc are devDependencies)
  as `sudo -u debian`, cloned as root (Debian 13 rejects `become_user` ACLs).
* Served from `/srv/tollgate/ci`, whole path chain `0755` so the unprivileged
  `caddy` user can traverse it.
* Caddy: VPS2 runs a **systemd** Caddy. The route is injected with
  `blockinfile` markers (`# BEGIN NGIT-CI-DASHBOARD ROUTES`) so it survives
  Caddyfile regeneration, `validate: caddy validate --config %s` guards the
  write, and the handler is `systemctl reload caddy` — **never**
  `docker restart tollgate-caddy`, which does not exist here and would reload
  nothing (the failure mode is silent).
* Cloudflare: A record `ci` → `23.182.128.51` with `proxied: false` (Caddy does
  its own TLS; the proxy would break the ACME challenge). The record is read
  back from the API and the play **fails** on a mismatch; stale records for the
  name are deleted first.
* Health check: **fatal** — the play aborts unless
  `https://ci.orangesync.tech/` answers 200 with a valid certificate and the
  body is the dashboard shell (not a placeholder page).

### Render verification (Playwright)

HTTP 200 alone is not acceptance for a client-rendered SPA. Two paths:

* On a host with Chrome/Chromium the role runs
  `roles/ngit_ci_dashboard/files/verify_dashboard.mjs` and fails when the shell
  does not render. VPS2 has no Chrome (Debian ships none), so there it records
  the check as delegated.
* From a workstation with Chrome:
  ```bash
  scripts/verify-ngit-ci-dashboard.sh                  # report only
  REQUIRE_RUN_ROWS=1 scripts/verify-ngit-ci-dashboard.sh   # enforce rows
  ```
  Same script; `PLAYWRIGHT_DIR` selects the checkout whose `node_modules`
  provides Playwright.

The script always reports the **run-row count**, and only fails on zero rows
when `ngit_ci_dashboard_require_run_rows` / `REQUIRE_RUN_ROWS=1` is set.

## Deliverable B — `ngit_ci`

* Source staged by git at `ngit_ci_repo_version`
  (`0580b27382b4fc9b6b3937d549a1cb2d125954fb`, v0.1.1 — verified md5-identical
  to the tree the live coordinator image was built from) into
  `~/ngit-ci-src`, then chowned to the deploy owner. `rev-parse HEAD` is
  asserted against the pin before anything is built.
* `docker-compose.yml` is generated from `docker-compose.yml.j2`, derived from
  upstream's compose with two deliberate deltas:
  * `name: ngit-ci-deploy` pins the compose project so
    `ngit-ci-deploy_coordinator-data` — which holds the signing identity — is
    **reused, never recreated**;
  * the build context points at the git-staged source instead of a hand copy.
* Environment: `templates/coordinator.env.j2` → `~/ngit-ci-deploy/.env` (0600).
  The hand deployment set only five keys and relied on compose defaults for the
  rest; the template now makes every effective value explicit, so the runtime
  config is identical apart from the concurrency change below.
* `ngit-ci-secrets.env` (per-repo secrets) is created empty when absent and
  **never overwritten**.
* The coordinator's signing key lives at `/data/.coordinator.nsec` on the
  volume. The role asserts only that the file *exists* — the key is never read,
  printed, copied or committed, and a re-run cannot rotate it.

### Concurrency: `NGIT_CI_MAX_CONCURRENT_JOBS` 1 → 3

DQ05 has 4 cores, 10.9 GB RAM, 180 GB free and idles around load 1.0. Raising
the ceiling to 3 lets independent runs proceed in parallel; per-job caps are
unchanged (`--memory=4g --memory-swap=4g --cpus=2 --pids-limit=2048`), so the
theoretical host ceiling becomes 3 × 4 GB = 12 GB against 10.9 GB RAM. The caps
are *ceilings*, not reservations, and jobs are short-lived, but sustained
oversubscription would push the host into swap/throttling. If that is ever
observed, reduce to `3 × 3g` (or back to 2) before raising further — **do not
go above 3 without operator sign-off**.

## Known limitation: the dashboard renders zero run rows today

`ci.orangesync.tech` serves correctly and the shell renders, but the run list is
empty because the coordinator has **no CI history**:

```console
$ nak req -k 39842 -a 765cd47badcbbc4a38c7d0c57d5607663b484c20cd59773f9f7064487f9431e8 wss://relay.ngit.dev | wc -l
0
$ nak req -k 9842 -a 765cd47b… wss://gitnostr.com | wc -l
0
```

The coordinator is healthy — it publishes its `kind:19843` advertisement and
`kind:19844` request-readiness list to `wss://index.ngit.dev` every 15 minutes —
but `NGIT_CI_EXECUTION_POLICY=request-required` means it stays closed until a
maintainer publishes a `kind:9843` Service Request (or a one-shot `kind:9840`
Manual Trigger) for a watched repository. No workflow has ever run on this
coordinator, so there is nothing to display.

To turn the run-row gate on for real:

1. have the maintainer of a watched repo publish a Service Request (kind 9843)
   and then push/PR — or a Manual Trigger (kind 9840);
2. watch the coordinator start a run: `docker compose logs -f coordinator`
   (in `~/ngit-ci-deploy` on DQ05);
3. re-run the render check with `REQUIRE_RUN_ROWS=1`.

Until then, treat "shell renders" as the enforced gate and "run rows" as
reported evidence — see `PROGRESS.md` for the current numbers.

## Troubleshooting

* **Route 404/502 but the Caddyfile looks right** — the reload never happened.
  Check `systemctl status caddy`, then `systemctl reload caddy` by hand and
  re-run `curl -I https://ci.orangesync.tech/`.
* **Certificate not issued** — DNS must resolve before ACME runs. Confirm the
  Cloudflare record is `proxied: false` and `dig +short ci.orangesync.tech`
  returns the VPS2 address.
* **Coordinator up but not advertising** — check the index relay connection in
  `docker compose logs coordinator`; the play fails after two minutes without an
  advertisement.
* **Identity missing** — `/data/.coordinator.nsec` is generated on first start.
  If the play reports it missing, the compose project name or volume name has
  changed: **stop** and restore the volume, do not let a new identity be minted
  (the dashboard renders events for the old pubkey).
