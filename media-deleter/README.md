# buzz-media-deleter

The delete path for the AB-2 audio bridge. One HTTP call, one sha256, one delete.

**Design decision: [`docs/adr/ADR-012`](../docs/adr/ADR-012-media-deletion-via-docker-network-sidecar.md).**
Read that first — it explains why this is a sidecar rather than `mc` mounted into
the tenant containers.

## Why it exists

The `nostr.py` bridge runs inside a hardened per-tenant Hermes container with no
docker socket, no MinIO credentials, no `mc`, and (by constraint) no `ssh exec`.
It still needs to delete a voice note it has already ingested. This sidecar is the
single narrow door: it holds the credentials on the relay host, and the tenant gets
only a network call.

## Contract

```
POST http://buzz-media-deleter:8099/delete
     Authorization: Bearer <MD_AUTH_TOKEN>
     {"sha256": "<64 lowercase hex>", "ext": "<1-8 lowercase alnum>"}
```

| Response | Meaning |
|---|---|
| `200 {"deleted":[…],"count":N,"verified":true}` | listed keys deleted, re-list confirms none remain |
| `404 {"missed":true,…}` | nothing in the bucket for that sha — **treat as success**, do not retry |
| `400` | malformed sha/ext or bad JSON |
| `401` | missing/bad bearer token |
| `500` | storage error (creds/5xx/transport) — unknown state; the hourly sweep is the backstop |

`GET /healthz` → `200 {"status":"ok"}`, no auth.

## Key set

Matching is by **sha256 basename across the whole bucket** (see
[`docs/ab4-key-layout.md`](../docs/ab4-key-layout.md)), not by a hard-coded
`_meta/{community}/` path. For an audio object that resolves to exactly two keys:

```
{sha256}.{ext}                        the flat content-addressed blob
_meta/{community_uuid}/{sha256}.json  the tenant read gate (must go too)
```

Images additionally have `{sha256}.thumb.jpg`; uploads records live under
`_uploads/{community}/{sha256}/`. All are matched if present. A sha that is only a
*prefix* of another object's name is not matched, so a delete cannot take a
neighbour with it. `ext` is logged but not used for matching — a wrong `ext` cannot
cause a partial delete.

## Install (on the relay host, VPS2)

```bash
sudo ./media-deleter/install.sh                # install or upgrade
sudo ./media-deleter/install.sh --verify-only  # probe a running deployment
```

`install.sh` is idempotent. It detects the relay's compose network by inspecting
the running `buzz-relay-minio` container (the compose project prefix is not
guaranteed across a re-provision), writes `/opt/buzz-media-deleter/.env` (0600)
reusing the relay's MinIO root creds, generates `MD_AUTH_TOKEN`, builds and starts
the stack, then verifies reachability **from the tenant container** — not just from
the host — because that is the contract the bridge depends on.

Then put the generated `MD_AUTH_TOKEN` into the tenant `.env`
(`/opt/tollgate/hermes/<tenant>/.env`) and recreate the tenant.

## Configuration

| Env | Default | Notes |
|---|---|---|
| `MD_MINIO_ACCESS_KEY` / `MD_MINIO_SECRET_KEY` | — | **required**; from `/opt/buzz-relay/.env` |
| `MD_AUTH_TOKEN` | — | bearer token; unset = auth disabled (loopback/dev only) |
| `MD_MINIO_ENDPOINT` | `http://minio:9000` | service name inside the relay network |
| `MD_MINIO_BUCKET` | `buzz-media` | |
| `MD_MINIO_REGION` | `us-east-1` | |
| `MD_LISTEN_PORT` | `8099` | |
| `MD_RELAY_NETWORK` | `buzz-relay-net` | detected by `install.sh` |
| `MD_TENANT_NETWORK` | `hermes-net-sitarani` | |

## Why stdlib SigV4 instead of `mc`

Two traps the AB-4 discovery verified live in the shipped MinIO image: its baked
`local` alias at `/tmp/.mc/config.json` has **empty credentials** (`Access Denied`
on every call), and the image is **distroless** — no `grep`, `sed`, or `awk` — so
any `docker exec … sh -c 'mc ls | grep …'` design breaks. Signing in Python avoids
both and keeps this image dependency-free (no pip install at build time).

## Tests

```bash
python3 -m pytest tests/test_buzz_media_deleter.py -q
```

32 tests, no network or live MinIO. The SigV4 math is verified against **AWS's own
published test vector**, so the crypto is proven non-circularly; the HTTP layer runs
against a fake S3 (`http.server`) that records the requests it receives.
