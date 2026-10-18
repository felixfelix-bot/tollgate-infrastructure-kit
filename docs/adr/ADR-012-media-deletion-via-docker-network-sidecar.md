# ADR-012: Media deletion for the audio bridge via a docker-network sidecar

- **Date:** 2026-10-18
- **Status:** Accepted
- **Task:** kanban `t_c2948e81` (AB-4 integration hook; parent `t_b5fa6bb9`)
- **Related:** `docs/ab4-key-layout.md` (key layout), `PATCHES.md` (relay audio patch),
  `docs/nostr-audio-ingest.md` (AB-2 bridge, in the hermes-agent repo)

## Context

The AB-2 audio bridge in `gateway/platforms/nostr.py` ingests voice notes: it
detects an audio attachment on a kind-9 message, downloads it from the relay's
Blossom path, transcribes it, and replaces the message text with the transcript.
Transient audio must not accumulate, so AB-4 adds a delete lifecycle: a helper
script and an hourly sweep on the relay host, plus a way for the bridge itself
to delete a clip it has already ingested.

That last part is the hard one. The bridge runs **inside a hardened per-tenant
Hermes container**, and that container deliberately has:

- **no docker socket** (`hermes_tenants_no_docker_socket: true` — the tenant
  compose template sets `no-new-privileges` and mounts no `/var/run/docker.sock`),
- **no MinIO credentials** (the relay's `.env` is on the host, not in the tenant),
- **no `mc` binary** and no host filesystem access,
- and, per the task constraint, **no `ssh exec`**: shelling out of the tenant
  container to the relay host is explicitly not allowed.

So the bridge cannot run `docker exec buzz-relay-minio mc rm …` itself, which is
the natural shape the AB-4 script uses on the host. It needs a narrow, network-only
door to the same operation.

Deletion is also not a single-object operation. Per `docs/ab4-key-layout.md` an
audio object is a flat content-addressed blob `{sha256}.{ext}` **plus** a
community-scoped metadata sidecar `_meta/{community_uuid}/{sha256}.json`, and the
sidecar is the tenant read gate — deleting the blob alone leaves a dangling
binding that the bucket sweep reports as `orphan_sidecar_count`.

## Options considered

### (a) Mount a minimal `mc` binary + alias config into the hermes containers

Bake `mc` into the tenant image and mount a pre-seeded alias config.

Rejected. It puts a general-purpose S3 client and **working MinIO credentials**
inside every friend's container. That inverts the security posture of the tenant
design: `mc` can `ls`, `cat`, `cp`, and `rm` the whole bucket, so one compromised
tenant gets read/write over every other tenant's media — the shared content-addressed
store makes this worse, since raw bytes are shared across communities and the
sidecar is the only gate. It also has two concrete operational traps the AB-4
discovery verified live: the alias baked into the shipped MinIO image
(`/tmp/.mc/config.json`) has **empty credentials** and returns `Access Denied`,
and that image is **distroless** (no `grep`/`sed`/`awk`), so any `docker exec …
sh -c 'mc ls | grep …'` design breaks. Seeding a working alias config means
writing credentials to a mounted file that every tenant can read.

### (b) A tiny sidecar HTTP endpoint on the tenant's docker network

A single-purpose service that holds the credentials, accepts one sha256, and
performs the delete.

**Chosen.** The credentials stay on the relay host in one place, the tenant gets
only an HTTP call, and the blast radius is one operation (`delete` by sha256) with
no read capability at all.

## Decision

Deploy **`buzz-media-deleter`**: a stdlib-only Python sidecar
(`media-deleter/buzz_media_deleter.py`) attached to **both** the relay's compose
network and the tenant's `hermes-net-<tenant>` network, published on **no host
port**.

The sidecar talks S3 directly with **stdlib SigV4** (`hmac`/`hashlib`) rather than
shelling out to `mc`. That sidesteps both `mc` traps above (the empty alias, and
the distroless image's missing text tools) and keeps the image dependency-free.

The key set is derived by **listing the bucket and matching the sha**, not by
hard-coding `_meta/{community_uuid}/`. This is the AB-4 discovery's recommendation
for two reasons: it is already correct for a multi-community future, and it is
immune to a new audio extension the sweep's `--regex` allowlist would not know
about.

### The one-line contract the nostr.py bridge uses

```python
urllib.request.urlopen(urllib.request.Request(
    "http://buzz-media-deleter:8099/delete",
    data=json.dumps({"sha256": sha256, "ext": ext}).encode(),
    headers={"Content-Type": "application/json",
             "Authorization": f"Bearer {os.environ['MD_AUTH_TOKEN']}"},
    method="POST"))
```

- **Endpoint:** `POST http://buzz-media-deleter:8099/delete` (service name on the
  tenant's docker network; `MD_LISTEN_PORT` overrides `8099`).
- **Body:** `{"sha256": "<64 lowercase hex>", "ext": "<1-8 lowercase alnum>"}` —
  exactly the `sha256` and `ext` the bridge already parsed from the `imeta` tag or
  the `/media/{sha256}.{ext}` URL.
- **Auth:** `Authorization: Bearer <MD_AUTH_TOKEN>`. The token is required
  whenever `MD_AUTH_TOKEN` is set on the sidecar; an unset token disables the
  check (loopback/dev only).
- **Success:** `200 {"deleted": [...], "count": N, "verified": true}` — the listed
  keys were deleted **and** a re-list confirmed none remain.
- **Already gone:** `404 {"missed": true, …}`. The bridge treats this as success:
  the clip is not there, which is the desired end state. Do not retry.
- **Errors:** `400` malformed sha/ext or bad JSON, `401` missing/bad token,
  `500` storage error (creds/5xx/transport). A `500` means *unknown state* — the
  bridge logs it and falls through to the user-facing reply; the hourly sweep is
  the backstop.
- `GET /healthz` → `200 {"status": "ok"}`, no auth — used by the healthcheck and
  by `install.sh --verify-only` to prove DNS + network wiring from the tenant.

The `ext` argument is accepted (the bridge has it for free and it makes request
logs legible) but is **not** used for key matching — matching is by sha256
basename across the whole bucket, so a wrong `ext` cannot cause a partial delete.

## Consequences

- **The tenant never holds S3 credentials.** The only secret it needs is
  `MD_AUTH_TOKEN`, and that token authorizes exactly one operation.
- **The sidecar reuses the relay's MinIO root creds**, read from
  `/opt/buzz-relay/.env` by `install.sh` rather than minting a second identity.
  This is a deliberate trade: the AB-4 discovery verified that `mc admin user list`
  with those creds returns `Access Denied`, so a least-privilege `s3:ListBucket` +
  `s3:DeleteObject` user **cannot be provisioned today** without an ops change to
  the MinIO container. Reusing root creds keeps the deployment shippable now, at
  the cost of the sidecar being able to do anything the relay can. This is the one
  item flagged as needing an ops decision in `docs/ab4-key-layout.md` §9.3 and it
  remains open — see "Follow-ups".
- **Deployment is two-network by construction.** If the sidecar is not attached to
  `hermes-net-<tenant>`, the bridge gets a DNS failure; `install.sh` detects the
  relay network from the running `buzz-relay-minio` container (the compose project
  prefix is not guaranteed across a re-provision) and verifies reachability **from
  the tenant container**, not just from the host.
- **No host port is published**, so the sidecar is not reachable from the internet
  or from other tenants' networks — only the relay network and the one tenant.
- **Failure is non-fatal to ingestion.** A failed delete leaves the clip in place;
  the hourly sweep still removes it an hour later. The bridge never blocks a reply
  on a delete.
- **A wrong `ext` cannot cause data loss** (matching is sha-basename-scoped), and
  a sha that is a strict prefix of another object's name is not matched — verified
  by test `test_prefix_sharing_sha_is_not_matched`.
- **`verified: false` is possible and meaningful.** A store that accepts a DELETE
  without removing the object surfaces as `verified: false` rather than a silent
  success (`test_verify_failure_is_reported_not_hidden`).
- **The host-side script and the sweep remain the primary path.** This sidecar is
  the *integration hook*, not a replacement for `scripts/buzz-media-delete.sh` or
  `/etc/cron.d/buzz-media-sweep`; the sweep is what guarantees eventual deletion.

## Testing

`tests/test_buzz_media_deleter.py` — 32 tests, no network or live MinIO required:

- **SigV4 math against AWS's own published test vector**
  (`GET https://iam.amazonaws.com/?Action=ListUsers&Version=2010-05-08`,
  `20150830T123600Z`, expected signature `5d672d79…`) — non-circular proof that the
  canonical-request/signature derivation is right.
- **Key matching**: blob + sidecar, image thumb, `_uploads/` prefix, other-community
  sidecar, no-match (miss), prefix-sharing sha rejected, bare-hash key.
- **End-to-end HTTP** against a fake S3 (`http.server`) that records requests:
  happy path, neighbour object survives, miss → 404, SigV4 headers on the wire,
  `verified: false` surfaced, 500 → `StorageError`.
- **Handler surface**: `/healthz` unauthenticated, `200`/`404`/`400`/`401`/`405`,
  bad JSON, bad sha, bad ext, path traversal in `ext` rejected.
- **Config from env** incl. garbage-port fallback, and URI encoding of key segments.

## Follow-ups

1. Provision a least-privilege MinIO user (`s3:ListBucket`, `s3:DeleteObject` on
   `buzz-media`) and switch `MD_MINIO_ACCESS_KEY`/`_SECRET_KEY` to it, so the
   sidecar stops running as root-equivalent. Blocked on `mc admin` being usable;
   needs an ops decision.
2. Decide whether the bridge should delete eagerly on ingest-complete (current
   contract) or defer entirely to the hourly sweep. Eager delete is what the
   contract above assumes; if AB-5 measures that clips are needed after ingest,
   the bridge should simply stop calling `/delete` and no sidecar change is needed.
3. Wire `MD_AUTH_TOKEN` into the tenant `.env` via the `hermes_tenants` role so a
   fresh tenant comes up with the contract working, rather than requiring a manual
   step.
