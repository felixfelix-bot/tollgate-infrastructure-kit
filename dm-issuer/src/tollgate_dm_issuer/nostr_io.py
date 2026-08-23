"""NostrIO — NIP-59 gift-wrap send/receive over Nostr relays (spec §1.3, §6, §7).

pynostr (as of 0.7) ships NIP-04 ECDH+AES-256-CBC primitives but does NOT
implement NIP-59 gift wrap or unwrap.  This module builds gift wrap on top
of those primitives:

* **Rumor (kind 14)** — unsigned chat rumor whose pubkey is the sender's.
* **Seal (kind 13)** — signed-by-sender event whose content is
  ``sk_sender.encrypt_message(rumor_json, recipient_pubkey)``.
* **Gift wrap (kind 1059)** — fresh-ephemeral-key event; the content is
  ``ephem_sk.encrypt_message(seal_json, recipient_pubkey)``; has ``p``
  tag = recipient; signed by the ephemeral key.

Unwrapping is the inverse:

* filter kind 1059 events with ``p`` tag matching issuer pubkey,
* decrypt content with issuer sk + giftwrap's ephemeral pubkey,
* verify the seal's signature against seal.pubkey (= sender),
* decrypt the seal's content with issuer sk + seal.pubkey (= sender),
* parse the resulting rumor as kind 14 (or any content-bearing kind).

**Sender identity = rumor.pubkey** (not giftwrap's ephemeral pubkey) — this
is the NIP-59 security property.

The I/O surface is pluggable:

* ``fetch_giftwraps: Callable[[int], Awaitable[list[dict]]]`` — relay-side
  scan returning event dicts.
* ``publish_event: Callable[[dict], Awaitable[bool]]`` — publishes the
  built gift wrap event dict; returns ``True`` on ≥1-relay success.

Tests inject in-memory versions that capture and surface events; the
production wrappers serialise this through pynostr's ``RelayManager`` in
``_default_fetch_factory`` and ``_default_publish_factory``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from pynostr.event import Event
from pynostr.key import PrivateKey, PublicKey

log = logging.getLogger(__name__)

KIND_GIFTWRAP = 1059
KIND_SEAL = 13
KIND_DM_RUMOR = 14

FetchFn = Callable[[int], Awaitable[list[dict]]]
PublishFn = Callable[[dict], Awaitable[bool]]


@dataclass
class DmMessage:
    event_id: str
    sender_npub: str
    content: str
    received_at_ts: int
    created_at_ts: int


class NostrIO:
    """NIP-59 send/receive layer over pluggable relay transport."""

    def __init__(self, *, issuer_pubkey_hex: str,
                 issuer_privkey_hex: Optional[str] = None,
                 relays: Optional[list[str]] = None,
                 fetch_giftwraps: Optional[FetchFn] = None,
                 publish_event: Optional[PublishFn] = None,
                 retries: int = 5,
                 backoff_base_secs: float = 30.0,
                 lookback_default_secs: int = 43200,
                 scan_timeout_secs: float = 8.0) -> None:
        self._issuer_pub_hex = issuer_pubkey_hex
        self._issuer_priv_hex = issuer_privkey_hex
        self._relays = tuple(relays or [])
        self._fetch = fetch_giftwraps or _default_fetch_factory(
            self._issuer_pub_hex, self._issuer_priv_hex, self._relays,
            scan_timeout_secs)
        self._publish = publish_event or _default_publish_factory(
            self._issuer_priv_hex, self._relays)
        self._retries = max(1, retries)
        self._backoff_base = max(0.0, backoff_base_secs)
        self._lookback_default_secs = lookback_default_secs

    @property
    def lookback_default_secs(self) -> int:
        return self._lookback_default_secs

    async def scan_dms_since(self, since_ts: int) -> list[DmMessage]:
        """Fetch and unwrap gift-wrap events newer than ``since_ts``.

        Invalid or non-issuer-addressed events are silently skipped
        (spec §7.4 relay-tolerant; log-and-continue).
        """
        events: list[dict] = []
        try:
            events.extend(await self._fetch(since_ts))
        except Exception as exc:
            log.warning("scan_dms_since fetch failed: %s", exc)
            return []
        out: list[DmMessage] = []
        for ev in events:
            try:
                msg = _unwrap_giftwrap(ev, self._issuer_priv_hex,
                                       self._issuer_pub_hex)
                if msg is not None:
                    out.append(msg)
            except Exception as exc:
                log.debug("skipping event %s: %s",
                          ev.get("id", "<no-id>"), exc)
        return out

    async def send_dm(self, recipient_npub: str, content: str,
                      *, created_at: Optional[int] = None) -> bool:
        """Send NIP-59 gift-wrapped DM to ``recipient_npub``.

        Returns ``True`` if at least one relay accepted the event.
        Retries with exponential backoff per §6 DM-DLV-2.
        """
        if self._issuer_priv_hex is None:
            log.error("send_dm requires issuer private key")
            return False
        try:
            recipient_pubkey_hex = PublicKey.from_npub(recipient_npub).hex()
        except Exception as exc:
            log.error("invalid recipient_npub: %s", exc)
            return False
        ts = created_at if created_at is not None else int(time.time())
        event = _build_giftwrap(self._issuer_priv_hex,
                                recipient_pubkey_hex, content, ts)
        last_exc: Optional[Exception] = None
        for attempt in range(self._retries):
            try:
                ok = await self._publish(event.to_dict())
                if ok:
                    log.info("send_dm OK recipient=%s attempt=%d",
                             recipient_npub, attempt)
                    return True
            except Exception as exc:
                last_exc = exc
                log.warning("send_dm publish failure attempt=%d: %s",
                            attempt, exc)
            if attempt + 1 < self._retries:
                await asyncio.sleep(self._backoff_base * (2 ** attempt))
        log.error("send_dm exhausted retries recipient=%s err=%s",
                  recipient_npub, last_exc)
        return False


def _build_giftwrap(sender_privkey_hex: str, recipient_pubkey_hex: str,
                    content: str, created_at: int) -> Event:
    """Build the full NIP-59 gift wrap (rumor → seal → giftwrap) signed
    by the sender (seal) and an ephemeral key (gift wrap)."""
    sender_sk = PrivateKey(bytes.fromhex(sender_privkey_hex))
    sender_pub_hex = sender_sk.public_key.hex()

    rumor = Event(kind=KIND_DM_RUMOR, content=content,
                  pubkey=sender_pub_hex, created_at=created_at)
    rumor_dict = _to_rumor_dict(rumor)

    seal_ct = sender_sk.encrypt_message(
        message=json.dumps(rumor_dict),
        public_key_hex=recipient_pubkey_hex,
    )
    seal = Event(kind=KIND_SEAL, content=seal_ct, pubkey=sender_pub_hex,
                 created_at=created_at)
    seal.compute_id()
    seal.sign(sender_privkey_hex)

    ephem_sk = PrivateKey(secrets.token_bytes(32))
    ephem_pub_hex = ephem_sk.public_key.hex()
    giftwrap_ct = ephem_sk.encrypt_message(
        message=json.dumps(seal.to_dict()),
        public_key_hex=recipient_pubkey_hex,
    )
    giftwrap = Event(kind=KIND_GIFTWRAP, content=giftwrap_ct,
                     pubkey=ephem_pub_hex, created_at=created_at)
    giftwrap.add_pubkey_ref(recipient_pubkey_hex)
    giftwrap.compute_id()
    giftwrap.sign(ephem_sk.hex())
    return giftwrap


def _to_rumor_dict(event: Event) -> dict:
    return {
        "kind": event.kind,
        "content": event.content,
        "pubkey": event.pubkey,
        "created_at": event.created_at,
        "tags": list(event.tags),
    }


def _unwrap_giftwrap(giftwrap_dict: dict, issuer_priv_hex: str,
                      issuer_pub_hex: str) -> Optional[DmMessage]:
    """Inverse of ``_build_giftwrap``. Returns ``None`` if any check fails."""
    if giftwrap_dict.get("kind") != KIND_GIFTWRAP:
        return None
    if issuer_priv_hex is None:
        return None
    recipient_pubs = {t[1] for t in giftwrap_dict.get("tags", [])
                      if t and t[0] == "p" and len(t) >= 2}
    if issuer_pub_hex not in recipient_pubs:
        return None
    ephemeral_pub_hex = giftwrap_dict.get("pubkey", "")
    giftwrap_ct = giftwrap_dict.get("content", "")
    if not ephemeral_pub_hex or not giftwrap_ct:
        return None
    issuer_sk = PrivateKey(bytes.fromhex(issuer_priv_hex))
    try:
        seal_json = issuer_sk.decrypt_message(
            encoded_message=giftwrap_ct,
            public_key_hex=ephemeral_pub_hex,
        )
    except Exception as exc:
        log.debug("decrypt giftwrap content failed id=%s: %s",
                  giftwrap_dict.get("id", ""), exc)
        return None
    seal_dict = json.loads(seal_json)
    if seal_dict.get("kind") != KIND_SEAL:
        return None
    sender_pub_hex = seal_dict.get("pubkey", "")
    if not sender_pub_hex:
        return None
    seal = Event.from_dict(seal_dict)
    if not seal.verify():
        log.warning("rejecting unverified seal sender=%s", sender_pub_hex)
        return None
    try:
        rumor_json = issuer_sk.decrypt_message(
            encoded_message=seal.content,
            public_key_hex=sender_pub_hex,
        )
    except Exception as exc:
        log.debug("decrypt seal content failed: %s", exc)
        return None
    rumor_dict = json.loads(rumor_json)
    return DmMessage(
        event_id=giftwrap_dict.get("id", ""),
        sender_npub=PublicKey.from_hex(sender_pub_hex).npub,
        content=rumor_dict.get("content", ""),
        received_at_ts=int(time.time()),
        created_at_ts=int(rumor_dict.get("created_at", 0) or 0),
    )


def _default_fetch_factory(issuer_pub_hex, issuer_priv_hex, relays,
                            scan_timeout_secs):
    """Production relay scan via pynostr RelayManager (asyncio.to_thread)."""

    async def _fetch(since_ts: int) -> list[dict]:
        if not relays:
            return []
        return await asyncio.to_thread(
            _sync_fetch_with_relay_manager,
            issuer_pub_hex, relays, since_ts, scan_timeout_secs,
        )

    return _fetch


def _sync_fetch_with_relay_manager(issuer_pub_hex: str, relays: list[str],
                                    since_ts: int, timeout: float) -> list[dict]:
    from pynostr.filters import Filters
    from pynostr.relay_manager import RelayManager

    mgr = RelayManager(timeout=timeout)
    for url in relays:
        mgr.add_relay(url)
    mgr.open_connections()
    f = Filters(kinds=[KIND_GIFTWRAP], limit=250)
    f.add_arbitrary_tag("p", issuer_pub_hex)
    mgr.add_subscription_on_all_relays(sub_id=f"scan-{since_ts}", filters=f)
    try:
        mgr.run_sync()
    finally:
        mgr.close_connections()
    out: list[dict] = []
    for evt in mgr.message_pool.get_all_events():
        out.append(evt.to_dict() if hasattr(evt, "to_dict") else dict(evt))
    return out


def _default_publish_factory(issuer_priv_hex, relays):
    """Production relay publish via pynostr RelayManager (asyncio.to_thread)."""

    async def _publish(event_dict: dict) -> bool:
        if not relays:
            return False
        return await asyncio.to_thread(
            _sync_publish_with_relay_manager,
            event_dict, relays,
        )

    return _publish


def _sync_publish_with_relay_manager(event_dict: dict,
                                      relays: list[str]) -> bool:
    from pynostr.relay_manager import RelayManager

    evt = Event.from_dict(event_dict)
    mgr = RelayManager(timeout=10.0)
    for url in relays:
        mgr.add_relay(url)
    mgr.open_connections()
    try:
        mgr.publish_event(evt)
        mgr.run_sync()
    finally:
        mgr.close_connections()
    return True
