# REPORT — t_c2948e81: ADR + implement AB-2 delete integration path

**Status: complete and pushed, awaiting review (NOT self-completed — G6).**
Branch `ab4-delete-sweep` → `felixfelix-bot/tollgate-infrastructure-kit`.

## Chosen path

**Option (b): a tiny sidecar HTTP endpoint on the docker network** —
`buzz-media-deleter`, stdlib-only Python. Option (a) (mount `mc` + alias config
into the hermes containers) was rejected:

1. It puts a general-purpose S3 client and **working MinIO credentials** inside
   every friend's container — one compromised tenant gets read/write over every
   tenant's media. Worse here because raw bytes are a shared content-addressed
   store and the community-scoped `_meta/` sidecar is the only tenant read gate.
2. It breaks on contact. The sibling discovery task (t_380adf0e) verified live
   that the alias baked into the shipped MinIO image has **empty credentials**
   (`Access Denied`) and the image is **distroless** (no `grep`/`sed`/`awk`), so
   any `docker exec … mc ls | grep …` design fails.

The sidecar keeps credentials on the relay host in one place, gives the tenant no
read capability at all, and has a blast radius of exactly one operation.

## The one-line contract

```
POST http://buzz-media-deleter:8099/delete
     Authorization: Bearer <MD_AUTH_TOKEN>
     {"sha256": "<64 lowercase hex>", "ext": "<1-8 lowercase alnum>"}
```

```python
urllib.request.urlopen(urllib.request.Request(
    "http://buzz-media-deleter:8099/delete",
    data=json.dumps({"sha256": sha256, "ext": ext}).encode(),
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {os.environ['MD_AUTH_TOKEN']}"},
    method="POST"))
```

| Response | Meaning for the bridge |
|---|---|
| `200 {"deleted":[…],"count":N,"verified":true}` | deleted **and** a re-list confirmed none remain |
| `404 {"missed":true}` | already gone — **treat as success, do not retry** |
| `400` | malformed sha/ext or bad JSON |
| `401` | missing/bad bearer token |
| `500` | storage error — unknown state; the hourly sweep is the backstop |

`GET /healthz` → `200 {"status":"ok"}`, no auth. `ext` is accepted for log
legibility but **not** used for matching: keys are matched by sha256 basename
across the whole bucket, so a wrong `ext` cannot cause a partial delete.

## Commit SHAs (pushed, verified with `git ls-remote`)

Branch `ab4-delete-sweep`:

- **`d930943`** — `feat(media-deleter): ADR-012 + docker-network sidecar as the AB-2 delete path`
  (G3: ADR + implementation in the SAME commit)
- **`57a5287`** — `test(media-deleter): container E2E for the deployed artifact + docs`
- **`c9af1b3`** — `docs(media-deleter): PROGRESS + REPORT for t_c2948e81`
- **`c1121fd`** — `fix(docs): restore repo-wide PROGRESS.md clobbered by the AB-4 notes commit`

Base is `7ec519d` (the sibling discovery task's key-layout commit).

**`c1121fd` is a repair.** `c9af1b3` replaced the repo-wide 467-line
`PROGRESS.md` (CI authority, strfry agg, follow triage, onboarding v2 history)
with 31 lines of per-task notes. That file is the repo's cross-task log, not a
per-task scratchpad, and the loss would have reached `main` at merge. The repair
restores the previous content verbatim and appends the AB-4 entry as a new
section, so `PROGRESS.md` is now `7ec519d` + 9 added lines.

## What was built

| Path | What |
|---|---|
| `docs/adr/ADR-012-media-deletion-via-docker-network-sidecar.md` | the ADR: context, both options, decision, contract, consequences, follow-ups |
| `docs/adr/README.md` | index entry |
| `media-deleter/buzz_media_deleter.py` | the sidecar (stdlib SigV4 via hmac/hashlib, no `mc`, no deps) |
| `media-deleter/Dockerfile` | python:3.13-slim, non-root uid 10001, healthcheck, no pip install |
| `media-deleter/docker-compose.yml` | attached to relay net + tenant net, **no host port**, read_only |
| `media-deleter/install.sh` | idempotent; detects the relay network from the live minio container; reuses relay MinIO creds; generates `MD_AUTH_TOKEN`; verifies reachability **from the tenant container** |
| `media-deleter/README.md`, `.env.example` | operator docs |
| `media-deleter/e2e-container-test.sh`, `media-deleter/tests/fake_s3.py` | container E2E |
| `tests/test_buzz_media_deleter.py` | 32 unit tests |
| `ansible/roles/buzz_media_deleter/`, `ansible/playbooks/53-buzz-media-deleter.yml` | reproducible deploy |

Key-set derivation lists the bucket and matches the sha256 basename — correct for
a multi-community future and immune to a new audio extension the sweep's regex
would not know (`docs/ab4-key-layout.md` §9.1–9.2). A sha that merely *prefixes*
another object's name is not matched.

## Verification (real output, re-run on this branch tip)

```
$ python3 -m pytest tests/test_buzz_media_deleter.py -q
32 passed in 14.32s

$ cd ansible && ansible-playbook --syntax-check playbooks/53-buzz-media-deleter.yml
playbook: playbooks/53-buzz-media-deleter.yml        # exit 0
   (must be run from ansible/ so ansible.cfg's roles_path=roles applies;
    from the repo root the role is not found — same as every other playbook here)

$ shellcheck media-deleter/install.sh   → clean
$ docker compose -f media-deleter/docker-compose.yml config   → valid
```

SigV4 is verified against **AWS's own published test vector**, not a round-trip
against our own signer. The container E2E (16/16, per `c9af1b3`) builds the real
image and drives the contract from a *separate* container over a docker network,
which is the tenant's actual view.

Secret scan over `7ec519d..HEAD` is clean: the only `MINIO_ROOT_PASSWORD` hit is
`install.sh` reading it out of `/opt/buzz-relay/.env` at install time
(`grep … | cut -d= -f2-`); no credential literal is committed, and
`.env.example` ships every secret blank.

## Honest caveats

1. **`~/plans/audio-bridge-p1-design.md` does not exist on this machine.** The
   sibling discovery task located it on `cobrador`, not DQ05. Ground truth came
   from the sibling cards and the verified `docs/ab4-key-layout.md`, which is the
   artifact §E asked that task to produce. Nothing in the ADR depends on
   unverified §E prose.
2. **VPS2 is unreachable from here**, so the sidecar **has not been deployed and
   no live run against real MinIO has happened.** `install.sh` and playbook 53 are
   ready but unrun against the live host. All verification above is local.
3. **The sidecar reuses the relay's MinIO root credentials.** A least-privilege
   user cannot be provisioned today (`mc admin user list` → `Access Denied`).
   Flagged as ADR follow-up #1 and `docs/ab4-key-layout.md` §9.3 — an **ops
   decision**, not something this card can resolve.
4. **Not done (out of scope):** `MD_AUTH_TOKEN` is not yet wired into the tenant
   `.env` by the `hermes_tenants` role (ADR follow-up #3); the host delete script
   and hourly sweep cron belong to sibling cards t_f8266a92 / t_b5fa6bb9.

## For the reviewer

- Read `docs/adr/ADR-012-media-deletion-via-docker-network-sidecar.md` first —
  the decision and its consequences are the deliverable.
- The thing worth attacking: is root-cred reuse acceptable given tenant-network
  isolation, or must follow-up #1 block deployment?
- Reproduce: `python3 -m pytest tests/test_buzz_media_deleter.py -q` (32 pass),
  `bash media-deleter/e2e-container-test.sh` (16 pass).
