# AB-4 findings — MinIO `mc` key layout for buzz-media blobs + sidecars

**Status:** VERIFIED against live VPS2 (testserver2, `23.182.128.51`) + source on 2026-10-18.
**Task:** kanban `t_380adf0e` (discovery for AB-4 delete/sweep, parent `t_b5fa6bb9`).
**Resolves:** the IMPLEMENTATION NOTE in `~/plans/audio-bridge-p1-design.md` §E
("exact key layout to confirm in `crates/buzz-media/src/upload.rs` / `bucket_index.rs`")
and the `Assumptions / unverified items` bullet "S3 key layout (`<sha256>` + ext sidecar naming)".

Audience: whoever writes `scripts/buzz-media-delete.sh` and the hourly sweep.
**You do not need to read the Rust source to implement the delete script** — everything
load-bearing is below, with file:line citations for anyone who wants to re-verify.

---

## 0. TL;DR — the five facts that matter

```
bucket            local/buzz-media                       (MinIO alias `local`, bucket `buzz-media`)
blob key          {sha256}.{ext}                         e.g. 0f24d7….m4a     <- FLAT, no prefix
sidecar key       _meta/{community_uuid}/{sha256}.json    e.g. _meta/a3312780-….json
thumb key         {sha256}.thumb.jpg                      IMAGE ONLY — never exists for audio
upload records    _uploads/{community_uuid}/{sha256}/{ULID}.json   OFF by default on VPS2
community uuid    a3312780-4cfe-48eb-af8a-f405f369a4f8   (single community: relay.orangesync.tech)
```

For an **audio** object the complete delete set is exactly **two keys**: the flat blob
and the `_meta/` sidecar. No thumb, no `_uploads/` record (feature disabled on VPS2),
no `repos/` pointer, and **no database row** (migrations 0001–0030 contain no media/blob
table — deletion is S3-object-only, no psql step).

Two findings that change how the delete script must be written:

1. The spec's literal command `docker exec buzz-relay-minio mc rm --force local/buzz-media/<key>`
   **does not work** — the image's baked `local` alias has empty credentials and every call
   returns `Access Denied`. Use the `MC_HOST_` form in §6.2.
2. An auth'd GET returning **404 does not prove the delete worked**. A half-delete (blob
   gone but sidecar left, or vice versa) also returns 404. The script must assert both
   objects are absent via `mc stat`, then check the HTTP 404 (§8.1).

---

## 1. Bucket

- Bucket name: **`buzz-media`** — created by the `buzz-relay-minio-init` one-shot container.
- Credentials on VPS2 are static MinIO root creds (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`
  in the `buzz-relay-minio` container env), and the relay reaches it at
  `BUZZ_S3_ENDPOINT=http://minio:9000` with `BUZZ_S3_ADDRESSING_STYLE=path`,
  `BUZZ_S3_BUCKET=buzz-media`, `BUZZ_S3_REGION=us-east-1`.
- Bucket is **private** (`mc anonymous get` → `Access permission for 'loc/buzz-media' is 'private'`)
  and **un-versioned** (`mc version info` → `is un-versioned`). Un-versioned matters:
  a plain delete is a real delete, not a delete-marker.
- No host ports are published; the only way in is `docker exec` inside the compose network.

## 2. Blob key — flat, `{sha256}.{ext}`

Written in `crates/buzz-media/src/upload.rs:91`:
```rust
let key = format!("{sha256}.{ext}");
```
`sha256` is lowercase hex of the raw bytes (computed in the same function, `upload.rs:83`),
`ext` is the canonical extension derived from the validated MIME (images: `mime_to_ext`;
generic/audio files: from the deny-list validator). The blob is a **shared
content-addressed store**: the key has **no community prefix and no directory**. It is a
single flat object at the bucket root.

Live proof (`mc ls --recursive local/buzz-media/`, 48 objects, 2026-10-18):
```
[2026-08-16 00:26:03 UTC]  81KiB STANDARD 0f24d7241fcf5c7ec2e2ec53104bbac05679f2745d7c52fd5b6ed598fc69728b.m4a
[2026-10-01 03:58:01 UTC]  24KiB STANDARD 006c5bbc6a717ba97b8e00a28f546d91586794ec17c054f1ef3a6fd55f26ef49.mp3
```
`mc stat` on the first:
```
Name      : 0f24d724….m4a
Date      : 2026-08-16 00:26:03 UTC
Size      : 81 KiB
Metadata  :
  Content-Type: audio/mp4
```

Extension is **not** guessable in general (`.bin` exists, `.Z` is legal per
`bucket_index.rs:81-86`), so the delete script must either take the exact
`sha256.ext` as its argument or discover keys with `mc find --name "<sha>. *"`.

## 3. Sidecar key — `_meta/{community_uuid}/{sha256}.json`

`crates/buzz-media/src/storage.rs:227-229`:
```rust
pub fn sidecar_key(community: CommunityId, sha256: &str) -> String {
    format!("_meta/{community}/{sha256}.json")
}
```
and the upload pipeline derives it from the **resolved request tenant**
(`upload.rs:92`, `MediaStorage::ctx_sidecar_key(ctx, &sha256)`).

The sidecar is the **tenant read gate**: raw bytes are shared CAS across communities, but
a blob is only servable to a tenant that has a sidecar binding under that tenant's
community UUID. This is why the community UUID must be part of the delete path, and why
"delete the blob" without "delete the sidecar" leaves a dangling binding that the
buckets-weep reports as `orphan_sidecar_count` (`bucket_index.rs:300-304`).

Live proof:
```
_meta/a3312780-4cfe-48eb-af8a-f405f369a4f8/0f24d7241fcf5c7ec2e2ec53104bbac05679f2745d7c52fd5b6ed598fc69728b.json   113 B
```
Sidecar content for an audio object (note `thumb_url` is the empty string, and
`uploaded_at` is a **unix timestamp integer**):
```json
{"dim":"","blurhash":"","thumb_url":"","ext":"m4a","mime_type":"audio/mp4","size":83170,"uploaded_at":1786839963}
```
Sidecar content for an image (thumb fields populated):
```json
{"dim":"1200x600","blurhash":"L9Ryvq4.?a?b~owbSixatB%hI9Io","thumb_url":"https://relay.orangesync.tech/media/0db5b803….thumb.jpg","ext":"jpg","mime_type":"image/jpeg","size":67844,"uploaded_at":1789133391}
```

### 3.1 Where the community UUID comes from

On VPS2 there is exactly **one** community:
```sql
select id, host from communities;
-- a3312780-4cfe-48eb-af8a-f405f369a4f8 | relay.orangesync.tech
```
Resolve it at runtime rather than hard-coding, so the script survives a re-provisioned
relay:
```sh
docker exec buzz-relay-postgres psql -U "$(docker exec buzz-relay-postgres printenv POSTGRES_USER)" \
  -d "$(docker exec buzz-relay-postgres printenv POSTGRES_DB)" -tAc \
  "select id from communities where host = 'relay.orangesync.tech'"
```
Alternative discovery that needs no DB and no UUID knowledge (recommended for the
delete script, because it is also correct for a multi-community future) — let `mc find`
enumerate every key whose basename starts with the sha:
```sh
docker exec buzz-relay-minio mc find local/buzz-media --name "<sha256>.*"
# ->
# local/buzz-media/0f24d724….m4a
# local/buzz-media/_meta/a3312780-…/0f24d724….json
```
**VERIFIED**: `mc find` with a glob matches at any depth and exits `0` even when nothing
matches (empty output) — so it is safe to run unconditionally, but its exit code cannot
be used to detect a miss. Detect a miss from empty output instead.

## 4. Thumbnail key — `{sha256}.thumb.jpg` (images only)

Set at `crates/buzz-relay/src/api/media.rs:515` (`descriptor.thumb = Some(format!("{base}/{}.thumb.jpg", …))`),
generated in `crates/buzz-media/src/thumbnail.rs:43`. Thumbs are **only** produced for
`image/*` (`thumbnail.rs:18-20` returns no thumb for any other MIME), and the extension is
always `.jpg`. Classification order in `bucket_index.rs:54-60` matches thumb **before**
blob, because `{sha}.thumb.jpg` has three dot-segments.

For the AB-4 audio path a thumb **never exists** — verified: zero `*.thumb.jpg` objects in
the bucket share a sha with any audio object. The delete script should still remove
`{sha256}.thumb.jpg` opportunistically (ignore-missing) so the same script is correct for
a mixed image/audio set.

## 5. `_uploads/` records — disabled on VPS2

Key shape (`crates/buzz-media/src/upload_record.rs:181-183`):
```rust
format!("_uploads/{}/{sha256}/{event_id}.json", ctx.community())   // event_id = ULID
```
This is a **prefix per sha** (one record per accepted upload event), not a single key.
Entirely gated behind `BUZZ_MEDIA_UPLOAD_RECORDS`, which is **unset on VPS2**
(verified: `docker exec buzz-relay printenv | grep UPLOAD_RECORDS` → nothing), and the
`_uploads/` prefix is **empty** in the live bucket. So: no action needed, but a
future-proof delete should `mc rm --recursive --force` that prefix if it exists.
**VERIFIED**: `mc rm --recursive --force` on a non-existent prefix exits `0` (idempotent),
unlike single-object `mc rm` which exits `1`.

## 6. Copy-pasteable delete commands

### 6.1 The command shape in the task spec does NOT work

The spec's literal command —
```sh
docker exec buzz-relay-minio mc rm --force local/buzz-media/<key>
```
— **fails on VPS2**. The `local` alias baked into the minio image at `/tmp/.mc/config.json`
has **empty credentials**, so every S3 call returns
`Access Denied` / `Insufficient permissions to access this path`, exit `1`. VERIFIED live:
```
$ docker exec buzz-relay-minio mc rm --force local/buzz-media/9999….mp3
mc: <ERROR> Failed to remove `…`. Insufficient permissions to access this path
rc=1
```
(The `mc` in the image reads `MC_CONFIG_DIR=/tmp/.mc`; `/tmp/.mc/config.json` is seeded with
`gcs`/`local`/`play`/`s3` aliases where `local` has `accessKey: ""`. The root creds live in
the container env, **not** in that file.)

### 6.2 Working shape — pass creds via `MC_HOST_` (no file written, no creds in `ps`)

Read the creds from the container's own env and inject them as an `MC_HOST_<alias>` URL.
This is the recommended form for the delete script: no alias state is mutated, nothing
persists on disk, and the secret never appears in the host's process table (it is expanded
inside the `docker exec` environment).

```sh
# Resolve creds from the container itself, then delete blob + sidecar + thumb(if any).
C=buzz-relay-minio
SHA=<64-hex-lowercase>
COMM=a3312780-4cfe-48eb-af8a-f405f369a4f8        # or resolve from psql, see 3.1
EXT=m4a                                            # or discover via mc find

U=$(docker exec $C printenv MINIO_ROOT_USER)
P=$(docker exec $C printenv MINIO_ROOT_PASSWORD)
MCX="docker exec -e MC_HOST_local=http://${U}:${P}@localhost:9000 $C mc"

# 1) blob
$MCX rm --force "local/buzz-media/${SHA}.${EXT}"
# 2) sidecar
$MCX rm --force "local/buzz-media/_meta/${COMM}/${SHA}.json"
# 3) thumb (images only; absent for audio -> non-zero exit, ignore)
$MCX rm --force "local/buzz-media/${SHA}.thumb.jpg" || true
```
**VERIFIED** end-to-end with a synthetic sha: both objects removed, `rc=0`, and a
subsequent `mc stat` on each returned non-zero.

### 6.3 Alternative shape — `sh -c` alias-set from env

Equivalent, and the cleanest if you prefer `local` to stay the alias name used throughout
the script. Creds are expanded **inside** the container, so they never touch the host
command line:
```sh
docker exec $C sh -c '
  mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null 2>&1
  mc rm --force "local/buzz-media/'"$SHA.$EXT"'" "local/buzz-media/_meta/'"$COMM/$SHA"'.json"
'
```
**VERIFIED** `rc=0`. Caveat: this **writes** `/tmp/.mc/config.json` inside the container and
leaves the creds there (that is what an earlier probe of mine did; I restored it). Prefer
6.2 unless you deliberately want a persistent alias.

### 6.4 Miss detection (required: spec says "exit non-zero on miss")

`mc rm --force` is **not** silently-successful on a miss:
- missing object, valid creds → `Object does not exist`, **exit 1** (VERIFIED)
- multi-target `mc rm --force A B` where A exists and B is missing → A is deleted,
  B reports the error, and the command still **exit 1** (VERIFIED) — so a single
  multi-key invocation is safe for "partial miss = failure" but you lose which one missed.
- missing object, **no** creds → `Insufficient permissions`, exit 1 (a creds bug looks
  identical to a miss on exit code alone — always check stderr text).

Recommended: delete keys in a loop, capture each `rc`, and fail if the **blob** was
missing (the sidecar alone missing is a benign already-deleted case):
```sh
miss=0
for key in "${SHA}.${EXT}" "_meta/${COMM}/${SHA}.json"; do
  out=$($MCX rm --force "local/buzz-media/$key" 2>&1) || {
    case "$out" in
      *"does not exist"*) echo "already absent: $key" >&2 ;;
      *) echo "DELETE FAILED: $key: $out" >&2; miss=1 ;;
    esac
  }
done
```
Treat `Insufficient permissions` / `Access Denied` as a **hard** error (creds problem), not
as "already gone".

### 6.5 Idempotent variant — wipe every key for a sha in one shot

`mc find` + `mc rm` is the simplest correct-by-construction form, because it does not need
`ext` or the community UUID at all:
```sh
keys=$($MCX find local/buzz-media --name "${SHA}.*")   # basename glob, matches _meta/ too
[ -z "$keys" ] && { echo "nothing to delete for $SHA" >&2; exit 1; }   # the "miss"
echo "$keys" | while read -r k; do $MCX rm --force "$k"; done
```
**VERIFIED**: `mc find local/buzz-media --name "<sha>.*"` returns both the flat blob and
the nested `_meta/...json` (glob is basename-scoped at any depth), exit `0`, and prints
nothing on no match.

## 7. Hourly sweep primitives

`mc find` supports the age + name filter the sweep needs, in one pass:
```sh
# every audio-ish object older than 1h
$MCX find local/buzz-media --older-than 1h --regex '(mp3|m4a|ogg|opus|wav|flac|aac)$'
```
**VERIFIED** live: returned the 5 pre-existing `.m4a` objects, exit `0`.
Notes for the sweep author:
- `--older-than` and `--name`/`--regex` compose; multiple `--name` flags also compose.
- `--json` (`mc ls --recursive --json`) emits one object per line with
  `lastModified` as RFC-3339 (`"2026-10-01T03:58:01.707Z"`) and a bare `key`
  (no bucket prefix) — use this if you prefer sorting/filtering in the harness rather
  than in `mc`.
- The sweep must delete the **sidecar too**, or it recreates the orphan-sidecar anomaly
  that `bucket_index.rs` already tracks. Cleanest: collect the audio blob keys, strip the
  extension to the sha, then for each sha run the §6.5 `mc find`-based wipe.
- `mc` in the minio image is `RELEASE.2025-08-13T08-35-41Z`. It is a **distroless**
  image: there is **no `grep`, no `sed`, no `awk`** (VERIFIED — all three "command not
  found"). Do all text processing on the **host** side of `docker exec`, or use `mc --json`
  plus a host tool. This is a real trap for a `docker exec … sh -c 'mc ls … | grep …'`
  design.

## 8. Verify step (auth'd GET → 404, not 401)

Confirmed live through `https://relay.orangesync.tech/media/…` with `nak`-signed events
(kind 24242, `t=get`, `x=<sha>`, `expiration=now+300`):

| # | request | result |
|---|---|---|
| 1 | no auth, existing blob | **401** |
| 2 | valid auth (`x` = that sha), existing blob | **200** + bytes |
| 3 | valid auth (`x` = missing sha), missing blob | **404** `{"error":"not found"}` |
| 4 | auth signed for a *different* sha, existing blob | **403** `{"error":"insufficient scope"}` |
| 5 | valid auth, bare hash (no `.ext`) | **200** |
| 6 | valid auth, `.thumb.jpg` of an image | **200** |
| 7 | valid auth, correct sha but **wrong ext** | **404** |

### 8.1 A 404 does NOT prove the delete worked — the script must also assert object absence

This was tested directly on live VPS2 with a synthetic sha (`a1b2c3d4…`), seeding a blob +
sidecar, then probing the relay after each partial state:

| bucket state | `mc stat` blob | `mc stat` sidecar | GET `{sha}.m4a` | GET `{sha}` bare |
|---|---|---|---|---|
| both present | present | present | **200** | **200** |
| **blob deleted, sidecar kept** | gone | present | **404** | **404** |
| **sidecar deleted, blob kept** | present | gone | **404** | **404** |
| both gone (intended) | gone | gone | **404** | **404** |

**The HTTP verify step cannot distinguish a complete delete from a half-delete.** A delete
that removed only the blob (sidecar left dangling) or only the sidecar (blob left orphaned)
produces exactly the same 404 as a correct full delete. So:

- The spec's "verify = auth'd GET returns 404" is a **necessary but not sufficient** gate.
  It proves the object is *no longer servable*, not that the storage was actually reclaimed.
- The delete script MUST additionally assert **both** objects are absent with `mc stat`
  (non-zero for each), and only then run the HTTP 404 check. Asserting the HTTP 404 alone
  would let a script that silently fails to delete the sidecar pass verification while
  leaving a dangling tenant binding behind (exactly the `orphan_sidecar_count` anomaly that
  `bucket_index.rs:300-304` tracks).
- Practical ordering: `mc rm` blob + sidecar → `mc stat` both (expect non-zero) →
  auth'd GET `{sha}.{ext}` → expect 404. Any step failing = retry, then alert.

Consequences for the delete script's verify step:
- **404 is the success signal** (rows 3), exactly as §E of the design assumes.
- **401** means the auth event itself is malformed/rejected — a *test* bug, not a delete
  failure. **403** means the auth was valid but scoped to a different `x` — the script must
  mint a fresh event whose `x` is the sha it just deleted.
- **Row 7 of the table above is a trap:** verify with the **exact `{sha256}.{ext}` you
  deleted**. A wrong-ext probe returns 404 *even when the blob still exists*, which would
  let a broken delete pass verification.
- Bare-hash verification (`{sha}`) is **not** a sidecar-independent check: with the sidecar
  present and the blob gone it still returns 404 (row 2), and with the sidecar gone it
  404s regardless of the blob (row 3). It adds nothing over the `{sha}.{ext}` probe, so
  verify with the explicit `{sha}.{ext}` form and rely on `mc stat` for storage truth.

## 9. Remaining ambiguity (explicitly flagged)

1. **`BUZZ_MAX_AUDIO_BYTES` / ext set.** Which extensions actually get written depends on
   `sniff_allowed_audio()` + `mime_to_ext`. Live bucket contains `.mp3 .m4a .ogg .opus .wav
   .flac .aac .bin` (audio) — matching the §E sweep list — but a new codec would be written
   under an extension the sweep does not know. The **`mc find --name "<sha>.*"`** approach
   (§6.5) is immune to this; the `--regex '(mp3|m4a|…)$'` sweep is not. Low risk, but it is
   a real gap: a future audio ext would leak past the sweep forever.
2. **Multi-community future.** Today the sidecar prefix is one UUID. The §6.5 `mc find`
   form is community-agnostic and therefore already correct; any hard-coded
   `_meta/{uuid}/` path is not. Recommend the script resolve/derive nothing and use find.
3. **No dedicated sweeper S3 user exists.** `mc admin user list` with the root creds returns
   `Access Denied` (the root creds are usable but not admin-capable via the baked alias —
   verified as `rc=1`, `AccessDenied`). The design's §E note that a sweeper credential
   "can be reused" is therefore **not yet true**: either use the root creds (as verified
   above) or provision a dedicated user with `s3:ListBucket` + `s3:DeleteObject` before the
   sweeper ships with a least-privilege identity. **This is the one item that needs an ops
   decision, not a discovery.**
4. **Concurrent-writer race.** A delete racing an in-flight upload of the same sha can
   leave a blob without a sidecar (the uploader writes blob → record → sidecar; the
   uploader intentionally does **not** clean up orphan blobs on failure, `upload.rs:134-140`).
   This is pre-existing, bounded, and swept by the bucket sweep's `orphan_blob` gauge; the
   delete script must not "fix" it by deleting a blob it did not create.
5. **`_uploads/` becomes non-empty if someone enables `BUZZ_MEDIA_UPLOAD_RECORDS`.** Then a
   complete per-sha delete has a third component (`mc rm --recursive --force
   local/buzz-media/_uploads/{community}/{sha256}/`). Disabled today; include it
   defensively (it exits 0 when absent).

## 10. Baseline used for this verification

Captured immediately after cleanup, so a later worker can tell drift from real change:
`mc ls --recursive local/buzz-media/ | wc -l` → **48** objects, of which
29 at the bucket root (blobs + thumbs) and 19 sidecars under
`_meta/a3312780-4cfe-48eb-af8a-f405f369a4f8/`. No `_uploads/`, no `repos/`, no `probe/`
objects. Bucket un-versioned, private. Container `buzz-relay-minio` healthy,
`buzz-relay` running image `tollgate/buzz:audio`.

Probe hygiene: all probe objects created during this discovery were removed, and the
container's `/tmp/.mc/config.json` was restored to its shipped state (the `local` alias
left with empty creds, as the image ships it). `/root/.mc` was absent before probing and
was removed again afterwards. No production object was deleted; no container restarted.
