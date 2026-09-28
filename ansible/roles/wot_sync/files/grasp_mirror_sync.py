#!/usr/bin/env python3
"""
grasp-mirror-sync — Keep the grasp-mirror daemon's MIRROR_NPUBS env in sync
with the root npub's kind-3 follow list. Runs locally on the grasp-mirror
host as a systemd timer.

Two data sources, tried in order:
  1. Local allowlist  (WOT_ALLOWED_PATH) — the strfry-agg-reconcile output.
     Used when grasp-mirror is co-located with strfry-agg. Zero network,
     always fresh within the reconcile interval.
  2. kind-3 fetch     (RELAYS + ROOT_NPUB) — fetches the newest kind-3
     contact-list event from the bootstrap relays and extracts its ``p``
     tags. Used when the allowlist is absent (separate host).

In both cases the hex pubkeys are converted to bech32 npubs and written as
``MIRROR_NPUBS=npub1...,npub1...`` into the grasp-mirror env file. The
daemon is restarted only when the set actually changes.

Usage:
  grasp-mirror-sync                 # live sync
  grasp-mirror-sync --dry-run       # report only, no writes / no restart

Environment overrides:
  ROOT_NPUB            root npub whose kind-3 is followed (bech32 npub1...)
  WOT_ALLOWED_PATH     local allowlist (hex pubkeys); optional fast path
  WOT_RELAYS           comma-separated wss:// relays for kind-3 fetch
  GRASP_ENV_FILE       env file to rewrite (MIRROR_NPUBS line)
  GRASP_SERVICE        systemd unit to restart on change (default grasp-mirror)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("grasp-mirror-sync")

DEFAULT_ROOT_NPUB = os.environ.get(
    "ROOT_NPUB", "npub1c03rad0r6q833vh57kyd3ndu2jry30nkr0wepqfpsm05vq7he25slryrnw"
)
DEFAULT_ALLOWED = os.environ.get(
    "WOT_ALLOWED_PATH", "/opt/tollgate/strfry-agg/state/allowed.npubs"
)
DEFAULT_RELAYS = os.environ.get(
    "WOT_RELAYS", "wss://relay.damus.io,wss://nos.lol"
).split(",")
DEFAULT_ENV_FILE = os.environ.get(
    "GRASP_ENV_FILE", "/opt/tollgate/grasp-mirror/grasp-mirror.env"
)
DEFAULT_SERVICE = os.environ.get("GRASP_SERVICE", "grasp-mirror")

# --- bech32 (npub <-> hex) — vendored from strfry_agg.crypto, no deps ---------

_BECH32_CHARSET = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_NPUB_HRP = "npub"


def _polymod(values: list[int]) -> int:
    gen = [0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3]
    chk = 1
    for v in values:
        top = chk >> 25
        chk = (chk & 0x1FFFFFF) << 5 ^ v
        for i in range(5):
            chk ^= gen[i] if ((top >> i) & 1) else 0
    return chk


def _hrp_expand(hrp: str) -> list[int]:
    return [ord(x) >> 5 for x in hrp] + [0] + [ord(x) & 31 for x in hrp]


def _bech32_create_checksum(hrp: str, data: list[int]) -> list[int]:
    values = _hrp_expand(hrp) + data
    pm = _polymod(values + [0, 0, 0, 0, 0, 0]) ^ 1
    return [(pm >> 5 * (5 - i)) & 31 for i in range(6)]


def _convertbits(data: list[int], frombits: int, tobits: int, pad: bool) -> list[int]:
    acc = bits = 0
    ret: list[int] = []
    maxv = (1 << tobits) - 1
    max_acc = (1 << (frombits + tobits - 1)) - 1
    for v in data:
        if v < 0 or (v >> frombits):
            raise ValueError("invalid data value")
        acc = ((acc << frombits) | v) & max_acc
        bits += frombits
        while bits >= tobits:
            bits -= tobits
            ret.append((acc >> bits) & maxv)
    if pad:
        if bits:
            ret.append((acc << (tobits - bits)) & maxv)
    elif bits >= frombits or ((acc << (tobits - bits)) & maxv):
        raise ValueError("non-zero padding bits")
    return ret


def _bech32_encode(hrp: str, data: list[int]) -> str:
    combined = data + _bech32_create_checksum(hrp, data)
    return hrp + "1" + "".join(_BECH32_CHARSET[d] for d in combined)


def _bech32_decode(bech: str) -> tuple[str, list[int]]:
    if any(ord(x) < 33 or ord(x) > 126 for x in bech):
        raise ValueError("invalid character")
    bech = bech.lower()
    pos = bech.rfind("1")
    if pos < 1 or pos + 7 > len(bech):
        raise ValueError("invalid separator position")
    if not all(x in _BECH32_CHARSET for x in bech[pos + 1 :]):
        raise ValueError("invalid data character")
    hrp = bech[:pos]
    data = [_BECH32_CHARSET.index(x) for x in bech[pos + 1 :]]
    if _polymod(_hrp_expand(hrp) + data) != 1:
        raise ValueError("invalid checksum")
    return hrp, data[:-6]


def hex_to_npub(hex_str: str) -> str:
    c = hex_str.lower().strip()
    if len(c) != 64:
        raise ValueError(f"expected 64-char hex, got {len(c)}")
    return _bech32_encode(_NPUB_HRP, _convertbits(list(bytes.fromhex(c)), 8, 5, True))


def npub_to_hex(npub: str) -> str:
    hrp, data = _bech32_decode(npub.strip())
    if hrp != _NPUB_HRP:
        raise ValueError(f"expected HRP npub, got {hrp}")
    decoded = _convertbits(data, 5, 8, False)
    if len(decoded) != 32:
        raise ValueError(f"expected 32 bytes, got {len(decoded)}")
    return bytes(decoded).hex()


# --- WoT set acquisition -----------------------------------------------------


def _valid_hex(value: str) -> bool:
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def load_allowlist(path: Path) -> set[str] | None:
    """Hex pubkey set from a local allowlist, or None if file absent."""
    if not path.is_file():
        return None
    out: set[str] = set()
    for line in path.read_text(errors="replace").splitlines():
        pk = line.strip().lower()
        if pk and not pk.startswith("#"):
            if _valid_hex(pk):
                out.add(pk)
            elif pk.startswith("npub1"):
                try:
                    out.add(npub_to_hex(pk))
                except ValueError:
                    continue
    return out


async def _fetch_kind3_one(url: str, root_hex: str, timeout: float = 8.0) -> dict | None:
    try:
        import websockets
    except ImportError:
        log.error("websockets library not installed — cannot fetch kind-3")
        return None
    sub = "gms-" + str(abs(hash(url)))[-8:]
    try:
        async with websockets.connect(url, max_size=2 ** 20, close_timeout=3) as ws:
            await ws.send(
                json.dumps(["REQ", sub, {"authors": [root_hex], "kinds": [3], "limit": 1}])
            )
            newest: dict | None = None
            while True:
                try:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=timeout))
                except asyncio.TimeoutError:
                    break
                if not isinstance(msg, list):
                    continue
                if msg and msg[0] == "EVENT" and len(msg) >= 3 and msg[2]:
                    evt = msg[2]
                    if newest is None or evt.get("created_at", 0) > newest.get(
                        "created_at", 0
                    ):
                        newest = evt
                elif msg and msg[0] == "EOSE" and msg[1] == sub:
                    break
            return newest
    except Exception as exc:
        log.warning("relay fetch failed %s: %s", url, exc)
        return None


async def _fetch_kind3(root_hex: str, relays: list[str]) -> dict | None:
    best: dict | None = None
    for url in relays:
        evt = await _fetch_kind3_one(url, root_hex)
        if evt and (best is None or evt.get("created_at", 0) > best.get("created_at", 0)):
            best = evt
    return best


def extract_followed(kind3: dict) -> set[str]:
    """Lowercase hex pubkeys from a kind-3 event's ``p`` tags."""
    out: set[str] = set()
    for tag in kind3.get("tags", []) or []:
        if not tag or tag[0] != "p" or len(tag) < 2:
            continue
        v = str(tag[1]).strip()
        if _valid_hex(v.lower()):
            out.add(v.lower())
        elif v.startswith("npub1"):
            try:
                out.add(npub_to_hex(v))
            except ValueError:
                continue
    return out


def get_wot_set(
    allowlist_path: Path, root_npub: str, relays: list[str]
) -> tuple[set[str], str]:
    """Return (hex pubkey set, source label). Prefers local allowlist."""
    al = load_allowlist(allowlist_path)
    if al is not None:
        return al, f"allowlist:{allowlist_path}"
    root_hex = npub_to_hex(root_npub)
    evt = asyncio.run(_fetch_kind3(root_hex, relays))
    if not evt:
        return set(), "kind3:fetch-failed"
    return extract_followed(evt), f"kind3:{root_npub}"


# --- env file rewrite --------------------------------------------------------


def read_current_mirror_npubs(env_file: Path) -> str:
    """Current MIRROR_NPUBS value (empty string if unset/absent)."""
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(errors="replace").splitlines():
        if line.strip().startswith("MIRROR_NPUBS="):
            return line.split("=", 1)[1].strip()
    return ""


def write_env(env_file: Path, mirror_npubs_csv: str) -> None:
    """Rewrite the env file, setting MIRROR_NPUBS=... and preserving others."""
    env_file.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    seen = False
    if env_file.is_file():
        for line in env_file.read_text(errors="replace").splitlines():
            if line.strip().startswith("MIRROR_NPUBS="):
                lines.append(f"MIRROR_NPUBS={mirror_npubs_csv}")
                seen = True
            else:
                lines.append(line)
    if not seen:
        lines.append(f"MIRROR_NPUBS={mirror_npubs_csv}")
    env_file.write_text("\n".join(lines) + "\n")


def restart_service(service: str) -> bool:
    """Best-effort `systemctl restart`. Returns True on success."""
    try:
        r = subprocess.run(
            ["systemctl", "restart", service],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode != 0:
            log.error("systemctl restart %s failed: %s", service, r.stderr.strip())
        return r.returncode == 0
    except Exception as exc:
        log.error("systemctl restart %s raised: %s", service, exc)
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Sync grasp-mirror MIRROR_NPUBS from kind-3 / allowlist"
    )
    p.add_argument("--dry-run", action="store_true", help="report only")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--root-npub", default=DEFAULT_ROOT_NPUB)
    p.add_argument("--allowed", default=DEFAULT_ALLOWED, help="local allowlist path")
    p.add_argument(
        "--relays", default=",".join(DEFAULT_RELAYS), help="comma-separated wss:// relays"
    )
    p.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    p.add_argument("--service", default=DEFAULT_SERVICE)
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )

    relays = [r.strip() for r in args.relays.split(",") if r.strip()]
    wot, source = get_wot_set(Path(args.allowed), args.root_npub, relays)
    if not wot:
        log.error("no followed npubs obtained from %s — leaving env unchanged", source)
        return 0

    npubs = sorted(hex_to_npub(h) for h in wot)
    new_csv = ",".join(npubs)
    current = read_current_mirror_npubs(Path(args.env_file))

    if current == new_csv:
        if args.verbose:
            log.info("MIRROR_NPUBS unchanged (%d npubs from %s)", len(npubs), source)
        return 0

    if args.dry_run:
        print(
            f"DRY-RUN: would set MIRROR_NPUBS to {len(npubs)} npubs from {source} "
            f"(was {len([x for x in current.split(',') if x])})",
            file=sys.stderr,
        )
        return 0

    write_env(Path(args.env_file), new_csv)
    ok = restart_service(args.service)
    action = "restarted" if ok else "env written but restart FAILED"
    print(
        f"GRASP-SYNC: {action}; MIRROR_NPUBS now {len(npubs)} npubs from {source}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
