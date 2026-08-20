# V2 Remediation Plan — hermes-for-friends

**Author:** senior infrastructure consultant (subagent), for operator + manager review
**Date:** 2026-08-14
**Status:** DRAFT — do not commit until manager review
**Inputs:** kanban `t_112c4901` (V2-03, 7 runs, comments #39/#42), repo `felixfelix-bot/tollgate-infrastructure-kit` (branches `hermes-v2/*`), `PLAN-hermes-for-friends-v2.md`, live forensics from worker-inspector runs 5–6.

---

## 0. Executive summary

Five pain points, one meta-root-cause: **the live VPS2 deployment has drifted from the repo, and the repo itself encodes several first-deployment bugs** (missing coincurve in the slim image, no config bootstrap, root-owned nsec, self-matching healthcheck). The E2E failure is not one bug but a *chain of three independent blockers* (config never loaded → coincurve missing → nsec unreadable), each of which would have masked the next.

Strategy:

1. **Phase 1** — unblock V2-03 today with the operator-approved, reversible in-place fix on `hermes-sitarani` and get the E2E green. Fastest path, no image rebuild in the critical path.
2. **Phase 2** — land the *root-cause* fixes in the repo (image + Ansible role), so that V2-12 (fresh SSD deploy) cannot hit any of these walls. This phase is the gate for V2-12.
3. **Phase 3** — make the dispatch loop quota-aware (pause+resume, not block) so z.ai 503 outages stop burning retry budgets.
4. **Phase 4** — harden VPS2 (resource caps, load alerting, out-of-band access) so a meltdown doesn't take SSH with it again.
5. **Phase 5** — SSD VPS unblock (contingent on provider); V2-11..14 proceed on a rehearsed, already-fixed stack.

Everything in Phase 2 lands on `hermes-v2/*` branches, pushed to `felixfelix`, quality gates G1–G5, per standing worker conventions.

---

## 1. Root-cause analysis (what actually broke, and why)

### 1.1 V2-03 E2E failure chain (proven from source + logs, run 6)

| # | Symptom | Root cause | Class |
|---|---------|-----------|-------|
| a | `Channel directory built: 0 target(s)` — nostr adapter never loads | `/opt/data/.hermes/config.yaml` was written **after** the 13:56 container start; `run.py` iterates `config.platforms` at startup only. The Ansible role never templates `config.yaml` at all — the platform block was hand-injected post-hoc by an earlier worker run. | **Missing bootstrap step in role/image** |
| b | `RuntimeError: coincurve not installed — required for Nostr signing` | `Dockerfile.slim` (commit `9ed1a65`, branch `hermes-v2/trim-image`) builds with `uv sync --frozen --no-install-project --extra messaging --extra anthropic`. coincurve is **not** in the installed extra set (lazy optional dep of the nostr adapter). The commit message claims "preserving coincurve" — wrong. The G1/G2 test (`tests/test-hermes-slim-image.sh`) only exercised `hermes --version` + shallow imports; `nostr.py` lazy-imports coincurve **inside a function**, so the import check passed vacuously. | **Build recipe bug + vacuous test** |
| c | `PermissionError` reading `/nsec/nsec.txt` | Role writes the nsec via `ansible.builtin.copy` **as root, mode 0600, no owner**; gateway runs as uid 10000 (`hermes`). Additionally the `nsec/` **directory** is created `0700 root:root` — even a chowned file is unreachable if the dir is not traversable by uid 10000. | **Ownership never modeled in role** |

Secondary findings (fix while we're here):

- `.env` template in `hermes_tenants/tasks/main.yml` contains a malformed line — `ZAI_API_KEY=*** item.zai_api_key }}` (missing `{{`) — the variable is silently never interpolated.
- Compose template mounts the data volume at `/data` while the slim image sets `HERMES_HOME=/opt/data`; the live box was hand-patched to `/opt/data`. Template and image disagree → fresh deploys will recreate the "config written to the wrong home" class of bug.
- `ansible/playbooks/45-multi-tenant-hermes.yml` still defines tenants `ours/friend1/friend2` on `main` while live containers are `sitarani/chiefmonkey/bekka` (rename landed on a branch, playbook not reconciled).
- `tests/e2e-buzz-hermes.sh` + `docs/E2E-BUZZ-HERMES.md` are drafted but **untracked** in the working tree (repo currently checked out on `feat/fips-proxyjump-ingress`).

### 1.2 False-healthy healthcheck

`pgrep -f 'hermes gateway run'` runs inside `sh -c` — the wrapper's own command line matches the pattern, so the healthcheck always succeeds even while the gateway crash-loops. Proven during run 5 (root-owned logs crash-loop reported "healthy"). The correct healthcheck (HTTP `curl -sf http://localhost:8080/health`) **already exists** on branch `hermes-v2/routstrd-sidecar` — it just never reached `main` / the live box. Note the chicken-and-egg: with zero platforms enabled nothing binds :8080, so HTTP-only healthcheck will (correctly) report *unhealthy* until pain point 1a is fixed. That is signal, not noise.

### 1.3 Retry-budget burn during z.ai 503 outages

Current mechanics: a worker hitting sustained 503s grinds to the 90-iteration budget → `timed_out` → dispatcher `gave_up`/`promoted` → re-claim → burn again. On `t_112c4901` alone: 2 protocol violations, 3 × "Iteration budget exhausted (90/90)", 1 operator-decision block, 7 runs total. The Kalman gate (`rate_limit_gate.py` + `staggered-dispatch.sh`) already pauses **new dispatch** on 429s/peak-hours, but (a) it does not know about 503 outages or quota-window exhaustion, and (b) pausing dispatch does not stop in-flight retries, and (c) there is no task-level "pause, don't consume budget" primitive — the only worker-side options are block/complete/crash, two of which are wrong and one of which burns budget.

### 1.4 VPS2 meltdown (load 120+, SSH timeouts)

4-core box running: 3 × hermes containers (one crash-looping under s6 with immediate restarts — s6 has no exponential backoff by default), buzz relay + postgres + redis, routstrd sidecars (671MB image each), strfry/blossom/ngit/mint stack, plus E2E polling (`nak req` every 7s over SSH) and an OOM kill of ngit-grasp at 12:52 — the wedged-userspace signature (TCP accepts, no banner on :22/:443) is classic memory-pressure/swap-thrash collapse. Root causes: **no enforced resource caps on the live compose** (the repo template's `mem_limit`/`cpus` never converged to the box), no load alerting below catastrophe (V2-10 monitoring exists but thresholds too late), and no out-of-band access when sshd starves (NetBird data plane broken — B3; FIPS mesh has no VPS2 peer).

### 1.5 SSD VPS offline

Both IPs (64.188.7.38, 66.92.204.38) down → V2-11..14 blocked. Nothing repo-side can fix a dead box; the remediation is (a) provider escalation, (b) continuous reachability probing so V2-11 triggers the moment it returns, and (c) **rehearsing V2-12's deployability now** so the migration is a re-run, not a debugging session. The 653-line leftover test aimed at the SSD VPS (found during run 5) shows workers already idled on this — keep V2-12 prep decoupled and cheap.

---

## 2. Phased task breakdown

Conventions for every task: branch `hermes-v2/<topic>` off latest `main` (or the named parent branch), push to `felixfelix` remote, quality gates G1–G5 (TDD where a test is possible; for infra tasks G1 = verification bash script, G2 = script exits 0 on live VPS2), atomic conventional commits. Worktrees only under `~/worktrees/`, never `/tmp`.

### PHASE 1 — Unblock V2-03 E2E (target: today, ~2–3 h wall clock)

#### T1.1 Approve + execute the in-place fix on hermes-sitarani (OPERATOR GATE — see D1)

- **Assignee:** worker-admin (operator approves; execution is the worker's pending proposal from comment #42)
- **Scope (on VPS2, per tenant `sitarani` only):**
  1. `pip3 download coincurve` (cp313 wheel) on the VPS2 host → extract into the **data volume** `/opt/data/pylibs` (volume, not venv — must survive the P5 recreate).
  2. Add `PYTHONPATH=/opt/data/pylibs` to `/opt/tollgate/hermes/sitarani/.env`.
  3. `chown 10000:10000` the nsec **file** and the `nsec/` **directory** (both — see §1.1c).
  4. `chown -R 10000:10000 /opt/data/logs` (prevent the run-5 root-owned-logs crash-loop from recurring).
  5. Verify `/opt/data/.hermes/config.yaml` contains `platforms.nostr.enabled=true` (written at 14:47, never yet loaded).
  6. `docker compose up -d` → **recreate** (this is the load step for the config).
- **Files/branches:** none (live op; reversible). Debt marker: the PYTHONPATH hack gets a removal task (T2.4) — do not let it live past the image rebuild.
- **Verification:**
  - `docker logs hermes-sitarani` shows a nostr line and **not** `Channel directory built: 0 target(s)`;
  - `docker exec hermes-sitarani python3 -c "import coincurve"` exits 0 (non-lazy, direct);
  - `docker exec -u 10000 hermes-sitarani cat /nsec/nsec.txt >/dev/null` exits 0;
  - `curl -s -o /dev/null -w '%{http_code}' http://localhost:9000/health` = 200.
- **Dependencies:** operator decision D1.
- **Effort:** 30 min.

#### T1.2 Commit the E2E artifacts properly

- **Assignee:** worker-inspector (author of the draft).
- **Scope:** commit the already-drafted `tests/e2e-buzz-hermes.sh` (208 lines, P0–P8) and `docs/E2E-BUZZ-HERMES.md` on branch `hermes-v2/e2e-buzz-test`. They are currently **untracked** in a working tree sitting on `feat/fips-proxyjump-ingress` — create the branch from `main` without disturbing the current checkout (use a `~/worktrees/` worktree).
- **Verification:** `git ls-tree -r hermes-v2/e2e-buzz-test --name-only | grep e2e-buzz`; `bash -n tests/e2e-buzz-hermes.sh` clean; push exit 0.
- **Dependencies:** none (parallel with T1.1).
- **Effort:** 20 min.

#### T1.3 Run the E2E, capture evidence, complete V2-03

- **Assignee:** worker-inspector.
- **Scope:** run `tests/e2e-buzz-hermes.sh` against live VPS2 (P0 pre-flight → P8 LLM-leg evidence). Run inside `tmux` on a pre-established SSH connection (meltdown insurance, §4 risks). On pass: kanban comment with the P0–P8 transcript, `kanban_complete`. If P7 (bot reply) fails but P0–P5 pass, capture `agent.log` tail — the remaining delta is LLM-leg (routstr/z.ai), not nostr.
- **Verification:** script exits 0; cleanup restored `NOSTR_GROUPS` (script trap) — verify `.env` on VPS2 matches pre-run value afterwards.
- **Dependencies:** T1.1, T1.2.
- **Effort:** 45 min (incl. one likely iteration).

### PHASE 2 — Root-cause fixes in repo (gate for V2-12; ~1 day of worker time)

#### T2.1 Dockerfile.slim: coincurve baked in + build-time hard gate + non-vacuous test

- **Assignee:** worker-admin. **Branch:** `hermes-v2/slim-coincurve` (off `hermes-v2/trim-image`).
- **Scope:**
  1. Builder stage: explicitly install coincurve pinned to the `uv.lock` resolution — `uv pip install --frozen coincurve==<locked-version>` (do not rely on extras naming; or verify and fix the extra, e.g. `--extra nostr`, whichever pyproject actually declares — verify, don't assume).
  2. **Build-time hard gate** (the real fix for the vacuous test): add to the runtime stage
     `RUN /opt/hermes/.venv/bin/python -c "import coincurve; from coincurve import PrivateKey; PrivateKey(bytes(range(32))).sign(b'x')"` — a *non-lazy import + actual schnorr/sign call*. The build fails if the wheel is missing or the ABI is broken. Also gate `import nostr`-adapter module top-level if cheap.
  3. Upgrade `tests/test-hermes-slim-image.sh`: replace shallow import checks with `docker run --rm $IMAGE python3 -c "<same import+sign one-liner>"` plus `curl` of the gateway `/health` after a platform-config smoke start.
  4. While in the file: fix the `/data` vs `HERMES_HOME=/opt/data` mismatch (§1.1 secondary) — either mount-target alignment in compose (T2.2) or set the volume/home consistently; document in `hermes-docker/README.md`.
- **Verification:** `docker build` fails when the coincurve line is deliberately removed (prove the gate bites); image size still < 1GB; test script exits 0 on a built image; G3 README update in same commit.
- **Dependencies:** none (parallel). **Effort:** 1.5–2 h.

#### T2.2 Ansible role `hermes_tenants`: config bootstrap, nsec ownership, .env fix, healthcheck, caps

- **Assignee:** worker-admin. **Branch:** `hermes-v2/tenant-bootstrap` (off `main`; cherry-pick the healthcheck + caps hunks from `hermes-v2/routstrd-sidecar` to avoid rebasing that whole stack).
- **Scope (all in `ansible/roles/hermes_tenants/` + playbook 45):**
  1. **Config bootstrap before first gateway start** — two layers:
     - *Image layer (preferred root fix):* extend `Dockerfile.slim` with a `cont-init.d/03-nostr-bootstrap` script that renders `platforms.nostr` into `$HERMES_HOME/.hermes/config.yaml` from `NOSTR_RELAYS`/`NOSTR_GROUPS`/`NOSTR_NSEC_PATH` env **iff the file/key is absent** (never clobber user edits; idempotent). Runs as root in cont-init, before s6 stage 2 drops to uid 10000. This makes *any* deployment (VPS2, SSD, compose, plain docker run) self-bootstrapping — exactly what V2-12 needs.
     - *Role layer (declarative):* template `config.yaml.j2` (platforms.nostr, relays, groups, gateway port) into a per-tenant path mounted at the hermes home, so the config is visible in the repo, reviewable, and drift-detectable.
  2. **nsec ownership in Ansible, not manual chown:** `owner: "10000"`, `group: "10000"` (numeric — controller has no such user) on the nsec **file** and on the `nsec/` **directory**; plus an idempotent reconcile task (`file: state=touch`-style or `stat`+`command` chown) fixing pre-existing root-owned files on already-deployed boxes.
  3. Fix the `.env` template: `ZAI_API_KEY={{ item.zai_api_key }}` (currently malformed — value never lands).
  4. Align volume mount target with `HERMES_HOME` (`/opt/data` in slim image) in `docker-compose.tenant.yml.j2`.
  5. **Healthcheck HTTP-only:** adopt the `routstrd-sidecar` template's `curl -sf http://localhost:8080/health || exit 1` for both hermes and routstrd services; raise `start_period` to 120s (platform bring-up is slow on first boot); delete the pgrep variant everywhere (grep the repo for `pgrep -f` to catch strays).
  6. **Resource caps (VPS2 meltdown class-fix):** keep `mem_limit`/`cpus` on both services (already in sidecar template), add `mem_reservation`, and set VPS2-appropriate defaults (see D7 — suggest hermes `1g`/`1.0` CPU, routstrd `256m`/`0.5`). Add `oom_score_adj` or `stop_grace_period: 30s` for clean LLM-drain shutdowns.
  7. Reconcile playbook 45 tenant list to `sitarani/chiefmonkey/bekka` (rename landed on boxes but not on `main`).
- **Verification:** molecule converge green (role has molecule scaffolding); `--check --diff` against VPS2 shows only expected changes; rendered compose contains no `pgrep`, has both caps blocks; `docker inspect hermes-X --format '{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}'` non-zero after apply; on a scratch container: first `up -d` from *empty volume* produces a loaded nostr adapter (the V2-12 rehearsal in miniature).
- **Dependencies:** T2.1 (bootstrap script ships in the image; role can land first with the file templated only). **Effort:** 3–4 h.

#### T2.3 Merge the `hermes-v2/*` stack to main

- **Assignee:** worker-admin (manager reviews). **Branch:** merge train on `main`.
- **Scope:** ordered merge: `fix-compose-entrypoint` → `fix-gateway-port` → `rename-containers` → `trim-image` → `slim-coincurve` → `routstrd-docker` → `routstrd-sidecar` → `tenant-bootstrap` → `e2e-buzz-test`. Resolve conflicts once, in order of age.
- **Verification:** post-merge molecule + `bash -n` on all `tests/*.sh`; `git log --oneline` linear-ish; push to `felixfelix` + `github` remotes.
- **Dependencies:** T2.1, T2.2, T1.2. **Effort:** 1 h.

#### T2.4 Rebuild image, converge VPS2, retire the in-place hack

- **Assignee:** worker-admin.
- **Scope:** build `hermes-agent:nostr-slim2` (new tag — canary strategy, see D2); deploy to `hermes-sitarani` first; re-run E2E (T1.3 script) against it; then chiefmonkey + bekka; run the converged Ansible role over all three; **remove** `PYTHONPATH=/opt/data/pylibs` from sitarani's `.env` and delete `/opt/data/pylibs` (debt marker from T1.1 closed); confirm no manual drift remains (`diff` live compose vs rendered template should be empty).
- **Verification:** E2E green on all 3 tenants (or at minimum sitarani + health 200 on others); `docker exec hermes-chiefmonkey python3 -c "import coincurve"` OK with no volume hack; live `/opt/tollgate/hermes/*/docker-compose.yml` byte-identical to freshly rendered templates.
- **Dependencies:** T2.3; **schedule after** E2E green + off-peak (D8). **Effort:** 1.5 h.

### PHASE 3 — Quota-aware dispatch (local machine work; parallel with everything; ~3 h)

#### T3.1 Extend the Kalman gate: 503-outage + quota-window awareness

- **Assignee:** worker-admin. **Files:** `~/.hermes/scripts/rate_limit_gate.py` (and the `~/.hermes/bot/` cron copy it feeds), state at `~/.hermes/state/rate_limit_gate.json`.
- **Scope:**
  - New check `recent_503`: ≥3 z.ai 503s within 10 min (from `zai_usage.db` samples or the localhost:9099 proxy log) → `paused=true`, `reason="zai-503-outage"`, `resume_at = now + min(Retry-After, 20 min)` re-evaluated each 5-min cron run.
  - New check `quota_windows`: poll the quota collector (5-hour/weekly/monthly windows, `used_pct`, `resets_at` — same source the dq05 monitor uses); any window ≥ 85% → advisory `paused` with `resume_at = next window reset`.
  - Keep fail-open on missing data (existing behavior) but fail-closed on *confirmed* 503 burst.
- **Verification:** unit-testable pure functions (feed synthetic sample sets; assert pause/resume_at); forced-live test: point at a fixture DB with a 503 burst → gate file shows paused + resume_at; staggered-dispatch honors it (already does — `check_gate`).
- **Dependencies:** none. **Effort:** 1–1.5 h.

#### T3.2 Dispatcher pause+resume semantics (stop burning budget)

- **Assignee:** worker-admin. **Files:** `~/.hermes/scripts/staggered-dispatch.sh` (+ a small `kanban-quota-sweeper` script or a mode inside it).
- **Scope:**
  1. While gate is paused with a `zai-*` reason: dispatcher writes a board-level pause marker (`~/.hermes/state/board_pause_<board>`) and **skips the board entirely** — no claims, no promotes, no failure accounting. Tasks sit `ready`, budgets untouched.
  2. Auto-resume: when `resume_at` passes and the gate is clear, remove markers. **Fail-safe max pause 6 h** — after that, force one claim to probe (a single canary task) so a stale gate can't silently stop the board forever; alert manager.
  3. Sweeper: any task blocked with reason prefix `quota-paused:` gets auto-`unblock`ed (re-queued, not counted as failure) once the gate clears.
- **Verification:** integration test on a scratch board: fabricate gate pause → dispatch → assert no claim + marker exists; clear gate + run sweeper → assert blocked task re-queued with failures counter unchanged; kill-switch test for the 6 h fail-safe.
- **Dependencies:** T3.1. **Effort:** 1–1.5 h.

#### T3.3 Worker convention: quota-paused taxonomy (skill + guidance update)

- **Assignee:** worker-inspector (docs) with manager sign-off (it changes worker protocol). **Files:** `~/.hermes/skills/devops/kanban-worker/SKILL.md` (manager profile copy — cross-profile edit needs explicit approval, see D9).
- **Scope — how a worker distinguishes 503-exhaustion from real failure:**
  - **Quota/outage signature:** failure at the *first* LLM call; HTTP 503 (or 429) from `localhost:9099`/routstr upstream; error text mentions quota/capacity/upstream; **and** the gate file (`~/.hermes/state/rate_limit_gate.json`) says `paused` with a `zai-*` reason; **and** the failure is identical across unrelated steps. → Action: `kanban_block(reason="quota-paused: gate says <reason>, resume_at <ts> — no work lost, not a task defect")` **early** (≤10 iterations in), never `complete`, never grind to 90.
  - **Real failure signature:** error is task-specific (fails at different steps, references concrete files/hosts/logic), or non-LLM (SSH, DNS, docker). → Action: normal diagnose→fix→block-with-diagnosis flow.
  - Tie-breaker rule: if unsure after 2 probes spaced 10 min and the gate is clear → treat as real failure.
- **Verification:** skill renders; dry-run a mock worker prompt against the taxonomy (manager spot-check).
- **Dependencies:** T3.1/T3.2 (names must match). **Effort:** 45 min.

### PHASE 4 — VPS2 stability (~2.5 h)

#### T4.1 Enforce resource caps + systemd guards

- **Assignee:** worker-admin. **Files:** landed via T2.2 role; plus `ansible/playbooks/01-system.yml` (systemd drop-ins).
- **Scope:** apply converged compose (caps per D7); add `CPUQuota=300%` + `MemoryMax=` on `docker.service` slice so containers *in aggregate* can't starve sshd; protect sshd with its own slice (`CPUWeight=900`, `MemoryMin=`) so SSH survives the next meltdown; confirm zram (playbook `00-zram`) is active on VPS2 — if not, run it (4 GB box running this stack without zram is how you get load-120 swap death).
- **Verification:** `docker stats --no-stream` shows caps respected under a synthetic load test (`stress-ng` in one container cannot push host load past the slice cap); SSH stays responsive during the test; `systemctl show sshd -p CPUWeight`.
- **Dependencies:** T2.4 (caps ride the converged deploy). **Effort:** 1 h.

#### T4.2 Load alerting with early thresholds + out-of-band access

- **Assignee:** worker-admin. **Files:** `scripts/hermes-health-check.sh` (V2-10, branch `hermes-v2/monitoring`), thresholds + a node-probe cron.
- **Scope:** alert ladder — warn at load>8 (15-min avg), page at >15, "meltdown imminent" at >30 (this box reached 120 before anyone noticed); disk + RAM headroom checks; every-5-min sample persisted (sar/atop) so the *next* post-mortem has data (§1.4 is currently unexplainable for lack of it). Out-of-band: add a VPS2 peer to the FIPS mesh or fix NetBird (B3) — decision D6.
- **Verification:** threshold unit test; fire a synthetic alert; confirm delivery channel.
- **Dependencies:** none (parallel). **Effort:** 1 h.

#### T4.3 Meltdown post-mortem (data-driven)

- **Assignee:** worker-inspector.
- **Scope:** once sar/atop history exists (or from dmesg/OOM timeline + docker events for the Aug 14 incident): identify the load-120 driver (prime suspects: s6 crash-loop restart storm from the root-owned-logs PermissionError — fixed by T1.1/T2.2; unbounded nak/SSH E2E polling; buzz postgres under memory pressure). Write `docs/POSTMORTEM-vps2-load120.md`; feed any residual gaps back into T4.1 caps.
- **Verification:** doc identifies ≥1 measured culprit or explicitly states data insufficient + what T4.2 now collects.
- **Dependencies:** T4.2 (for future data); historical portion can start immediately. **Effort:** 45 min.

### PHASE 5 — SSD VPS unblock (contingent; V2-11..14)

#### T5.1 Provider escalation + continuous probe

- **Assignee:** operator (ticket) + worker-admin (probe cron).
- **Scope:** file provider ticket for both IPs; cron probe (1/min, from ≥2 vantage points — e.g., T470 and VPS2) of 64.188.7.38 + 66.92.204.38 (ICMP + TCP:22); on first success, auto-notify + flip V2-11 to ready.
- **Verification:** probe log; simulated flip on a test IP.
- **Effort:** 30 min + ticket latency.

#### T5.2 V2-12 rehearsal checklist (do NOW, don't wait for the box)

- **Assignee:** worker-inspector.
- **Scope:** a "fresh-deploy must-not-hit" checklist validated against Phase 2 outputs: coincurve baked+gated (T2.1), config self-bootstrap from env (T2.2 image layer), nsec owner 10000 by construction (T2.2), HTTP healthcheck (T2.2), resource caps (T2.2), HERMES_HOME/mount alignment (T2.1/T2.2), .env interpolation fixed (T2.2). Rehearse: molecule converge from scratch + a `docker compose up -d` from empty volumes on a scratch dir on VPS2. Anything the rehearsal hits becomes a Phase 2 bug, not a V2-12 discovery.
- **Verification:** checklist doc `docs/SSD-DEPLOY-CHECKLIST.md` with each item pointing at the landed commit.
- **Dependencies:** T2.3. **Effort:** 1 h.

#### T5.3 V2-12/13/14 execution (when SSD returns)

- **Assignee:** worker-admin (12, 13), worker-inspector (14). Standard plan tasks, now de-risked: deploy via converged Ansible, DNS cutover (Cloudflare zone `bc6dec2a`), integration test = re-run `tests/e2e-buzz-hermes.sh` (parameterized `VPS2_HOST=…`) + the V2-14 list.
- **Effort:** as original plan (3 h / 30 min / 1.5 h).

---

## 3. Decision points for the operator

| # | Decision | Options | Recommendation |
|---|----------|---------|----------------|
| **D1** | Unblock path for V2-03: in-place live fix vs image-rebuild-first | (A) Approve worker's in-place fix (wheel into volume + PYTHONPATH + chown + recreate) — 30 min, reversible, E2E today. (B) Rebuild image first, deploy, then E2E — cleaner but puts a ~2 h build+canary in the critical path on an already-fragile box. (C) Operator applies fix manually. | **A now, B in parallel** (T2.1/T2.4 already scheduled). A is reversible and explicitly time-boxed by the T2.4 debt-removal step. The worker's proposal is sound; the only correction is to chown the nsec *directory* too, not just the file. |
| **D2** | Image rollout strategy for the rebuilt slim image | (A) Reuse tag `hermes-agent:nostr-slim` (all 3 tenants roll on next `up`). (B) New tag `:nostr-slim2`, canary on sitarani, then others. | **B.** Shared-tag mutation is how one bad rebuild takes out all tenants at once; canary costs 20 min. |
| **D3** | Healthcheck during bootstrap window | (A) HTTP-only now (containers honestly `unhealthy` until nostr platform loads; monitoring must not page on that window). (B) Keep pgrep as fallback during transition. | **A.** The false-healthy signal already cost a full debugging run; `start_period: 120s` + monitoring grace handles the bootstrap window. |
| **D4** | Quota-pause mechanism | (A) Board-level dispatcher pause only. (B) Task-level `quota-paused:` auto-block + sweeper only. (C) Both. | **C** — dispatcher pause stops *new* budget burn; the sweeper rescues tasks already mid-block when the outage hit. Belt and braces, both cheap. |
| **D5** | 503/outage detection source | (A) zai_usage.db sampling only. (B) Proxy (localhost:9099) health/`/v1/models` probe. (C) Quota-window API poller (used_pct/resets_at). | **A+B now, C optional.** B is the cheapest live signal; A is already wired into the gate; C adds precision but another dependency. |
| **D6** | Out-of-band access to VPS2 | (A) Add VPS2 peer to FIPS mesh. (B) Fix NetBird data plane (B3). (C) Neither — accept SSH-only risk. | **A** — smallest delta, proven path (FIPS ProxyJump landed `9d67d13`); the Aug 14 wedge had zero bypass available. |
| **D7** | Resource cap values (VPS2, 4 GB) | hermes: 512m/1.0 (role default) vs 1g/1.0; routstrd: 256m/0.5; docker slice: CPUQuota 300%/MemoryMax ~3g | **1g per hermes** (s6 + python + nostr + LLM client realistically peaks 400–700m; 512m invites OOM-kill crash-loops — worse than caps), routstrd 256m, slice guards as listed. |
| **D8** | When to converge live VPS2 to Ansible | (A) Immediately, mid-E2E. (B) After E2E green + off-peak serial per tenant. | **B.** Don't churn the box under test; the E2E retarget (P5) itself recreates the container — one recreate per run is enough. |
| **D9** | Editing the shared `kanban-worker` skill (T3.3) | (A) Manager applies the taxonomy edit in the manager session. (B) Worker drafts a patch file; manager commits. | **B** — keeps cross-profile writes explicit and reviewable, matches the profile guard. |
| **D10** | SSD VPS wait policy | (A) Wait for provider indefinitely. (B) 48 h window, then lease a cheap scratch VPS to rehearse V2-12 + run the E2E against a second box. | **B.** The rehearsal (T5.2) is valuable regardless; a $5 box derisks a 3 h migration task and doubles as the E2E's second target. |

---

## 4. Risk notes

- **Canary risk (T2.4):** a rebuilt slim image is a new image — the build-time gate catches missing wheels, not behavioral regressions. Mitigation: canary on sitarani + full E2E before touching bekka/chiefmonkey; keep `hermes-agent:nostr` (fat) as instant rollback tag.
- **PYTHONPATH hack tail risk:** if T2.4 slips, the volume hack becomes load-bearing. Mitigation: kanban debt task created *by* T1.1, blocked-on T2.3, visible on the board; the wheel is cp313-specific — a future Python bump in the image silently breaks it (another reason it must not linger).
- **Bootstrap idempotency:** `03-nostr-bootstrap` must never overwrite an existing `platforms.nostr` block (friends' manual edits would be lost, and an E2E retarget mid-flight could race a recreate). Write-only-if-absent + log when skipping.
- **HTTP healthcheck noise:** until 1a is fixed fleet-wide, `unhealthy` is *correct*. Monitoring (T4.2) must gate pages on `start_period` + platform-loaded evidence, or the first week pages constantly and gets muted — worse than the bug.
- **nsec ownership:** numeric uid 10000 assumed = image `hermes` user (Dockerfile `useradd -u 10000`). If a future image changes the uid, the role silently breaks — add a build-time assertion `id -u hermes` = the role variable, or derive from image inspection.
- **Quota-pause stuck risk:** a gate that never clears freezes all boards. Mitigation: 6 h fail-safe canary (T3.2), fail-open on missing data (preserved), manager alert on pause >2 h.
- **503 false positives:** one transient 503 pausing dispatch costs throughput. Mitigation: burst threshold (≥3/10 min) + 20 min max backoff per pause; single 503s remain worker-retryable.
- **VPS2 converge downtime:** each tenant recreate = one gateway restart (~30–60 s nostr re-subscribe). Off-peak serial (D8); warn friends in the group; E2E must not be running.
- **E2E self-modifying state:** P5 rewrites `.env` + recreates; cleanup trap restores, but a hard kill mid-P5 leaves the bot on the test group. Mitigation: post-run verify step (compare `.env` to pre-run snapshot; script already snapshots `ORIG_GROUPS`) — add a final P9 assertion before declaring pass.
- **Meltdown recurrence during Phase 1:** E2E polling + live fix all happen on the box that hit load 120 today. Mitigation: run E2E in `tmux` over a pre-established SSH session; keep T4.1 caps as the follow-up; if load >15 (T4.2 ladder), pause E2E.
- **Merge-train conflicts:** `hermes-v2/*` branches all touch the same two templates (compose, role). Mitigation: T2.2 cherry-picks rather than rebases the whole stack; merge in age order (T2.3); manager reviews the combined diff, not per-branch.

---

## 5. Sequencing summary

```
NOW        T1.1 (D1 approved) ──► T1.3 E2E GREEN ──► V2-03 complete
           T1.2 (parallel, 20m)
           T2.1 slim-coincurve ─┐
           T3.1/T3.2/T3.3 gate ─┼── all parallel, local/repo only
           T4.2 alerting ───────┘
AFTER E2E  T2.2 tenant-bootstrap ──► T2.3 merge train ──► T2.4 rebuild+converge+debt-removal
           T4.1 caps+systemd (rides T2.4) ──► T4.3 post-mortem
ANYTIME    T5.1 SSD probe (cron) ──► on SSD return: T5.2 checklist ──► V2-11..14
```

**Critical path to E2E green:** D1 → T1.1 → T1.3 (≈2 h). **Critical path to V2-12 safety:** T2.1 + T2.2 → T2.3 → T5.2 rehearsal (≈1 day, parallelizable with Phase 1/3). Nothing in Phase 5 blocks Phases 1–4, and V2-12 becomes a re-run of a rehearsed, converged playbook rather than a fresh debugging session.

---

## 6. Traceability

| Pain point | Fixed by (stopgap) | Fixed by (root cause) |
|---|---|---|
| 1a config never loaded | T1.1 recreate | T2.2 image cont-init bootstrap + role template |
| 1b coincurve missing | T1.1 volume wheel + PYTHONPATH | T2.1 baked wheel + build-time sign gate + real test |
| 1c nsec PermissionError | T1.1 chown file+dir | T2.2 Ansible owner 10000 + reconcile task |
| 2 false-healthy pgrep | (E2E P2 ignores docker health) | T2.2 HTTP-only healthcheck, pgrep deleted repo-wide |
| 3 retry-budget burn | — | T3.1 gate + T3.2 pause/resume + T3.3 worker taxonomy |
| 4 VPS2 meltdown | (tmux/off-peak ops discipline) | T4.1 caps + slice guards + zram, T4.2 early alerts, T4.3 post-mortem |
| 5 SSD VPS offline | — | T5.1 probe+ticket, T5.2 rehearsal, D10 policy |
