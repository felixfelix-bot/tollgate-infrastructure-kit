# Local Patch Registry — tollgate-infrastructure-kit

Every deviation from upstream in a deployed service is documented here, with
exact repos, tags and SHAs. Each entry must include: what changed, why, where
the patch lives, how the artifact is built, and how to reproduce the state.

---

## buzz relay (relay.orangesync.tech) — tollgate:audio-validate (audio bridge P1)

- **Date**: 2026-08-16 (kanban task t_c40afae4)
- **Upstream**: https://github.com/block/buzz (Apache-2.0), monorepo `buzz`
- **Patch branch**: https://github.com/felixfelix-bot/buzz/tree/audio-validate-patch
- **Patched commit**: 69f9244c4 (base: upstream main @ 78cbffeb6)
- **Deployed image**: `tollgate/buzz:audio` (= `ghcr.io/felixfelix-bot/buzz:tollgate-audio`,
  built by deployment-only workflow `.github/workflows/tollgate-audio-image.yml`
  in the patch branch; GH Actions run 31916136562)

### What changed

Generic file upload path now accepts magic-byte-sniffed audio containers as
media blobs (voice notes for tollgate chat), instead of rejecting them:

1. `crates/buzz-media/src/validation.rs` — `sniff_allowed_audio()` allowlist
   by magic bytes: mp3 (ID3/0xFFEx), m4a (ftyp M4A brand), ogg (OggS + known
   codec at audio-only capture patterns), opus, wav (RIFF/WAVE), flac (fLaC),
   adts aac. Sniffed audio is capped by `max_audio_bytes` (no image
   re-encode, no ffmpeg pipeline — raw bytes pass through).
2. `crates/buzz-media/src/config.rs` — `max_audio_bytes` (default 25 MiB,
   validated `<= max_file_bytes`), env `BUZZ_MAX_AUDIO_BYTES`.
3. `crates/buzz-relay/src/api/media.rs` — sniffed audio (incl. M4A) is routed
   to the generic file path, NOT the video pipeline; served with
   `Content-Disposition: attachment` (never inlined). All non-M4A ISO-BMFF
   brands remain rejected as before (video rules untouched).
4. `BUZZ_MAX_AUDIO_BYTES=26214400` set in `/opt/buzz-relay/docker-compose.yml`.

### Why

Tollgate chat needs voice notes through the buzz relay. Upstream only accepts
images/GIF/video on the media path and rejects audio outright (415). Design
spec: `/home/c03rad0r/plans/audio-bridge-p1-design.md` (local).

### Guardrails kept

- Everything else at upstream defaults; video/ISO-BMFF pipeline untouched.
- Audio blobs served as attachments; no HTML/SVG/inline-active content.
- Size caps enforced before S3 write; membership (BUZZ_REQUIRE_RELAY_MEMBERSHIP)
  and 24242 auth (NIP-98 style `Authorization: Nostr`) unchanged.

### Deployment state (VPS2 23.182.128.51, /opt/buzz-relay)

- `buzz-relay-minio` (minio/minio:latest): internal-only MinIO on the
  compose network (`buzz-relay-net`), volume `buzz-relay-minio`, 512m limit,
  NO host ports published (Sitarani at 127.0.0.1:9000 on the host is a
  different, pre-existing MinIO and was not touched).
- `buzz-relay-minio-init` (minio/mc): one-shot, creates bucket `buzz-media`,
  sets anonymous access to none (private).
- buzz-relay env additions (secrets in `/opt/buzz-relay/.env`, chmod 600):
  `BUZZ_S3_ENDPOINT=http://minio:9000`, `BUZZ_S3_ACCESS_KEY`/`BUZZ_S3_SECRET_KEY`
  (static MinIO root creds), `BUZZ_S3_BUCKET=buzz-media`, `BUZZ_S3_REGION=us-east-1`,
  `BUZZ_S3_ADDRESSING_STYLE=path`, `BUZZ_MEDIA_BASE_URL=https://relay.orangesync.tech/media`,
  `BUZZ_MAX_AUDIO_BYTES=26214400`.
- Compose backup before change: `docker-compose.yml.bak-audio-bridge`.

### Verification (2026-08-16)

- Unit gates: `cargo fmt --check` clean; `cargo test -p buzz-media --lib`
  119/119 pass (incl. new audio sniff/cap tests); relay routing test
  `m4a_audio_sniff_is_not_routed_to_video_pipeline` passes; `cargo check -p
  buzz-deletion` clean.
- P0-a (minio, unpatched image): minio-init exits 0, bucket private,
  `PUT /upload` → 401 unauthenticated.
- P0-b (patched image): signed 24242 upload of a real 10s m4a → 201/200 +
  BlobDescriptor; authenticated GET `/media/<sha256>.m4a` returns identical
  bytes; object present in `buzz-media` bucket (mc ls); outputs quoted in
  kanban task t_c40afae4.

### Rebuild / rollback

- Rebuild: push to `audio-validate-patch` branch (workflow auto-runs) or
  dispatch "Tollgate audio image" workflow; then on VPS2:
  `docker pull ghcr.io/felixfelix-bot/buzz:tollgate-audio && docker tag
  ghcr.io/felixfelix-bot/buzz:tollgate-audio tollgate/buzz:audio && cd
  /opt/buzz-relay && docker compose up -d buzz-relay`.
- Rollback code: set relay image back to `ghcr.io/block/buzz:latest`,
  `docker compose up -d buzz-relay` (minio service may stay; harmless with
  stock image — stock relay simply does not read the S3 env).
- Rollback everything: restore `docker-compose.yml.bak-audio-bridge`,
  `docker compose up -d`, `docker compose rm -sf minio minio-init` (volume
  `buzz-relay-minio` can be dropped afterwards if desired).
