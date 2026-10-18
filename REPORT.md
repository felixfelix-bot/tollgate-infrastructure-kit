# REPORT — t_c2948e81: ADR + implement AB-2 delete integration path

**Status: implementation complete, pushed, awaiting review (NOT self-completed — G6).**

## Chosen path

**Option (b): a tiny sidecar HTTP endpoint on the docker network** —
`buzz-media-deleter`, a stdlib-only Python service. Not option (a).

Why (a) — mounting a minimal `mc` + alias config into the hermes containers — was
rejected:

1. **It puts working MinIO credentials inside every friend's container.** `mc` is a
   general-purpose S3 client: it can `ls`, `cat`, `cp`, and `rm` the whole bucket.
   One compromised tenant would get read/write over every other tenant's media.
   That is worse here than usual because raw media bytes are a *shared
   content-addressed store* (`{sha}.{ext}` with no community prefix) and the
   community-scoped `_meta/` sidecar is the only tenant read gate.
2. **It breaks on contact, per the sibling discovery task's live findings**
   (`docs/ab4-key-layout.md`): the alias baked into the shipped MinIO image
   (`/tmp/.mc/config.json`) has **empty credentials** and returns `Access Denied`,
   and the image is **distroless** (no `grep`/`sed`/`awk`), so any
   `docker exec … sh -c 'mc ls | grep …'` design fails. Seeding a working alias
   config means writing credentials to a file every tenant can read.

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
| `200 {"deleted":[…],"count":N,"verified":true}` | deleted **and** re-list confirmed none remain |
| `404 {"missed":true}` | already gone — **treat as success, do not retry** |
| `400` | malformed sha/ext or bad JSON |
| `401` | missing/bad bearer token |
| `500` | storage error — unknown state; the hourly sweep is the backstop |

`GET /healthz` → `200 {"status":"ok"}`, no auth.

`ext` is accepted for log legibility but **not** used for matching: keys are
matched by sha256 basename across the whole bucket, so a wrong `ext` cannot cause
a partial delete.

## Commit SHAs (pushed, verified with `git ls-remote`)

Branch `ab4-delete-sweep` on `felixfelix-bot/tollgate-infrastructure-kit`:

- **`d930943`** — `feat(media-deleter): ADR-012 + docker-network sidecar as the AB-2 delete path`
  (G3: ADR + implementation in the SAME commit)
- **`57a5287`** — `test(media-deleter): container E2E for the deployed artifact + docs`

`git ls-remote --heads origin ab4-delete-sweep` → `57a5287ed938665d49d4f6a75066e76826225696`
(base `7ec519d`, the sibling discovery task's key-layout commit).

## What was built

| Path | What |
|---|---|
| `docs/adr/ADR-012-media-deletion-via-docker-network-sidecar.md` | the ADR: context, both options, decision, contract, consequences, follow-ups |
| `docs/adr/README.md` | index entry |
| `media-deleter/buzz_media_deleter.py` | the sidecar (stdlib SigV4 via hmac/hashlib, no `mc`, no deps) |
| `media-deleter/Dockerfile` | python:3.13-slim, non-root uid 10001, healthcheck, no pip install |
| `media-deleter/docker-compose.yml` | attached to relay net + tenant net, **no host port**, read_only |
| `media-deleter/install.sh` | idempotent install; detects the relay network from the live minio container; reuses relay MinIO creds; generates `MD_AUTH_TOKEN`; verifies reachability **from the tenant container** |
| `media-deleter/README.md`, `.env.example` | operator docs |
| `media-deleter/e2e-container-test.sh`, `media-deleter/tests/fake_s3.py` | container E2E |
| `tests/test_buzz_media_deleter.py` | 32 unit tests |
| `ansible/roles/buzz_media_deleter/`, `ansible/playbooks/53-buzz-media-deleter.yml` | reproducible deploy (ansible syntax-check passes) |

Key-set derivation lists the bucket and matches the sha256 basename — correct for
a multi-community future and immune to a new audio extension the sweep's regex
would not know (`docs/ab4-key-layout.md` §9.1–9.2). A sha that merely *prefixes*
another object's name is not matched.

## Verification (real output)

**Unit tests — 32/32 pass, no network or live MinIO:**
```
$ python3 -m pytest tests/test_buzz_media_deleter.py -q
................................                                         [100%]
32 passed in 13.12s
$ python3 -m unittest tests.test_buzz_media_deleter
Ran 32 tests in 12.594s
OK
```
Notable: the SigV4 math is verified against **AWS's own published test vector**
(`GET https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08`,
`20150830T123600Z`, expected signature `5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7`)
— non-circular proof, not a round-trip against my own signer. Also covered:
blob+sidecar, image thumb, `_uploads/` prefix, other-community sidecar, miss,
prefix-collision rejected, `verified:false` surfaced, 500→`StorageError`,
auth 401/200, path traversal in `ext` → 400.

**Container E2E — 16/16 pass** (real image, real HTTP, driven from a *separate*
container by service name — the tenant's actual view; fake S3 is a container too):
```
PASS  image built
PASS  sidecar container started
PASS  healthz 200 inside the sidecar
PASS  healthz 200 from a separate container (by service name)
PASS  no token -> 401
PASS  wrong token -> 401
PASS  valid token -> 200 (200, '{"deleted": ["0f24d724….m4a",
      "_meta/a3312780-…/0f24d724….json"], "count": 2, "verified": true, "remaining": []}')
PASS  re-delete -> 404 (objects really gone, not just acked)
PASS  malformed sha -> 400
PASS  path-traversal ext -> 400
PASS  unknown path -> 404
PASS  exactly the blob + sidecar were deleted (no neighbour touched)
PASS  neighbour object untouched.mp3 was never deleted
PASS  runs as non-root (uid 10001)
PASS  image has an expected /app layout
=== ALL CONTAINER E2E CHECKS PASSED ===
```
The delete assertions read the fake S3's own DELETE log, so they verify the wire
traffic rather than restating the response body.

**Gates:** credential gate (fleet `~/.git-hooks`) ran and **passed** on both
commits — no `--no-verify`, allowlist untouched. Ansible `--syntax-check` passes;
`docker compose config` validates; `shellcheck` clean on `install.sh`.

## Honest caveats

1. **`~/plans/audio-bridge-p1-design.md` does not exist on this machine** (no
   `~/plans` at all; also absent from the repo and from session history). I could
   not read §E as instructed. Ground truth was instead taken from the sibling
   cards' bodies and the discovery task's verified `docs/ab4-key-layout.md`, which
   is the artifact §E asked that task to produce. Nothing in the ADR depends on
   unverified §E prose.
2. **VPS2 (23.182.128.51) is unreachable from here** — `ssh` times out, so no live
   MinIO probe was possible. All verification is local (unit + real-container E2E).
   **The sidecar has not been deployed to VPS2 and no live end-to-end run against
   real MinIO has been performed.** `install.sh` / playbook 53 are ready but unrun
   against the live host.
3. **The sidecar currently reuses the relay's MinIO root credentials.** The
   discovery task verified `mc admin user list` returns `Access Denied`, so a
   least-privilege `s3:ListBucket`+`s3:DeleteObject` user cannot be provisioned
   today without an ops change. This is flagged as follow-up #1 in the ADR and is
   an **ops decision**, not something this task could resolve.
4. **Two host quirks worked around** (documented in the E2E script): attached
   `docker run` with redirected stdout hangs ~2 min after printing (reproduced on
   plain `python:3.13-slim`, so it is the host, not this image) — the script uses
   detached run + `docker wait`; and the script pre-cleans its container/network
   names so an interrupted run does not break the next one.
5. **Not done (out of scope for this card):** the tenant `.env` is not yet wired
   with `MD_AUTH_TOKEN` by the `hermes_tenants` role (ADR follow-up #3); the host
   delete script and hourly sweep cron belong to the sibling cards t_f8266a92 /
   t_b5fa6bb9, not here.

## For the reviewer

- Read `docs/adr/ADR-012-media-deletion-via-docker-network-sidecar.md` first —
  the decision and its consequences are the deliverable.
- The one thing worth attacking: is the sidecar's root-cred reuse acceptable
  given the tenant-network isolation, or must follow-up #1 block deployment?
- Reproduce: `python3 -m pytest tests/test_buzz_media_deleter.py -q` (32 pass),
  `bash media-deleter/e2e-container-test.sh` (16 pass).
