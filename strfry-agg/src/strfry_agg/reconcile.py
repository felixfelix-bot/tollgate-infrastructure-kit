"""Follow-list reconciliation logic (pure, network-free).

The aggregation relay only stores events from the npubs the root npub follows.
This module computes the diff between the currently-served set and a freshly
fetched kind-3 follow list, so the relay can:

* grow  -- newly-followed npubs get scraped on the next sync pass
* shrink -- unfollowed npubs get their events purged via ``strfry delete``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .crypto import hex_to_npub, is_valid_pubkey_hex, npub_to_hex

ALLOWED_KINDS_DEFAULT = (1, 3, 5, 6, 7, 10000, 10002, 30023)


@dataclass
class ReconcileResult:
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    unchanged: set[str] = field(default_factory=set)
    new_set: set[str] = field(default_factory=set)
    old_set: set[str] = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return bool(self.added or self.removed)


def extract_followed_pubkeys(kind3_event: dict) -> set[str]:
    """Parse a kind-3 contact list event into a set of lowercase hex pubkeys.

    Nostr kind-3 events carry followed pubkeys in ``["p", <hex>, ...]`` tags.
    Non-``p`` tags and malformed pubkeys are skipped. Both hex and bech32 npub
    tag values are tolerated and normalised to hex.
    """
    followed: set[str] = set()
    for tag in kind3_event.get("tags", []) or []:
        if not tag or tag[0] != "p" or len(tag) < 2:
            continue
        value = str(tag[1]).strip()
        if is_valid_pubkey_hex(value):
            followed.add(value.lower())
            continue
        if value.startswith("npub1"):
            try:
                followed.add(npub_to_hex(value))
            except ValueError:
                continue
    return followed


def diff_followed(old: Iterable[str], new: Iterable[str]) -> ReconcileResult:
    """Compute added/removed/unchanged between two hex-pubkey sets."""
    old_set = {str(x).lower().strip() for x in old if str(x).strip()}
    new_set = {str(x).lower().strip() for x in new if str(x).strip()}
    return ReconcileResult(
        added=new_set - old_set,
        removed=old_set - new_set,
        unchanged=old_set & new_set,
        new_set=new_set,
        old_set=old_set,
    )


def build_delete_filter(pubkeys: Iterable[str], kinds: Iterable[int] | None = None) -> dict:
    """Build a Nostr filter for ``strfry delete`` to purge unfollowed authors.

    If no pubkeys are given, returns an empty dict sentinel so callers can skip
    the (no-op) delete entirely rather than deleting everything.
    """
    pks = [str(x).lower().strip() for x in pubkeys if str(x).strip()]
    if not pks:
        return {}
    flt: dict = {"authors": pks}
    if kinds:
        flt["kinds"] = list(kinds)
    return flt


def build_sync_filter(pubkeys: Iterable[str], kinds: Iterable[int] | None = None) -> dict:
    """Build a Nostr filter for ``strfry sync`` (negentropy) for given authors."""
    pks = [str(x).lower().strip() for x in pubkeys if str(x).strip()]
    flt: dict = {"authors": pks}
    if kinds:
        flt["kinds"] = list(kinds)
    return flt


def format_allowlist(pubkeys: Iterable[str]) -> str:
    """Render a hex-pubkey allowlist (one per line) for the write-policy plugin."""
    lines = sorted({str(x).lower().strip() for x in pubkeys if str(x).strip()})
    return "\n".join(lines) + ("\n" if lines else "")


def format_env_npubs(pubkeys: Iterable[str]) -> str:
    """Render the comma-separated npub list mirrored into ``.env``."""
    npubs = []
    for pk in sorted({str(x).lower().strip() for x in pubkeys if str(x).strip()}):
        try:
            npubs.append(hex_to_npub(pk))
        except ValueError:
            continue
    return ",".join(npubs)


def parse_allowlist(text: str) -> set[str]:
    """Parse an allowlist file back into a set of hex pubkeys."""
    out: set[str] = set()
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if is_valid_pubkey_hex(line):
            out.add(line.lower())
        elif line.startswith("npub1"):
            try:
                out.add(npub_to_hex(line))
            except ValueError:
                continue
    return out
