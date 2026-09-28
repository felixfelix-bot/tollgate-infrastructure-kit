# nip29_relay Ansible Role

Deploys a [strfry](https://github.com/hoytech/strfry) Nostr relay with the
[relay29](https://github.com/fiatjaf/relay29) write-policy plugin for
[NIP-29](https://github.com/nostr-protocol/nips/blob/master/29.md) group
management, plus negentropy mesh sync via systemd timer.

## Requirements

- Debian 12+ (or Ubuntu 22.04+)
- Go 1.21+ (installed via apt or the role's `golang` package)
- Build toolchain: gcc, make, libsecp256k1, flatbuffers, lmdb, zstd, boost, ssl

## Role Variables

See [`defaults/main.yml`](defaults/main.yml) for the full list. Key variables:

| Variable | Default | Description |
|---|---|---|
| `nip29_port` | `7780` | Relay listen port |
| `nip29_base_dir` | `/opt/strfry-nip29` | Install directory for binaries + config |
| `nip29_db_dir` | `{{ nip29_base_dir }}/db` | LMDB database directory |
| `nip29_relay_nsec` | env `NIP29_RELAY_NSEC` | Relay private key (nsec or hex) |
| `nip29_domain` | `{{ ansible_host }}` | Public domain/IP for the relay |
| `nip29_sync_peers` | `[]` | List of peer relay URLs for negentropy sync |
| `nip29_sync_interval_min` | `5` | Sync timer interval in minutes |

## Build Notes

The strfry29 plugin binary is compiled as **`strfry29-bin`** (not `strfry29`)
to avoid a name conflict with the Go source directory `./strfry29/` inside the
relay29 repo. The build command is:

```
go build -buildvcs=false -o strfry29-bin ./strfry29/
```

`-buildvcs=false` prevents Go from embedding VCS metadata, which can fail in
shallow clones or CI environments.

## Config Notes

- **strfry.conf** uses `writePolicy { plugin = ... }` syntax (not the older
  `type = "callback"` + `path =` form). The plugin path points to
  `strfry29-bin` with a 10-second timeout.
- **strfry29.json** expects `relay_secret_key` in **hex** format
  (`d2d3ea1d...`). If you provide an `nsec1...` bech32 key, the role
  auto-converts it to hex at deploy time.
- When either config file changes, the LMDB database (`data.mdb` + `lock.mdb`)
  is **wiped** before restart to prevent stale group events from causing a
  "group already exists" dead loop.

## Known Issues

### strfry29 group metadata import bug

**Symptom:** After group creation, the relay29 plugin emits metadata events
(kind 39000) but they are not persisted to the strfry LMDB database. The
plugin's write callback returns successfully, but the events never land in the
DB. This causes downstream clients to see groups without metadata.

**Workaround:** Extract the metadata events from the strfry logs and import
them manually:

```bash
# 1. Find metadata events in the strfry journal
journalctl -u strfry-nip29 --no-pager | grep '"kind":39000'

# 2. Save the event JSON to a file, then import:
strfry --config /opt/strfry-nip29/strfry.conf import --no-verify < events.jsonl
```

This must be done once after initial group creation. Subsequent group
modifications are handled correctly once the metadata is in the DB.

**Root cause:** The relay29 plugin writes metadata events to strfry's write
callback, but strfry's negentropy layer does not re-index events that arrive
via the plugin path. Importing with `--no-verify` bypasses the write-policy
check and inserts them directly.

## License

MIT
