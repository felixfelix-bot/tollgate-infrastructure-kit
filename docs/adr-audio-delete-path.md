# ADR: media delete path for the AB-2 audio bridge

- **Date:** 2026-10-18
- **Status:** Accepted
- **Task:** kanban `t_c2948e81`
- **Canonical record:** [`docs/adr/ADR-012-media-deletion-via-docker-network-sidecar.md`](adr/ADR-012-media-deletion-via-docker-network-sidecar.md)

This file exists because card `t_c2948e81` names `docs/adr-audio-delete-path.md`
as its deliverable path. The full ADR follows the repo's numbering convention and
lives in `docs/adr/` like ADR-001…ADR-011; this page is the short form plus a
pointer, so the card's path resolves to the real decision.

## Context

The AB-2 bridge in `gateway/platforms/nostr.py` ingests a voice note, transcribes
it, and must then delete the transient audio. It runs inside a hardened per-tenant
container with **no docker socket, no MinIO credentials, no `mc`, no host
filesystem access, and — by constraint — no `ssh exec`**. So it cannot run the
host-side `docker exec buzz-relay-minio mc rm …` that the AB-4 script uses.

Deletion is also not one object: an audio clip is a flat content-addressed blob
`{sha256}.{ext}` **plus** a community-scoped sidecar `_meta/{community_uuid}/{sha256}.json`
(see `docs/ab4-key-layout.md`). Deleting the blob alone leaves a dangling binding.

## Options

**(a) Mount a minimal `mc` binary + alias config into the hermes containers.**
Rejected. It puts a general-purpose S3 client and working MinIO credentials inside
every friend's container, so one compromised tenant gets read/write over every
tenant's media — worse here because raw bytes are a shared content-addressed store
and the sidecar is the only tenant read gate. It also breaks on contact: the alias
baked into the shipped MinIO image has empty credentials and returns `Access
Denied`, and that image is distroless (no `grep`/`sed`/`awk`), so any
`mc ls | grep` design fails.

**(b) A tiny sidecar HTTP endpoint on the docker network.** **Chosen.**

## Decision

Deploy **`buzz-media-deleter`** (`media-deleter/buzz_media_deleter.py`): a
stdlib-only Python service that speaks S3 directly via SigV4 (`hmac`/`hashlib`) —
no `mc`, no pip install — attached to both the relay compose network and
`hermes-net-<tenant>`, publishing **no host port**. It derives the key set by
listing the bucket and matching the sha256 basename, which is correct for a
multi-community future and immune to an audio extension the sweep's regex would
not know; a sha that merely *prefixes* another object's name is not matched.

## The one-line contract

```
POST http://buzz-media-deleter:8099/delete
     Authorization: Bearer <MD_AUTH_TOKEN>
     {"sha256": "<64 lowercase hex>", "ext": "<1-8 lowercase alnum>"}
```

| Response | Meaning for the bridge |
|---|---|
| `200 {"deleted":[…],"count":N,"verified":true}` | deleted **and** a re-list confirmed none remain |
| `404 {"missed":true}` | already gone — **treat as success, do not retry** |
| `400` | malformed sha/ext or bad JSON |
| `401` | missing/bad bearer token |
| `500` | storage error, unknown state — the hourly sweep is the backstop |

`GET /healthz` → `200 {"status":"ok"}`, no auth. `ext` is accepted for log
legibility but not used for matching, so a wrong `ext` cannot cause a partial
delete.

## Consequences

- The tenant never holds S3 credentials; its only secret authorizes one operation.
- Credentials stay on the relay host in one place; blast radius is a single delete
  by sha256, with no read capability.
- A failed delete is non-fatal: the clip stays and the hourly sweep removes it.
  The bridge never blocks a reply on a delete.
- The sidecar currently reuses the relay's MinIO root credentials, because a
  least-privilege user cannot be provisioned today (`mc admin user list` →
  `Access Denied`). Flagged as ADR-012 follow-up #1 — an ops decision.
- `MD_AUTH_TOKEN` is not yet wired into the tenant `.env` by the `hermes_tenants`
  role (follow-up #3).
