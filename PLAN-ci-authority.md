# PLAN-ci-authority.md — single authoritative ngit-ci coordinator on the VPS

Status: in progress. Owner: operator (Felix). Extends `docs/ngit-ci.md` and
`docs/PLAN-bandwidth-ci-relocation.md`.

## Decision

- **Primary (authoritative): `hermes-nvme`** (VPS `23.182.128.219`).
- **Hot standby: `vps2` / `testserver2`** (`23.182.128.51`).
- **A single coordinator identity, `765cd47badcbbc4a38c7d0c57d5607663b484c20cd59773f9f7064487f9431e8`.**
- **Exactly one live signer** at any time, enforced by the fleet CI lease
  (`fleet-ci-task` / `scripts/fleet/ci_lease.py`) plus `ci_active_host`.
- **CI compute stays on the VPS** (per `PLAN-bandwidth-ci-relocation.md`): the
  coordinator and its dind sidecar run together on the primary.

## Finding that triggered this (relay-verified, 2026-09-30)

Two coordinators were live under the same compose project name with **different
identities**:

| Host | Coordinator pubkey | Policy | Repos |
|------|--------------------|--------|-------|
| DQ05 (local) | `765cd47bad…9431e8` (the anchor) | `automatic` | ~20 |
| hermes-nvme (VPS) | `707aa55724c37a5d…ab641e` | `request-required` | 3 |

Mapping was proven by matching each host's `Published coordinator advertisement`
log event id to the kind-19843 event author on the relay (DQ05 → `765cd47bad`,
hermes-nvme → `707aa557`). The VPS migration recreated the `coordinator-data`
volume, so the coordinator generated a **new** key instead of carrying the
authorized one. The anchor therefore stayed on the metered local network while
the VPS signed with an identity no Service Request authorizes.

## Target

```
hermes-nvme (23.182.128.219)            vps2 / testserver2 (23.182.128.51)
  coordinator (765cd47bad…)  RUNNING      coordinator (same key) STOPPED
  dind sidecar               RUNNING      dind sidecar           STOPPED
  holds the CI lease         ACTIVE       holds the volume, standby
```

## Implementation (config-as-code)

1. **Identity as a managed secret.** `ngit_ci_coordinator_nsec` is supplied from
   the fleet secret store (SOPS/age, ADR-014) or `NGIT_CI_COORDINATOR_NSEC`.
   `ngit_ci_force_identity=true` imports it into `/data/.coordinator.nsec` once
   (never on a normal run). `ngit_ci_coordinator_hex` is asserted after start.
2. **Single active signer.** `ngit_ci_is_active` = this host is `ci_active_host`.
   Non-active hosts keep the volume and config warm but the containers stopped.
3. **VPS target.** `ngit_ci_owner` defaults to `debian`; playbook 54 targets the
   `ci_runners` group; `ngit_ci_primary_host`/`ngit_ci_standby_host` in group_vars.
4. **Union watch list + policy in group_vars.** `ngit_ci_repos` is the union of
   both stacks; policy is `request-required` (DQ05's `automatic` is dropped).
5. **act-runner authority.** `act_runner` is gated by `ci_active_host` too, pins
   `act` (`act_runner_act_version`) and templates `~/.config/act/actrc`.
6. **Failover playbook** `55-ci-failover.yml`: re-run the CI roles with an
   overridden `ci_active_host`, then reconcile `ci`/`runner` DNS.
7. **Decommission the ad-hoc path.** DQ05's `~/ngit-ci-deploy` compose and its
   untracked `.env` are removed; a cold tarball of the anchor volume is retained.

## Cutover (one-time, one signer at a time)

```bash
# 1. back up the anchor volume on DQ05 (never print the nsec)
ssh c03rad0r@100.90.22.201 'docker run --rm -v ngit-ci-deploy_coordinator-data:/data \
  -v /tmp:/backup alpine tar czf /backup/anchor-coordinator-data.tgz -C /data .'

# 2. stop DQ05 so only one signer can exist
ssh c03rad0r@100.90.22.201 'cd ~/ngit-ci-deploy && docker compose down'

# 3. stage the anchor nsec in the secret store, then import on the VPS
ansible-playbook -i ansible/inventory/hosts.yml ansible/playbooks/54-ngit-ci.yml \
  -l hermes-nvme -e ngit_ci_force_identity=true

# 4. verify the VPS now advertises as the anchor
scripts/verify-ngit-ci-identity.sh
```

## Verification

- `scripts/verify-ngit-ci-identity.sh` reports the anchor hex from the latest
  kind-19843 event.
- `docker ps` shows coordinator + dind on `hermes-nvme` only; DQ05 has none.
- A test push yields kind-9842 authored by the anchor.
- Failover drill: stop the primary, run `55-ci-failover.yml -e ci_active_host=vps2`,
  confirm the standby advertises the same identity and the primary is stopped.

## Open items

- Confirm the coordinator's internal health endpoint (role verifies the container
  and the advertisement instead of inventing a URL).
- Remove `bitcoin_knots`-style unrelated drift from the ngit-ci branch before merge.
