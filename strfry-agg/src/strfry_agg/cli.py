"""Command-line entry points for the strfry aggregation relay.

Two commands, deployed to the VPS and driven by systemd timers:

* ``strfry-agg-reconcile`` -- refresh the served-npub set from the root npub's
  kind-3 follow list, purge unfollowed authors (shrink), and rewrite the
  allowlist consumed by the write-policy plugin + the .env mirror.

* ``strfry-agg-scrape`` -- for each served npub, resolve its NIP-65 relay list
  and negentropy-sync (download-only) its events into the local strfry DB.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import reconcile
from .crypto import npub_to_hex
from .nostr_fetch import fetch_kind3, fetch_relay_list
from .relaylist import extract_relays_from_10002, pick_scrape_relays

log = logging.getLogger("strfry_agg.cli")


@dataclass
class AggConfig:
    root_npub: str
    bootstrap_relays: list[str]
    strfry_container: str
    state_dir: Path
    env_file: Path
    scrape_kinds: list[int]
    max_scrape_relays_per_author: int = 3


def _load_config() -> AggConfig:
    env_path = Path(os.environ.get("STRFRY_AGG_ENV", "/opt/tollgate/.env"))
    env: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")

    root = os.environ.get("STRFRY_AGG_ROOT_NPUB") or env.get("STRFRY_AGG_ROOT_NPUB", "")
    if not root:
        log.error("STRFRY_AGG_ROOT_NPUB not set")
        sys.exit(2)

    bootstrap = (
        os.environ.get("STRFRY_AGG_BOOTSTRAP_RELAYS")
        or env.get("STRFRY_AGG_BOOTSTRAP_RELAYS")
        or "wss://relay.damus.io,wss://nos.lol"
    )
    kinds = (
        os.environ.get("STRFRY_AGG_SCRAPE_KINDS")
        or env.get("STRFRY_AGG_SCRAPE_KINDS")
        or "1,3,5,6,7,10000,10002,30023"
    )

    return AggConfig(
        root_npub=root,
        bootstrap_relays=[r.strip() for r in bootstrap.split(",") if r.strip()],
        strfry_container=os.environ.get("STRFRY_AGG_CONTAINER", "tollgate-strfry-agg"),
        state_dir=Path(os.environ.get("STRFRY_AGG_STATE_DIR", "/opt/tollgate/strfry-agg/state")),
        env_file=env_path,
        scrape_kinds=[int(k) for k in kinds.split(",") if k.strip().isdigit()],
    )


def _allowlist_path(cfg: AggConfig) -> Path:
    return cfg.state_dir / "allowed.npubs"


def _read_allowlist(cfg: AggConfig) -> set[str]:
    p = _allowlist_path(cfg)
    if not p.exists():
        return set()
    return reconcile.parse_allowlist(p.read_text())


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _mirror_env(cfg: AggConfig, hex_set: set[str]) -> None:
    npubs_csv = reconcile.format_env_npubs(hex_set)
    _update_env_line(cfg.env_file, "STRFRY_AGG_SERVED_NPUBS", npubs_csv)


def _update_env_line(env_file: Path, key: str, value: str) -> None:
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    out: list[str] = []
    found = False
    for line in lines:
        if line.startswith(key + "="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    _atomic_write(env_file, "\n".join(out) + "\n")


def _run_strfry(cfg: AggConfig, args: list[str], timeout: int = 1200) -> tuple[int, str]:
    cmd = ["docker", "exec", cfg.strfry_container, "/app/strfry"] + args
    log.info("run: %s", " ".join(cmd))
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0:
            log.warning("strfry rc=%d stderr=%s", r.returncode, (r.stderr or "").strip()[-400:])
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        log.error("strfry timed out: %s", " ".join(args))
        return 124, ""


def reconcile_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Reconcile strfry-agg served npub set")
    parser.add_argument("--dry-run", action="store_true", help="compute diff only, no writes/deletes")
    args = parser.parse_args(argv)

    cfg = _load_config()
    try:
        root_hex = npub_to_hex(cfg.root_npub)
    except ValueError as exc:
        log.error("invalid root npub: %s", exc)
        return 2

    old_set = _read_allowlist(cfg)
    log.info("current served set: %d npubs", len(old_set))

    kind3 = asyncio.run(fetch_kind3(root_hex, cfg.bootstrap_relays))
    if not kind3:
        log.warning("no kind-3 found for root npub; keeping existing allowlist")
        return 0

    new_set = reconcile.extract_followed_pubkeys(kind3)
    result = reconcile.diff_followed(old_set, new_set)
    log.info(
        "reconcile: +%d added, -%d removed, =%d unchanged (total %d)",
        len(result.added), len(result.removed), len(result.unchanged), len(result.new_set),
    )

    if args.dry_run:
        return 0

    _atomic_write(_allowlist_path(cfg), reconcile.format_allowlist(result.new_set))
    _mirror_env(cfg, result.new_set)

    if result.removed:
        delete_filter = reconcile.build_delete_filter(result.removed)
        if delete_filter:
            _run_strfry(cfg, ["delete", "--filter", json.dumps(delete_filter)], timeout=3600)
        log.info("purged events for %d unfollowed npubs", len(result.removed))

    return 0


def scrape_main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Negentropy-scrape served npubs into strfry-agg")
    parser.add_argument("--author", help="scrape a single npub/hex instead of the full allowlist")
    parser.add_argument("--limit", type=int, default=0, help="max authors to scrape this run (0=all)")
    args = parser.parse_args(argv)

    cfg = _load_config()
    kinds = cfg.scrape_kinds

    if args.author:
        try:
            authors = [npub_to_hex(args.author)] if args.author.startswith("npub1") else [args.author.lower()]
        except ValueError as exc:
            log.error("invalid author: %s", exc)
            return 2
    else:
        authors = sorted(_read_allowlist(cfg))
        if args.limit > 0:
            authors = authors[: args.limit]

    if not authors:
        log.warning("no served npubs to scrape (run reconcile first)")
        return 0

    log.info("scraping %d authors", len(authors))
    flt = reconcile.build_sync_filter(authors, kinds)

    relay_seen: set[str] = set()
    author_relays: dict[str, list[str]] = {}
    for hexpk in authors:
        evt = asyncio.run(fetch_relay_list(hexpk, cfg.bootstrap_relays))
        rl = extract_relays_from_10002(evt or {})
        relays = pick_scrape_relays(rl, cfg.bootstrap_relays)[: cfg.max_scrape_relays_per_author]
        author_relays[hexpk] = relays
        relay_seen.update(relays)

    log.info("distinct upstream relays: %d", len(relay_seen))

    failures = 0
    for hexpk in authors:
        relays = author_relays.get(hexpk, [])
        if not relays:
            continue
        author_filter = reconcile.build_sync_filter([hexpk], kinds)
        for relay in relays:
            rc, _ = _run_strfry(
                cfg,
                ["sync", relay, "--dir", "down", "--filter", json.dumps(author_filter)],
                timeout=600,
            )
            if rc != 0:
                failures += 1
                break

    log.info("scrape complete (%d author/relay failures)", failures)
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    cmd = Path(sys.argv[0]).stem
    if "scrape" in cmd:
        sys.exit(scrape_main())
    sys.exit(reconcile_main())
