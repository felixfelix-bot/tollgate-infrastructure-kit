"""Minimal Nostr relay client for fetching kind-3 / kind-10002 events.

Uses the ``websockets`` library (already installed on the VPS via the backup
role). Tries each configured bootstrap relay in turn and returns the newest
matching event for a single-author filter.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterable

log = logging.getLogger("strfry_agg.nostr")


async def _fetch_one(url: str, filt: dict, timeout: float = 8.0) -> dict | None:
    import websockets

    sub_id = "agg-" + str(id(filt))[-8:]
    try:
        async with websockets.connect(url, max_size=2 ** 20, close_timeout=3) as ws:
            await ws.send(json.dumps(["REQ", sub_id, filt]))
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
                    if newest is None or evt.get("created_at", 0) > newest.get("created_at", 0):
                        newest = evt
                elif msg and msg[0] == "EOSE" and msg[1] == sub_id:
                    break
            return newest
    except Exception as exc:
        log.warning("relay fetch failed %s: %s", url, exc)
        return None


async def fetch_newest_event(relays: Iterable[str], filt: dict, timeout: float = 8.0) -> dict | None:
    """Return the newest matching event across the given relays (or None)."""
    best: dict | None = None
    for url in relays:
        evt = await _fetch_one(url, filt, timeout=timeout)
        if evt and (best is None or evt.get("created_at", 0) > best.get("created_at", 0)):
            best = evt
    return best


def fetch_newest_event_sync(relays: Iterable[str], filt: dict, timeout: float = 8.0) -> dict | None:
    """Synchronous wrapper around :func:`fetch_newest_event`."""
    return asyncio.run(fetch_newest_event(list(relays), filt, timeout=timeout))


async def fetch_kind3(root_pubkey_hex: str, relays: Iterable[str]) -> dict | None:
    return await fetch_newest_event(relays, {"authors": [root_pubkey_hex], "kinds": [3], "limit": 1})


async def fetch_relay_list(pubkey_hex: str, relays: Iterable[str]) -> dict | None:
    return await fetch_newest_event(
        relays, {"authors": [pubkey_hex], "kinds": [10002], "limit": 1}
    )
